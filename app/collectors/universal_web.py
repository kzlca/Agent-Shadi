"""Evidence-based web connector helpers.

This module never executes pasted HTML or AI-generated code. It only parses HTML,
validates CSS selectors and returns data extracted from a live browser page.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any
from bs4 import BeautifulSoup, Tag, Comment
from urllib.parse import urlsplit, urlunsplit
from soupsieve import SelectorSyntaxError

MAX_HTML = 250_000
MAX_SELECTOR = 500
_FIELD_NAMES = ("text", "sender", "timestamp", "message_id", "attachment")


def _soup(source: str) -> BeautifulSoup:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Provide an HTML sample first.")
    if len(source) > MAX_HTML:
        raise ValueError(f"HTML sample is too large. Limit: {MAX_HTML:,} characters per sample.")
    return BeautifulSoup(source, "html.parser")


def _css_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _selector_for(node: Tag) -> str | None:
    """Build a compact evidence-backed selector for one element."""
    if node.get("data-message-id") is not None:
        return "[data-message-id]"
    for attr in ("data-testid", "data-test-id", "data-qa", "data-cy"):
        value = node.get(attr)
        if isinstance(value, str) and value.strip():
            return f'[{attr}="{_css_quote(value.strip())}"]'
    node_id = node.get("id")
    if isinstance(node_id, str) and node_id.strip() and not re.search(r"\d{4,}", node_id):
        return f'#{node_id.strip()}'.replace(" ", "")
    classes = [str(x) for x in (node.get("class") or []) if re.fullmatch(r"[A-Za-z_-][\w-]*", str(x))]
    stable = [x for x in classes if not re.search(r"(?:^|[-_])[a-f0-9]{6,}|\d{4,}", x, re.I)]
    if stable:
        return node.name + "".join("." + x for x in stable[:2])
    role = node.get("role")
    if isinstance(role, str) and role.strip():
        return f'[role="{_css_quote(role.strip())}"]'
    return node.name if node.name in {"article", "li", "time"} else None


def _safe_select(soup: BeautifulSoup | Tag, selector: str) -> list[Tag]:
    selector = str(selector or "").strip()
    if not selector:
        return []
    if len(selector) > MAX_SELECTOR:
        raise ValueError(f"CSS selector exceeds {MAX_SELECTOR} characters.")
    if "javascript:" in selector.lower() or "<script" in selector.lower():
        raise ValueError("A selector must be CSS, not executable code or HTML.")
    try:
        return [x for x in soup.select(selector) if isinstance(x, Tag)]
    except (SelectorSyntaxError, Exception) as exc:
        raise ValueError(f"Invalid CSS selector `{selector}`: {str(exc)[:180]}") from exc


def _candidate_selectors(node: Tag) -> list[str]:
    """Return stable selector alternatives, preserving independent evidence."""
    selectors: list[str] = []
    if node.get("data-message-id") is not None:
        selectors.append("[data-message-id]")
    for attr in ("data-testid", "data-test-id", "data-qa", "data-cy"):
        value = node.get(attr)
        if isinstance(value, str) and value.strip():
            selectors.append(f'[{attr}="{_css_quote(value.strip())}"]')
    node_id = node.get("id")
    if isinstance(node_id, str) and node_id.strip() and not re.search(r"\d{4,}", node_id):
        selectors.append(f'#{node_id.strip()}'.replace(" ", ""))
    classes = [str(x) for x in (node.get("class") or []) if re.fullmatch(r"[A-Za-z_-][\w-]*", str(x))]
    stable = [x for x in classes if not re.search(r"(?:^|[-_])[a-f0-9]{6,}|\d{4,}", x, re.I)]
    if stable:
        selectors.append(node.name + "".join("." + x for x in stable[:2]))
    role = node.get("role")
    if isinstance(role, str) and role.strip():
        selectors.append(f'[role="{_css_quote(role.strip())}"]')
    if node.name in {"article", "li", "time"}:
        selectors.append(node.name)
    return list(dict.fromkeys(selectors))


def _node_text(node: Tag) -> str:
    return " ".join(node.get_text(" ", strip=True).split())[:1200]


_AI_SAFE_ATTRIBUTES = {
    "class", "id", "role", "aria-label", "aria-labelledby", "aria-owns",
    "data-testid", "data-test-id", "data-qa", "data-cy", "data-message-id",
    "data-time", "data-timestamp", "datetime", "href", "src", "alt",
    "title", "type", "name", "rel", "target",
}
_AI_DROP_TAGS = {"script", "style", "noscript", "iframe", "object", "embed",
                 "svg", "canvas", "template", "meta", "link", "head"}


def compact_html_for_model(source: str, max_chars: int, *, max_nodes: int = 180,
                           max_text_chars: int = 2600) -> str:
    """Return a small, inert DOM excerpt for LLM analysis.

    The original HTML remains untouched for local inspection/validation. This
    serializer removes scripts, styles, event handlers, bulky attributes and
    tracking query strings, then caps nodes/text and prunes from the end while
    preserving well-formed HTML.
    """
    if not source or not str(source).strip() or max_chars <= 0:
        return ""
    soup = BeautifulSoup(str(source), "html.parser")
    for node in list(soup.find_all(list(_AI_DROP_TAGS))):
        node.decompose()

    for tag in soup.find_all(True):
        clean = {}
        for key, value in (tag.attrs or {}).items():
            key = str(key).lower()
            if key not in _AI_SAFE_ATTRIBUTES:
                continue
            if isinstance(value, list):
                value = " ".join(str(x) for x in value[:8])
            value = " ".join(str(value).split())
            if not value or value.lower().startswith("data:"):
                continue
            if key in {"href", "src"}:
                try:
                    parts = urlsplit(value)
                    if parts.scheme or parts.netloc:
                        value = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
                    else:
                        value = urlunsplit(("", "", parts.path, "", ""))
                except Exception:
                    pass
            limit = 220 if key in {"href", "src"} else (180 if key in {"class", "aria-label", "title", "alt"} else 100)
            value = value[:limit]
            if key == "class":
                value = " ".join(value.split()[:8])
            if value:
                clean[key] = value
        tag.attrs = clean

    all_tags = list(soup.find_all(True))
    for tag in reversed(all_tags[max(1, max_nodes):]):
        if tag.parent is not None:
            tag.decompose()

    remaining_text = max(0, min(max_text_chars, max_chars // 2))
    for node in list(soup.find_all(string=True)):
        if isinstance(node, Comment):
            node.extract()
            continue
        text_value = " ".join(str(node).split())
        if not text_value or remaining_text <= 0:
            node.extract()
            continue
        clipped = text_value[:remaining_text]
        remaining_text -= len(clipped)
        if clipped != str(node):
            node.replace_with(clipped)

    rendered = str(soup)
    # Keep the output syntactically useful instead of cutting through a tag.
    # Removing tail-most elements preserves the leading message samples.
    while len(rendered) > max_chars:
        candidates = [tag for tag in soup.find_all(True) if tag.name not in {"html", "body"}]
        if not candidates:
            break
        candidates[-1].decompose()
        rendered = str(soup)
    if len(rendered) > max_chars:
        # Extreme attribute-only fragments: remove the remaining tree safely.
        soup.clear()
        rendered = str(soup)[:max_chars]
    return rendered


def compact_html_samples_for_model(individual_html: str, list_html: str,
                                  total_chars: int = 7500) -> tuple[str, str]:
    """Compact both samples under one predictable character budget."""
    if list_html and list_html.strip():
        individual_budget = min(2800, max(1500, int(total_chars * 0.38)))
        list_budget = max(500, total_chars - individual_budget)
    else:
        individual_budget, list_budget = total_chars, 0
    individual = compact_html_for_model(individual_html, individual_budget,
                                        max_nodes=100, max_text_chars=1600)
    listing = compact_html_for_model(list_html, list_budget,
                                     max_nodes=220, max_text_chars=max(1000, list_budget // 2)) if list_budget else ""
    # In unusual trees, serialized tag overhead can consume the allocated
    # budgets. Make a final proportional pass to enforce the combined limit.
    excess = len(individual) + len(listing) - total_chars
    if excess > 0:
        listing = compact_html_for_model(listing, max(500, len(listing) - excess),
                                         max_nodes=180, max_text_chars=max(500, (len(listing) - excess) // 2))
    return individual, listing


def compact_analysis_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Keep the most useful deterministic selector evidence within a small prompt budget."""
    candidates = []
    for item in (evidence.get("message_candidates") or [])[:8]:
        candidates.append({
            "selector": str(item.get("selector") or "")[:180],
            "tag": str(item.get("tag") or "")[:24],
            "count": int(item.get("count") or 0),
            "evidence": list(item.get("evidence") or [])[:4],
            "examples": [str(x)[:70] for x in (item.get("examples") or [])[:1]],
        })
    fields = {}
    for field in _FIELD_NAMES:
        fields[field] = [{
            "selector": str(x.get("selector") or "")[:180],
            "attribute": str(x.get("attribute") or "textContent")[:40],
            "tag": str(x.get("tag") or "")[:24],
            "sample": str(x.get("sample") or "")[:65],
        } for x in (evidence.get("field_candidates", {}).get(field) or [])[:4]]
    return {
        "individual_sample": evidence.get("individual_sample") or {},
        "list_sample": evidence.get("list_sample") or {},
        "message_candidates": candidates,
        "field_candidates": fields,
        "warnings": [str(x)[:180] for x in (evidence.get("warnings") or [])[:4]],
    }



