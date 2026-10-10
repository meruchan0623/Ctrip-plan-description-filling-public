import unittest

import translation_rules

# 语言组 -> 站点 locale（与对照表“语言”列一致）
LOCALES = {
    "ar": "ar-XX", "zh-HK": "zh-HK", "zh-TW": "zh-TW", "zh-SGMY": "zh-SGMY", "en": "en-US",
    "ja": "ja-JP", "ko": "ko-KR", "th": "th-TH", "de": "de-DE", "es": "es-ES",
    "fr": "fr-FR", "id": "id-ID", "ms": "ms-MY", "vi": "vi-VN", "it": "it-IT",
    "nl": "nl-NL", "ru": "ru-RU", "fi": "fi-FI", "uk": "uk-UA", "da": "da-DK",
    "sv": "sv-SE", "el": "el-GR", "pl": "pl-PL", "tr": "tr-TR", "pt": "pt-BR",
}

# 来源：规格名称_当前与计划对照.xlsx 各 sheet 的“计划改动”列
EXPECTED = {
    "每日-0.5GB": {
        "ar": "0.5GB يوميًا",
        "zh-HK": "每日0.5GB",
        "zh-TW": "每日0.5GB",
        "zh-SGMY": "每日0.5GB",
        "en": "Daily 0.5GB",
        "ja": "毎日0.5GB",
        "ko": "매일 0.5GB",
        "th": "0.5GB/วัน",
        "de": "0,5 GB/Tag",
        "es": "0,5 GB/día",
        "fr": "0,5 Go/jour",
        "id": "0.5GB/hari",
        "ms": "0.5GB/hari",
        "vi": "0,5GB/ngày",
        "it": "0,5 GB/giorno",
        "nl": "0,5 GB/dag",
        "ru": "0,5 ГБ/день",
        "fi": "0,5 GB/päivä",
        "uk": "0,5 ГБ/день",
        "da": "0,5 GB/dag",
        "sv": "0,5 GB/dag",
        "el": "0,5 GB/ημέρα",
        "pl": "0,5 GB/dzień",
        "tr": "Günlük 0,5 GB",
        "pt": "0,5 GB/dia",
    },
    "总量-50GB": {
        "ar": "50GB إجمالي",
        "zh-HK": "總量50GB",
        "zh-TW": "總量50GB",
        "zh-SGMY": "总量50GB",
        "en": "Total 50GB",
        "ja": "合計50GB",
        "ko": "총 50GB",
        "th": "รวม 50GB",
        "de": "Gesamt 50 GB",
        "es": "Total 50 GB",
        "fr": "Total 50 Go",
        "id": "Total 50GB",
        "ms": "Jumlah 50GB",
        "vi": "Tổng 50GB",
        "it": "Totale 50 GB",
        "nl": "Totaal 50 GB",
        "ru": "Всего 50 ГБ",
        "fi": "Yhteensä 50 GB",
        "uk": "Всього 50 ГБ",
        "da": "I alt 50 GB",
        "sv": "Totalt 50 GB",
        "el": "Σύνολο 50 GB",
        "pl": "Łącznie 50 GB",
        "tr": "Toplam 50 GB",
        "pt": "Total 50 GB",
    },
    "每日-100GB": {
        "ar": "100GB يوميًا (10Mbps)",
        "zh-HK": "每日100GB（限速10Mbps）",
        "zh-TW": "每日100GB（限速10Mbps）",
        "zh-SGMY": "每日100GB（限速10Mbps）",
        "en": "Daily 100GB (10Mbps)",
        "ja": "毎日100GB（10Mbps）",
        "ko": "매일 100GB (10Mbps)",
        "th": "100GB/วัน (10Mbps)",
        "de": "100 GB/Tag (10 Mbps)",
        "es": "100 GB/día (10Mbps)",
        "fr": "100 Go/jour (10Mbps)",
        "id": "100GB/hari (10Mbps)",
        "ms": "100GB/hari (10 Mbps)",
        "vi": "100GB/ngày (10Mbps)",
        "it": "100 GB/giorno (10Mbps)",
        "nl": "100 GB/dag (10Mbps)",
        "ru": "100 ГБ/день (10 Мбит/с)",
        "fi": "100 GB/päivä (10Mbps)",
        "uk": "100 ГБ/день (10 Мбіт/с)",
        "da": "100 GB/dag (10Mbps)",
        "sv": "100 GB/dag (10Mbps)",
        "el": "100 GB/ημέρα (10Mbps)",
        "pl": "100 GB/dzień (10Mbps)",
        "tr": "Günlük 100 GB (10Mbps)",
        "pt": "100 GB/dia (10Mbps)",
    },
    "每日-100GB-不限速": {
        "ar": "100GB يوميًا (بدون حد للسرعة)",
        "zh-HK": "每日100GB（不限速）",
        "zh-TW": "每日100GB（不限速）",
        "zh-SGMY": "每日100GB（不限速）",
        "en": "Daily 100GB (No Speed Limit)",
        "ja": "毎日100GB（速度制限なし）",
        "ko": "매일 100GB (속도 제한 없음)",
        "th": "100GB/วัน (ไม่จำกัดความเร็ว)",
        "de": "100 GB/Tag (volle Geschwindigkeit)",
        "es": "100 GB/día (sin límite de velocidad)",
        "fr": "100 Go/jour (débit non limité)",
        "id": "100GB/hari (tanpa batas kecepatan)",
        "ms": "100GB/hari (kelajuan penuh)",
        "vi": "100GB/ngày (không giới hạn tốc độ)",
        "it": "100 GB/giorno (senza limiti di velocità)",
        "nl": "100 GB/dag (geen snelheidslimiet)",
        "ru": "100 ГБ/день (без ограничения скорости)",
        "fi": "100 GB/päivä (ei nopeusrajoitusta)",
        "uk": "100 ГБ/день (без обмеження швидкості)",
        "da": "100 GB/dag (ingen hastighedsgrænse)",
        "sv": "100 GB/dag (ingen hastighetsgräns)",
        "el": "100 GB/ημέρα (χωρίς όριο ταχύτητας)",
        "pl": "100 GB/dzień (bez limitu prędkości)",
        "tr": "Günlük 100 GB (hız sınırı yok)",
        "pt": "100 GB/dia (sem limite de velocidade)",
    },
}


