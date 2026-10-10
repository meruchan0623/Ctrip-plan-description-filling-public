"""Translation-domain data and deterministic tree transformations."""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterator

import translation_rules


LEGACY_TRANSLATION_FIELD_LABELS = {
    "productName": "产品名称",
    "productDesc": "产品描述",
    "productIntroduction": "产品介绍",
    "feeInclude": "费用包含",
    "feeExclude": "费用不含",
    "howToUse": "使用方法",
    "attention": "注意事项",
    "postBookingTravelReminder": "预订后旅行提醒",
    "operationAttention": "携程处理注意事项",
    "salesPropertyName": "销售属性名",
    "salesPropertyValueName": "销售属性值",
    "packageDesc": "套餐名称",
    "packageIntroduction": "套餐介绍",
    "resourceName": "套餐规格量词",
    "packageResourceName": "套餐规格量词",
}
LEGACY_TRANSLATION_FIELD_CODES = frozenset(LEGACY_TRANSLATION_FIELD_LABELS)


@dataclass
class TranslationFieldSnapshot:
    product_id: str
    locale: str
    module_code: str
    module_name: str
    field_code: str
    field_name: str
    value_key: str
    self_key: str
    path: str
    origin: str
    old_translation: str


@dataclass
class TranslationSnapshot:
    product_id: str
    created_at: str
    locales: list[str]
    raw_by_locale: dict[str, dict[str, Any]]
    fields: dict[str, TranslationFieldSnapshot]
    locale_options: dict[str, dict[str, Any]] | None = None


@dataclass
class TranslationTemplateRow:
    row_number: int
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    value_key: str
    self_key: str
    origin: str
    old_translation: str
    target_translation: str = ""
    online: bool = True
    validation_error: str = ""


@dataclass
class TranslationDiffPlan:
    row: TranslationTemplateRow
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    self_key: str
    old_value: str
    new_value: str
    online: bool
    status: str = "pending"
    message: str = ""
    baseline_source_locale: str = ""


@dataclass
class TranslationResultRow:
    product_id: str
    locale: str
    module_code: str
    field_code: str
    field_name: str
    self_key: str
    status: str
    old_value: str = ""
    new_value: str = ""
    online: bool = True
    interface_name: str = "productTranslationPush"
    message: str = ""
    row_number: int | str = ""


@dataclass
class TranslationOnlineContext:
    enabled: bool = False
    online: bool = False
    product_ids: list[str] = field(default_factory=list)
    selected_languages: list[str] = field(default_factory=list)
    locales_by_product: dict[str, list[str]] = field(default_factory=dict)


def default_translation_execution_config() -> translation_rules.TranslationExecutionConfig:
    return translation_rules.TranslationExecutionConfig(
        selected_languages=translation_rules.DEFAULT_SELECTED_LANGUAGES.copy(),
        selected_modules=translation_rules.DEFAULT_SELECTED_MODULES.copy(),
        sales_attr_mode="strict",
        long_day_package_template_mode="none",
        package_special_rules=translation_rules.normalize_special_rule_config({}),
        online=True,
        include_unopened_locales=False,
    )


@dataclass
class TranslationRuleRuntime:
    task_path: str = ""
    detail_template_path: str = ""
    package_template_path: str = ""
    config: translation_rules.TranslationExecutionConfig = field(default_factory=default_translation_execution_config)
    online_context: TranslationOnlineContext = field(default_factory=TranslationOnlineContext)


def translation_execution_config_to_dict(config: translation_rules.TranslationExecutionConfig) -> dict[str, Any]:
    return {
        "selected_languages": list(config.selected_languages or []),
        "selected_modules": list(config.selected_modules or []),
        "sales_attr_mode": str(config.sales_attr_mode or "strict"),
        "long_day_package_template_mode": str(config.long_day_package_template_mode or "none"),
        "package_special_rules": translation_rules.normalize_special_rule_config(config.package_special_rules),
        "online": bool(config.online),
        "include_unopened_locales": bool(config.include_unopened_locales),
    }


def translation_execution_config_from_dict(data: Any) -> translation_rules.TranslationExecutionConfig:
    config = default_translation_execution_config()
    if not isinstance(data, dict):
        return config
    languages = [str(item) for item in data.get("selected_languages", []) if str(item) in translation_rules.ALL_TEMPLATE_LANGUAGES]
    if languages:
        config.selected_languages = languages
    modules = [str(item) for item in data.get("selected_modules", []) if str(item) in translation_rules.MODULE_LABELS]
    if modules:
        config.selected_modules = modules
    if str(data.get("sales_attr_mode") or "") in {"strict", "fuzzy_prefix", "ai_translation"}:
        config.sales_attr_mode = str(data["sales_attr_mode"])
    if str(data.get("long_day_package_template_mode") or "") in {"none", "stop", "throttle"}:
        config.long_day_package_template_mode = str(data["long_day_package_template_mode"])
    config.package_special_rules = translation_rules.normalize_special_rule_config(
        data.get("package_special_rules") if isinstance(data.get("package_special_rules"), dict) else {}
    )
    if "online" in data:
        config.online = bool(data["online"])
    config.include_unopened_locales = bool(data.get("include_unopened_locales", False))
    return config


