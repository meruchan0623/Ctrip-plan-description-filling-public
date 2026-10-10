import copy
import tempfile
import unittest
from pathlib import Path

import app
import translation_rules

PRODUCT_ID = "100000001"


def _raw(locale, values):
    fields = []
    for code, value in values.items():
        fields.append({"fieldCode": code, "fieldName": code, "selfKey": f"{code}-key", "translation": value, "origin": f"origin-{code}"})
    return {"targetLocale": locale, "translationModules": [{"moduleCode": "basicInfo", "moduleName": "基础信息", "fields": fields}]}


FULL = {"productName": "Name", "feeInclude": "Incl", "feeExclude": "Excl", "productIntroduction": "Intro", "salesPropertyValueName": "Daily-1GB"}
EMPTY = {key: "" for key in FULL}

OPENED = {"allLocales": True, "availableLocales": True, "translatedLocales": True, "operableLocales": True, "status": 2}
UNOPENED = {"allLocales": True, "availableLocales": True}


def _snapshot(state, options):
    locales = list(state)
    return app.build_translation_snapshot_from_response(
        PRODUCT_ID,
        locales,
        {"translations": [copy.deepcopy(state[locale]) for locale in locales]},
        locale_options={locale: dict(options[locale], locale=locale) for locale in locales},
    )


class LocaleAllowedForWriteTests(unittest.TestCase):
    def test_unopened_locale_is_rejected_by_default(self):
        self.assertFalse(app.locale_allowed_for_write("en-GB", UNOPENED))
        self.assertFalse(app.locale_allowed_for_write("de-CH", UNOPENED))

    def test_unopened_locale_is_allowed_when_flag_is_set(self):
        self.assertTrue(app.locale_allowed_for_write("en-GB", UNOPENED, include_unopened=True))
        self.assertTrue(app.locale_allowed_for_write("ar-SA", UNOPENED, include_unopened=True))

    def test_flag_does_not_allow_unknown_locale(self):
        self.assertFalse(app.locale_allowed_for_write("xx-XX", {"locale": "xx-XX"}, include_unopened=True))

    def test_opened_and_zh_sgmy_behaviour_unchanged(self):
        self.assertTrue(app.locale_allowed_for_write("en-US", OPENED))
        self.assertTrue(app.locale_allowed_for_write("zh-SG", UNOPENED))


class BaselineSourceLocaleTests(unittest.TestCase):
    def test_unopened_locale_uses_translated_sibling_in_same_group(self):
        snapshot = _snapshot(
            {"en-US": _raw("en-US", FULL), "en-GB": _raw("en-GB", EMPTY), "de-DE": _raw("de-DE", FULL)},
            {"en-US": OPENED, "en-GB": UNOPENED, "de-DE": OPENED},
        )
        self.assertEqual(app.translation_baseline_source_locale(snapshot, "en-GB"), "en-US")

    def test_zh_sgmy_without_sibling_has_no_source(self):
        snapshot = _snapshot(
            {"zh-CN": _raw("zh-CN", FULL), "zh-HK": _raw("zh-HK", FULL), "zh-SG": _raw("zh-SG", EMPTY)},
            {"zh-CN": OPENED, "zh-HK": OPENED, "zh-SG": UNOPENED},
        )
        self.assertEqual(app.translation_baseline_source_locale(snapshot, "zh-SG"), "")

    def test_zh_sg_prefers_zh_my(self):
        snapshot = _snapshot(
            {"zh-MY": _raw("zh-MY", FULL), "zh-SG": _raw("zh-SG", EMPTY)},
            {"zh-MY": OPENED, "zh-SG": UNOPENED},
        )
        self.assertEqual(app.translation_baseline_source_locale(snapshot, "zh-SG"), "zh-MY")

    def test_opened_locale_with_empty_field_is_not_filled(self):
        partial = dict(FULL, productIntroduction="")
        snapshot = _snapshot(
            {"en-US": _raw("en-US", FULL), "en-GB": _raw("en-GB", partial)},
            {"en-US": OPENED, "en-GB": OPENED},
        )
        self.assertEqual(app.translation_baseline_source_locale(snapshot, "en-GB"), "")


class RuleDiffUnopenedLocaleTests(unittest.TestCase):
    def _plans(self, include_unopened):
        snapshot = _snapshot(
            {"en-US": _raw("en-US", FULL), "en-GB": _raw("en-GB", EMPTY), "zh-SG": _raw("zh-SG", EMPTY)},
            {"en-US": OPENED, "en-GB": UNOPENED, "zh-SG": UNOPENED},
        )
        for field in snapshot.fields.values():
            if field.field_code == "salesPropertyValueName":
                field.origin = "每日-1GB"
        task = translation_rules.TranslationRuleTask(row_number=2, product_id=PRODUCT_ID, source=PRODUCT_ID, row_data={"productId": PRODUCT_ID})
        config = translation_rules.TranslationExecutionConfig(
            selected_languages=["en", "zh-sgmy"],
            selected_modules=["sales_property"],
            online=True,
            include_unopened_locales=include_unopened,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            detail_path = Path(tmpdir) / "detail_templates.xlsx"
            translation_rules.create_detail_template_xlsx(str(detail_path), translation_rules.ALL_TEMPLATE_LANGUAGES)
            return app.build_translation_rule_diff_plans({PRODUCT_ID: snapshot}, [task], str(detail_path), "", config)

    def test_unopened_locales_are_skipped_by_default(self):
        by_locale = {(plan.locale, plan.status): plan for plan in self._plans(False)}
        self.assertIn(("en-GB", "invalid"), by_locale)
        self.assertIn("operableLocales", by_locale[("en-GB", "invalid")].message)
        self.assertNotIn(("en-GB", "pending"), by_locale)

    def test_unopened_locale_gets_pending_plan_saved_offline(self):
        plans = self._plans(True)
        en_gb = [plan for plan in plans if plan.locale == "en-GB" and plan.field_code == "salesPropertyValueName"]
        self.assertEqual(len(en_gb), 1)
        self.assertEqual(en_gb[0].status, "pending")
        self.assertEqual(en_gb[0].new_value, "Daily 1GB")
        self.assertFalse(en_gb[0].online)
        self.assertEqual(en_gb[0].baseline_source_locale, "en-US")
        self.assertIn("仅保存不上线", en_gb[0].message)
        zh_sg = [plan for plan in plans if plan.locale == "zh-SG"]
        self.assertTrue(zh_sg)
        self.assertTrue(all(plan.status == "invalid" and "同组完整译本" in plan.message for plan in zh_sg))


class ConfigRoundTripTests(unittest.TestCase):
    def test_include_unopened_locales_round_trip(self):
        config = app.translation_execution_config_from_dict({"online": False, "include_unopened_locales": True})
        self.assertTrue(config.include_unopened_locales)
        self.assertTrue(app.translation_execution_config_to_dict(config)["include_unopened_locales"])
        self.assertFalse(app.translation_execution_config_from_dict({}).include_unopened_locales)


if __name__ == "__main__":
    unittest.main()
