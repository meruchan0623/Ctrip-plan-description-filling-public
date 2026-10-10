import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import app


class RequestStatsStoreTests(unittest.TestCase):
    def test_records_total_daily_and_run_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            current_day = ["2026-06-12"]
            store = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: current_day[0],
            )

            store.record_request("product")
            store.record_request("product", 2)
            store.record_failure("product")

            self.assertEqual(store.summary_text("product"), "请求 累计 3/1 | 今日 3/1 | 本次 3/1")

            reloaded = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: current_day[0],
            )
            self.assertEqual(reloaded.summary_text("product"), "请求 累计 3/1 | 今日 3/1 | 本次 0/0")

    def test_daily_counts_roll_over_without_resetting_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            current_day = ["2026-06-12"]
            store = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: current_day[0],
            )
            store.record_request("translation")
            store.record_failure("translation")

            current_day[0] = "2026-06-13"
            store.record_request("translation", 2)

            self.assertEqual(store.summary_text("translation"), "请求 累计 3/1 | 今日 2/0 | 本次 3/1")

    def test_corrupt_json_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "request_stats.json"
            path.write_text("{not-json", encoding="utf-8")

            store = app.RequestStatsStore(path, today_provider=lambda: "2026-06-12")

            self.assertIn("请求统计文件读取失败", store.load_error)
            self.assertEqual(store.summary_text("image"), "请求 累计 0/0 | 今日 0/0 | 本次 0/0")

    def test_docking_requests_use_an_independent_area(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: "2026-08-11",
            )

            store.record_request("docking", 2)
            store.record_failure("docking")

            self.assertEqual(store.summary_text("docking"), "请求 累计 2/1 | 今日 2/1 | 本次 2/1")
            self.assertEqual(store.summary_text("product"), "请求 累计 0/0 | 今日 0/0 | 本次 0/0")


class FakeResponse:
    ok = True
    status_code = 200
    text = '{"responseBaseData":{"success":true}}'


class FakeSession:
    def __init__(self):
        self.preparer = app.requests.Session()

    def prepare_request(self, request):
        return self.preparer.prepare_request(request)

    def send(self, prepared, timeout=90):
        return FakeResponse()


class CtripRequestsClientStatsTests(unittest.TestCase):
    def test_successful_request_records_total_only(self):
        recorded = []
        client = app.CtripRequestsClient.__new__(app.CtripRequestsClient)
        client.log = lambda _message: None
        client.request_interval_seconds = 0
        client.request_interval_provider = None
        client.session = FakeSession()
        client.last_request_at = 0.0
        client.cookie_header = "session=fake"
        client.loaded_trip_cookies = 0
        client.stats_area = "product"
        client.stats_recorder = recorded.append
        client._wait_for_request_slot = lambda _stop_event: None

        result = client._request_json("https://example.invalid/api", "123", {"productId": "123"}, threading.Event())

        self.assertEqual(result["responseBaseData"]["success"], True)
        self.assertEqual(recorded, ["product"])

    def test_cookie_validation_request_uses_global_limiter(self):
        with mock.patch.object(app.requests, "Session", return_value=FakeSession()), \
             mock.patch.object(app.GLOBAL_REQUEST_LIMITER, "wait") as wait:
            result = app.request_json_with_cookie(
                "https://example.invalid/api",
                "123",
                {"productId": "123"},
                "session=fake",
            )

        self.assertEqual(result["responseBaseData"]["success"], True)
        wait.assert_called_once()