def translation_request_base_data() -> dict[str, Any]:
    return {"extParameterList": [{"key": "page_version", "value": "4.0"}]}


def translation_field_key(product_id: str, locale: str, self_key: str) -> str:
    return f"{product_id}:{locale}:{self_key}"


def translation_modules_from_locale(raw: dict[str, Any]) -> list[dict[str, Any]]:
    modules = raw.get("translationModules")
    return modules if isinstance(modules, list) else []


def translation_field_value(field: dict[str, Any]) -> tuple[str, str]:
    for key in ("translation", "targetValue", "target", "value", "content", "fieldValue", "translateValue"):
        if key in field:
            value = field.get(key)
            return key, "" if value is None else str(value)
    return "value", ""


def translation_field_origin(field: dict[str, Any]) -> str:
    for key in ("origin", "originValue", "sourceValue", "source", "original", "originalValue"):
        if field.get(key) is not None:
            return str(field[key])
    return ""


def iter_translation_fields(
    items: Any, module_code: str = "", module_name: str = "", path: str = ""
) -> Iterator[tuple[str, str, str, dict[str, Any]]]:
    if isinstance(items, list):
        for index, item in enumerate(items):
            child_path = f"{path}/{index}" if path else str(index)
            yield from iter_translation_fields(item, module_code, module_name, child_path)
        return
    if not isinstance(items, dict):
        return
    current_code = str(items.get("moduleCode") or items.get("moduleType") or items.get("code") or module_code)
    current_name = str(items.get("moduleName") or items.get("name") or module_name)
    if items.get("fieldCode") and any(key in items for key in ("translation", "origin", "originLast", "ibuKey", "selfKey", "valueKey")):
        yield current_code, current_name, path, items
    for key in ("subItems", "children", "items", "translationModules", "fields"):
        children = items.get(key)
        if isinstance(children, list):
            child_path = f"{path}/{key}" if path else key
            yield from iter_translation_fields(children, current_code, current_name, child_path)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_translation_snapshot_from_response(
    product_id: str,
    locales: list[str],
    response: dict[str, Any],
    locale_options: dict[str, dict[str, Any]] | None = None,
    retain_raw: bool = False,
) -> TranslationSnapshot:
    raw_sources: dict[str, dict[str, Any]] = {}
    raw_by_locale: dict[str, dict[str, Any]] = {}
    translations = response.get("translations")
    if isinstance(translations, list):
        for item in translations:
            if isinstance(item, dict):
                locale = str(item.get("targetLocale") or item.get("locale") or "")
                if locale:
                    raw_sources[locale] = item
                    if retain_raw:
                        raw_by_locale[locale] = copy.deepcopy(item)
    elif translation_modules_from_locale(response):
        locale = locales[0] if locales else str(response.get("targetLocale") or response.get("locale") or "")
        if locale:
            raw_sources[locale] = response
            if retain_raw:
                raw_by_locale[locale] = copy.deepcopy(response)
    snapshot_locales = [locale for locale in locales if locale in raw_sources]
    snapshot_locales.extend(locale for locale in raw_sources if locale not in snapshot_locales)
    fields: dict[str, TranslationFieldSnapshot] = {}
    for locale in snapshot_locales:
        for module_code, module_name, path, raw_field in iter_translation_fields(translation_modules_from_locale(raw_sources[locale])):
            field_code = str(raw_field.get("fieldCode") or raw_field.get("code") or "")
            if field_code not in LEGACY_TRANSLATION_FIELD_CODES:
                continue
            self_key = str(raw_field.get("selfKey") or raw_field.get("key") or "") or (f"path:{path}" if path else "")
            if not self_key:
                continue
            value_key, old_translation = translation_field_value(raw_field)
            field_name = str(raw_field.get("fieldName") or raw_field.get("name") or LEGACY_TRANSLATION_FIELD_LABELS.get(field_code, field_code))
            field = TranslationFieldSnapshot(
                str(product_id), locale, module_code, module_name, field_code, field_name,
                value_key, self_key, path, translation_field_origin(raw_field), old_translation,
            )
            fields[translation_field_key(str(product_id), locale, self_key)] = field
    return TranslationSnapshot(str(product_id), _now_iso(), snapshot_locales, raw_by_locale, fields, locale_options)


def _locale_allowed_for_write(locale: str, option: dict[str, Any]) -> bool:
    return not option or bool(option.get("operableLocales") or option.get("translatedLocales"))


