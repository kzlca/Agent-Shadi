import unittest

from app.collectors.universal_web import analyze_html, validate_selectors, normalize_connector_payload
from app.collectors.web_inspector import WebInspectorManager, _SCAN_PAGE_SCRIPT, _CAPTURE_SCRIPT


EITAA_INDIVIDUAL = '''
<div class="etme_widget_message_wrap js-widget_message_wrap date_visible" id="4270">
  <div class="etme_widget_message" data-post="channel/4270">
    <div class="etme_widget_message_author accent_color"><a class="etme_widget_message_owner_name"><span dir="auto">Channel Author</span></a></div>
    <div class="etme_widget_message_text js-message_text" dir="rtl">Example property message</div>
    <div class="etme_widget_message_footer compact js-message_footer">
      <span class="etme_widget_message_meta"><a class="etme_widget_message_date"><time datetime="2026-07-01T08:03:09+00:00" class="time">۱۱:۳۳</time></a></span>
    </div>
  </div>
</div>'''

EITAA_LIST = '''
<div class="etme_container">
<section class="etme_channel_history js-message_history">
 <div class="etme_widget_message_centered js-messages_more_wrap"><a href="/channel?before=4269" class="js-messages_more" data-before="4269">Older</a></div>
 <div class="etme_widget_message_wrap js-widget_message_wrap" id="4269">
  <div class="etme_widget_message" data-post="channel/4269">
   <div class="etme_widget_message_author accent_color"><a class="etme_widget_message_owner_name">Author One</a></div>
   <div class="etme_widget_message_text js-message_text">Older body</div>
   <span class="etme_widget_message_meta"><a class="etme_widget_message_date"><time datetime="2026-06-30T08:00:00+00:00">۱۱:۳۰</time></a></span>
  </div>
 </div>
 <div class="etme_widget_message_wrap js-widget_message_wrap" id="4270">
  <div class="etme_widget_message" data-post="channel/4270">
   <div class="etme_widget_message_author accent_color"><a class="etme_widget_message_owner_name">Author Two</a></div>
   <div class="etme_widget_message_text js-message_text">Newer body</div>
   <span class="etme_widget_message_meta"><a class="etme_widget_message_date"><time datetime="2026-07-01T08:03:09+00:00">۱۱:۳۳</time></a></span>
  </div>
 </div>
 <div><a href="/channel?after=4270" class="js-messages_more" data-after="4270">Newer</a></div>
</section></div>'''


class EitaaPresetTests(unittest.TestCase):
    def test_eitaa_dom_gets_exact_timestamp_id_and_pagination_preset(self):
        result = analyze_html(EITAA_INDIVIDUAL, EITAA_LIST)
        self.assertEqual(result.get("site_preset"), "eitaa")
        config = result["recommended_config"]
        self.assertEqual(config["root"]["selector"], "div.etme_widget_message_wrap.js-widget_message_wrap")
        self.assertEqual(config["fields"]["timestamp"], {"selector": ".etme_widget_message_date time", "attribute": "datetime"})
        self.assertEqual(config["fields"]["message_id"], {"selector": ":root", "attribute": "id"})
        self.assertEqual(config["navigation"]["strategy"], "pagination")
        self.assertEqual(config["navigation"]["button_selector"], "a.js-messages_more[data-before]")

    def test_eitaa_preset_validates_against_repeated_message_roots(self):
        config = analyze_html(EITAA_INDIVIDUAL, EITAA_LIST)["recommended_config"]
        validation = validate_selectors(EITAA_LIST, config)
        self.assertEqual(validation["root"]["matched"], 2)
        self.assertEqual(validation["fields"]["text"]["coverage"], 100)
        self.assertEqual(validation["fields"]["sender"]["coverage"], 100)
        self.assertEqual(validation["fields"]["timestamp"]["samples"][0], "2026-06-30T08:00:00+00:00")
        self.assertEqual(validation["fields"]["message_id"]["samples"][0], "4269")
        self.assertTrue(validation["ready"])

    def test_connector_normalizer_keeps_eitaa_pagination_and_selectors(self):
        config = analyze_html(EITAA_INDIVIDUAL, EITAA_LIST)["recommended_config"]
        item = normalize_connector_payload({"name": "Eitaa", "url": "https://eitaa.com/channel", "config": config})
        self.assertEqual(item["config"]["navigation"]["strategy"], "pagination")
        self.assertEqual(item["config"]["fields"]["timestamp"]["attribute"], "datetime")


