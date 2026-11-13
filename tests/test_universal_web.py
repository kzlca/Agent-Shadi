import unittest

from app.collectors.universal_web import (analyze_html, validate_selectors, normalize_connector_payload,
                                           compact_html_for_model, compact_html_samples_for_model, compact_analysis_evidence)

ONE = '''<div class="message-item" data-message-id="m-1"><span class="author">Ada</span><div class="message-text">First message</div><time datetime="2026-11-09T08:00:00Z">08:00</time><a class="attachment" href="/file/1">file</a></div>'''
LIST = '''<section id="chat"><div class="message-item" data-message-id="m-1"><span class="author">Ada</span><div class="message-text">First message</div><time datetime="2026-11-09T08:00:00Z">08:00</time><a class="attachment" href="/file/1">file</a></div><div class="message-item" data-message-id="m-2"><span class="author">Bob</span><div class="message-text">Second message</div><time datetime="2026-11-09T08:01:00Z">08:01</time></div></section>'''

class UniversalWebTests(unittest.TestCase):
    def test_html_analysis_finds_repeated_message_root_and_fields(self):
        result = analyze_html(ONE, LIST)
        selectors = {x["selector"]: x["count"] for x in result["message_candidates"]}
        self.assertGreaterEqual(selectors.get("div.message-item", 0), 2)
        self.assertGreaterEqual(selectors.get("[data-message-id]", 0), 2)
        self.assertTrue(any(x["selector"] == "div.message-text" for x in result["field_candidates"]["text"]))
        self.assertTrue(any(x["selector"] == "span.author" for x in result["field_candidates"]["sender"]))
        self.assertTrue(any(x["selector"] == "time" for x in result["field_candidates"]["timestamp"]))
        self.assertTrue(any(x["selector"] == ":root" and x["attribute"] == "data-message-id" for x in result["field_candidates"]["message_id"]))

    def test_single_message_sample_warns_that_boundaries_are_unverified(self):
        result = analyze_html(ONE, "")
        self.assertTrue(result["warnings"])
        self.assertEqual(result["message_candidates"], [])

    def test_ai_html_compaction_preserves_repeated_message_evidence_and_strips_noise(self):
        source = '<section onclick="steal()">' + "".join(
            f'<div class="message" data-message-id="{i}"><span class="sender">User {i}</span>'
            f'<p class="body">Message body {i}</p><a href="/item/{i}?token=secret">Open</a>'
            '<script>not for the model</script></div>' for i in range(100)
        ) + '</section>'
        compact = compact_html_for_model(source, 5000)
        self.assertLessEqual(len(compact), 5000)
        self.assertIn('class="message"', compact)
        self.assertIn('data-message-id=', compact)
        self.assertNotIn('onclick', compact)
        self.assertNotIn('<script', compact)
        self.assertNotIn('token=secret', compact)
        evidence = compact_analysis_evidence(analyze_html(compact, compact))
        self.assertTrue(any(x["count"] >= 2 for x in evidence["message_candidates"]))

    def test_two_ai_html_samples_obey_one_combined_budget(self):
        individual = '<article class="message">' + ('<p class="body">Long content</p>' * 300) + '</article>'
        listing = '<section>' + ''.join(
            f'<article class="message" data-message-id="{i}"><p class="body">Text {i}</p></article>'
            for i in range(500)
        ) + '</section>'
        one, many = compact_html_samples_for_model(individual, listing, total_chars=4200)
        self.assertLessEqual(len(one) + len(many), 4200)
        self.assertIn('class="message"', one)
        self.assertIn('data-message-id=', many)

    def test_selector_validation_reports_field_coverage_and_real_preview(self):
        config = {
            "root": {"selector": "div.message-item"},
            "fields": {
                "text": {"selector": ".message-text", "attribute": "textContent"},
                "sender": {"selector": ".author", "attribute": "textContent"},
                "timestamp": {"selector": "time", "attribute": "datetime"},
                "message_id": {"selector": ":root", "attribute": "data-message-id"},
            },
        }
        result = validate_selectors(LIST, config)
        self.assertEqual(result["root"]["matched"], 2)
        self.assertEqual(result["fields"]["text"]["coverage"], 100)
        self.assertEqual(result["preview"][0]["text"], "First message")
        self.assertEqual(result["preview"][0]["message_id"], "m-1")
        self.assertTrue(result["ready"])

    def test_invalid_css_selector_is_reported_not_silently_ignored(self):
        config = {"root": {"selector": "div["}, "fields": {"text": {"selector": ".message-text"}}}
        with self.assertRaisesRegex(ValueError, "Invalid CSS selector"):
            validate_selectors(LIST, config)

    def test_connector_normalization_rejects_non_web_urls_and_non_css_method(self):
        payload = {"name": "Test", "url": "file:///etc/passwd", "config": {}}
        with self.assertRaisesRegex(ValueError, "http:// or https://"):
            normalize_connector_payload(payload)
        payload["url"] = "https://example.com/inbox"
        payload["config"] = {"root": {"method": "xpath", "selector": "//div"}}
        with self.assertRaisesRegex(ValueError, "executes CSS"):
            normalize_connector_payload(payload)

    def test_connector_normalization_applies_safe_defaults_and_limits(self):
        result = normalize_connector_payload({
            "name": "Support inbox", "url": "https://example.com/inbox", "description": "Collect messages",
            "config": {"root": {"selector": "[data-message-id]"}, "fields": {"text": {"selector": ".content"}}, "navigation": {"strategy": "scroll_container", "wait_ms": 500, "max_scrolls": 900}},
        })
        self.assertEqual(result["config"]["root"]["selector"], "[data-message-id]")
        self.assertEqual(result["config"]["navigation"]["wait_ms"], 500)
        self.assertEqual(result["config"]["navigation"]["max_scrolls"], 500)

    def test_date_range_navigation_mode_defaults_to_auto_and_is_configurable(self):
        base={"name":"Connector","url":"https://example.com","config":{"root":{"selector":".message"},"fields":{"text":{"selector":".body"}}}}
        defaulted=normalize_connector_payload(base)
        self.assertEqual(defaulted["config"]["navigation"]["date_range_mode"],"auto")
        manual=normalize_connector_payload({**base,"config":{**base["config"],"navigation":{"date_range_mode":"manual"}}})
        self.assertEqual(manual["config"]["navigation"]["date_range_mode"],"manual")
        with self.assertRaisesRegex(ValueError,"Date-range navigation mode"):
            normalize_connector_payload({**base,"config":{**base["config"],"navigation":{"date_range_mode":"sometimes"}}})

    def test_connector_persists_direct_url_username_platform_id_and_active_identity_selector(self):
        item = normalize_connector_payload({
            "name": "Messenger", "url": "https://web.example.com/app",
            "config": {
                "channel": {
                    "name": "Example room", "target_url": "https://example.com/rooms/room-42",
                    "username": "@room_handle", "platform_id": "room-42",
                    "identity_selector": ".chat-header [data-room-id]", "identity_attribute": "data-room-id",
                },
                "root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}},
            },
        })
        channel = item["config"]["channel"]
        self.assertEqual(channel["target_url"], "https://example.com/rooms/room-42")
        self.assertEqual(channel["username"], "room_handle")
        self.assertEqual(channel["platform_id"], "room-42")
        self.assertEqual(channel["identity_selector"], ".chat-header [data-room-id]")
        self.assertEqual(channel["identity_attribute"], "data-room-id")

    def test_connector_detects_web_eitaa_origin_and_adds_editable_app_route_template(self):
        item = normalize_connector_payload({
            "name": "Eitaa", "url": "https://web.eitaa.com/",
            "config": {"channel": {"name": "Sample listings", "target_url": "https://eitaa.com/sample_listings_feed", "username": "sample_listings_feed"},
                       "root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}}}
        })
        self.assertEqual(item["config"]["site_preset"], "eitaa")
        self.assertEqual(item["config"]["channel"]["target_url_template"], "{app_origin}/#@{username}")

    def test_public_eitaa_channel_url_is_migrated_to_web_app_entrypoint(self):
        item = normalize_connector_payload({
            "name": "Eitaa public link draft", "url": "https://eitaa.com/sample_listings_feed",
            "config": {"site_preset": "eitaa", "root": {"selector": ".message"},
                       "fields": {"text": {"selector": ".body"}},
                       "channel": {"name": "Sample listings"}},
        })
        self.assertEqual(item["url"], "https://web.eitaa.com/")
        channel = item["config"]["channel"]
        self.assertEqual(channel["target_url"], "https://eitaa.com/sample_listings_feed")
        self.assertEqual(channel["username"], "sample_listings_feed")
        self.assertEqual(channel["target_url_template"], "{app_origin}/#@{username}")
        self.assertEqual(item["config"]["site_preset"], "eitaa")

    def test_numeric_eitaa_archive_path_is_not_mistaken_for_username(self):
        item = normalize_connector_payload({
            "name": "Eitaa archive", "url": "https://eitaa.com/channel/4270",
            "config": {"site_preset": "eitaa", "root": {"selector": ".message"},
                       "fields": {"text": {"selector": ".body"}}},
        })
        self.assertEqual(item["url"], "https://web.eitaa.com/")
        self.assertEqual(item["config"]["channel"]["target_url"], "https://eitaa.com/channel/4270")
        self.assertEqual(item["config"]["channel"]["username"], "")
        self.assertEqual(item["config"]["channel"]["target_url_template"], "")

    def test_connector_persists_custom_generic_route_template(self):
        item = normalize_connector_payload({
            "name": "Support", "url": "https://app.example.net/",
            "config": {"channel": {"username": "help", "target_url_template": "{app_origin}/#/rooms/{username}"},
                       "root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}}}
        })
        self.assertEqual(item["config"]["channel"]["target_url_template"], "{app_origin}/#/rooms/{username}")

    def test_connector_rejects_unsafe_target_urls_and_invalid_identity_selectors(self):
        base = {"name": "Messenger", "url": "https://example.com/app", "config": {"root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}}}}
        for target_url in ("javascript:alert(1)", "file:///etc/passwd", "https://user:pass@example.com/room"):
            payload = {**base, "config": {**base["config"], "channel": {"target_url": target_url}}}
            with self.subTest(target_url=target_url), self.assertRaisesRegex(ValueError, "Direct channel URL"):
                normalize_connector_payload(payload)
        payload = {**base, "config": {**base["config"], "channel": {"identity_selector": "div["}}}
        with self.assertRaisesRegex(ValueError, "Invalid active identity CSS selector"):
            normalize_connector_payload(payload)

    def test_generic_connector_defaults_allow_slow_pages_to_load(self):
        result = normalize_connector_payload({
            "name": "Slow inbox", "url": "https://example.com/inbox",
            "config": {"root": {"selector": ".message"}, "fields": {"text": {"selector": ".body"}}},
        })
        nav = result["config"]["navigation"]
        self.assertEqual(nav["wait_mode"], "adaptive")
        self.assertEqual(nav["max_wait_ms"], 8000)
        self.assertEqual(nav["max_idle_cycles"], 6)
