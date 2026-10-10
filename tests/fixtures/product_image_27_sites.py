# -*- coding: utf-8 -*-
"""脱敏的 27 语言站点 ProductInfo 构造器。

全站点头图测试统一使用此 fixture，不访问线上接口。
"""

LANGUAGE_SITES = (
    ("简体中文", "chinese"),
    ("阿拉伯语", "Arabic"),
    ("丹麦语", "Danish"),
    ("德语", "german"),
    ("希腊语", "Greek"),
    ("英语", "english"),
    ("西班牙语", "span"),
    ("芬兰语", "Finnish"),
    ("法语", "french"),
    ("印尼语", "indonesian"),
    ("意大利语", "italian"),
    ("日语", "japanese"),
    ("韩语", "korean"),
    ("马来语", "malay"),
    ("荷兰语", "dutch"),
    ("波兰语", "Polish"),
    ("葡萄牙语", "Portuguese"),
    ("俄语", "russian"),
    ("瑞典语", "Swedish"),
    ("泰语", "thai"),
    ("土耳其语", "Turkish"),
    ("乌克兰语", "Ukrainian"),
    ("越南语", "vietnamese"),
    ("繁体中文(香港)", "chineseHk"),
    ("繁体中文（马来西亚）", "chineseMy"),
    ("繁体中文（新加坡）", "chineseSg"),
    ("繁体中文(台湾)", "chineseTw"),
)


def make_product_info_27_sites(images_per_site: int = 1):
    """返回包含 27 个语言站点的脱敏 ProductInfo。

    每个站点默认有一张图片；可通过 images_per_site 调整。
    """
    rows = []
    for index, (_label, code) in enumerate(LANGUAGE_SITES, start=1):
        rows.append({
            "languagelocale": _label,
            "languageCode": code,
            "unknownLocaleField": f"keep-{code}",
            "imageList": [
                {
                    "imageId": index * 100 + image_index,
                    "imageUrl": f"https://img.example/{code}/{image_index}.jpg",
                    "imageName": f"{code}-{image_index}.jpg",
                    "imageSource": "ttd",
                    "unknownImageField": f"keep-image-{code}-{image_index}",
                }
                for image_index in range(1, images_per_site + 1)
            ],
        })
    return {
        "productId": 100000004,
        "productVersion": 17,
        "productBasicInfo": {
            "imageList": [rows[0]["imageList"][0]],
            "getImageLocaleInfo": {
                "imageSetting": 2,
                "useLanguageCode": True,
                "images": rows,
            },
            "unknownProductField": "keep-product",
        },
    }