class FakePage:
    def __init__(self, pages, first_url):
        self.pages = pages
        self.url = first_url
        self.waits = []
        self.goto_calls = []

    def evaluate(self, script, args):
        if script != _SCAN_PAGE_SCRIPT:
            raise AssertionError("Unexpected browser script")
        return self.pages[self.url]

    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url

    def wait_for_selector(self, selector, timeout=0):
        return True

    def wait_for_timeout(self, ms):
        self.waits.append(ms)




class FakeScrollFallbackPage(FakePage):
    def __init__(self, initial, scroll_results, first_url="https://eitaa.test/channel"):
        super().__init__({first_url: initial}, first_url)
        self.initial = initial
        self.scroll_results = list(scroll_results)
        self.scroll_calls = []

    def evaluate(self, script, args):
        if script == _SCAN_PAGE_SCRIPT:
            return self.initial
        if script == _CAPTURE_SCRIPT:
            self.scroll_calls.append(args)
            if self.scroll_results:
                return self.scroll_results.pop(0)
            return {"items": [], "root_count": 0, "scroll_cycles": 0,
                    "scroll_diagnostics": {"scroller_resolution": {"selected_by": "none"}, "last_cycles": []}}
        raise AssertionError("Unexpected browser script")


def message(message_id, day):
    return {"raw_text": f"Message {message_id}", "source_ref": f"id:{message_id}", "posted_at": f"{day}T08:00:00+00:00", "sender": "Channel", "attachments": []}


def page(items, before=None, after=None):
    return {"items": items, "root_count": len(items), "before_href": before, "after_href": after}


