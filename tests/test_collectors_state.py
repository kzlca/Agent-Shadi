import sys
import types
import unittest
from unittest.mock import Mock

# Collector runtime dependencies are declared in requirements.txt. Lightweight
# import stubs keep these DOM-state unit tests runnable in source-only CI images.
sys.modules.setdefault("emoji", types.SimpleNamespace(emojize=lambda text, language="alias": text))
sys.modules.setdefault("jdatetime", types.SimpleNamespace(date=types.SimpleNamespace(today=lambda: None)))
if "playwright.sync_api" not in sys.modules:
    playwright=types.ModuleType("playwright"); playwright.__path__=[]
    sync_api=types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright=lambda: None
    sync_api.TimeoutError=TimeoutError
    sys.modules["playwright"]=playwright
    sys.modules["playwright.sync_api"]=sync_api

from app.collectors import telegram_collector, rubika_collector


class FakePage:
    def __init__(self, url="https://web.telegram.org/k/#@target_feed", titles=None, raises=False):
        self.url=url
        self.titles=titles or []
        self.raises=raises
        self.keyboard=Mock()
    def evaluate(self, script, *args):
        if self.raises:
            raise RuntimeError("page closed")
        return self.titles
    def wait_for_timeout(self, milliseconds):
        return None


class CollectorResumeSafetyTests(unittest.TestCase):
    def test_telegram_route_alone_does_not_prove_active_channel_identity(self):
        page=FakePage()
        with self.assertRaisesRegex(RuntimeError,"Cannot verify the active Telegram channel"):
            telegram_collector.verify_expected_channel(page,"Telegram","https://web.telegram.org/k/#@target_feed","Target Feed")

    def test_telegram_rejects_wrong_channel_after_inspector_resume(self):
        page=FakePage(url="https://web.telegram.org/k/#@different_feed",titles=["Different Feed"])
        with self.assertRaisesRegex(RuntimeError,"No messages were collected"):
            telegram_collector.verify_expected_channel(page,"Telegram","https://web.telegram.org/k/#@target_feed","Target Feed")

    def test_telegram_authenticated_app_host_is_not_misreported_as_wrong_public_host(self):
        page=FakePage(url="https://web.telegram.org/k/",titles=[])
        with self.assertRaisesRegex(RuntimeError,"Cannot verify the active Telegram channel"):
            telegram_collector.verify_expected_channel(page,"Telegram","https://t.me/target_feed","@target_feed")

    def test_telegram_accepts_clicked_result_and_active_header_on_authenticated_app(self):
        page=FakePage(url="https://web.telegram.org/k/",titles=["Target Feed"])
        self.assertTrue(telegram_collector.verify_expected_channel(
            page,"Telegram","https://t.me/target_feed","@target_feed",
            selected_result_text="Target Feed @target_feed", expected_active_title="Target Feed"
        ))

    def test_telegram_operator_selection_requires_visible_header_evidence(self):
        page=FakePage(url="https://web.telegram.org/k/",titles=[])
        with self.assertRaisesRegex(RuntimeError,"Cannot verify the active Telegram channel"):
            telegram_collector.verify_expected_channel(
                page,"Telegram","https://t.me/target_feed","@target_feed",
                selected_result_text="some clicked row", allow_operator_selection=True
            )

    def test_telegram_rejects_chat_switch_after_selected_header_was_pinned(self):
        page=FakePage(url="https://web.telegram.org/k/",titles=["Different Feed"])
        with self.assertRaisesRegex(RuntimeError,"active Telegram chat changed after selection"):
            telegram_collector.verify_expected_channel(
                page,"Telegram","https://t.me/target_feed","@target_feed",
                selected_result_text="Target Feed @target_feed", expected_active_title="Target Feed",
                allow_operator_selection=True
            )

    def test_telegram_search_identity_evidence_handles_username_and_header_match(self):
        username=telegram_collector._telegram_identity_evidence(
            "Target Feed\n@target_feed", ["Target Feed"], "target_feed")
        self.assertTrue(username["username_match"])
        self.assertTrue(username["evidence_match"])
        title=telegram_collector._telegram_identity_evidence(
            "Target Feed\n2.4K subscribers", ["Target Feed"], "target_feed")
        self.assertTrue(title["matching_header"])
        self.assertTrue(title["evidence_match"])

    def test_rubika_rejects_wrong_channel_after_inspector_resume(self):
        page=FakePage(url="https://web.rubika.ir/#@different_feed",titles=["Different Feed"])
        with self.assertRaisesRegex(RuntimeError,"No messages were collected"):
            rubika_collector.verify_expected_channel(page,"Rubika","https://web.rubika.ir/#@target_feed","Target Feed")

    def test_rubika_accepts_active_title_from_the_selected_matching_result(self):
        page=FakePage(url="https://web.rubika.ir/",titles=["Sample feed 119"])
        self.assertTrue(rubika_collector.verify_expected_channel(
            page,"Rubika","https://web.rubika.ir/#@sample_feed_119","sample_feed_119","Sample feed 119\n@sample_feed_119"
        ))

    def test_rubika_result_picker_requires_a_matching_result(self):
        class ResultPage:
            def __init__(self, result): self.result=result; self.calls=[]
            def evaluate(self, script, terms): self.calls.append(terms); return self.result
        matched=ResultPage({"clicked":True,"text":"Sample feed 119 @sample_feed_119","score":80})
        self.assertTrue(rubika_collector._click_rubika_search_result(matched,["@sample_feed_119","sample_feed_119"])["clicked"])
        self.assertEqual(matched.calls, [["@sample_feed_119","sample_feed_119"]])
        unmatched=ResultPage({"clicked":False,"reason":"no_matching_search_result","candidates":["A different channel"]})
        self.assertFalse(rubika_collector._click_rubika_search_result(unmatched,["@sample_feed_119"])["clicked"])

    def test_rubika_search_mismatch_waits_for_explicit_operator_selection(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        open_block=source[source.index("def open_channel("):source.index("def wait_for_rubika_channel_ready(")]
        extract_block=source[source.index("def extract_messages("):source.index("# Classify AFTER collection")]
        self.assertNotIn("_click_rubika_search_result(",open_block)
        self.assertIn("wait_for_manual_rubika_channel_selection(",open_block)
        self.assertIn("_install_rubika_operator_click_watch(page)",open_block)
        self.assertNotIn("search_input.fill(",open_block)
        self.assertNotIn("search_input.press(",open_block)
        self.assertIn("operator_select_channel",open_block)
        self.assertIn("not proof of username ownership",open_block)
        self.assertLess(extract_block.index('readiness = wait_for_rubika_channel_ready'),extract_block.index('pause_in_inspector(\n        page, platform, search_name, end_date_str'))
        self.assertIn('expected_active_title=expected_active_title',extract_block)
        self.assertIn('active_title=expected_active_title',extract_block)
        self.assertIn('payload = extract_visible_messages(page, selectors, current_fallback)',extract_block)

    def test_rubika_in_app_checkpoint_reports_the_observed_display_title(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn('pause_in_inspector(\n        page, platform, search_name, end_date_str',source)
        control=Path(rubika_collector.__file__).parents[0]/"inspector_control.py"
        control_source=control.read_text(encoding="utf-8")
        self.assertIn("Active chat header detected:",control_source)

    def test_rubika_accepts_user_selected_persian_display_title_for_username(self):
        page=FakePage(url="https://web.rubika.ir/",titles=["Sample property feed"])
        self.assertTrue(rubika_collector.verify_expected_channel(
            page,"Rubika","https://web.rubika.ir/#@sample_feed_119","sample_feed_119",
            selected_result_text="Sample property feed", expected_active_title="Sample property feed"
        ))

    def test_rubika_rejects_channel_change_after_manual_selection_even_if_route_has_username(self):
        page=FakePage(url="https://web.rubika.ir/#@sample_feed_119",titles=["یک کانال دیگر"])
        with self.assertRaisesRegex(RuntimeError,"No messages were collected"):
            rubika_collector.verify_expected_channel(
                page,"Rubika","https://web.rubika.ir/#@sample_feed_119","sample_feed_119",
                expected_active_title="Sample property feed"
            )

    def test_manual_rubika_click_stops_search_before_stale_enter_submission(self):
        class ClickedSearchPage:
            def evaluate(self, script, *args):
                return {"title":"Sample property feed","titles":["Sample property feed"],
                        "message_count":0,"signature":"","click":{"at":123,"text":"Sample property feed 8,960 members"}}
        self.assertTrue(rubika_collector._rubika_manual_selection_started(ClickedSearchPage(), ""))

    def test_manual_rubika_does_not_treat_search_result_title_as_open_chat_without_click(self):
        class UnclickedSearchPage:
            def evaluate(self, script, *args):
                return {"title":"Sample property feed","titles":["Sample property feed"],
                        "message_count":5,"signature":"search-preview-1","click":None}
        self.assertFalse(rubika_collector._rubika_manual_selection_started(UnclickedSearchPage(), ""))

    def test_manual_rubika_selection_requires_stable_open_chat(self):
        class ManualSelectionPage:
            def __init__(self):
                self.calls=0
            def evaluate(self, script, *args):
                self.calls += 1
                return {"title":"Sample property feed","titles":["Sample property feed"],
                        "message_count":6,"signature":"msg-a|msg-b","click":{"at":123,"text":"Sample property feed 8,960 members"}}
            def wait_for_timeout(self, milliseconds):
                import time; time.sleep(min(milliseconds,10)/1000)
        page=ManualSelectionPage()
        chosen=rubika_collector.wait_for_manual_rubika_channel_selection(page,"sample_feed_119",timeout_seconds=1)
        self.assertTrue(chosen["operator_selected"])
        self.assertEqual(chosen["active_title"],"Sample property feed")
        self.assertEqual(chosen["message_count"],6)

    def test_rubika_has_only_one_open_channel_implementation(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("def open_channel("),1,"A legacy duplicate open_channel would override the verified search implementation")

    def test_telegram_scroll_failure_never_sends_pageup(self):
        page=FakePage(raises=True)
        result=telegram_collector.scroll_up(page)
        self.assertFalse(result["result"]["ok"])
        page.keyboard.press.assert_not_called()

    def test_rubika_scroll_failure_never_sends_pageup(self):
        page=FakePage(raises=True)
        result=rubika_collector.scroll_up(page)
        self.assertFalse(result["ok"])
        page.keyboard.press.assert_not_called()

    def test_telegram_requires_confirmed_history_boundary_before_success(self):
        from pathlib import Path
        source=Path(telegram_collector.__file__).read_text(encoding="utf-8")
        self.assertIn("if not scan_complete:",source)
        self.assertIn("history scan stopped before confirming the requested start date",source)
        self.assertIn("stable_rounds>=3",source)

    def test_rubika_requires_confirmed_history_boundary_before_success(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn("if not scan_complete:",source)
        self.assertIn("history scan stopped before confirming the requested start date",source)
        self.assertIn("stable>=3",source)

    def test_manual_channel_selection_precedes_history_checkpoint_and_no_auto_search_is_used(self):
        from pathlib import Path
        telegram=Path(telegram_collector.__file__).read_text(encoding="utf-8")
        rubika=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        telegram_extract=telegram[telegram.index("def extract_messages("):]
        rubika_open=rubika[rubika.index("def open_channel("):rubika.index("def wait_for_rubika_channel_ready(")]
        self.assertIn("wait_for_manual_telegram_channel_selection(",telegram_extract)
        self.assertIn("wait_for_manual_rubika_channel_selection(",rubika_open)
        self.assertNotIn("_click_telegram_search_result(",telegram_extract)
        self.assertNotIn("_activate_telegram_search_result(",telegram_extract)
        self.assertNotIn("_click_rubika_search_result(",rubika_open)
        self.assertIn("pause_in_inspector(",telegram_extract)
        self.assertIn("operator_select_channel",telegram_extract)
        self.assertIn("operator_select_channel",rubika_open)

    def test_channel_ready_check_requires_stable_message_signature_not_only_count(self):
        from pathlib import Path
        telegram=Path(telegram_collector.__file__).read_text(encoding="utf-8")
        rubika=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn("last_signature",telegram)
        self.assertIn("signature==last_signature",telegram)
        self.assertIn("previous_signature",rubika)
        self.assertIn("signature==previous_signature",rubika)

    def test_rubika_scroll_probe_discovers_live_message_ancestors_not_hardcoded_classes(self):
        class ProbePage:
            def __init__(self): self.arguments=[]
            def evaluate(self, script, selector):
                self.arguments.append(selector)
                return {"message_count":15,"candidates":[{
                    "tag":"div","className":"virtual-history","depth":2,"contained":15,
                    "scrollTop":740,"scrollHeight":4200,"clientHeight":680,"overflowY":"auto",
                    "x":200,"y":80,"width":760,"height":600,"mouse_x":618,"mouse_y":410,"score":220
                }]}
        page=ProbePage()
        state=rubika_collector.get_rubika_scroll_state(page,".message-item")
        self.assertEqual(state["className"],"virtual-history")
        self.assertEqual(state["message_count"],15)
        self.assertEqual(page.arguments,[".message-item"])

    def test_rubika_scroll_uses_targeted_wheel_and_dom_fallback(self):
        class Mouse:
            def __init__(self): self.moves=[]; self.wheels=[]
            def move(self,x,y): self.moves.append((x,y))
            def wheel(self,x,y): self.wheels.append((x,y))
        class AdaptivePage:
            def __init__(self): self.mouse=Mouse(); self.direct_calls=0
            def evaluate(self,script,*args):
                if "message_rect" in script:
                    return {"message_count":15,"candidates":[{
                        "tag":"div","className":"virtual-history","depth":2,"contained":15,
                        "scrollTop":740,"scrollHeight":4200,"clientHeight":680,"overflowY":"auto",
                        "x":200,"y":80,"width":760,"height":600,"mouse_x":618,"mouse_y":410,"score":220
                    }]}
                if "titleDetails" in script:
                    return {"signature":"same-viewport","title":"Channel"}
                if "({selector,index,amount})" in script:
                    self.direct_calls += 1
                    return {"ok":True,"before":740,"after":0,"moved":True,"scrollHeight":4200,"clientHeight":680}
                raise AssertionError("Unexpected browser evaluation")
            def wait_for_timeout(self,ms): pass
        page=AdaptivePage()
        result=rubika_collector.scroll_up(page,amount=900,message_selector=".message-item")
        self.assertTrue(result["ok"])
        self.assertEqual(result["strategy"],"targeted_dom_scroll")
        self.assertEqual(page.mouse.moves,[(618.0,410.0)])
        self.assertEqual(page.mouse.wheels,[(0,-900)])
        self.assertEqual(page.direct_calls,1)


    def test_rubika_scroll_continues_after_a_candidate_evaluate_succeeds_without_moving(self):
        class Mouse:
            def move(self, x, y): pass
            def wheel(self, x, y): pass
        class CandidatePage:
            def __init__(self):
                self.mouse = Mouse()
                self.direct_indices = []
            def evaluate(self, script, *args):
                if "message_rect" in script:
                    return {"message_count": 15, "candidates": [
                        {"tag":"div","className":"dead-wrapper","depth":1,"contained":15,
                         "scrollTop":0,"scrollHeight":700,"clientHeight":700,"overflowY":"auto",
                         "x":100,"y":80,"width":700,"height":550,"mouse_x":480,"mouse_y":350,"score":240},
                        {"tag":"section","className":"real-history","depth":3,"contained":15,
                         "scrollTop":900,"scrollHeight":6200,"clientHeight":700,"overflowY":"auto",
                         "x":120,"y":90,"width":680,"height":530,"mouse_x":490,"mouse_y":350,"score":210},
                    ]}
                if "titleDetails" in script:
                    return {"signature":"unchanged-viewport","title":"Channel"}
                if "({selector,index,amount})" in script:
                    index = args[0]["index"]
                    self.direct_indices.append(index)
                    if index == 0:
                        return {"ok":True,"moved":False,"before":0,"after":0,"className":"dead-wrapper"}
                    return {"ok":True,"moved":True,"before":900,"after":0,"className":"real-history"}
                raise AssertionError("Unexpected evaluation")
            def wait_for_timeout(self, ms): pass
        page = CandidatePage()
        result = rubika_collector.scroll_up(page, amount=1200, message_selector=".message-item")
        self.assertTrue(result["ok"])
        self.assertEqual(page.direct_indices, [0, 1])
        self.assertEqual(result["strategy"], "targeted_dom_scroll")
        self.assertEqual(result["candidate"]["direct"]["className"], "real-history")


    def test_rubika_manual_selection_flags_result_header_mismatch(self):
        evidence = rubika_collector.rubika_manual_identity_evidence(
            "Sample property feed\n8,960 members\nMessage preview",
            ["Do not reply", "Sample property feed"],
        )
        self.assertTrue(evidence["evidence_match"])
        self.assertEqual(evidence["matching_header"], "Sample property feed")
        mismatch = rubika_collector.rubika_manual_identity_evidence(
            "Sample property feed\n8,960 members", ["Do not reply"]
        )
        self.assertFalse(mismatch["evidence_match"])
        self.assertEqual(mismatch["matching_header"], "")

    def test_manual_click_text_is_not_fabricated_from_active_header(self):
        from pathlib import Path
        source = Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn('"clicked_result_text": manual.get("clicked_result_text") or ""', source)
        self.assertIn('if selection.get("identity_requires_operator_confirmation")', source)

    def test_collection_diagnostic_identifies_mismatched_manual_rubika_channel(self):
        from app import server
        diagnosis = server._collector_state_diagnosis({
            "status": "operator_paused",
            "phase_message": "MANUAL IDENTITY CHECK (MISMATCH / NOT PROVEN): clicked result='گنبد'; active chat header detected='Do not reply'",
            "logs": [],
        })
        self.assertEqual(diagnosis["code"], "manual_channel_identity_mismatch")
        self.assertIn("Do not continue", diagnosis["next_step"])

    def test_collection_diagnostic_identifies_stalled_rubika_scroll(self):
        from app import server
        diagnosis = server._collector_state_diagnosis({
            "status": "failed", "phase": "failed", "logs": [
                "Rubika history is not moving; no observable history progress after adaptive scroll attempts"
            ]
        })
        self.assertEqual(diagnosis["code"], "message_history_scroll_stalled")
        self.assertEqual(diagnosis["severity"], "error")

    def test_collection_diagnostic_explains_manual_history_recovery(self):
        from app import server
        diagnosis = server._collector_state_diagnosis({
            "status": "operator_paused", "phase": "operator_paused",
            "phase_message": "MANUAL HISTORY RECOVERY: automatic Rubika scrolling stalled at cycle 4."
        })
        self.assertEqual(diagnosis["code"], "manual_history_recovery_required")
        self.assertIn("Continue history", diagnosis["next_step"])

    def test_rubika_manual_recovery_checkpoint_is_bounded_and_revalidates_channel(self):
        from pathlib import Path
        source = Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn("def request_manual_history_recovery", source)
        self.assertIn("manual_recovery_count >= 2", source)
        self.assertIn("verify_expected_channel(\n            page, platform, url, search_name", source)
        self.assertIn("MANUAL HISTORY RECOVERY", source)
        self.assertIn("Manual history recovery was confirmed, but the visible message list still did not change", source)

    def test_rubika_scroll_fails_closed_when_no_message_ancestor_exists(self):
        class NoScrollerPage:
            def evaluate(self,script,*args):
                return {"message_count":0,"candidates":[],"error":"no messages"}
        result=rubika_collector.scroll_up(NoScrollerPage(),message_selector=".message-item")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"],"message_scroller_not_found")

    def test_rubika_stops_after_two_scroll_attempts_without_progress(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        self.assertIn("consecutive_scroll_failures >= 2",source)
        self.assertIn("Rubika history is not moving",source)
        self.assertIn("viewport_signature",source)

    def test_manual_channel_checkpoint_does_not_claim_username_is_verified(self):
        from pathlib import Path
        source=Path(rubika_collector.__file__).read_text(encoding="utf-8")
        control=Path(rubika_collector.__file__).parents[0]/"inspector_control.py"
        control_source=control.read_text(encoding="utf-8")
        self.assertIn("identity_requires_operator_confirmation",source)
        self.assertIn("not proof of username ownership",source)
        self.assertIn("MANUAL IDENTITY CHECK",control_source)
        self.assertIn('selection.get("clicked_result_text", "")',source)

    def test_collection_ui_explicitly_asks_to_confirm_manual_channel_identity(self):
        from pathlib import Path
        js=Path(rubika_collector.__file__).parents[1]/"static"/"app.js"
        source=js.read_text(encoding="utf-8")
        self.assertIn("Confirm the selected channel before scanning",source)
        self.assertIn("Confirm channel & continue",source)
        self.assertIn("not independently verified",source)


if __name__=="__main__":
    unittest.main()
