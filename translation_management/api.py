"""Translation API boundary using an injected JSON transport."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, Protocol

from .models import (
    TranslationDiffPlan,
    apply_translation_to_modules,
    normalize_translation_push_fields,
    translation_request_base_data,
)

TRANSLATION_AVAILABLE_LOCALES_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationAvailableLocales"
TRANSLATION_LIST_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationList"
TRANSLATION_PUSH_URL = "https://m.ctrip.com/restapi/soa2/16359/productTranslationPush"
TRANSLATION_AI_REFERENCE_URL = "https://m.ctrip.com/restapi/soa2/16359/queryAiTranslationReference"


class TranslationRequestTransport(Protocol):
    def __call__(
        self, url: str, product_id: str, body: dict[str, Any], stop_event: threading.Event, *, timeout: int = 90
    ) -> dict[str, Any]: ...


class TranslationApiClient:
    def __init__(self, post_json: TranslationRequestTransport, log: Callable[[str], None] | None = None) -> None:
        self._post_json = post_json
        self._log = log or (lambda _message: None)

    def load_available_locales(self, product_id: str, stop_event: threading.Event) -> dict[str, Any]:
        return self._post_json(TRANSLATION_AVAILABLE_LOCALES_URL, str(product_id), {
            "productId": str(product_id), "requestBaseData": translation_request_base_data(),
        }, stop_event)

    def load_translation_list(self, product_id: str, locales: list[str], stop_event: threading.Event) -> dict[str, Any]:
        return self._post_json(TRANSLATION_LIST_URL, str(product_id), {
            "productId": str(product_id), "requestBaseData": translation_request_base_data(),
            "needMeta": True, "locales": locales, "fromTranslationConfirm": False,
        }, stop_event, timeout=120)

    def query_ai_reference(self, product_id: str, target_locale: str, original_content: str, stop_event: threading.Event) -> str:
        response = self._post_json(TRANSLATION_AI_REFERENCE_URL, str(product_id), {
            "productId": str(product_id), "requestBaseData": translation_request_base_data(),
            "targetLocale": target_locale, "originalContent": original_content,
        }, stop_event, timeout=120)
        return str(response.get("aiTranslationContent") or "").strip()

    def build_push_payload(
        self, product_id: str, locale: str, raw_translation: dict[str, Any], changed_plans: list[TranslationDiffPlan], online: bool
    ) -> dict[str, Any]:
        modules = copy.deepcopy(raw_translation.get("translationModules") or [])
        if not isinstance(modules, list) or not modules:
            raise RuntimeError(f"{locale} 未返回 translationModules")
        for plan in changed_plans:
            if not apply_translation_to_modules(modules, plan.self_key, plan.row.value_key, plan.new_value):
                raise RuntimeError(f"未能在最新翻译树中定位 selfKey={plan.self_key}")
        normalize_translation_push_fields(modules)
        payload: dict[str, Any] = {
            "productId": str(product_id), "requestBaseData": translation_request_base_data(),
            "online": bool(online), "locale": str(locale), "translationModules": modules, "aiGen": False,
        }
        for key in ("tour", "clause"):
            if key in raw_translation:
                payload[key] = copy.deepcopy(raw_translation[key])
        return payload

    def save_translation(
        self, product_id: str, locale: str, raw_translation: dict[str, Any], changed_plans: list[TranslationDiffPlan], online: bool,
        stop_event: threading.Event,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        payload = self.build_push_payload(product_id, locale, raw_translation, changed_plans, online)
        return payload, self._post_json(TRANSLATION_PUSH_URL, str(product_id), payload, stop_event, timeout=120)