class EitaaPaginationTests(unittest.TestCase):
    def test_pagination_walks_older_then_newer_and_filters_exact_date_range(self):
        base = "https://eitaa.test/channel"
        older1 = base + "?before=older1"
        older2 = base + "?before=older2"
        newer2 = base + "?after=older2"
        newer1 = base + "?after=older1"
        pages = {
            base: page([message("7", "2026-07-03"), message("8", "2026-07-04")], older1, newer1),
            older1: page([message("5", "2026-07-01"), message("6", "2026-07-02")], older2, newer1),
            older2: page([message("3", "2026-06-29"), message("4", "2026-06-30")], None, newer2),
            newer2: page([message("5", "2026-07-01"), message("6", "2026-07-02")], older2, newer1),
            newer1: page([message("7", "2026-07-03"), message("8", "2026-07-04")], older1, None),
        }
        manager = WebInspectorManager()
        fake = FakePage(pages, base)
        config = {"site_preset": "eitaa", "root": {"selector": ".message"}, "fields": {}, "navigation": {"strategy": "pagination", "wait_ms": 250, "max_scrolls": 20}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100, "dateStart": "2026-06-29", "dateEnd": "2026-07-04"})
        days = {x["posted_at"][:10] for x in result["items"]}
        self.assertEqual(days, {"2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04"})
        self.assertTrue(result["date_range"]["complete"])
        self.assertEqual(result["date_range"]["in_range"], 6)
        self.assertEqual(result["scroll_cycles"], 4)


    def test_boundary_dates_spanning_multiple_pages_are_not_truncated(self):
        base = "https://eitaa.test/channel"
        older1 = base + "?before=older1"
        older2 = base + "?before=older2"
        pages = {
            base: page([message("5", "2026-07-02"), message("6", "2026-07-03")], older1, None),
            older1: page([message("3", "2026-07-01"), message("4", "2026-07-02")], older2, base),
            older2: page([message("1", "2026-06-30"), message("2", "2026-07-01")], None, older1),
        }
        manager = WebInspectorManager()
        fake = FakePage(pages, base)
        config = {"site_preset": "eitaa", "root": {"selector": ".message"}, "fields": {}, "navigation": {"strategy": "pagination", "wait_ms": 250, "max_scrolls": 20}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100, "dateStart": "2026-07-01", "dateEnd": "2026-07-02"})
        ids = {x["source_ref"] for x in result["items"]}
        self.assertEqual(ids, {"id:2", "id:3", "id:4", "id:5"})
        self.assertTrue(result["date_range"]["complete"])
        self.assertEqual(result["date_range"]["oldest_seen"], "2026-06-30")
        self.assertEqual(result["date_range"]["newest_seen"], "2026-07-03")

    def test_missing_older_pagination_link_falls_back_to_upward_message_scrolling(self):
        base = "https://eitaa.test/channel"
        initial_items = [message("10", "2026-11-10"), message("11", "2026-11-10")]
        initial = {"items": initial_items, "root_count": 2, "before_href": None, "after_href": None,
                   "root_selector_diagnostics": {"mode": "universal_auto_discovery"},
                   "message_root_candidates": [{"selector": "div.bubbles-group", "count": 2}]}
        scroll_result = {
            "items": [message("10", "2026-11-10"), message("11", "2026-11-10"), message("9", "2026-11-09")],
            "root_count": 3,
            "scroll_diagnostics": {
                "scroller": "div.message-pane", "scroller_resolution": {"selected_by": "message_ancestor_inference"},
                "last_cycles": [{"scroll_moved": True, "older_edge": False, "newer_edge": True, "scroll": {"top": 150}}]
            },
            "warnings": []
        }
        fake = FakeScrollFallbackPage(initial, [scroll_result], base)
        manager = WebInspectorManager()
        config = {"site_preset": "eitaa", "root": {"selector": ".old-message-root"}, "fields": {},
                  "navigation": {"strategy": "pagination", "direction": "up", "max_scrolls": 20, "timestamp_timezone": "Asia/Tehran"}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100,
                                                   "dateStart": "2026-11-10", "dateEnd": "2026-11-10"})
        self.assertEqual(result["strategy"], "infinite_scroll")
        self.assertEqual(result["requested_strategy"], "pagination")
        self.assertEqual(result["scroll_cycles"], 1)
        self.assertEqual({x["source_ref"] for x in result["items"]}, {"id:10", "id:11"})
        self.assertTrue(result["date_range"]["complete"])
        self.assertEqual(result["date_range"]["oldest_seen"], "2026-11-09")
        self.assertIn("Switching to automatic upward scrolling", " ".join(result["warnings"]))
        self.assertEqual(fake.scroll_calls[0]["strategy"], "infinite_scroll")
        self.assertEqual(fake.scroll_calls[0]["maxScrollCycles"], 1)

    def test_scroll_fallback_verifies_newest_edge_then_scans_older_boundary(self):
        base = "https://eitaa.test/channel"
        initial_items = [message("10", "2026-11-10"), message("11", "2026-11-10")]
        initial = {"items": initial_items, "root_count": 2, "before_href": None, "after_href": None}
        newer_edge_step = {
            "items": initial_items,
            "root_count": 2,
            "scroll_diagnostics": {
                "scroller": "div.message-pane",
                "scroller_resolution": {"selected_by": "message_ancestor_inference"},
                "last_cycles": [{"scroll_moved": True, "older_edge": False, "newer_edge": True, "scroll": {"top": 900, "maxTop": 900}}],
            },
            "warnings": [],
        }
        older_boundary_step = {
            "items": initial_items + [message("9", "2026-11-09")],
            "root_count": 3,
            "scroll_diagnostics": {
                "scroller": "div.message-pane",
                "scroller_resolution": {"selected_by": "message_ancestor_inference"},
                "last_cycles": [{"scroll_moved": True, "older_edge": False, "newer_edge": False, "scroll": {"top": 0, "maxTop": 900}}],
            },
            "warnings": [],
        }
        fake = FakeScrollFallbackPage(initial, [newer_edge_step, older_boundary_step], base)
        manager = WebInspectorManager()
        config = {
            "site_preset": "eitaa", "root": {"selector": ".old-message-root"}, "fields": {},
            "navigation": {"strategy": "pagination", "direction": "up", "max_scrolls": 20, "timestamp_timezone": "Asia/Tehran"},
        }
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100,
                                                   "dateStart": "2026-11-10", "dateEnd": "2026-11-10"})
        self.assertTrue(result["date_range"]["complete"])
        self.assertTrue(result["date_range"]["end_bound_confirmed"])
        self.assertTrue(result["date_range"]["start_bound_confirmed"])
        self.assertEqual(result["date_range"]["oldest_seen"], "2026-11-09")
        self.assertEqual([call["phase"] for call in fake.scroll_calls], ["newer", "older"])
        self.assertEqual([call["config"]["navigation"]["direction"] for call in fake.scroll_calls], ["down", "up"])
        traversal = result["scroll_diagnostics"]["boundary_traversal"]
        self.assertEqual(traversal["newer_stop_reason"], "newer_history_exhausted")
        self.assertEqual(traversal["older_stop_reason"], "start_boundary_crossed")

    def test_iso_timestamps_use_eitaa_tehran_calendar_not_machine_timezone(self):
        raw = "2026-06-30T21:30:00+00:00"
        self.assertEqual(WebInspectorManager._iso_day(raw), "2026-07-01")
        normalized = WebInspectorManager._localize_timestamp(raw)
        self.assertIsNotNone(normalized)
        self.assertTrue(normalized.endswith("+03:30"))
        self.assertEqual(normalized[:10], "2026-07-01")

    def test_naive_eitaa_timestamp_is_treated_as_utc(self):
        normalized = WebInspectorManager._localize_timestamp("2026-06-30T21:30:00")
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized[:10], "2026-07-01")


    def test_pagination_rejects_same_host_scheme_downgrade(self):
        base = "https://eitaa.test/channel"
        fake = FakePage({base: page([message("1", "2026-07-01")], "http://eitaa.test/channel?before=1", None)}, base)
        manager = WebInspectorManager()
        config = {"site_preset": "eitaa", "root": {"selector": ".message"}, "fields": {}, "navigation": {"strategy": "pagination", "wait_ms": 250, "max_scrolls": 10}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100, "dateStart": "2026-06-30", "dateEnd": "2026-07-02"})
        self.assertFalse(fake.goto_calls)
        self.assertIn("current website origin", " ".join(result["warnings"]))
        self.assertFalse(result["date_range"]["complete"])

    def test_pagination_rejects_cross_origin_links(self):
        base = "https://eitaa.test/channel"
        fake = FakePage({base: page([message("1", "2026-07-01")], "https://evil.test/steal", None)}, base)
        manager = WebInspectorManager()
        config = {"site_preset": "eitaa", "root": {"selector": ".message"}, "fields": {}, "navigation": {"strategy": "pagination", "wait_ms": 250, "max_scrolls": 10}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100, "dateStart": "2026-06-30", "dateEnd": "2026-07-02"})
        self.assertFalse(fake.goto_calls)
        self.assertIn("current website origin", " ".join(result["warnings"]))
        self.assertFalse(result["date_range"]["complete"])

    def test_generic_connector_uses_its_configured_timezone(self):
        raw = "2026-06-30T21:30:00+00:00"
        self.assertEqual(WebInspectorManager._iso_day(raw, "UTC"), "2026-06-30")
        self.assertEqual(WebInspectorManager._iso_day(raw, "Asia/Tehran"), "2026-07-01")

    def test_generic_date_pagination_without_previous_selector_uses_scroll_fallback(self):
        base = "https://forum.example.test/archive"
        initial = {"items": [message("1", "2026-07-01")], "root_count": 1, "before_href": None, "after_href": None}
        cycle = {"items": [message("1", "2026-07-01"), message("0", "2026-06-29")], "root_count": 2,
                 "scroll_diagnostics": {"scroller_resolution": {"selected_by": "message_ancestor_inference"},
                                         "last_cycles": [{"scroll_moved": True, "older_edge": False, "newer_edge": True}]}}
        fake = FakeScrollFallbackPage(initial, [cycle], base)
        manager = WebInspectorManager()
        config = {"root": {"selector": ".post"}, "fields": {}, "navigation": {"strategy": "pagination", "wait_ms": 250}}
        result = manager._capture_paginated(fake, {"config": config, "maxMessages": 100, "dateStart": "2026-06-30", "dateEnd": "2026-07-02"})
        self.assertEqual(result["strategy"], "infinite_scroll")
        self.assertEqual(result["date_range"]["in_range"], 1)
        self.assertEqual(result["date_range"]["oldest_seen"], "2026-06-29")


if __name__ == "__main__":
    unittest.main(verbosity=2)
