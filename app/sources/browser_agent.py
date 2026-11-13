"""Evidence-driven, source-neutral browser observation and bounded actions.

The agent observes rendered, visible UI and uses a deliberately small action
vocabulary. Page text is data, never executable instructions. Credentials and
input values are excluded from observations.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse


OBSERVE_SCRIPT = r"""() => {
 const visible = el => { const r=el.getBoundingClientRect(),s=getComputedStyle(el); return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden'; };
 const text = el => String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim().slice(0,420);
 const selector = el => {
   for (const a of ['data-testid','data-qa','data-cy','data-peer-id','data-message-id','aria-label','placeholder','name']) {
     const v=el.getAttribute(a); if(v && !/["\\]/.test(v)) { const q=`[${a}="${v}"]`; try { if(document.querySelectorAll(q).length===1) return q; } catch {} }
   }
   if(el.id && !/\d{4,}/.test(el.id)) return '#'+CSS.escape(el.id);
   const cls=[...el.classList].filter(x=>/^[\w-]+$/.test(x)&&!/[a-f0-9]{8,}|\d{4,}/i.test(x)).slice(0,2);
   const base=el.tagName.toLowerCase()+cls.map(x=>'.'+CSS.escape(x)).join('');
   try { if(document.querySelectorAll(base).length===1) return base; } catch {}
   const siblings=el.parentElement?[...el.parentElement.children].filter(x=>x.tagName===el.tagName):[];
   return base+`:nth-of-type(${Math.max(1,siblings.indexOf(el)+1)})`;
 };
 const nodes=[...document.querySelectorAll('a,button,input,textarea,select,[role="button"],[role="link"],[role="option"],[role="tab"],[contenteditable="true"]')].filter(visible).slice(0,180);
 const controls=nodes.map(el=>({tag:el.tagName.toLowerCase(),role:el.getAttribute('role')||'',type:el.getAttribute('type')||'',name:el.getAttribute('name')||'',autocomplete:el.getAttribute('autocomplete')||'',text:text(el),aria:el.getAttribute('aria-label')||'',placeholder:el.getAttribute('placeholder')||'',href:el.getAttribute('href')||'',selector:selector(el),peer_id:el.getAttribute('data-peer-id')||el.closest('[data-peer-id]')?.getAttribute('data-peer-id')||'',disabled:!!el.disabled}));
 const candidates=new Map();
 for(const el of document.querySelectorAll('article,[role="article"],[role="listitem"],li,[data-message-id],[data-testid]')){
   if(!visible(el)) continue; const t=text(el); if(t.length<20||t.length>6000) continue;
   const s=selector(el),v=candidates.get(s)||{selector:s,count:0,samples:[]}; v.count++; if(v.samples.length<3&&!v.samples.includes(t))v.samples.push(t); candidates.set(s,v);
 }
 const repeated=[...candidates.values()].filter(x=>x.count>=2&&x.count<=3000).sort((a,b)=>b.count-a.count).slice(0,24);
 const scrollables=[...document.querySelectorAll('*')].filter(el=>{if(!visible(el))return false;const s=getComputedStyle(el);return /(auto|scroll)/.test(s.overflowY)&&el.scrollHeight>el.clientHeight+80;}).slice(0,30).map(el=>({selector:selector(el),scroll_top:el.scrollTop,scroll_height:el.scrollHeight,client_height:el.clientHeight,visible_text:text(el).slice(0,160)}));
 const body=String(document.body?.innerText||'').replace(/\s+/g,' ').trim().slice(0,12000);
 const messageNodes=[...document.querySelectorAll('[data-message-id],.message,article,[role="article"]')].filter(visible).slice(0,80);
 return {url:location.href,title:document.title,ready_state:document.readyState,body_text:body,body_chars:(document.body?.innerText||'').length,controls,repeated_candidates:repeated,scrollables,visible_content_count:messageNodes.length,active_element:{tag:document.activeElement?.tagName?.toLowerCase()||'',role:document.activeElement?.getAttribute('role')||'',placeholder:document.activeElement?.getAttribute('placeholder')||''}};
}"""


def observe_page(page) -> dict[str, Any]:
    raw = page.evaluate(OBSERVE_SCRIPT)
    compact = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    raw["observation_hash"] = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:20]
    return raw


def validate_action(action: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict):
        raise ValueError("An agent action must be an object.")
    kind = str(action.get("type") or "").strip().lower()
    if kind not in {"click", "fill", "press", "scroll", "wait", "navigate"}:
        raise ValueError("Unsupported browser action. Allowed: click, fill, press, scroll, wait, navigate.")
    out: dict[str, Any] = {"type": kind}
    if kind in {"click", "fill", "press"}:
        selector = str(action.get("selector") or "").strip()
        if not selector or len(selector) > 500 or any(x in selector.lower() for x in ("javascript:", "<script", "=>", "function(")):
            raise ValueError("A bounded CSS selector is required for this action.")
        out["selector"] = selector
    if kind == "fill":
        value = str(action.get("value") or "")
        if len(value) > 2000:
            raise ValueError("Input text exceeds 2,000 characters.")
        out["value"] = value
    if kind == "press":
        key = str(action.get("key") or "Enter").strip()
        if key not in {"Enter", "Escape", "Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"}:
            raise ValueError("Unsupported key.")
        out["key"] = key
    if kind == "scroll":
        direction = str(action.get("direction") or "down").lower()
        if direction not in {"up", "down", "left", "right"}:
            raise ValueError("Unsupported scroll direction.")
        out.update(direction=direction, amount=max(100, min(1200, int(action.get("amount") or 650))))
        selector = str(action.get("selector") or "").strip()
        if selector:
            if len(selector) > 500: raise ValueError("Scroll selector is too long.")
            out["selector"] = selector
    if kind == "wait":
        out["milliseconds"] = max(100, min(5000, int(action.get("milliseconds") or 800)))
    if kind == "navigate":
        url = str(action.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Navigation requires a credential-free HTTP(S) URL.")
        out["url"] = url[:2000]
    return out


def execute_action(page, action: dict[str, Any]) -> dict[str, Any]:
    action = validate_action(action)
    before = observe_page(page)
    kind = action["type"]
    if kind == "click":
        locator = page.locator(action["selector"]).first
        locator.wait_for(state="visible", timeout=7000)
        locator.click(timeout=7000)
    elif kind == "fill":
        locator = page.locator(action["selector"]).first
        locator.wait_for(state="visible", timeout=7000)
        locator.fill(action["value"], timeout=7000)
    elif kind == "press":
        page.locator(action["selector"]).first.press(action["key"], timeout=7000)
    elif kind == "scroll":
        amount = action["amount"] * (-1 if action["direction"] in {"up", "left"} else 1)
        if action.get("selector"):
            page.locator(action["selector"]).first.evaluate("(el, delta) => el.scrollBy({top:delta,left:delta,behavior:'instant'})", amount)
        else:
            page.mouse.wheel(0 if action["direction"] in {"left", "right"} else amount,
                             amount if action["direction"] in {"left", "right"} else 0)
    elif kind == "wait":
        page.wait_for_timeout(action["milliseconds"])
    elif kind == "navigate":
        page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(350)
    after = observe_page(page)
    changed = before["observation_hash"] != after["observation_hash"]
    return {"action": action, "changed": changed, "before": before, "after": after,
            "evidence": {"url_changed": before["url"] != after["url"],
                         "title_changed": before["title"] != after["title"],
                         "content_count_before": before["visible_content_count"],
                         "content_count_after": after["visible_content_count"],
                         "body_chars_before": before["body_chars"],
                         "body_chars_after": after["body_chars"]}}
