"""Generic rendered-page adapter for authenticated and public browser sources.

It consumes an already-open Playwright page. Session creation, sign-in and
operator confirmation stay with the browser runtime/inspector. No platform URLs
or channel-specific selectors are embedded here.
"""
from __future__ import annotations

from typing import Any

from .contracts import CaptureBatch, SourceInspection, SourceItem, SourceKind, SourceSpec


_DISCOVER_SCRIPT = r"""() => {
  const norm = value => String(value || '').replace(/\s+/g, ' ').trim();
  const candidates = new Map();
  const nodes = document.querySelectorAll('article,[role="article"],[role="listitem"],li,[data-message-id],[data-testid]');
  for (const node of nodes) {
    const text = norm(node.innerText || node.textContent);
    if (text.length < 12 || text.length > 12000) continue;
    let selector = '';
    if (node.hasAttribute('data-message-id')) selector = '[data-message-id]';
    else if (node.hasAttribute('data-testid')) {
      const value = node.getAttribute('data-testid');
      if (value && !/["\\]/.test(value)) selector = `[data-testid="${value}"]`;
    }
    if (!selector && node.id && !/\d{4,}/.test(node.id)) selector = `#${CSS.escape(node.id)}`;
    if (!selector && node.classList && node.classList.length) {
      const stable = [...node.classList].filter(x => /^[A-Za-z_-][\w-]*$/.test(x) && !/[a-f0-9]{8,}|\d{4,}/i.test(x)).slice(0, 2);
      if (stable.length) selector = node.tagName.toLowerCase() + stable.map(x => `.${CSS.escape(x)}`).join('');
    }
    if (!selector) selector = node.tagName.toLowerCase();
    const prior = candidates.get(selector) || {selector, count: 0, samples: []};
    prior.count += 1;
    if (prior.samples.length < 3 && !prior.samples.includes(text.slice(0, 180))) prior.samples.push(text.slice(0, 180));
    candidates.set(selector, prior);
  }
  return [...candidates.values()].filter(x => x.count >= 2 && x.count <= 2000)
    .sort((a,b) => (b.count - a.count) || (a.selector.length - b.selector.length)).slice(0, 20);
}"""

_CAPTURE_SCRIPT = r"""(nodes) => nodes.map((node, index) => {
  const text = String(node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim();
  const time = node.querySelector('time[datetime],time[title],[data-timestamp]');
  const author = node.querySelector('[rel="author"],[data-author], [class*="author"], [class*="sender"]');
  const link = node.querySelector('a[href]');
  const stableId = node.getAttribute('data-message-id') || node.getAttribute('data-id') || node.id || '';
  return {index, text, stable_id: stableId, published_at: time?.getAttribute('datetime') || time?.getAttribute('data-timestamp') || time?.getAttribute('title') || '',
    author: String(author?.innerText || author?.textContent || '').trim().slice(0,160), href: link?.href || '',
    tag: node.tagName.toLowerCase()};
})"""


class BrowserDOMSourceAdapter:
    name = "browser_dom"
    kinds = (SourceKind.BROWSER,)

    def inspect(self, source: SourceSpec, **context: Any) -> SourceInspection:
        page = context.get("page")
        if page is None:
            return SourceInspection(source, False, warnings=["An open authenticated browser page is required."])
        try:
            state = page.evaluate("() => ({title: document.title, url: location.href, ready: document.readyState, text: (document.body?.innerText || '').length})")
            candidates = page.evaluate(_DISCOVER_SCRIPT)
            return SourceInspection(source, True, title=str(state.get("title") or ""),
                                    content_type="text/html", capabilities=["inspect_dom", "sample", "capture", "pagination_probe"],
                                    item_candidates=candidates,
                                    evidence={"url": state.get("url"), "ready_state": state.get("ready"),
                                              "visible_text_chars": state.get("text"), "candidate_count": len(candidates)})
        except Exception as exc:
            return SourceInspection(source, False, warnings=[f"Could not inspect the rendered page: {str(exc)[:240]}"])

    def sample(self, source: SourceSpec, limit: int = 10, **context: Any) -> CaptureBatch:
        return self.capture(source, limit=limit, **context)

    def capture(self, source: SourceSpec, limit: int = 1000, cursor: str | None = None,
                **context: Any) -> CaptureBatch:
        page = context.get("page")
        selector = str(context.get("item_selector") or source.options.get("item_selector") or "").strip()
        text_selector = str(context.get("text_selector") or source.options.get("text_selector") or "").strip()
        if page is None:
            raise ValueError("An open authenticated browser page is required.")
        if not selector:
            inspection = self.inspect(source, page=page)
            return CaptureBatch(source, [], complete=False,
                                warnings=["No item selector has been validated. Inspect candidates and approve one before capture."],
                                diagnostics={"candidates": inspection.item_candidates}).validate()
        if len(selector) > 500 or any(x in selector.lower() for x in ("javascript:", "<script", "=>", "function(")):
            raise ValueError("The item selector must be a CSS selector, not executable code.")
        locator = page.locator(selector)
        count = locator.count()
        start = int(cursor or 0)
        end = min(count, start + max(1, min(int(limit), 10000)))
        # Evaluate a bounded slice in the page context; avoid serializing the full DOM.
        raw_items = locator.evaluate_all(_CAPTURE_SCRIPT) [start:end]
        items: list[SourceItem] = []
        for row in raw_items:
            content = row.get("text") or ""
            if text_selector:
                try:
                    content = locator.nth(int(row["index"])).locator(text_selector).inner_text(timeout=1500)
                except Exception:
                    content = ""
            if not str(content).strip():
                continue
            stable_id = str(row.get("stable_id") or row.get("href") or f"{selector}:{row.get('index')}")
            items.append(SourceItem(content=str(content), source_id=source.id, source_label=source.label,
                                    source_uri=source.uri or str(page.url), item_id=stable_id,
                                    item_type="web_item", published_at=row.get("published_at") or None,
                                    author=row.get("author") or "", content_type="text/html",
                                    metadata={"selector": selector, "dom_index": row.get("index"),
                                              "tag": row.get("tag"), "href": row.get("href") or ""}))
        return CaptureBatch(source, items, complete=end >= count,
                            cursor=None if end >= count else str(end),
                            diagnostics={"selector": selector, "matched_nodes": count,
                                         "range": [start, end], "captured_nonempty": len(items),
                                         "page_url": str(page.url)}).validate()