class SalesPropertyValueTests(unittest.TestCase):
    def test_matches_plan_sheet_for_all_languages(self):
        for origin, expectations in EXPECTED.items():
            self.assertEqual(len(expectations), 25, origin)
            for lang, expected in expectations.items():
                with self.subTest(origin=origin, lang=lang):
                    self.assertEqual(translation_rules.translate_sales_property_value(origin, LOCALES[lang]), expected)

    def test_speed_limit_parsed_from_origin(self):
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-限速20Mbps", "en-US"), "Daily 100GB (20Mbps)")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-限速20Mbps", "ru-RU"), "100 ГБ/день (20 Мбит/с)")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB", "zh-SGMY"), "每日100GB（限速10Mbps）")

    def test_network_prefix_is_stripped(self):
        self.assertEqual(translation_rules.translate_sales_property_value("4G网络-每日-1GB", "vi-VN"), "1GB/ngày")
        self.assertEqual(translation_rules.translate_sales_property_value("5G网络-总量-10GB", "fr-FR"), "Total 10 Go")

    def test_fuzzy_prefix_keeps_suffix(self):
        self.assertEqual(translation_rules.translate_sales_property_value("每日-1GB 备注", "en-US", "fuzzy_prefix"), "Daily 1GB 备注")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-1GB 备注", "en-US", "strict"), "")

    def test_non_standard_origin_returns_empty(self):
        self.assertEqual(translation_rules.translate_sales_property_value("不限量套餐", "en-US"), "")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-1GB", "xx-XX"), "")

    def test_speed_limit_unit_is_preserved(self):
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-限速512Kbps", "en-US"), "Daily 100GB (512Kbps)")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-限速1Gbps", "ru-RU"), "100 ГБ/день (1Gbps)")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-限速1.5Mbps", "uk-UA"), "100 ГБ/день (1.5 Мбіт/с)")

    def test_mainland_simplified_chinese_is_skipped(self):
        for origin in ("每日-1GB", "总量-10GB", "每日-100GB", "每日-100GB-不限速"):
            self.assertEqual(translation_rules.translate_sales_property_value(origin, "zh-CN"), "", origin)
            self.assertEqual(translation_rules.translate_sales_property_value(origin, "zh"), "", origin)

    def test_locale_aliases(self):
        self.assertEqual(translation_rules.translate_sales_property_value("每日-1GB", "zh-SG"), "每日1GB")
        self.assertEqual(translation_rules.translate_sales_property_value("总量-1GB", "zh-Hant"), "總量1GB")
        self.assertEqual(translation_rules.translate_sales_property_value("每日-100GB-不限速", "pt-PT"), "100 GB/dia (sem limite de velocidade)")


if __name__ == "__main__":
    unittest.main()
