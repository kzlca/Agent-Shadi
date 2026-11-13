import tempfile
import unittest
from pathlib import Path

from app.collectors.web_inspector import WebInspectorManager, _INIT_SCRIPT, _OPEN_CHANNEL_SCRIPT, _CAPTURE_SCRIPT, _SCAN_PAGE_SCRIPT, resolve_channel_target_url, safe_chromium_launch_args


class WebInspectorProfileTests(unittest.TestCase):
    def test_idle_status_reports_existing_profile_without_reading_cookie_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "browser-profile"
            cookie_db = profile / "Default" / "Network" / "Cookies"
            local_storage = profile / "Default" / "Local Storage" / "leveldb" / "CURRENT"
            indexed_db = profile / "Default" / "IndexedDB" / "https_example.com_0.indexeddb.leveldb" / "CURRENT"
            cookie_db.parent.mkdir(parents=True)
            local_storage.parent.mkdir(parents=True)
            indexed_db.parent.mkdir(parents=True)
            cookie_db.write_bytes(b"cookie metadata only")
            local_storage.write_text("MANIFEST-000001")
            indexed_db.write_text("MANIFEST-000002")

            state = WebInspectorManager().status("connector-1", profile, True)

            self.assertEqual(state["status"], "idle")
            self.assertTrue(state["session"]["persistent"])
            self.assertTrue(state["session"]["profile_exists"])
            self.assertTrue(state["session"]["cookies_database_present"])
            self.assertTrue(state["session"]["local_storage_present"])
            self.assertTrue(state["session"]["indexed_db_present"])
            self.assertTrue(state["session"]["has_saved_site_data"])
            self.assertNotIn("cookie metadata only", str(state))

    def test_date_only_values_do_not_shift_when_timezone_is_applied(self):
        self.assertEqual(WebInspectorManager._localize_timestamp("2026-06-30", "America/Los_Angeles"), "2026-06-30")
        self.assertEqual(WebInspectorManager._iso_day("2026-06-30", "America/Los_Angeles"), "2026-06-30")

    def test_temporary_profile_is_reported_as_temporary(self):
        state = WebInspectorManager().status("connector-2", None, False)
        self.assertFalse(state["session"]["persistent"])
        self.assertFalse(state["session"]["profile_exists"])

    def test_inspector_has_modifier_free_selection_and_repeated_item_action(self):
        self.assertIn("Click select: OFF", _INIT_SCRIPT)
        self.assertIn("contextmenu", _INIT_SCRIPT)
        self.assertIn("Select nearest repeated item", _INIT_SCRIPT)
        self.assertIn("e.altKey", _INIT_SCRIPT)  # retained as optional compatibility path

    def test_inspector_supports_guided_field_picks_and_reusable_repeated_selectors(self):
        self.assertIn("window.__structuraSetSelectionMode", _INIT_SCRIPT)
        self.assertIn("repeatedGroupFor", _INIT_SCRIPT)
        self.assertIn("root_selector:rootSelector", _INIT_SCRIPT)
        self.assertIn("field_selector:fieldSelector", _INIT_SCRIPT)
        self.assertIn("selectorWithin(rootNode,el,rootSelector)", _INIT_SCRIPT)

    def test_identity_can_verify_exact_active_header_id_and_title_before_root_mapping(self):
        self.assertIn("headerIdentityVerified=(exactIdInHeader|| (targetUrlMatch&&visibleExactPeerId))&&titleVerified&&nonGenericActiveTitle", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("platform_id_and_active_title", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("message_root_candidates", _OPEN_CHANNEL_SCRIPT)

    def test_capture_uses_shared_universal_discovery_and_reports_dom_diagnostics(self):
        self.assertIn("resolveUniversalMessageRoots", _CAPTURE_SCRIPT)
        self.assertIn("universal_recovery", _CAPTURE_SCRIPT)
        self.assertIn("message_discovery_diagnostics", _CAPTURE_SCRIPT)
        self.assertIn("dom_diagnostics", _CAPTURE_SCRIPT)
        self.assertIn("message_ancestor_inference", _CAPTURE_SCRIPT)

    def test_guided_picker_is_primary_setup_step_and_html_paste_is_optional(self):
        app_js = (Path(__file__).parent.parent / "app" / "static" / "app.js").read_text(encoding="utf-8")
        visual_step = app_js.index('web-stage-num">2</span><div><b>Pick elements directly in the source browser')
        picker = app_js.index('class="web-guided-picker"', visual_step)
        optional_html = app_js.index('<details class="web-evidence-advanced">', picker)
        selector_review = app_js.index('web-stage-num">3</span><div><b>Review and configure the detected selectors')
        self.assertLess(visual_step, picker)
        self.assertLess(picker, optional_html)
        self.assertLess(optional_html, selector_review)
        self.assertIn('data-wc-pick="root"', app_js)
        self.assertIn('Browser opened. Sign in and open the target conversation, then press Pick again.', app_js)

    def test_open_channel_candidate_discovery_uses_block_level_message_wrappers(self):
        self.assertIn('bubble-content', _OPEN_CHANNEL_SCRIPT)
        self.assertIn('div.message', _OPEN_CHANNEL_SCRIPT)
        self.assertNotIn("'[class*=\"message\"]'", _OPEN_CHANNEL_SCRIPT)

    def test_arm_selection_rejects_closed_or_not_started_browser(self):
        with self.assertRaisesRegex(RuntimeError, "Open the connector browser"):
            WebInspectorManager().arm_selection("connector-not-running", "root")

    def test_selection_callback_acknowledges_persisted_revision(self):
        manager=WebInspectorManager()
        manager._sessions["connector-ack"]={"status":"ready","selected":None,"selection_revision":4,"logs":[]}
        result=manager._on_select("connector-ack",{"tag":"div","selector":".message","selected_for":"root"})
        self.assertEqual(result,{"ok":True,"selection_revision":5,"selected_for":"root"})
        status=manager.status("connector-ack")
        self.assertEqual(status["selection_revision"],5)
        self.assertEqual(status["selected"]["selector"],".message")

    def test_selection_callback_rejects_missing_or_stopped_session(self):
        manager=WebInspectorManager()
        self.assertFalse(manager._on_select("missing",{"selector":".message"})["ok"])
        manager._sessions["stopped"]={"status":"stopped","selection_revision":0,"logs":[]}
        self.assertFalse(manager._on_select("stopped",{"selector":".message"})["ok"])


    def test_inspector_init_script_waits_for_document_element_before_observing(self):
        self.assertIn("documentObserver.observe(document,{childList:true,subtree:true})", _INIT_SCRIPT)
        self.assertIn("const root = document.documentElement", _INIT_SCRIPT)
        self.assertIn("root.nodeType !== 1", _INIT_SCRIPT)
        self.assertNotIn("observe(document.documentElement,{childList:true})", _INIT_SCRIPT)

    def test_eitaa_preset_maps_public_channel_url_to_authenticated_app_route(self):
        resolved, details = resolve_channel_target_url(
            {"target_url": "https://eitaa.com/sample_listings_feed", "username": "sample_listings_feed"},
            "https://web.eitaa.com/", ""
        )
        self.assertEqual(resolved, "https://web.eitaa.com/#@sample_listings_feed")
        self.assertEqual(details["source"], "site_preset_default")

    def test_generic_route_template_is_editable_and_uses_only_declared_tokens(self):
        resolved, details = resolve_channel_target_url(
            {"name": "Support room", "target_url": "https://public.example.net/room/support-42",
             "username": "support-42", "platform_id": "room-42",
             "target_url_template": "{app_origin}/#/rooms/{username}?peer={platform_id}"},
            "https://app.example.net/inbox", ""
        )
        self.assertEqual(resolved, "https://app.example.net/#/rooms/support-42?peer=room-42")
        self.assertEqual(details["source"], "configured_template")

    def test_legacy_public_eitaa_app_url_resolves_against_authenticated_web_client(self):
        resolved, details = resolve_channel_target_url(
            {"target_url": "https://eitaa.com/sample_listings_feed", "username": "sample_listings_feed"},
            "https://eitaa.com/sample_listings_feed", "eitaa"
        )
        self.assertEqual(resolved, "https://web.eitaa.com/#@sample_listings_feed")
        self.assertEqual(details["source"], "site_preset_default")
        self.assertEqual(details["application_url"], "https://web.eitaa.com/")
        self.assertEqual(details["application_url_source"], "eitaa_web_client_fallback")

    def test_generic_direct_target_url_is_preserved_without_template(self):
        resolved, details = resolve_channel_target_url(
            {"target_url": "https://example.net/rooms/42"}, "https://app.example.net/", ""
        )
        self.assertEqual(resolved, "https://example.net/rooms/42")
        self.assertEqual(details["mode"], "direct")

    def test_route_template_rejects_missing_tokens_and_unsafe_resolved_routes(self):
        with self.assertRaisesRegex(ValueError, "needs values"):
            resolve_channel_target_url({"target_url_template": "{app_origin}/room/{username}"}, "https://app.example.net", "")
        with self.assertRaisesRegex(ValueError, "safe HTTP"):
            resolve_channel_target_url({"username": "room", "target_url_template": "javascript:{username}"}, "https://app.example.net", "")


    def test_message_discovery_is_platform_neutral_and_keeps_eitaa_body_fallback(self):
        self.assertIn("message_root_candidates", _OPEN_CHANNEL_SCRIPT)
        self.assertIn("semanticRootTokens", _CAPTURE_SCRIPT)
        self.assertIn(".translatable-message", _CAPTURE_SCRIPT)
        self.assertIn("time-inner", _CAPTURE_SCRIPT)
        self.assertIn("universal_auto_discovery", _CAPTURE_SCRIPT)

    def test_chromium_never_uses_no_sandbox_and_refuses_root_execution(self):
        source = Path(__file__).parent.parent / "app" / "collectors" / "web_inspector.py"
        code = source.read_text(encoding="utf-8")
        self.assertNotIn('browser_args.append("--no-sandbox")', code)
        self.assertNotIn('"--no-sandbox"', code)
        self.assertEqual(safe_chromium_launch_args(1000), ["--disable-dev-shm-usage"])
        with self.assertRaisesRegex(RuntimeError, "running as root"):
            safe_chromium_launch_args(0)

    def test_persian_jalali_timestamp_is_normalized_to_gregorian_day(self):
        self.assertEqual(
            WebInspectorManager._localize_timestamp("۱۴۰۵/۰۸/۱۹ ۱۰:۲۰:۳۰", "Asia/Tehran"),
            "2026-11-10T10:20:30+03:30",
        )
        self.assertEqual(
            WebInspectorManager._iso_day("۱۴۰۵/۰۸/۱۹", "Asia/Tehran"),
            "2026-11-10",
        )
        self.assertEqual(
            WebInspectorManager._localize_timestamp("۱۹ آبان ۱۴۰۵ ۱۰:۲۰", "Asia/Tehran"),
            "2026-11-10T10:20:00+03:30",
        )
        self.assertEqual(
            WebInspectorManager._localize_timestamp("2026/11/10 10:20:30", "Asia/Tehran"),
            "2026-11-10T10:20:30+03:30",
        )

    def test_capture_script_contains_adaptive_wait_and_configurable_scroll(self):
        self.assertIn("wait_mode", _CAPTURE_SCRIPT)
        self.assertIn("scroll_step_ratio", _CAPTURE_SCRIPT)
        self.assertIn("max_idle_cycles", _CAPTURE_SCRIPT)
        self.assertIn("consume the full adaptive budget", _CAPTURE_SCRIPT)
        self.assertIn("scroll_diagnostics", _CAPTURE_SCRIPT)


    def test_date_range_promotes_manual_connector_to_auto_scroll_by_default(self):
        config={"navigation":{"strategy":"manual","date_range_mode":"auto"}}
        self.assertEqual(WebInspectorManager.resolve_capture_strategy(config,None,"2026-11-10","2026-11-10"),("manual","infinite_scroll",True))
        self.assertEqual(WebInspectorManager.resolve_capture_strategy(config,None,None,None),("manual","manual",False))

    def test_date_range_manual_only_setting_preserves_manual_capture(self):
        config={"navigation":{"strategy":"manual","date_range_mode":"manual"}}
        self.assertEqual(WebInspectorManager.resolve_capture_strategy(config,None,"2026-11-10","2026-11-10"),("manual","manual",False))

    def test_channel_identity_does_not_trust_hash_or_url_without_open_conversation(self):
        self.assertIn("A URL/hash is routing intent, not proof",_OPEN_CHANNEL_SCRIPT)
        self.assertIn("wantedUser && activeConversation",_OPEN_CHANNEL_SCRIPT)
        self.assertIn("userSelectorVerified || userHeaderVerified || (urlHasUser&&titleVerified)",_OPEN_CHANNEL_SCRIPT)
        self.assertIn("const routeVerified=targetUrlMatch && activeConversation",_OPEN_CHANNEL_SCRIPT)
        self.assertIn("genericTitles",_OPEN_CHANNEL_SCRIPT)

    def test_capture_recovers_when_saved_root_and_text_selectors_are_stale(self):
        self.assertIn("safeQuery(root, String(def.selector))",_CAPTURE_SCRIPT)
        self.assertIn("configured_root_with_automatic_text",_CAPTURE_SCRIPT)
        self.assertIn("universal_recovery",_CAPTURE_SCRIPT)
        self.assertIn("selectorError",_CAPTURE_SCRIPT)

    def test_capture_reports_actual_scroll_movement_and_avoids_wrong_page_fallback(self):
        self.assertIn("scroll_moved:moved",_CAPTURE_SCRIPT)
        self.assertIn("message_ancestor_inference",_CAPTURE_SCRIPT)
        self.assertIn("older_edge_confirmed",_CAPTURE_SCRIPT)

    def test_human_readable_timestamp_title_uses_connector_timezone(self):
        localized=WebInspectorManager._localize_timestamp("11 November 2026, 00:20:59","Asia/Tehran")
        self.assertEqual(localized,"2026-11-11T00:20:59+03:30")

    def test_generic_page_scan_uses_connector_defined_previous_and_next_selectors(self):
        self.assertIn("nav.previous_page_selector", _SCAN_PAGE_SCRIPT)
        self.assertIn("nav.next_page_selector", _SCAN_PAGE_SCRIPT)
        self.assertIn("config.site_preset === 'eitaa'", _SCAN_PAGE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
