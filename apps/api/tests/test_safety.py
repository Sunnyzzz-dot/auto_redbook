from app.services.safety import rule_check


def test_rule_check_blocks_sensitive_topics() -> None:
    report = rule_check("稳赚无风险", "贷款套现教程", ["副业"])

    assert report["level"] == "block"
    assert any(hit["type"] == "sensitive_topic" for hit in report["hits"])


def test_rule_check_passes_normal_content() -> None:
    report = rule_check("通勤包分享", "这几个收纳细节很实用", ["穿搭", "包包"])

    assert report["level"] == "pass"
