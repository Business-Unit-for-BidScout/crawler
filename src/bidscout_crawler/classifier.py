import json
import os
import re
import urllib.request
from dataclasses import asdict, dataclass

CLASSES = {"procurement_notice", "award_or_result_notice", "procurement_change_notice", "contract_notice", "other_procurement_related", "not_procurement", "uncertain"}
AWARD = ("中标候选", "中标公告", "中标结果", "成交公告", "成交结果", "结果公告", "结果公示", "入围结果")
CHANGE = ("更正公告", "变更公告", "延期公告", "终止公告", "废标公告", "流标公告", "暂停公告")
CONTRACT = ("合同公告", "采购合同", "合同公示", "合同备案")
PROCURE = ("招标公告", "采购公告", "采购意向", "竞争性磋商", "竞争性谈判", "询价公告", "比选公告", "单一来源", "市场调研", "需求调查", "征集公告", "遴选公告")
RELATED = ("采购", "招标", "投标", "成交", "中标", "询价", "磋商", "比选", "竞价", "合同")

@dataclass
class Classification:
    primary_class: str
    confidence: float
    reason: str
    supporting_quotes: list[str]
    needs_human_review: bool
    method: str
    def to_dict(self): return asdict(self)

def _quotes(text, words, limit=3):
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines()]
    return [x[:240] for x in lines if any(w in x for w in words)][:limit]

def classify_rules(title, text):
    content = f"{title}\n{text}"[:200000]
    groups = (
        ("award_or_result_notice", AWARD, .96, "正文包含明确的中标、成交或结果公告表述"),
        ("procurement_change_notice", CHANGE, .96, "正文包含明确的更正、延期、终止、废标或流标表述"),
        ("contract_notice", CONTRACT, .95, "正文包含明确的合同公告或合同公示表述"),
        ("procurement_notice", PROCURE, .94, "正文包含明确的采购意向、招标、询价、磋商或比选表述"),
    )
    for label, words, confidence, reason in groups:
        if any(w in content for w in words): return Classification(label, confidence, reason, _quotes(content, words), False, "rules")
    if any(w in content for w in RELATED): return Classification("other_procurement_related", .70, "内容与采购相关，但公告阶段不明确", _quotes(content, RELATED), True, "rules")
    if len(text.strip()) < 80: return Classification("uncertain", .25, "正文过短或抽取不足", [title[:240]], True, "rules")
    return Classification("not_procurement", .72, "未发现明确采购公告证据", [title[:240]], False, "rules")

def classify_ai(title, text, source_name):
    key = os.getenv("OPENAI_API_KEY")
    if not key: return None
    base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = "你是公告分类器，不筛选商业价值。只能选择：" + ",".join(sorted(CLASSES)) + "。输出JSON：primary_class, confidence, reason, supporting_quotes, needs_human_review。证据不足选uncertain。\n" + f"来源：{source_name}\n标题：{title}\n正文：{text[:30000]}"
    payload = json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(base + "/chat/completions", data=payload, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "BidScout-Crawler/0.1"})
    with urllib.request.urlopen(req, timeout=90) as r: d = json.load(r)
    raw = d["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S)
    result = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
    label = result.get("primary_class")
    if label not in CLASSES: raise ValueError("invalid class")
    source = f"{title}\n{text}"
    quotes = [str(x)[:240] for x in result.get("supporting_quotes", [])[:3] if str(x) in source]
    if not quotes and label != "uncertain": raise ValueError("unverifiable evidence")
    return Classification(label, float(result.get("confidence", 0)), str(result.get("reason", ""))[:500], quotes, bool(result.get("needs_human_review", label == "uncertain")), f"ai:{model}")

def classify(title, text, source_name):
    try:
        return classify_ai(title, text, source_name) or classify_rules(title, text)
    except Exception as exc:
        result = classify_rules(title, text)
        result.reason += f"；AI失败后规则回退：{type(exc).__name__}"
        return result
