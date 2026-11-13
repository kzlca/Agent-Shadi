"""Regression tests for Telegram active-chat identity verification."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


SOURCE_PATH = Path(__file__).parents[1] / "app/collectors/telegram_collector.py"
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")


def load_production_helpers():
    """Load pure production helpers without importing runtime dependencies."""
    tree = ast.parse(SOURCE, filename=str(SOURCE_PATH))
    names = {"_telegram_identity_evidence", "verify_expected_channel"}
    nodes = [
        item for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name in names
    ]
    module = ast.Module(body=nodes, type_ignores=[])
    namespace = {
        "re": re,
        "urlparse": urlparse,
        "_telegram_active_chat_state": lambda page: page.state,
    }
    exec(compile(module, str(SOURCE_PATH), "exec"), namespace)
    return namespace


class FakePage:
    def __init__(self, state, url="https://web.telegram.org/k/"):
        self.state = state
        self.url = url

    def evaluate(self, _script):
        return self.state


class TelegramIdentityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers = load_production_helpers()
        cls.evidence = staticmethod(helpers["_telegram_identity_evidence"])
        cls.verify = staticmethod(helpers["verify_expected_channel"])

    def test_username_in_search_row_does_not_prove_active_chat(self):
        state = self.evidence(
            "Sample property feed\n@sample_feed_118, 1,234 subscribers",
            ["Another sample feed"],
            "sample_feed_118",
        )
        self.assertTrue(state["username_match"], "the search result itself matched the configured username")
        self.assertFalse(state["evidence_match"], "the active chat is a different channel")
        self.assertEqual(state["row_title"], "Sample property feed")

    def test_active_header_matching_the_clicked_result_proves_identity(self):
        state = self.evidence(
            "Sample property feed\n@sample_feed_118, 1,234 subscribers",
            ["Sample property feed"],
            "sample_feed_118",
        )
        self.assertTrue(state["evidence_match"])
        self.assertEqual(state["evidence_source"], "active_header")

    def test_matching_peer_id_proves_identity_even_when_header_is_an_alias(self):
        state = self.evidence(
            "Sample property feed\n@sample_feed_118, 1,234 subscribers",
            ["Another sample feed"],
            "sample_feed_118",
            active_peer_ids=["-1001234567890"],
            expected_peer_id="-1001234567890",
        )
        self.assertTrue(state["evidence_match"])
        self.assertEqual(state["evidence_source"], "peer_id")

    def test_conflicting_active_peer_id_overrides_coincidental_title_match(self):
        state = self.evidence(
            "Sample property feed\n@sample_feed_118, 1,234 subscribers",
            ["Sample property feed"],
            "sample_feed_118",
            active_peer_ids=["-100999"],
            expected_peer_id="-1001234567890",
        )
        self.assertTrue(state["peer_id_conflict"])
        self.assertFalse(state["evidence_match"])

    def test_wrong_active_header_fails_even_after_operator_continue(self):
        page = FakePage({
            "title": "Another sample feed",
            "titles": ["Another sample feed"],
            "active_peer_ids": [],
        })
        with self.assertRaisesRegex(RuntimeError, "changed after selection"):
            self.verify(
                page, "Telegram", "https://t.me/sample_feed_118", "@sample_feed_118",
                selected_result_text="Sample property feed\n@sample_feed_118, 1,234 subscribers",
                expected_active_title="Sample property feed",
                allow_operator_selection=True,
                expected_peer_id="-1001234567890",
            )

    def test_peer_id_change_after_checkpoint_is_rejected(self):
        page = FakePage({
            "title": "Another sample feed",
            "titles": ["Another sample feed"],
            "active_peer_ids": ["-100999"],
        })
        with self.assertRaisesRegex(RuntimeError, "peer changed after selection"):
            self.verify(
                page, "Telegram", "https://t.me/sample_feed_118", "@sample_feed_118",
                selected_result_text="Sample property feed\n@sample_feed_118",
                expected_active_title="Sample property feed",
                expected_peer_id="-1001234567890",
            )

    def test_matching_active_header_passes_post_continue_verification(self):
        page = FakePage({
            "title": "Sample property feed",
            "titles": ["Sample property feed"],
            "active_peer_ids": [],
        })
        self.assertTrue(self.verify(
            page, "Telegram", "https://t.me/sample_feed_118", "@sample_feed_118",
            selected_result_text="Sample property feed\n@sample_feed_118",
            expected_active_title="Sample property feed",
        ))

    def test_wait_requires_identity_and_content_not_just_stable_bubbles(self):
        self.assertIn("if clicked and title and identity_confirmed and content_confirmed:", SOURCE)
        self.assertIn("may belong to a previously open chat", SOURCE)

    def test_manual_continue_cannot_bypass_telegram_identity_verification(self):
        start = SOURCE.index("def verify_expected_channel(")
        end = SOURCE.index("def wait_for_telegram_channel_ready(", start)
        verifier = SOURCE[start:end]
        self.assertIn("The active Telegram chat does not match", verifier)
        self.assertIn("active pane reports", verifier)
        telegram_branch = verifier.split('if platform.casefold() == "telegram":', 1)[1]
        self.assertNotIn("if allow_operator_selection and titles:", telegram_branch)
        self.assertNotIn("expected_token and re.search", telegram_branch)

    def test_active_title_is_not_replaced_by_another_matching_candidate(self):
        self.assertIn('active_title = title', SOURCE)
        self.assertNotIn('active_title = str(last_evidence.get("matching_header") or title)', SOURCE)

    def test_active_title_selectors_exclude_broad_dir_auto_search_nodes(self):
        start = SOURCE.index("const titleSelectors = [")
        end = SOURCE.index("];", start)
        selectors = SOURCE[start:end]
        self.assertNotIn('[dir="auto"]', selectors)
        self.assertIn(".topbar .peer-title", selectors)
        self.assertIn("#column-center", selectors)

    def test_actual_message_extractor_is_preflighted_before_any_scrolling(self):
        self.assertIn("preflight_items = _extract_visible_telegram_messages(page, selectors)", SOURCE)
        self.assertIn("Collection stopped before scrolling", SOURCE)
        self.assertLess(SOURCE.index("preflight_items = _extract_visible_telegram_messages"), SOURCE.index("for cycle in range(1, max_cycles + 1)"))

    def test_message_body_selector_covers_telegram_text_content_variants(self):
        self.assertIn('".text-content"', SOURCE)
        self.assertIn('".message-content"', SOURCE)
        self.assertIn('".content-inner"', SOURCE)

    def test_peer_identity_is_rechecked_during_history_scan(self):
        scan = SOURCE[SOURCE.index("for cycle in range(1, max_cycles + 1):"):SOURCE.index("for item in items:", SOURCE.index("for cycle in range(1, max_cycles + 1):"))]
        self.assertIn('expected_peer_id=str(selection.get("peer_id") or "")', scan)


if __name__ == "__main__":
    unittest.main()