def build_translation_diff_plans(
    snapshots: dict[str, TranslationSnapshot], rows: list[TranslationTemplateRow]
) -> list[TranslationDiffPlan]:
    plans: list[TranslationDiffPlan] = []
    for row in rows:
        plan = TranslationDiffPlan(
            row, row.product_id, row.locale, row.module_code, row.field_code, row.field_name,
            row.self_key, row.old_translation, row.target_translation, row.online,
        )
        if row.validation_error:
            plan.status, plan.message = "invalid", row.validation_error
        elif not (snapshot := snapshots.get(row.product_id)):
            plan.status, plan.message = "invalid", "内存快照不存在，请重新预载翻译件"
        elif not _locale_allowed_for_write(row.locale, (snapshot.locale_options or {}).get(row.locale, {})):
            plan.status, plan.message = "invalid", "该语言未开站且不在 operableLocales，接口版默认跳过"
        elif not (field := snapshot.fields.get(translation_field_key(row.product_id, row.locale, row.self_key))):
            plan.status, plan.message = "invalid", "内存快照中未找到该翻译字段"
        else:
            plan.module_code = field.module_code
            plan.field_code = field.field_code
            plan.field_name = field.field_name
            plan.self_key = field.self_key
            plan.old_value = field.old_translation
            if row.target_translation == field.old_translation:
                plan.status, plan.message = "unchanged", "目标翻译与当前快照一致"
        plans.append(plan)
    return plans


def apply_translation_to_modules(items: Any, self_key: str, value_key: str, new_value: str) -> bool:
    if str(self_key).startswith("path:"):
        return _apply_translation_by_path(items, str(self_key)[5:], value_key, new_value)
    changed = False
    if isinstance(items, list):
        return any(apply_translation_to_modules(item, self_key, value_key, new_value) for item in items)
    if not isinstance(items, dict):
        return False
    if str(items.get("selfKey") or items.get("key") or "") == self_key:
        items[value_key or "translation"] = new_value
        if "aiGen" in items:
            items["aiGen"] = False
        changed = True
    for child_key in ("fields", "subItems", "children", "items", "translationModules"):
        children = items.get(child_key)
        if isinstance(children, list):
            for child in children:
                changed = apply_translation_to_modules(child, self_key, value_key, new_value) or changed
    return changed


def _apply_translation_by_path(items: Any, path: str, value_key: str, new_value: str) -> bool:
    current = items
    for part in path.split("/"):
        if isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False
    if not isinstance(current, dict):
        return False
    current[value_key or "translation"] = new_value
    if "aiGen" in current:
        current["aiGen"] = False
    return True


def normalize_translation_push_fields(items: Any) -> None:
    if isinstance(items, list):
        for item in items:
            normalize_translation_push_fields(item)
        return
    if not isinstance(items, dict):
        return
    field_code = str(items.get("fieldCode") or items.get("code") or "")
    if field_code:
        _key, value = translation_field_value(items)
        if not value.strip():
            value = translation_field_origin(items)
        items.setdefault("translation", value)
        if not str(items.get("translation") or "").strip() and value.strip():
            items["translation"] = value
        items.setdefault("ibuKey", field_code)
    for key in ("fields", "subItems", "children", "items", "translationModules"):
        normalize_translation_push_fields(items.get(key))


def translation_report_headers() -> list[str]:
    return [
        "产品ID", "语言地区", "模块编码", "字段编码", "字段名称", "字段键",
        "修改前译文", "修改后译文", "是否上线", "调用接口", "处理状态", "结果说明", "模板行号",
    ]


def translation_result_row_values(item: TranslationResultRow) -> list[Any]:
    return [
        item.product_id, item.locale, item.module_code, item.field_code, item.field_name, item.self_key,
        item.old_value, item.new_value, "是" if item.online else "否", item.interface_name,
        item.status, item.message, item.row_number,
    ]


def _translation_result_sort_key(item: TranslationResultRow, product_order: dict[str, int] | None) -> tuple[Any, ...]:
    order = product_order or {}
    row_number = item.row_number
    try:
        sortable_row = int(row_number)
    except (TypeError, ValueError):
        sortable_row = 0
    return (
        order.get(str(item.product_id), len(order)), str(item.product_id), str(item.locale),
        sortable_row, str(item.module_code), str(item.field_code), str(item.self_key), str(item.status),
    )


def write_translation_report(
    path: str,
    results: list[TranslationResultRow],
    product_order: dict[str, int] | None = None,
    metadata: list[list[Any]] | None = None,
) -> None:
    """Write the existing CSV/XLSX result layout without any UI dependency."""
    headers = translation_report_headers()
    ordered = sorted(results, key=lambda item: _translation_result_sort_key(item, product_order))
    if path.lower().endswith(".csv"):
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(translation_result_row_values(item) for item in ordered)
        return
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("缺少 openpyxl，无法导出 xlsx") from exc
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "翻译结果"
    worksheet.append(headers)
    for item in ordered:
        worksheet.append(translation_result_row_values(item))
    if metadata:
        summary = workbook.create_sheet("执行摘要")
        summary.append(["项目", "值"])
        for row in metadata:
            summary.append(row)
    workbook.save(path)
