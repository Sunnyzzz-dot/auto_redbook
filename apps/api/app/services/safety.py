from __future__ import annotations

from typing import Any

ABSOLUTE_CLAIMS = ["最有效", "百分百", "永久", "根治", "稳赚", "无风险", "第一", "唯一"]
CONTACT_WORDS = ["微信", "加V", "私信领", "手机号", "二维码"]
SENSITIVE_TOPICS = ["处方药", "贷款套现", "暴富", "代孕", "赌博"]


def rule_check(title: str, body: str, hashtags: list[str]) -> dict[str, Any]:
    text = f"{title}\n{body}\n{' '.join(hashtags)}"
    hits: list[dict[str, str]] = []
    for word in ABSOLUTE_CLAIMS:
        if word in text:
            hits.append({"type": "absolute_claim", "word": word})
    for word in CONTACT_WORDS:
        if word in text:
            hits.append({"type": "off_platform_contact", "word": word})
    for word in SENSITIVE_TOPICS:
        if word in text:
            hits.append({"type": "sensitive_topic", "word": word})

    level = "pass"
    if hits:
        level = "review"
    if any(hit["type"] == "sensitive_topic" for hit in hits):
        level = "block"
    return {"level": level, "hits": hits}