def detect_eitaa_preset(individual_html: str, list_html: str = "") -> dict[str, Any] | None:
    """Return a deterministic, evidence-backed Eitaa public-channel connector preset."""
    source = f"{individual_html or ''}\n{list_html or ''}"
    if not any(token in source for token in ("etme_widget_message_wrap", "etme_channel_history", "js-message_history")):
        return None
    # Selectors are based on the supplied Eitaa DOM: the message wrapper owns
    # its numeric id; the <time datetime> carries an ISO-8601 timestamp; and
    # data-before is the site's older-history pagination cursor.
    return {
        "version": 1,
        "site_preset": "eitaa",
        "root": {"method": "css", "selector": "div.etme_widget_message_wrap.js-widget_message_wrap"},
        "fields": {
            "text": {"selector": ".etme_widget_message_text.js-message_text", "attribute": "textContent"},
            "sender": {"selector": ".etme_widget_message_author .etme_widget_message_owner_name", "attribute": "textContent"},
            "timestamp": {"selector": ".etme_widget_message_date time", "attribute": "datetime"},
            "message_id": {"selector": ":root", "attribute": "id"},
            "attachment": {"selector": ".etme_widget_message_photo_wrap", "attribute": "href"},
        },
        "navigation": {
            "strategy": "pagination",
            "scroll_selector": ".etme_channel_history.js-message_history",
            "button_selector": "a.js-messages_more[data-before]",
            "direction": "up",
            "wait_ms": 1200,
            "wait_mode": "adaptive",
            "min_wait_ms": 250,
            "max_wait_ms": 8000,
            "stable_ms": 350,
            "scroll_step_ratio": 0.78,
            "max_idle_cycles": 6,
            "timestamp_timezone": "Asia/Tehran",
            "max_scrolls": 500,
        },
        "deduplication": {"method": "message_id_or_fingerprint"},
    }

