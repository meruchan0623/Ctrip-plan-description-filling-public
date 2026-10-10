import threading
import unittest


class WorkflowCommonTests(unittest.TestCase):
    def test_write_gate_excludes_other_business_areas_until_release(self):
        from workflow_common import InMemoryApplicationWriteGate, WriteGateRequest

        gate = InMemoryApplicationWriteGate()
        first = WriteGateRequest("product_edit", "save", ("100000001",))
        second = WriteGateRequest("product_images", "save_all", ("100000001",))

        self.assertTrue(gate.acquire(first))
        self.assertFalse(gate.acquire(second))
        self.assertTrue(gate.acquire(first))
        gate.release("product_edit")
        self.assertTrue(gate.acquire(second))

    def test_runtime_settings_are_thread_safe_and_include_timeout(self):
        from workflow_common import RuntimeRequestSettings

        settings = RuntimeRequestSettings(0.5, 2, 90)
        updated = settings.update(
            request_interval_seconds=1.25,
            parallel_requests=4,
            timeout_seconds=120,
        )

        self.assertEqual(updated.request_interval_seconds, 1.25)
        self.assertEqual(updated.parallel_requests, 4)
        self.assertEqual(updated.timeout_seconds, 120)
        self.assertEqual(settings.snapshot(), updated)

    def test_response_outcome_requires_ack_business_success_and_readback(self):
        from workflow_common import WriteStatus, classify_write_outcome

        response = {
            "ResponseStatus": {"Ack": "Success"},
            "responseBaseData": {"success": True},
        }

        self.assertEqual(classify_write_outcome(response, readback_matches=True), WriteStatus.SUCCEEDED)
        self.assertEqual(classify_write_outcome(response, readback_matches=False), WriteStatus.FAILED)
        self.assertEqual(classify_write_outcome(response, readback_matches=None), WriteStatus.UNKNOWN)

        business_failure = {
            "ResponseStatus": {"Ack": "Success"},
            "responseBaseData": {"success": False, "message": "validation failed"},
        }
        self.assertEqual(
            classify_write_outcome(business_failure, readback_matches=True),
            WriteStatus.FAILED,
        )

    def test_transport_protocol_accepts_structural_post_json_implementation(self):
        from ctrip_transport import CtripJsonTransport, is_ctrip_json_transport

        class Transport:
            def post_json(self, url, product_id, body, stop_event, *, timeout=90):
                self.last = (url, product_id, body, stop_event, timeout)
                return {"responseBaseData": {"success": True}}

        transport = Transport()
        self.assertTrue(is_ctrip_json_transport(transport))
        result = transport.post_json("https://example.invalid", "1", {}, threading.Event())
        self.assertTrue(result["responseBaseData"]["success"])
        self.assertIsInstance(transport, CtripJsonTransport)


if __name__ == "__main__":
    unittest.main()
