"""Configurable, evidence-based routing rules for every message source.

Acquisition and routing are deliberately separate: collectors preserve every
message they capture; this module decides whether a captured message should be
queued for extraction or held for review. No policy rule deletes source data.
"""
from __future__ import annotations

import re
from typing import Any

POLICY_MODES = {"all", "include", "exclude", "real_estate"}
RULE_FIELDS = {
    "text", "source", "source_ref", "posted_at", "channel",
    "message_length", "has_link", "has_attachment", "attachment_count", "sender",
}
RULE_OPERATORS = {
    "contains", "not_contains", "equals", "not_equals", "starts_with",
    "ends_with", "regex", "not_regex", "greater_than", "less_than", "before", "after",
    "is_empty", "is_not_empty", "in_list", "not_in_list",
}


def default_collection_policy(mode: str = "all") -> dict[str, Any]:
    return {
        "version": 1,
        "mode": mode if mode in POLICY_MODES else "all",
        "logic": "all",
        "rules": [],
        "keep_unmatched_in_inbox": True,
    }


def validate_collection_policy(value: Any) -> dict[str, Any]:
    if value is None:
        return default_collection_policy()
    if not isinstance(value, dict):
        raise ValueError("Collection policy must be a JSON object.")
    mode = str(value.get("mode") or "all").strip().lower()
    if mode not in POLICY_MODES:
        raise ValueError("Choose Capture all, Keep matching, Exclude matching or Real-estate preset.")
    logic = str(value.get("logic") or "all").strip().lower()
    if logic not in {"all", "any"}:
        raise ValueError("Rule logic must be 'all' or 'any'.")
    raw_rules = value.get("rules") or []
    if not isinstance(raw_rules, list) or len(raw_rules) > 50:
        raise ValueError("A collection policy can contain up to 50 rules.")
    rules = []
    for index, raw in enumerate(raw_rules, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"Rule {index} must be an object.")
        field = str(raw.get("field") or "text").strip()
        operator = str(raw.get("operator") or "contains").strip()
        rule_value = str(raw.get("value") or "").strip()
        if field not in RULE_FIELDS:
            raise ValueError(f"Rule {index}: unsupported field '{field}'.")
        if operator not in RULE_OPERATORS:
            raise ValueError(f"Rule {index}: unsupported operator '{operator}'.")
        if operator not in {"is_empty", "is_not_empty"} and not rule_value:
            raise ValueError(f"Rule {index}: enter a value for this condition.")
        if len(rule_value) > 500:
            raise ValueError(f"Rule {index}: values are limited to 500 characters.")
        if operator in {"regex", "not_regex"}:
            # Keep the power of regex while rejecting common catastrophic
            # backtracking constructs in user-supplied expressions.
            if len(rule_value) > 160 or re.search(r"\([^)]*[+*][^)]*\)[+*{]", rule_value) or re.search(r"\\[1-9]", rule_value):
                raise ValueError(f"Rule {index}: this regular expression is too complex or unsafe.")
            try:
                re.compile(rule_value, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Rule {index}: invalid regular expression: {exc}") from exc
        rules.append({"field": field, "operator": operator, "value": rule_value})
    if mode in {"include", "exclude"} and not rules:
        raise ValueError("Add at least one condition before enabling a custom filter.")
    return {
        "version": 1,
        "mode": mode,
        "logic": logic,
        "rules": rules,
        # Non-matching messages remain available in the inbox with status
        # 'filtered'; they are not silently discarded.
        "keep_unmatched_in_inbox": True,
    }


def _real_estate_match(text: str, channel_hint: str = "") -> tuple[bool, str]:
    normalized = re.sub(r"\s+", " ", str(text or "").replace("ي", "ی").replace("ك", "ک")).strip().lower()
    if len(normalized) < 15:
        return False, "Real-estate preset: message is too short to be a listing."
    property_terms = ("ویلایی", "ویلا", "آپارتمان", "اپارتمان", "زمین", "تجاری", "مغازه", "باغ", "سوله", "اداری", "سوئیت", "ملک", "خانه", "منزل", "دفتر")
    rent_terms = ("اجاره", "رهن", "رهن کامل", "قابل تبدیل", "مستاجر", "مستاجری", "استیجاری")
    detail_terms = ("متر", "متراژ", "خواب", "طبقه", "پارکینگ", "انباری", "آسانسور", "کابینت", "حیاط", "آدرس", "لوکیشن", "خیابان", "بلوار", "سند")
    score = 0
    hits = []
    p = [x for x in property_terms if x in normalized]
    r = [x for x in rent_terms if x in normalized]
    d = [x for x in detail_terms if x in normalized]
    if p: score += 3; hits.append("property terms: " + ", ".join(p[:3]))
    if r: score += 4; hits.append("rental terms: " + ", ".join(r[:3]))
    if d: score += min(3, len(d)); hits.append("property details: " + ", ".join(d[:3]))
    if re.search(r"\d[\d,.]*\s*(?:میلیون|میلیارد|تومان|متر)", normalized): score += 2; hits.append("price/area pattern")
    if re.search(r"(?:09|\+?98)\d{8,11}", normalized): score += 1; hits.append("contact number")
    if re.search(r"#[\w\u0600-\u06ff]+", normalized): score += 1; hits.append("hashtag")
    rental_channel = any(x in str(channel_hint).lower() for x in ("اجاره", "استیجاری", "رهن", "rental", "rent"))
    threshold = 4 if rental_channel else 5
    matched = score >= threshold
    return matched, ("Real-estate preset matched: " if matched else "Real-estate preset did not match: ") + ("; ".join(hits) if hits else "no listing indicators") + f" (score {score}/{threshold})."


def _context_value(field: str, context: dict[str, Any]) -> Any:
    text = str(context.get("text") or "")
    if field == "message_length": return len(text)
    if field == "has_link": return bool(re.search(r"https?://|www\.", text, re.I))
    if field == "has_attachment": return bool(context.get("has_attachment") or context.get("attachments"))
    if field == "attachment_count": return int(context.get("attachment_count") or len(context.get("attachments") or []))
    if field == "channel": return context.get("channel") or context.get("source_ref") or ""
    return context.get(field, "")


def _rule_matches(rule: dict[str, str], context: dict[str, Any]) -> bool:
    actual = _context_value(rule["field"], context)
    expected = rule["value"]
    op = rule["operator"]
    if op == "is_empty": return actual is None or str(actual).strip() == "" or actual is False
    if op == "is_not_empty": return not (actual is None or str(actual).strip() == "" or actual is False)
    if isinstance(actual, bool):
        wanted = expected.lower() in {"1", "true", "yes", "on", "بله"}
        if op in {"equals", "in_list"}: return actual == wanted
        if op in {"not_equals", "not_in_list"}: return actual != wanted
        return False
    actual_text = str(actual if actual is not None else "")
    left, right = actual_text.casefold(), expected.casefold()
    if op == "contains": return right in left
    if op == "not_contains": return right not in left
    if op == "equals": return left == right
    if op == "not_equals": return left != right
    if op == "starts_with": return left.startswith(right)
    if op == "ends_with": return left.endswith(right)
    if op == "regex": return bool(re.search(expected, actual_text, re.I))
    if op == "not_regex": return not bool(re.search(expected, actual_text, re.I))
    if op == "before": return left < right
    if op == "after": return left > right
    if op in {"in_list", "not_in_list"}:
        choices = [x.strip().casefold() for x in re.split(r"[,\n]", expected) if x.strip()]
        found = left in choices
        return found if op == "in_list" else not found
    if op in {"greater_than", "less_than"}:
        try:
            a, b = float(actual_text.replace(",", "")), float(expected.replace(",", ""))
            return a > b if op == "greater_than" else a < b
        except ValueError:
            return False
    return False


def evaluate_collection_policy(policy: dict[str, Any] | None, context: dict[str, Any], native_decision: dict[str, Any] | None = None) -> tuple[bool, str]:
    policy = validate_collection_policy(policy or default_collection_policy())
    mode = policy["mode"]
    if mode == "all": return True, "Capture all: no content filter applied."
    if mode == "real_estate":
        if isinstance(native_decision, dict) and native_decision.get("mode") == "real_estate":
            matched = bool(native_decision.get("matched"))
            return matched, str(native_decision.get("reason") or "Built-in real-estate classification rules")
        return _real_estate_match(str(context.get("text") or ""), str(context.get("channel") or context.get("source") or ""))
    results = [_rule_matches(rule, context) for rule in policy["rules"]]
    matched = all(results) if policy["logic"] == "all" else any(results)
    selected = matched if mode == "include" else not matched
    reason = f"Custom {policy['logic'].upper()} rules: {sum(results)}/{len(results)} conditions matched. "
    reason += "Included in extraction queue." if selected else "Held by collection policy; original message is retained."
    return selected, reason