class RequestLimitClampTests(unittest.TestCase):
    def test_request_interval_is_clamped_to_distribution_range(self):
        self.assertEqual(app.clamp_request_interval_seconds("0"), 0.2)
        self.assertEqual(app.clamp_request_interval_seconds("0.1"), 0.2)
        self.assertEqual(app.clamp_request_interval_seconds("0.2"), 0.2)
        self.assertEqual(app.clamp_request_interval_seconds("0.3"), 0.3)
        self.assertEqual(app.clamp_request_interval_seconds("0.5"), 0.5)
        self.assertEqual(app.clamp_request_interval_seconds("0.8"), 0.8)
        self.assertEqual(app.clamp_request_interval_seconds("1"), 1.0)
        self.assertEqual(app.clamp_request_interval_seconds("2"), 1.0)

    def test_parallel_requests_are_clamped_to_distribution_limit(self):
        self.assertEqual(app.clamp_parallel_requests_value("0"), 1)
        self.assertEqual(app.clamp_parallel_requests_value("4"), 4)
        self.assertEqual(app.clamp_parallel_requests_value("10"), 5)
        self.assertEqual(app.clamp_parallel_requests_value("30"), 5)


class GlobalRequestLimiterTests(unittest.TestCase):
    def test_wait_serializes_request_start_times(self):
        limiter = app.GlobalRequestLimiter(interval_seconds=0.5)
        limiter.configure_for_workload(0.5, 4)
        stop_event = threading.Event()
        starts = []
        lock = threading.Lock()

        def run_once():
            limiter.wait(stop_event)
            with lock:
                starts.append(time.monotonic())

        threads = [threading.Thread(target=run_once) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        starts.sort()
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(gap >= 0.45 for gap in gaps), gaps)


class AppRequestFailureStatsTests(unittest.TestCase):
    def test_docking_stats_refresh_the_docking_header_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app = mock.Mock(spec=[])
            fake_app.request_stats = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: "2026-08-11",
            )
            fake_app.docking_config_widget = mock.Mock()
            fake_app._active_log = lambda _message: None
            fake_app._refresh_request_stats_label = (
                app.App._refresh_request_stats_label.__get__(fake_app)
            )

            app.App._record_request_stat(fake_app, "docking")
            app.App._record_failure_stat(fake_app, "docking")

            fake_app.docking_config_widget.set_request_stats_text.assert_called_with(
                "请求 累计 1/1 | 今日 1/1 | 本次 1/1"
            )

    def test_image_stats_refresh_the_image_workspace_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app = mock.Mock(spec=[])
            fake_app.request_stats = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: "2026-06-12",
            )
            fake_app.product_image_workspace = mock.Mock()
            fake_app._active_log = lambda _message: None
            fake_app._refresh_request_stats_label = (
                app.App._refresh_request_stats_label.__get__(fake_app)
            )

            app.App._record_request_stat(fake_app, "image")
            app.App._record_failure_stat(fake_app, "image")

            fake_app.product_image_workspace.set_request_stats_text.assert_called_with(
                "请求 累计 1/1 | 今日 1/1 | 本次 1/1"
            )

    def test_result_failures_count_error_but_not_verify_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app = app.App.__new__(app.App)
            fake_app.request_stats = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: "2026-06-12",
            )
            fake_app.active_worker_area = "product"
            fake_app._active_log = lambda _message: None
            fake_app._refresh_request_stats_label = lambda _area: None

            fake_app._record_result_failures(
                [
                    app.ResultRow(product_id="1", package_name="", status="error"),
                    app.ResultRow(product_id="1", package_name="", status="verify_failed"),
                ]
            )

            self.assertEqual(fake_app.request_stats.summary_text("product"), "请求 累计 0/1 | 今日 0/1 | 本次 0/1")

    def test_translation_result_uses_translation_area(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_app = app.App.__new__(app.App)
            fake_app.request_stats = app.RequestStatsStore(
                Path(tmpdir) / "request_stats.json",
                today_provider=lambda: "2026-06-12",
            )
            fake_app.active_worker_area = "product"
            fake_app._active_log = lambda _message: None
            fake_app._refresh_request_stats_label = lambda _area: None

            fake_app._record_result_failures(
                [
                    app.TranslationResultRow(
                        product_id="1",
                        locale="en-US",
                        module_code="",
                        field_code="",
                        field_name="",
                        self_key="",
                        status="error",
                    )
                ]
            )

            self.assertEqual(fake_app.request_stats.summary_text("translation"), "请求 累计 0/1 | 今日 0/1 | 本次 0/1")


if __name__ == "__main__":
    unittest.main()
