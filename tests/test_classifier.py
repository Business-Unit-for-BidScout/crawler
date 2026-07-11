from bidscout_crawler.classifier import classify_rules

def test_classes():
    cases = {
        "procurement_notice": "某医院设备采购公告 竞争性磋商",
        "award_or_result_notice": "某项目中标结果公告",
        "procurement_change_notice": "采购项目更正公告 延期开标",
        "contract_notice": "政府采购合同公告",
        "other_procurement_related": "采购工作情况说明",
        "not_procurement": "医院开展世界读书日健康科普活动，欢迎群众参加。" * 5,
        "uncertain": "通知",
    }
    for expected, text in cases.items():
        assert classify_rules(text, text).primary_class == expected
