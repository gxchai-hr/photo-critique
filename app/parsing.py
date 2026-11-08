"""模型输出的解析与硬校验。

只依赖标准库，方便在装不上第三方包的机器上跑回归测试。
"""
from __future__ import annotations

import json
import re

BREAKDOWN_KEYS = ["构图", "用光", "色彩", "主题表达", "技术完成度", "标题匹配度"]


class FormatError(ValueError):
    """模型返回内容无法作为结果使用。"""


def extract_json(text: str) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise FormatError("模型没有返回内容")
    s = text.strip()
    s = re.sub(r"^```(?:json|JSON)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    if not (s.startswith("{") and s.endswith("}")):
        start, end = s.find("{"), s.rfind("}")
        if start < 0 or end <= start:
            raise FormatError("模型没有返回 JSON 对象")
        s = s[start:end + 1]
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", s)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise FormatError("模型返回内容不是合法 JSON") from exc
    if not isinstance(obj, dict):
        raise FormatError("模型返回的不是 JSON 对象")
    return obj


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False).strip()
    return "" if value is None else str(value).strip()


def _int(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(float(value))))
    except (TypeError, ValueError):
        return default


def _evidence_items(raw, label_key: str) -> list[dict]:
    items = raw if isinstance(raw, list) else []
    out = []
    for item in items:
        if isinstance(item, dict):
            point = _text(item.get(label_key) or item.get("point") or item.get("issue") or item.get("text"))
            evidence = _text(item.get("evidence") or item.get("画面证据") or item.get("说明"))
        else:
            point, evidence = _text(item), ""
        if point or evidence:
            out.append({"point": point, "evidence": evidence})
    return out


def validate_result(obj: dict) -> tuple[dict, list[str]]:
    """返回 (规范化结果, 警告列表)。结构性不合规直接抛 FormatError，触发一次重试。"""
    warnings: list[str] = []
    flag = obj.get("is_photograph")
    if not isinstance(flag, bool):
        raise FormatError("缺少有效的 is_photograph 布尔字段")

    if flag is False:
        reason = _text(obj.get("reject_reason")) or "这张图不属于相机实拍的摄影作品。"
        # 硬门控：拒绝时丢弃模型可能顺手生成的任何评分与点评。
        return {"is_photograph": False, "reject_reason": reason}, warnings

    score = _int(obj.get("score"), 0, 100, -1)
    if score < 0:
        raise FormatError("缺少有效的综合评分")

    breakdown = {}
    raw_bd = obj.get("score_breakdown")
    if isinstance(raw_bd, dict):
        for key in BREAKDOWN_KEYS:
            if key in raw_bd:
                breakdown[key] = _int(raw_bd[key], 0, 100, 0)

    highlights = _evidence_items(obj.get("highlights"), "point")
    problems = _evidence_items(obj.get("problems"), "issue")
    if len(highlights) < 3 or len(problems) < 3:
        raise FormatError("技术亮点或核心问题不足 3 条")

    suggestions = [_text(x) for x in (obj.get("suggestions") or []) if _text(x)] if isinstance(obj.get("suggestions"), list) else []
    if not suggestions:
        raise FormatError("缺少针对性的修改建议")

    title_raw = obj.get("title_analysis")
    title_analysis = None
    if isinstance(title_raw, list):
        title_analysis = [_text(x) for x in title_raw if _text(x)]
        if len(title_analysis) < 2:
            warnings.append("标题分析角度不足 2 个，可重试一次")
    elif isinstance(title_raw, str) and title_raw.strip():
        title_analysis = [title_raw.strip()]
        warnings.append("标题分析角度不足 2 个，可重试一次")

    ai_suspect = bool(obj.get("ai_suspect"))
    ai_downgraded = bool(obj.get("ai_downgraded"))
    if ai_suspect and not ai_downgraded:
        # 规则兜底：模型没降档，后端按约定强制降 10 分。
        score = max(0, score - 10)
        ai_downgraded = True
        warnings.append("模型未执行 AI 降档，已由服务端按规则扣减 10 分")

    if breakdown:
        mean = round(sum(breakdown.values()) / len(breakdown))
        if abs(score - mean) > 8:
            warnings.append(f"总分 {score} 与分项均值 {mean} 偏差较大，评分仅供参考")

    result = {
        "is_photograph": True,
        "reject_reason": "",
        "subject": _text(obj.get("subject")),
        "first_impression": _text(obj.get("first_impression")),
        "score": score,
        "score_breakdown": breakdown,
        "score_reason": _text(obj.get("score_reason")),
        "title_analysis": title_analysis,
        "highlights": highlights,
        "problems": problems,
        "suggestions": suggestions,
        "ai_suspect": ai_suspect,
        "ai_downgraded": ai_downgraded,
        "ai_evidence": _text(obj.get("ai_evidence")),
    }
    return result, warnings


def flatten_content(content) -> str:
    """兼容 content 为字符串或 OpenAI 风格的多段数组。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return ""
