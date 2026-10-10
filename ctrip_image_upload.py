# -*- coding: utf-8 -*-
"""携程产品图片上传——纯逻辑模块，不依赖 PyQt。

通过 POST /restapi/soa2/16359/json/uploadImage 把本地 JPEG/PNG 图片
上传到携程图片库，返回后续配置所需的 imageId / imageUrl / imageName。
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

UPLOAD_IMAGE_URL = "https://m.ctrip.com/restapi/soa2/16359/json/uploadImage"
ALLOWED_MIME_TYPES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/jpg"})
MAX_FILE_BYTES: int = 20 * 1024 * 1024

# 文件魔数→MIME，比扩展名可靠
_MAGIC_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


class ImageUploadError(RuntimeError):
    """uploadImage 接口业务失败或响应非法。"""


@dataclass(frozen=True)
class UploadResult:
    image_id: str
    image_url: str
    image_name: str


def _sniff_mime(path: Path) -> str:
    """仅通过文件头魔数判断 MIME，避免扩展名伪造绕过校验。"""
    with path.open("rb") as f:
        head = f.read(16)
    for magic, mime in _MAGIC_MIME:
        if head.startswith(magic):
            return mime
    return ""


def encode_image_as_data_url(image_path: str | Path) -> tuple[str, str]:
    """读取本地图片，返回 (mime_type, data_url)。

    对不支持的格式或超大文件抛 ValueError；文件不存在抛 FileNotFoundError。
    """
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"图片文件不存在：{path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"文件过大：{size} bytes，上限 {MAX_FILE_BYTES} bytes（20 MB）")
    if size == 0:
        raise ValueError("文件为空，无法上传")
    mime = _sniff_mime(path)
    if mime not in ALLOWED_MIME_TYPES:
        raise ValueError(f"不支持的图片格式：{mime or '未知'}，仅支持 JPEG/PNG")
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return mime, f"data:{mime};base64,{b64}"


def _default_image_name(path: Path, mime: str) -> str:
    suffix = ".png" if mime == "image/png" else ".jpg"
    return f"{path.stem}{suffix}"


def _check_response(data: Any) -> UploadResult:
    if not isinstance(data, dict):
        raise ImageUploadError(
            f"uploadImage 响应结构异常：{json.dumps(data, ensure_ascii=False)[:500]}"
        )
    response_status = data.get("ResponseStatus")
    if response_status is not None and not isinstance(response_status, dict):
        raise ImageUploadError("uploadImage 响应 ResponseStatus 结构异常")
    response_status = response_status or {}
    response_base = data.get("responseBaseData")
    if response_base is not None and not isinstance(response_base, dict):
        raise ImageUploadError("uploadImage 响应 responseBaseData 结构异常")
    response_base = response_base or {}
    ack = str(response_status.get("Ack") or "").lower()
    success = bool(response_base.get("success"))
    if ack != "success" or not success:
        errors = response_status.get("Errors") or []
        error_msg = response_base.get("message") or ""
        if not error_msg and errors:
            error_msg = "; ".join(str(e.get("Message") or e) for e in errors)
        raise ImageUploadError(
            f"uploadImage 业务失败：Ack={response_status.get('Ack')} "
            f"success={success} {error_msg}".strip()
        )
    image_id = data.get("imageId")
    image_url = data.get("imageUrl")
    image_name = data.get("imageName")
    if not (image_id and image_url and image_name):
        raise ImageUploadError(
            f"uploadImage 响应缺少必要字段：{json.dumps(data, ensure_ascii=False)[:500]}"
        )
    return UploadResult(
        image_id=str(image_id),
        image_url=str(image_url),
        image_name=str(image_name),
    )


def upload_image(
    image_path: str | Path,
    product_id: str,
    cookie_header: str,
    *,
    image_name: str | None = None,
    is_free_size: bool = False,
    timeout: int = 120,
) -> UploadResult:
    """上传本地图片到携程图片库。

    Args:
        image_path: 本地 JPEG/PNG 路径。
        product_id: 产品 ID，用于构造 referer 头。
        cookie_header: 已登录的 Cookie 字符串。
        image_name: 上传后的文件名；None 时从原文件名推断。
        is_free_size: 是否自由尺寸，默认 False（遵循 16:9 约束）。
        timeout: 请求超时秒数，默认 120。

    Returns:
        UploadResult(image_id, image_url, image_name)

    Raises:
        ValueError: 本地文件格式/大小不合法。
        FileNotFoundError: 文件不存在。
        ImageUploadError: 接口业务失败或响应缺字段。
        requests.RequestException: 网络层错误。
    """
    path = Path(image_path)
    mime, data_url = encode_image_as_data_url(path)
    name = image_name or _default_image_name(path, mime)
    body = {
        "file": data_url,
        "imageName": name,
        "isFreeSize": bool(is_free_size),
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://vbooking.ctrip.com",
        "referer": (
            "https://vbooking.ctrip.com/activity-vbk/product-edit"
            f"?productId={product_id}"
        ),
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124 Safari/537.36"
        ),
        "cookie": cookie_header,
    }
    resp = requests.post(UPLOAD_IMAGE_URL, headers=headers, json=body, timeout=timeout)
    if not resp.ok:
        raise ImageUploadError(f"uploadImage HTTP {resp.status_code}：{resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise ImageUploadError(f"uploadImage 返回非 JSON：{resp.text[:300]}") from exc
    return _check_response(data)
