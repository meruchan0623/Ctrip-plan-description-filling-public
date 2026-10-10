"""Product-edit field registry.

The registry is deliberately broad so the GUI can disclose every approved
field group.  Paths without an existing proven write fixture are marked
``observed_needs_write_test``; registering a field never authorizes a network
write and never invents a Ctrip payload.
"""

from __future__ import annotations

from .models import ProductFieldSpec


VERIFIED = "verified_write"
RECHECK = "implemented_needs_recheck"
OBSERVED = "observed_needs_write_test"


def _spec(
    code: str,
    label: str,
    draft_type: str,
    module: str,
    path: str,
    value_type: str = "string",
    risk: str = "normal",
    availability: str = OBSERVED,
    *,
    selectors: tuple[str, ...] = (),
    validators: tuple[str, ...] = (),
) -> ProductFieldSpec:
    return ProductFieldSpec(
        code=code,
        label=label,
        draft_type=draft_type,
        module=module,
        path=path,
        value_type=value_type,  # type: ignore[arg-type]
        risk=risk,  # type: ignore[arg-type]
        availability=availability,  # type: ignore[arg-type]
        readback_path=path,
        validators=validators,
        selector_keys=selectors,
    )


_ROWS: tuple[ProductFieldSpec, ...] = (
    # ProductInfo / basic information.  product_name is already represented by
    # the existing ProductInfo save path; the rest require write evidence.
    _spec("product_name", "产品名称", "ProductInfo", "产品信息", "productBasicInfo.name", availability=VERIFIED, validators=("non_empty", "max_length")),
    _spec("product_subtitle", "产品副标题", "ProductInfo", "产品信息", "productBasicInfo.subTitle"),
    _spec("product_note", "产品备注", "ProductInfo", "产品信息", "productBasicInfo.productNote"),
    _spec("vendor_product_id", "供应商产品ID", "ProductInfo", "产品信息", "productBasicInfo.vendorProductId"),
    _spec("vendor_product_name", "供应商产品名称", "ProductInfo", "产品信息", "productBasicInfo.vendorProductName"),
    _spec("product_locale", "产品语言", "ProductInfo", "产品信息", "productBasicInfo.locale", "enum"),
    _spec("district_list", "产品所属地区", "ProductInfo", "产品信息", "productBasicInfo.districtList", "list"),
    _spec("dest_district_list", "目的地地区", "ProductInfo", "产品信息", "productBasicInfo.destDistrictList", "list"),
    _spec("poi_list", "POI/景点关联", "ProductInfo", "产品信息", "productBasicInfo.poiList", "list"),
    _spec("sale_channel_list", "销售渠道", "ProductInfo", "产品信息", "productBasicInfo.saleChannelList", "list"),
    _spec("trip_sales_status", "产品销售状态", "ProductInfo", "产品信息", "productBasicInfo.tripSalesStatus", "enum", "sensitive"),
    _spec("local_time", "当地时间", "ProductInfo", "产品信息", "productBasicInfo.localTime", "time"),
    _spec("duration_type", "产品时长类型", "ProductInfo", "产品信息", "productBasicInfo.durationType", "enum"),
    _spec("travel_duration_min", "最短游玩时长", "ProductInfo", "产品信息", "productBasicInfo.travelDurationMin", "integer", validators=("non_negative",)),
    _spec("travel_duration_max", "最长游玩时长", "ProductInfo", "产品信息", "productBasicInfo.travelDurationMax", "integer", validators=("non_negative", "gte_travel_duration_min")),
    _spec("travel_duration_unit", "游玩时长单位", "ProductInfo", "产品信息", "productBasicInfo.travelDurationUnit", "enum"),
    _spec("description_property_list", "SIM/eSIM玩法属性", "ProductInfo", "产品信息", "productBasicInfo.descriptionPropertyList", "list"),
    _spec("sub_name_required", "子名称必填", "ProductInfo", "产品信息", "productBasicInfo.subNameRequired", "boolean"),
    _spec("overseas_property", "海外属性", "ProductInfo", "产品信息", "productBasicInfo.overseasProperty", "boolean"),
    _spec("product_relation", "产品关联", "ProductInfo", "产品信息", "productBasicInfo.productRelation", "object"),
    _spec("travel_date_variable", "行程日期可变", "ProductInfo", "产品信息", "productBasicInfo.travelDateVariable", "boolean"),
    _spec("brand_info", "品牌", "ProductInfo", "产品信息", "productBasicInfo.brandInfo", "object"),
    _spec("exhibition_poi_tags", "展览/POI标签", "ProductInfo", "产品信息", "poiTagList", "list"),
    _spec("emergency_contact", "紧急联系人", "ProductInfo", "产品信息", "productBasicInfo.emergencyContact", "object", "sensitive"),
    _spec("service_phone", "服务电话", "ProductInfo", "产品信息", "productBasicInfo.servicePhone", "string", "sensitive"),
    _spec("emergency_phone_list", "应急电话列表", "ProductInfo", "产品信息", "productBasicInfo.emergencyPhoneList", "list", "sensitive"),
    _spec("distribution_phone", "分销联系电话", "ProductInfo", "产品信息", "productBasicInfo.distributionContactPhoneList", "list", "sensitive"),
    _spec("im_contact", "即时通讯账号", "ProductInfo", "产品信息", "productBasicInfo.imId", "string", "sensitive"),
    _spec("local_service_org", "当地服务机构", "ProductInfo", "产品信息", "productBasicInfo.localAgencyId", "string", "sensitive"),
    _spec("sales_whitelist", "售卖白名单", "ProductInfo", "产品信息", "salesWhiteList", "list", "sensitive"),
    _spec("advance_booking_whitelist", "提前预订时间白名单", "ProductInfo", "产品信息", "advanceBookingTimeWhiteList", "list", "sensitive"),

    # ProductInfo / video and descriptions.
    _spec("video_type", "产品视频类型", "ProductInfo", "视频与描述", "videoType", "enum"),
    _spec("trip_video_type", "Trip视频类型", "ProductInfo", "视频与描述", "tripVideoType", "enum"),
    _spec("video_list", "视频列表", "ProductInfo", "视频与描述", "videoList", "video"),
    _spec("product_introduce", "产品介绍", "ProductInfo", "视频与描述", "productDescInfo.productIntroduce", "rich_text"),
    _spec("trip_photo_text_detail", "图文详情", "ProductInfo", "视频与描述", "tripPhotoAndTextDetail", "rich_text"),
    _spec("itinerary_list", "行程列表", "ProductInfo", "视频与描述", "itineraryList", "list"),
    _spec("additional_info_list", "补充说明", "ProductInfo", "视频与描述", "addInfoList", "list"),
    _spec("content_tree_list", "内容树", "ProductInfo", "视频与描述", "contentTreeList", "list"),
    _spec("description_rules", "说明规则", "ProductInfo", "视频与描述", "rules", "list"),
    _spec("range_list", "适用范围", "ProductInfo", "视频与描述", "rangeList", "list"),
    _spec("image_content_info_list", "图片内容信息", "ProductInfo", "视频与描述", "imageContentInfoList", "list"),
    _spec("trip_image_content_info_list", "Trip图片内容信息", "ProductInfo", "视频与描述", "tripImageContentInfoList", "list"),
    _spec("keep_c_end_consistent", "保持C端一致", "ProductInfo", "视频与描述", "keepCEndConsistent", "boolean"),
    _spec("image_offline_notice", "图片下线提示", "ProductInfo", "视频与描述", "imageOfflineNotice", "boolean"),

    # Activity, gifts and lifecycle are deliberate separate actions later.
    _spec("comment_reward", "评论奖励配置", "ProductInfo", "活动与上下线", "commentRewardInfo", "object", "sensitive"),
    _spec("gift_info", "赠品配置", "ProductInfo", "活动与上下线", "giftInfo", "object", "sensitive"),
    _spec("recommend_activity", "推荐活动信息", "ProductInfo", "活动与上下线", "productRecommendActivityInfo", "object"),
    _spec("addition_sale_list", "附加售卖列表", "ProductInfo", "活动与上下线", "productAdditionSaleInfo.additionSaleList", "list"),
    _spec("launch_setting_list", "上架/下架控制", "ProductInfo", "活动与上下线", "launchSettingList", "list", "high"),
    _spec("site_launch_scope", "站点/渠道上架范围", "ProductInfo", "活动与上下线", "launchSettingList", "list", "high"),
    _spec("audit_submit", "提交审核", "ProductInfo", "活动与上下线", "submitAudit", "boolean", "high"),
    _spec("draft_save", "草稿保存", "ProductInfo", "活动与上下线", "saveDraft", "boolean", "high"),
    _spec("formal_effect", "正式生效", "ProductInfo", "活动与上下线", "formalEffect", "boolean", "high"),
    _spec("multilingual_publish", "多语言发布", "ProductInfo", "活动与上下线", "multilingualPublish", "boolean", "high"),

    # BookingRule: traveller/contact and booking limits.
    _spec("contact_phone", "联系人手机号", "BookingRule", "游客与联系人", "productBookingRule.contactPhone", "string", "sensitive"),
    _spec("contact_email", "联系人邮箱", "BookingRule", "游客与联系人", "productBookingRule.contactEmail", "string", "sensitive"),
    _spec("contact_im", "即时通讯账号", "BookingRule", "游客与联系人", "productBookingRule.contactIm", "string", "sensitive"),
    _spec("need_customer_info", "是否需要游客信息", "BookingRule", "游客与联系人", "productBookingRule.needCustomerInfo", "boolean", "high"),
    _spec("customer_fill_mode", "游客填写方式", "BookingRule", "游客与联系人", "productBookingRule.customerFillMode", "enum", "high"),
    _spec("customer_info_item_list", "游客信息字段列表", "BookingRule", "游客与联系人", "productBookingRule.customerInfoItemList", "list", "high"),
    _spec("fill_in_number_limit", "游客填写人数限制", "BookingRule", "游客与联系人", "productBookingRule.fillInNumberLimit", "integer", "high", validators=("non_negative",)),
    _spec("contact_mode", "联系方式模式", "BookingRule", "游客与联系人", "productBookingRule.contactMode", "enum", "sensitive"),
    _spec("support_phone_type", "手机号支持范围", "BookingRule", "游客与联系人", "productBookingRule.supportPhoneType", "enum", "sensitive"),
    _spec("overseas_phone_support", "海外手机号支持", "BookingRule", "游客与联系人", "productBookingRule.overseasPhoneNumberSupport", "boolean", "sensitive"),
    _spec("quantity_unit", "数量单位", "BookingRule", "游客与联系人", "productBookingRule.quantityUnit", "enum"),
    _spec("can_update_contact_info", "联系人信息可修改", "BookingRule", "游客与联系人", "productBookingRule.canUpdateContactInfo", "boolean", "high"),
    _spec("can_modify_order_info", "订单信息可修改", "BookingRule", "游客与联系人", "productBookingRule.canModifyOrderInfo", "boolean", "high"),
    _spec("order_modify_infos", "可修改订单字段", "BookingRule", "游客与联系人", "productBookingRule.orderModifyInfos", "list", "high"),
    _spec("is_limit_booking", "是否限制预订", "BookingRule", "预订限制", "productBookingRule.isLimitBooking", "boolean", "high"),
    _spec("limit_booking_type", "限购类型", "BookingRule", "预订限制", "productBookingRule.limitBookingType", "enum", "high"),
    _spec("unify_limit_sign", "统一限制标识", "BookingRule", "预订限制", "productBookingRule.unifyLimitSign", "boolean", "high"),
    _spec("quantity_limit_rule", "数量限购规则", "BookingRule", "预订限制", "productBookingRule.quantityLimitRule", "object", "high"),
    _spec("member_device_limit_scope", "会员/设备限购范围", "BookingRule", "预订限制", "productBookingRule.memberDeviceLimitScope", "list", "high"),
    _spec("use_quantity_limit_type", "使用数量限制类型", "BookingRule", "预订限制", "productBookingRule.useQuantityLimitType", "enum", "high"),
    _spec("quantity_limit_type_list", "数量限制类型列表", "BookingRule", "预订限制", "productBookingRule.quantityLimitTypeList", "list", "high"),
    _spec("sale_unit_limit_settings", "销售单元限制", "BookingRule", "预订限制", "productBookingRule.useSaleUnitLimitSettings", "list", "high"),
    _spec("mixed_booking_limit", "混合预订限制", "BookingRule", "预订限制", "productBookingRule.mixedBookingLimit", "object", "high"),
    _spec("payment_time_limit", "支付确认时限", "BookingRule", "预订限制", "productBookingRule.paymentTimeLimit", "integer", "high", validators=("non_negative",)),
    _spec("sale_date_enabled", "开售日期启用", "BookingRule", "预订限制", "productBookingRule.saleDateEnabled", "boolean", "high"),
    _spec("sale_date", "开售日期", "BookingRule", "预订限制", "productBookingRule.saleDate", "date", "high"),
    _spec("ip_limit", "IP限制", "BookingRule", "预订限制", "productBookingRule.ipLimit", "object", "high"),
    _spec("sale_channel_limit", "售卖渠道限制", "BookingRule", "预订限制", "productBookingRule.saleChannelLimit", "list", "high"),
    _spec("address_modify_info", "地址修改信息", "BookingRule", "预订限制", "productBookingRule.addressModifyInfo", "object", "high"),
    _spec("combined_booking_limit", "组合预订限制", "BookingRule", "预订限制", "productBookingRule.combinedBookingLimit", "object", "high"),

    # Reserve mode, processing, connection and cancellation.
    _spec("reserve_mode", "预订模式", "ReserveMode", "预订模式与有效期", "productReserveMode.reserveMode", "enum", "high"),
    _spec("use_date_limit", "使用时限类型", "ReserveMode", "预订模式与有效期", "productReserveMode.useDateLimit", "enum", "high"),
    _spec("use_date_limit_same", "套餐使用相同有效期", "ReserveMode", "预订模式与有效期", "productReserveMode.useDateLimitSame", "boolean", "high"),
    _spec("valid_days_after_booking", "预订日起有效天数", "ReserveMode", "预订模式与有效期", "productReserveMode.validDaysAfterBooking", "integer", "high"),
    _spec("day_count_min", "最短有效天数", "ReserveMode", "预订模式与有效期", "productReserveMode.dayCountMin", "integer", "high"),
    _spec("day_count_max", "最长有效天数", "ReserveMode", "预订模式与有效期", "productReserveMode.dayCountMax", "integer", "high"),
    _spec("valid_date_range", "指定有效期", "ReserveMode", "预订模式与有效期", "productReserveMode.validDateRange", "date_range", "high"),
    _spec("date_type", "日期限制类型", "ReserveMode", "预订模式与有效期", "productReserveMode.dateType", "enum", "high"),
    _spec("available_date_list", "可使用日期", "ReserveMode", "预订模式与有效期", "productReserveMode.availableDateList", "list", "high"),
    _spec("unavailable_date_list", "不可使用日期", "ReserveMode", "预订模式与有效期", "productReserveMode.unavailableDateList", "list", "high"),
    _spec("special_date_rule", "特殊日期规则", "ReserveMode", "预订模式与有效期", "productReserveMode.specialDateRule", "list", "high"),
    _spec("expire_time", "过期时间", "ReserveMode", "预订模式与有效期", "productReserveMode.expireTime", "time", "high"),
    _spec("applicable_people_min", "适用人群最小值", "ReserveMode", "预订模式与有效期", "productReserveMode.applicablePeopleMin", "integer", "high"),
    _spec("applicable_people_max", "适用人群最大值", "ReserveMode", "预订模式与有效期", "productReserveMode.applicablePeopleMax", "integer", "high"),
    _spec("vbk_confirm_mode", "VBK确认方式", "BookingRule", "订单处理", "productBookingRule.vbkConfirmMode", "enum", "high"),
    _spec("confirm_order_time", "确认订单时长", "BookingRule", "订单处理", "productBookingRule.confirmOrderTime", "integer", "high"),
    _spec("immediate_confirm", "立即确认", "BookingRule", "订单处理", "productBookingRule.immediateConfirm", "boolean", "high"),
    _spec("confirm_by_use_time", "按使用时间确认", "BookingRule", "订单处理", "productBookingRule.confirmByUseTime", "boolean", "high"),
    _spec("advance_verification", "允许提前核单", "BookingRule", "订单处理", "productBookingRule.advanceVerification", "boolean", "high"),
    _spec("refund_confirm_time", "退订确认时间", "BookingRule", "订单处理", "productBookingRule.refundConfirmTime", "integer", "high"),
    _spec("new_order_notice", "新订通知", "BookingRule", "订单处理", "productBookingRule.newOrderNotice", "boolean", "sensitive"),
    _spec("refund_notice", "退订通知", "BookingRule", "订单处理", "productBookingRule.refundNotice", "boolean", "sensitive"),
    _spec("notice_channels", "通知渠道", "BookingRule", "订单处理", "productBookingRule.noticeChannels", "list", "sensitive"),
    _spec("send_voucher", "向用户发送凭证", "BookingRule", "订单处理", "productBookingRule.sendVoucher", "boolean", "high"),
    _spec("voucher_delivery_mode", "上传凭证方式", "BookingRule", "订单处理", "productBookingRule.voucherDeliveryMode", "enum", "high"),
    _spec("additional_note", "订后出行提醒", "BookingRule", "订单处理", "productBookingRule.additionalNote", "rich_text"),
    _spec("ctrip_process_note", "携程处理注意事项", "BookingRule", "订单处理", "productBookingRule.ctripProcessNote", "rich_text", "sensitive"),
    _spec("order_extend_info", "订单扩展信息", "BookingRule", "订单处理", "productBookingRule.orderExtendInfo", "object"),
    _spec("product_process_info", "产品处理信息", "BookingRule", "订单处理", "productBookingRule.productProcessInfo", "object"),
    _spec("pay_mode", "支付方式", "BookingRule", "订单处理", "productBookingRule.payMode", "enum", "high"),
    _spec("addition_sale_type", "附加售卖类型", "BookingRule", "订单处理", "productBookingRule.additionSaleType", "enum"),
    _spec("dock_vendor_product_id", "对接供应商产品ID", "BookingRule", "对接与续订", "productBookingRule.dockInformation.vendorProductId", "string", "sensitive"),
    _spec("dock_vendor_product_name", "对接供应商产品名称", "BookingRule", "对接与续订", "productBookingRule.dockInformation.vendorProductName", "string", "sensitive"),
    _spec("dock_system", "对接系统", "BookingRule", "对接与续订", "productBookingRule.dockInformation.system", "enum", "high"),
    _spec("dock_information", "对接信息", "BookingRule", "对接与续订", "productBookingRule.dockInformation", "object", "high"),
    _spec("support_lease_renew", "是否支持续订", "BookingRule", "对接与续订", "productBookingRule.supportLeaseRenew", "boolean", "high"),
    _spec("lease_renew_rule", "续订规则", "BookingRule", "对接与续订", "productBookingRule.leaseRenewRule", "object", "high"),
    _spec("cancel_type", "取消类型", "BookingRule", "退改规则", "productBookingRule.cancelType", "enum", "high"),
    _spec("refund_policy_cost_list", "多阶梯退款规则", "BookingRule", "退改规则", "productBookingRule.refundPolicyCostList", "list", "high"),
    _spec("refund_policy_template_id", "退款规则模板ID", "BookingRule", "退改规则", "productBookingRule.refundPolicyTemplateId", "string", "high"),
    _spec("can_partial_refund", "支持部分退", "BookingRule", "退改规则", "productBookingRule.canPartialRefund", "boolean", "high"),
    _spec("no_refund_after_activate", "激活后不可退", "BookingRule", "退改规则", "productBookingRule.noRefundAfterActivate", "boolean", "high"),
    _spec("no_refund_after_reserve", "预约后不可退", "BookingRule", "退改规则", "productBookingRule.noRefundAfterReserve", "boolean", "high"),
    _spec("additional_disclaimers", "附加免责声明", "BookingRule", "退改规则", "productBookingRule.additionalDisclaimers", "rich_text", "high"),
    _spec("overdue_refund", "过期自动退款", "BookingRule", "退改规则", "productBookingRule.overdueRefund", "boolean", "high"),
    _spec("not_send_auto_refund", "未寄出/未自取自动退款", "BookingRule", "退改规则", "productBookingRule.notSendAutoRefund", "boolean", "high"),
    _spec("auto_refund_time", "自动退款时间", "BookingRule", "退改规则", "productBookingRule.autoRefundTime", "time", "high"),
    _spec("special_date_refund_policy", "特殊日期退款策略", "BookingRule", "退改规则", "productBookingRule.specialDateRefundPolicy", "list", "high"),
    _spec("use_change_rule", "改期规则", "BookingRule", "退改规则", "productBookingRule.useChangeRule", "object", "high"),

    # Applicable people.
    _spec("is_applicable_people", "启用适用人群", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.isApplicablePeople", "boolean", "high"),
    _spec("applicable_people_remark", "适用人群说明", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.applicablePeopleRemark", "rich_text"),
    _spec("local_crowd_remark", "当地人群说明", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.localCrowdRemark", "rich_text"),
    _spec("sub_resource_setting_list", "子资源人群设置", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.subResourceSettingList", "list", "high"),
    _spec("crowd_range_type", "人群范围类型", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.crowdRangeType", "enum"),
    _spec("crowd_range_min", "人群范围最小值", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.crowdRangeMin", "integer"),
    _spec("crowd_range_max", "人群范围最大值", "ApplicablePeople", "适用人群", "productApplicablePeopleInfo.crowdRangeMax", "integer"),

    # PackageInfo.  Existing implementation reads packageResourceInfo and
    # locates resources by packageId/resourceId, so those selectors are safe.
    _spec("sale_property_list", "销售属性列表", "PackageInfo", "套餐与销售属性", "productPackageInfo.salePropertyList", "list"),
    _spec("package_active", "套餐有效状态", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].active", "boolean", "high", selectors=("packageId",)),
    _spec("package_name", "套餐名称", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].packageName", selectors=("packageId",)),
    _spec("package_display_order", "套餐显示顺序", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].displayOrder", "integer", selectors=("packageId",)),
    _spec("vendor_package_id", "供应商套餐ID", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].vendorPackageId", availability=VERIFIED, selectors=("packageId", "resourceId")),
    _spec("package_introduction", "套餐说明", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].introduction", "rich_text", availability=VERIFIED, selectors=("packageId",)),
    _spec("quantity_min", "最小可预订份数", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].quantityMin", "integer", selectors=("packageId",), validators=("positive",)),
    _spec("quantity_max", "最大可预订份数", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].quantityMax", "integer", selectors=("packageId",), validators=("gte_quantity_min",)),
    _spec("purchase_quantity_limit", "购买数量上限", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].purchaseQuantityLimit", "integer", selectors=("packageId",)),
    _spec("advance_booking_rule", "提前预订规则", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].advanceBookingRule", "object", selectors=("packageId",)),
    _spec("delivery_info", "配送/寄送/自取信息", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].deliveryInfo", "object", selectors=("packageId",)),
    _spec("resource_active", "资源启停", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].active", "boolean", "high", selectors=("packageId", "resourceId")),
    _spec("resource_quantity", "资源数量", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].quantity", "integer", selectors=("packageId", "resourceId")),
    _spec("resource_relation", "资源组合关系", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].relateId", "string", selectors=("packageId", "resourceId")),
    _spec("connection_system_key", "对接系统主键", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].connectionSystemKey", "string", "sensitive", selectors=("packageId", "resourceId")),
    _spec("connection_property_list", "对接属性列表", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].connectionPropertyList", "list", "sensitive", selectors=("packageId", "resourceId")),
    _spec("connection_code", "供应商套餐对接代码", "PackageInfo", "套餐与销售属性", "productPackageInfo.packageResourceInfo[].resourceInfoList[].connectionPropertyList[]", "string", availability=VERIFIED, selectors=("packageId", "resourceId", "key")),

    # PriceAndStock.  The registry advertises fields but does not construct a
    # price payload until request capture proves the exact route/shape.
    _spec("resource_cost_price", "资源成本价", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].costPrice", "decimal", availability=VERIFIED, selectors=("packageId", "resourceId"), validators=("decimal_non_negative",)),
    _spec("resource_sale_price", "资源售价", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].salePrice", "decimal", "high", selectors=("packageId", "resourceId")),
    _spec("resource_market_price", "资源市场价", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].marketPrice", "decimal", "high", selectors=("packageId", "resourceId")),
    _spec("sale_currency", "售价币种", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].saleCurrency", "enum", "high", selectors=("packageId", "resourceId")),
    _spec("cost_currency", "成本币种", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].costCurrency", "enum", "high", selectors=("packageId", "resourceId")),
    _spec("market_currency", "市场价币种", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].marketCurrency", "enum", "high", selectors=("packageId", "resourceId")),
    _spec("special_price_enabled", "特殊价格开关", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].specialPriceEnabled", "boolean", "high", selectors=("packageId",)),
    _spec("special_price_list", "特殊价格列表", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].specialPriceList", "list", "high", selectors=("packageId",)),
    _spec("resource_price_list", "资源价格列表", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList", "list", "high", selectors=("packageId",)),
    _spec("date_price_list", "日期价格列表", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].datePriceList", "list", "high", selectors=("packageId",)),
    _spec("stock_mode", "库存模式", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].stockMode", "enum", "high", selectors=("packageId", "resourceId")),
    _spec("stock_count", "库存数量", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].stockCount", "integer", "high", selectors=("packageId", "resourceId")),
    _spec("stock_alert_count", "库存预警值", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourcePriceAndStockList[].stockAlertCount", "integer", "high", selectors=("packageId", "resourceId")),
    _spec("resource_stock_list", "资源库存列表", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].resourceStockList", "list", "high", selectors=("packageId",)),
    _spec("shared_stock_relation", "共享库存关系", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].sharedStockRelation", "object", "high", selectors=("packageId",)),
    _spec("shared_resource_stock_list", "资源共享库存列表", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].sharedResourceStockList", "list", "high", selectors=("packageId",)),
    _spec("price_decoration_status", "价格装饰状态", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].priceDecorationStatus", "enum", selectors=("packageId",)),
    _spec("vendor_can_edit_cost_price", "供应商可编辑成本价", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].vendorCanEditCostPrice", "boolean", "high", selectors=("packageId",)),
    _spec("connection_price_update_disabled", "对接禁止更新价格", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].connectionPriceUpdateDisabled", "boolean", "high", selectors=("packageId",)),
    _spec("price_audit_attachment", "价格审核附件", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].priceAuditAttachment", "file", "high", selectors=("packageId",)),
    _spec("price_stock_active", "价格库存启停", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].active", "boolean", "high", selectors=("packageId",)),
    _spec("monthly_price_stock", "资源月历价格库存", "PriceAndStock", "价格与库存", "packagePriceAndStockList[].monthlyPriceStock", "list", "high", selectors=("packageId",)),
    _spec("low_commission_application", "低佣申请", "PriceAndStock", "价格与库存", "lowCommissionApplication", "object", "high"),
    _spec("bid_commission_application", "竞价佣金申请", "PriceAndStock", "价格与库存", "bidCommissionApplication", "object", "high"),
    _spec("negative_margin_handling", "负毛利处理", "PriceAndStock", "价格与库存", "negativeMarginHandling", "object", "high"),
    _spec("price_audit_cancel", "价格审核取消", "PriceAndStock", "价格与库存", "priceAuditCancel", "boolean", "high"),
    _spec("price_formal_effect", "价格正式生效", "PriceAndStock", "价格与库存", "priceFormalEffect", "boolean", "high"),
    _spec("price_stock_submit_audit", "价格库存提交审核", "PriceAndStock", "价格与库存", "priceStockSubmitAudit", "boolean", "high"),
)

FIELD_SPECS: tuple[ProductFieldSpec, ...] = _ROWS
_BY_CODE = {spec.code: spec for spec in FIELD_SPECS}
if len(_BY_CODE) != len(FIELD_SPECS):  # module import must fail loudly on unsafe ambiguity
    raise RuntimeError("产品字段注册表存在重复 code")


def field_spec(code: str) -> ProductFieldSpec:
    try:
        return _BY_CODE[code]
    except KeyError as exc:
        raise KeyError(f"未注册的产品字段：{code}") from exc


def field_specs_for_module(module: str) -> tuple[ProductFieldSpec, ...]:
    return tuple(spec for spec in FIELD_SPECS if spec.module == module)