def analyze_html(individual_html: str, list_html: str = "") -> dict[str, Any]:
    """Suggest selectors from real HTML evidence; no selectors are invented."""
    individual = _soup(individual_html)
    list_soup = _soup(list_html) if list_html.strip() else individual
    candidates: dict[str, dict[str, Any]] = {}
    for node in list_soup.find_all(True):
        for selector in _candidate_selectors(node):
            try:
                matches = _safe_select(list_soup, selector)
            except ValueError:
                continue
            if len(matches) < 1:
                continue
            # Candidate signatures must actually match elements of the supplied DOM.
            item = candidates.setdefault(selector, {"selector": selector, "tag": node.name, "count": len(matches), "examples": [], "evidence": []})
            if len(item["examples"]) < 2:
                item["examples"].append(_node_text(node)[:180])
            for attr in ("data-message-id", "data-testid", "role", "aria-label"):
                if node.get(attr) is not None and attr not in item["evidence"]:
                    item["evidence"].append(attr)
    repeated = [x for x in candidates.values() if x["count"] >= 2]
    repeated.sort(key=lambda x: (x["count"] >= 3, bool(x["evidence"]), x["count"], len(x["selector"])), reverse=True)
    repeated = repeated[:30]

    # The individual message is used to suggest its field selectors.
    message_root = individual.find(True)
    field_candidates: dict[str, list[dict[str, Any]]] = {k: [] for k in _FIELD_NAMES}
    if message_root:
        for node in individual.find_all(True):
            selector = _selector_for(node)
            if not selector:
                continue
            txt = _node_text(node)
            if node.name == "time" or any(node.get(a) for a in ("datetime", "data-time", "data-timestamp")):
                field_candidates["timestamp"].append({"selector": selector, "attribute": "datetime" if node.get("datetime") else ("data-time" if node.get("data-time") else "textContent"), "sample": txt[:100], "tag": node.name})
            cls = " ".join(node.get("class") or []).lower()
            attrs = " ".join(f"{k}={v}" for k, v in node.attrs.items() if isinstance(v, (str, int))).lower()
            if any(word in cls + " " + attrs for word in ("author", "sender", "username", "user-name", "participant")):
                field_candidates["sender"].append({"selector": selector, "attribute": "textContent", "sample": txt[:100], "tag": node.name})
            if node.name in {"img", "a", "video", "audio"} or node.get("src") or node.get("href"):
                field_candidates["attachment"].append({"selector": selector, "attribute": "src" if node.get("src") else ("href" if node.get("href") else "textContent"), "sample": str(node.get("alt") or node.get("href") or txt)[:100], "tag": node.name})
            if txt and len(txt) >= 2:
                field_candidates["text"].append({"selector": selector, "attribute": "textContent", "sample": txt[:100], "tag": node.name})
            if node.get("data-message-id") is not None:
                # When the message identifier lives on the message root itself,
                # the browser must read it from :root rather than searching for
                # a matching descendant that does not exist.
                field_selector = ":root" if node is message_root else selector
                field_candidates["message_id"].append({"selector": field_selector, "attribute": "data-message-id", "sample": str(node.get("data-message-id"))[:100], "tag": node.name})

    for field, items in field_candidates.items():
        # Favor semantic evidence, useful non-empty text, and shorter selectors.
        items.sort(key=lambda x: (field == "text" and len(x.get("sample", "")), field == "timestamp" and x["tag"] == "time", field == "attachment" and x["tag"] in {"img", "a"}, -len(x["selector"])), reverse=True)
        field_candidates[field] = items[:12]

    result = {
        "ok": True,
        "individual_sample": {"elements": len(individual.find_all(True)), "text_length": len(individual.get_text(" ", strip=True))},
        "list_sample": {"provided": bool(list_html.strip()), "elements": len(list_soup.find_all(True)), "text_length": len(list_soup.get_text(" ", strip=True))},
        "message_candidates": repeated,
        "field_candidates": field_candidates,
        "warnings": [] if list_html.strip() else ["Only one message sample was supplied. Provide the parent HTML containing several repeated messages to verify message boundaries."],
    }
    preset = detect_eitaa_preset(individual_html, list_html)
    if preset:
        result["site_preset"] = "eitaa"
        result["recommended_config"] = preset
        result["preset_explanations"] = {
            "root": "Eitaa message wrapper; one repeated element per post.",
            "text": "Message body inside the Eitaa message wrapper.",
            "sender": "Author name inside the message header.",
            "timestamp": "Exact ISO timestamp from the time datetime attribute.",
            "message_id": "Numeric message ID stored on the wrapper itself.",
            "navigation": "Older posts loaded through the data-before pagination link.",
        }
        result["warnings"].append("Eitaa structure detected. The recommended selectors and date-aware pagination are based on the supplied DOM; validate them against the full surrounding list before saving.")
    return result


