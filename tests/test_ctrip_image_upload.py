# -*- coding: utf-8 -*-
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import requests

import ctrip_image_upload as up


class EncodeImageAsDataUrlTests(unittest.TestCase):
    def _write_file(self, data: bytes, suffix: str) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        f.write(data)
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return Path(f.name)

    def test_jpeg_returns_correct_data_url(self):
        payload = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        path = self._write_file(payload, ".jpg")
        mime, data_url = up.encode_image_as_data_url(path)
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(data_url.startswith("data:image/jpeg;base64,"))
        expected_b64 = base64.b64encode(payload).decode("ascii")
        self.assertIn(expected_b64, data_url)

    def test_png_returns_correct_data_url(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        path = self._write_file(payload, ".png")
        mime, data_url = up.encode_image_as_data_url(path)
        self.assertEqual(mime, "image/png")
        self.assertTrue(data_url.startswith("data:image/png;base64,"))

    def test_gif_rejected(self):
        path = self._write_file(b"GIF89a" + b"\x00" * 50, ".gif")
        with self.assertRaisesRegex(ValueError, "不支持的图片格式"):
            up.encode_image_as_data_url(path)

    def test_txt_rejected(self):
        path = self._write_file(b"hello not an image", ".txt")
        with self.assertRaisesRegex(ValueError, "不支持的图片格式"):
            up.encode_image_as_data_url(path)

    def test_file_too_large_rejected(self):
        fake_stat = mock.Mock()
        fake_stat.st_size = up.MAX_FILE_BYTES + 1
        with mock.patch.object(Path, "is_file", return_value=True), \
             mock.patch.object(Path, "stat", return_value=fake_stat), \
             mock.patch("builtins.open", mock.mock_open(read_data=b"\xff\xd8\xff\xe0xxxx")):
            with self.assertRaisesRegex(ValueError, "文件过大"):
                up.encode_image_as_data_url("/fake/big.jpg")

    def test_empty_file_rejected(self):
        path = self._write_file(b"", ".jpg")
        with self.assertRaisesRegex(ValueError, "文件为空"):
            up.encode_image_as_data_url(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            up.encode_image_as_data_url("/nonexistent/path.jpg")

    def test_jpeg_extension_but_png_content_uses_magic(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        path = self._write_file(payload, ".jpg")
        mime, _ = up.encode_image_as_data_url(path)
        self.assertEqual(mime, "image/png")

    def test_default_image_name_preserves_stem(self):
        name = up._default_image_name(Path("/tmp/我的产品图.jpg"), "image/jpeg")
        self.assertEqual(name, "我的产品图.jpg")
        name_png = up._default_image_name(Path("/tmp/pic.png"), "image/png")
        self.assertEqual(name_png, "pic.png")


class UploadImageTests(unittest.TestCase):
    def _prepare_real_jpeg(self) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 200)
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return Path(f.name)

    @mock.patch("ctrip_image_upload.requests.post")
    def test_success_returns_upload_result(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": {"success": True},
                "imageId": 300000001,
                "imageUrl": "https://dimg04.c-ctrip.com/images/xxx.jpg",
                "imageName": "test.jpg",
            },
        )
        path = self._prepare_real_jpeg()
        result = up.upload_image(path, "100000001", "cookie=value")
        self.assertEqual(result.image_id, "300000001")
        self.assertEqual(result.image_url, "https://dimg04.c-ctrip.com/images/xxx.jpg")
        self.assertEqual(result.image_name, "test.jpg")
        call_kwargs = mock_post.call_args.kwargs
        self.assertEqual(call_kwargs["headers"]["cookie"], "cookie=value")
        self.assertIn("productId=100000001", call_kwargs["headers"]["referer"])
        body = call_kwargs["json"]
        self.assertTrue(body["file"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(body["imageName"], path.name)
        self.assertFalse(body["isFreeSize"])

    @mock.patch("ctrip_image_upload.requests.post")
    def test_business_failure_success_false_raises(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": {"success": False, "message": "invalid image"},
            },
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "invalid image"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_missing_fields_raises(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": {"success": True},
            },
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "缺少必要字段"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_http_error_raises(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=False, status_code=500, text="Internal Server Error"
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "HTTP 500"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_non_json_response_raises(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            text="<html>error</html>",
            json=lambda: (_ for _ in ()).throw(ValueError("no json")),
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "非 JSON"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_custom_image_name_used(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": {"success": True},
                "imageId": 1,
                "imageUrl": "https://x/y.jpg",
                "imageName": "custom.jpg",
            },
        )
        path = self._prepare_real_jpeg()
        up.upload_image(path, "100000001", "cookie=value", image_name="custom.jpg")
        self.assertEqual(
            mock_post.call_args.kwargs["json"]["imageName"], "custom.jpg"
        )

    @mock.patch("ctrip_image_upload.requests.post")
    def test_is_free_size_true_passed_through(self, mock_post):
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": {"success": True},
                "imageId": 1,
                "imageUrl": "https://x/y.jpg",
                "imageName": "y.jpg",
            },
        )
        path = self._prepare_real_jpeg()
        up.upload_image(path, "100000001", "cookie=value", is_free_size=True)
        self.assertTrue(mock_post.call_args.kwargs["json"]["isFreeSize"])

    @mock.patch("ctrip_image_upload.requests.post")
    def test_list_response_raises_clear_error(self, mock_post):
        """接口返回 JSON 数组（非 dict）时给出清晰错误而非 AttributeError。"""
        mock_post.return_value = mock.Mock(
            ok=True, status_code=200, json=lambda: [1, 2, 3]
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "响应结构异常"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_badly_typed_subfield_raises_clear_error(self, mock_post):
        """responseBaseData 为列表等非 dict 时给出清晰错误。"""
        mock_post.return_value = mock.Mock(
            ok=True,
            status_code=200,
            json=lambda: {
                "ResponseStatus": {"Ack": "Success", "Errors": []},
                "responseBaseData": ["not", "a", "dict"],
            },
        )
        path = self._prepare_real_jpeg()
        with self.assertRaisesRegex(up.ImageUploadError, "结构异常"):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_network_timeout_propagates(self, mock_post):
        """网络超时（requests.Timeout）不被吞掉，直接向上传播。"""
        mock_post.side_effect = requests.Timeout("timed out after 120s")
        path = self._prepare_real_jpeg()
        with self.assertRaises(requests.Timeout):
            up.upload_image(path, "100000001", "cookie=value")

    @mock.patch("ctrip_image_upload.requests.post")
    def test_connection_error_propagates(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("connection refused")
        path = self._prepare_real_jpeg()
        with self.assertRaises(requests.ConnectionError):
            up.upload_image(path, "100000001", "cookie=value")

    def test_renamed_fake_file_rejected_by_magic(self):
        """任意文件改名 .jpg 后必须被魔数校验拒绝（无扩展名回退）。"""
        f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        f.write(b"<html><body>not an image</body></html>")
        f.close()
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        with self.assertRaisesRegex(ValueError, "不支持的图片格式"):
            up.encode_image_as_data_url(f.name)


if __name__ == "__main__":
    unittest.main()