def validate_selectors(list_html: str, config: dict[str, Any]) -> dict[str, Any]:
    soup = _soup(list_html)
    root_selector = str((config.get("root") or {}).get("selector") or "").strip()
    if not root_selector:
        raise ValueError("Set a message root CSS selector before validating.")
    roots = _safe_select(soup, root_selector)
    field_defs = config.get("fields") if isinstance(config.get("fields"), dict) else {}
    fields: dict[str, Any] = {}
    preview: list[dict[str, Any]] = []
    for field_name in _FIELD_NAMES:
        definition = field_defs.get(field_name) or {}
        selector = str(definition.get("selector") or "").strip()
        attr = str(definition.get("attribute") or "textContent")
        covered = 0
        samples: list[str] = []
        for root in roots:
            target = root if not selector or selector == ":root" else (_safe_select(root, selector) or [None])[0]
            value = ""
            if target is not None:
                if attr in {"textContent", "innerText"}:
                    value = _node_text(target)
                elif attr == "outerHTML":
                    value = str(target)[:1200]
                else:
                    raw = target.get(attr)
                    if raw is not None:
                        value = " ".join(raw) if isinstance(raw, list) else str(raw)
                value = value.strip()
            if value:
                covered += 1
                if len(samples) < 3:
                    samples.append(value[:180])
        if selector:
            fields[field_name] = {"selector": selector, "attribute": attr, "matched": covered, "total": len(roots), "coverage": round(covered / max(1, len(roots)) * 100), "samples": samples}
        else:
            fields[field_name] = {"selector": "", "attribute": attr, "matched": 0, "total": len(roots), "coverage": 0, "samples": [], "optional": True}
    for root in roots[:10]:
        row: dict[str, Any] = {}
        for field_name in ("text", "sender", "timestamp", "message_id"):
            definition = field_defs.get(field_name) or {}
            selector = str(definition.get("selector") or "").strip()
            attr = str(definition.get("attribute") or "textContent")
            target = root if not selector or selector == ":root" else (_safe_select(root, selector) or [None])[0]
            if target is None:
                row[field_name] = ""
            elif attr in {"textContent", "innerText"}:
                row[field_name] = _node_text(target)
            else:
                raw = target.get(attr, "")
                row[field_name] = " ".join(raw) if isinstance(raw, list) else str(raw)
        preview.append(row)
    warnings = []
    if len(roots) < 2:
        warnings.append("The root selector matches fewer than two messages. Verify the parent HTML and message boundary before activation.")
    if not fields["text"].get("matched"):
        warnings.append("The text field currently matches no message. A collector without message text is not ready.")
    elif fields["text"]["coverage"] < 100:
        warnings.append("Some matched messages have no text under the current selector.")
    return {"ok": True, "root": {"selector": root_selector, "matched": len(roots)}, "fields": fields, "preview": preview, "warnings": warnings, "ready": len(roots) >= 2 and fields["text"].get("coverage", 0) > 0}


def normalize_connector_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Connector configuration must be a JSON object.")
    name = str(payload.get("name") or "").strip()
    url = str(payload.get("url") or "").strip()
    if not name:
        raise ValueError("Enter a connector name.")
    if len(name) > 120:
        raise ValueError("Connector name must be 120 characters or fewer.")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a valid http:// or https:// website URL without embedded credentials.")
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    # Normalize legacy connectors that used the older Eitaa public-channel DOM.
    # This preset repair is evidence-based and keeps the user's channel identity,
    # persistent-session policy and explanatory metadata intact.
    legacy_root = str(((config.get("root") or {}).get("selector") if isinstance(config.get("root"), dict) else "") or "")
    legacy_text = str((((config.get("fields") or {}).get("text") or {}).get("selector") if isinstance(config.get("fields"), dict) and isinstance((config.get("fields") or {}).get("text"), dict) else "") or "")
    legacy_host = (parsed.hostname or "").lower()
    if (config.get("site_preset") == "eitaa" or legacy_host in {"eitaa.com", "www.eitaa.com"}) and ("etme_widget_message" in legacy_root or "etme_widget_message" in legacy_text):
        known_preset = detect_eitaa_preset("<div class='etme_widget_message_wrap etme_channel_history'>", "")
        if known_preset:
            preserved = {key: config[key] for key in ("channel", "session", "ai_explanations") if key in config}
            config = {**config, **known_preset, **preserved}
    root = config.get("root") if isinstance(config.get("root"), dict) else {}
    root_selector = str(root.get("selector") or "").strip()
    if root_selector and (len(root_selector) > MAX_SELECTOR or "javascript:" in root_selector.lower()):
        raise ValueError("Message root must be a CSS selector of 500 characters or fewer.")
    method = str(root.get("method") or "css")
    if method != "css":
        raise ValueError("This build executes CSS selectors. Unsupported selector method: " + method)
    fields = config.get("fields") if isinstance(config.get("fields"), dict) else {}
    clean_fields = {}
    for field in _FIELD_NAMES:
        definition = fields.get(field) if isinstance(fields.get(field), dict) else {}
        selector = str(definition.get("selector") or "").strip()
        attribute = str(definition.get("attribute") or "textContent").strip()
        if len(selector) > MAX_SELECTOR:
            raise ValueError(f"{field} selector exceeds {MAX_SELECTOR} characters.")
        if attribute not in {"textContent", "innerText", "outerHTML", "href", "src", "datetime", "data-time", "data-timestamp", "data-message-id", "alt", "title"}:
            if not re.fullmatch(r"[a-zA-Z_:][a-zA-Z0-9_.:-]{0,79}", attribute):
                raise ValueError(f"Invalid HTML attribute for {field}.")
        clean_fields[field] = {"selector": selector, "attribute": attribute}
    navigation = config.get("navigation") if isinstance(config.get("navigation"), dict) else {}
    strategy = str(navigation.get("strategy") or "manual")
    if strategy not in {"manual", "scroll_container", "infinite_scroll", "load_more", "pagination"}:
        raise ValueError("Unsupported navigation strategy.")
    date_range_mode = str(navigation.get("date_range_mode") or "auto").strip().lower()
    if date_range_mode not in {"auto", "manual"}:
        raise ValueError("Date-range navigation mode must be auto or manual.")
    direction = str(navigation.get("direction") or "up")
    if direction not in {"up", "down"}:
        raise ValueError("Navigation direction must be up or down.")
    wait_ms = int(navigation.get("wait_ms") or 1200)
    if not 250 <= wait_ms <= 10000:
        raise ValueError("Wait time must be between 250 and 10,000 milliseconds.")
    wait_mode = str(navigation.get("wait_mode") or "adaptive").strip().lower()
    if wait_mode not in {"adaptive", "fixed"}:
        raise ValueError("Wait mode must be adaptive or fixed.")
    min_wait_ms = int(navigation.get("min_wait_ms") or 250)
    max_wait_ms = int(navigation.get("max_wait_ms") or max(8000, min_wait_ms))
    stable_ms = int(navigation.get("stable_ms") or 350)
    if not 100 <= min_wait_ms <= 5000:
        raise ValueError("Minimum adaptive wait must be between 100 and 5,000 milliseconds.")
    if not min_wait_ms <= max_wait_ms <= 15000:
        raise ValueError("Maximum adaptive wait must be at least the minimum and no more than 15,000 milliseconds.")
    if not 50 <= stable_ms <= 2500:
        raise ValueError("DOM stability window must be between 50 and 2,500 milliseconds.")
    raw_scroll_step_ratio = navigation.get("scroll_step_ratio", 0.78)
    scroll_step_ratio = float(0.78 if raw_scroll_step_ratio is None else raw_scroll_step_ratio)
    if not 0.2 <= scroll_step_ratio <= 1.5:
        raise ValueError("Scroll step ratio must be between 0.2 and 1.5 viewport heights.")
    scroll_amount_px = int(navigation.get("scroll_amount_px") or 0)
    if not 0 <= scroll_amount_px <= 10000:
        raise ValueError("Fixed scroll amount must be between 0 and 10,000 pixels (0 = viewport ratio).")
    max_idle_cycles = int(navigation.get("max_idle_cycles") or 6)
    if not 1 <= max_idle_cycles <= 20:
        raise ValueError("Maximum idle cycles must be between 1 and 20.")
    timestamp_timezone = str(navigation.get("timestamp_timezone") or "UTC").strip()[:80]
    if not timestamp_timezone:
        timestamp_timezone = "UTC"
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo(timestamp_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown timestamp timezone: {timestamp_timezone}") from exc
    channel_cfg = config.get("channel") if isinstance(config.get("channel"), dict) else {}
    target_url = str(channel_cfg.get("target_url") or "").strip()
    channel_username = str(channel_cfg.get("username") or "").strip().lstrip("@")
    site_preset = str(config.get("site_preset") or "").strip().lower()
    connector_host = (parsed.hostname or "").lower()
    if not site_preset and (connector_host == "eitaa.com" or connector_host.endswith(".eitaa.com")):
        site_preset = "eitaa"

    # Older Eitaa drafts often put the public channel URL in the Website URL
    # field. That field is the authenticated application entrypoint, while the
    # channel URL belongs in channel.target_url. Migrate this known public
    # origin to the web client and preserve the original canonical URL.
    if site_preset == "eitaa" and connector_host in {"eitaa.com", "www.eitaa.com"}:
        canonical_url = target_url or url
        if not target_url:
            target_url = canonical_url
        if not channel_username and canonical_url:
            try:
                canonical_parts = urlsplit(canonical_url)
                hash_match = re.search(r"(?:^|[#/@])@?([A-Za-z][A-Za-z0-9_]{2,})", canonical_parts.fragment)
                path_parts = [part for part in canonical_parts.path.split("/") if part]
                candidate = (hash_match.group(1) if hash_match else (path_parts[-1] if path_parts else "")).strip().lstrip("@")
                if candidate and not candidate.isdigit() and candidate.lower() not in {"channel", "user", "c", "index.php"}:
                    channel_username = candidate
            except Exception:
                pass
        url = "https://web.eitaa.com/"
        parsed = urlparse(url)
        connector_host = "web.eitaa.com"

    target_url_template = str(channel_cfg.get("target_url_template") or "").strip()
    if len(target_url_template) > 2000:
        raise ValueError("Target URL template must be 2,000 characters or fewer.")
    allowed_route_tokens = {"app_origin", "app_url", "username", "platform_id", "name", "target_url"}
    route_tokens = re.findall(r"\{([a-z_]+)\}", target_url_template)
    unknown_route_tokens = sorted(set(route_tokens) - allowed_route_tokens)
    residue = re.sub(r"\{[a-z_]+\}", "", target_url_template)
    if unknown_route_tokens or "{" in residue or "}" in residue:
        raise ValueError("Unknown token in target URL template. Supported tokens: " + ", ".join("{" + x + "}" for x in sorted(allowed_route_tokens)) + ".")
    if not target_url_template and connector_host == "web.eitaa.com" and channel_username:
        target_url_template = "{app_origin}/#@{username}"
    if target_url:
        target_parsed = urlparse(target_url)
        if (target_parsed.scheme not in {"http", "https"} or not target_parsed.hostname
                or target_parsed.username or target_parsed.password):
            raise ValueError("Direct channel URL must be a valid http:// or https:// URL without embedded credentials.")
        if len(target_url) > 2000:
            raise ValueError("Direct channel URL must be 2,000 characters or fewer.")
    identity_selector = str(channel_cfg.get("identity_selector") or "").strip()
    if len(identity_selector) > MAX_SELECTOR or "javascript:" in identity_selector.lower():
        raise ValueError("Active identity selector must be CSS of 500 characters or fewer.")
    if identity_selector:
        try:
            from soupsieve import compile as compile_css_selector
            compile_css_selector(identity_selector)
        except Exception as exc:
            raise ValueError(f"Invalid active identity CSS selector: {exc}") from exc
    identity_attribute = str(channel_cfg.get("identity_attribute") or "data-peer-id").strip()
    if identity_attribute not in {"textContent", "innerText", "id", "title", "aria-label", "href"} and not re.fullmatch(r"data-[a-zA-Z0-9_.:-]{1,70}", identity_attribute):
        raise ValueError("Unsupported active identity attribute. Use visible text or a standard data-* attribute.")
    session_cfg = config.get("session") if isinstance(config.get("session"), dict) else {}
    persist_session = session_cfg.get("persist", True)
    if not isinstance(persist_session, bool):
        persist_session = True
    return {
        "name": name,
        "url": url,
        "description": str(payload.get("description") or "")[:1000],
        "config": {
            "version": 1,
            **({"site_preset": site_preset} if site_preset == "eitaa" else {}),
            "channel": {
                "name": str(channel_cfg.get("name") or "")[:160],
                "target_url": target_url,
                "target_url_template": target_url_template,
                "username": channel_username[:160],
                "platform_id": str(channel_cfg.get("platform_id") or "").strip()[:160],
                "identity_selector": identity_selector,
                "identity_attribute": identity_attribute,
                "search_input_selector": str(channel_cfg.get("search_input_selector") or "")[:MAX_SELECTOR],
                "search_result_selector": str(channel_cfg.get("search_result_selector") or "")[:MAX_SELECTOR],
            },
            "root": {"method": "css", "selector": root_selector},
            "fields": clean_fields,
            "session": {"persist": persist_session},
            "navigation": {
                "strategy": strategy,
                "date_range_mode": date_range_mode,
                "scroll_selector": str(navigation.get("scroll_selector") or "")[:MAX_SELECTOR],
                "button_selector": str(navigation.get("button_selector") or "")[:MAX_SELECTOR],
                "previous_page_selector": str(navigation.get("previous_page_selector") or "")[:MAX_SELECTOR],
                "next_page_selector": str(navigation.get("next_page_selector") or "")[:MAX_SELECTOR],
                "direction": direction,
                "wait_ms": wait_ms,
                "wait_mode": wait_mode,
                "min_wait_ms": min_wait_ms,
                "max_wait_ms": max_wait_ms,
                "stable_ms": stable_ms,
                "scroll_step_ratio": scroll_step_ratio,
                "scroll_amount_px": scroll_amount_px,
                "max_idle_cycles": max_idle_cycles,
                "timestamp_timezone": timestamp_timezone,
                "max_scrolls": max(1, min(500, int(navigation.get("max_scrolls") or 30))),
            },
            "deduplication": {"method": str(((config.get("deduplication") or {}).get("method") if isinstance(config.get("deduplication"), dict) else "") or "message_id_or_fingerprint")},
            "ai_explanations": config.get("ai_explanations") if isinstance(config.get("ai_explanations"), dict) else {},
        },
    }
