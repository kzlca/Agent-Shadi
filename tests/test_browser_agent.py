import unittest
from unittest.mock import Mock

from app.sources.browser_agent import validate_action, execute_action


class BrowserAgentTests(unittest.TestCase):
    def test_only_bounded_actions_are_allowed(self):
        self.assertEqual(validate_action({"type": "wait", "milliseconds": 900})["milliseconds"], 900)
        with self.assertRaises(ValueError):
            validate_action({"type": "evaluate", "script": "alert(1)"})
        with self.assertRaises(ValueError):
            validate_action({"type": "navigate", "url": "javascript:alert(1)"})

    def test_action_payload_is_bounded(self):
        with self.assertRaises(ValueError):
            validate_action({"type": "fill", "selector": "input", "value": "x" * 2001})
        with self.assertRaises(ValueError):
            validate_action({"type": "press", "selector": "input", "key": "Control+W"})

    def test_execution_records_before_and_after_evidence(self):
        page = Mock()
        page.evaluate.side_effect = [
            {"url": "https://example.test", "title": "Before", "ready_state": "complete", "body_text": "before", "body_chars": 6, "controls": [], "repeated_candidates": [], "scrollables": [], "visible_content_count": 0, "active_element": {}},
            {"url": "https://example.test/channel", "title": "After", "ready_state": "complete", "body_text": "after", "body_chars": 5, "controls": [], "repeated_candidates": [], "scrollables": [], "visible_content_count": 4, "active_element": {}},
        ]
        page.locator.return_value.first.click = Mock()
        result = execute_action(page, {"type": "click", "selector": "a.result"})
        self.assertTrue(result["changed"])
        self.assertTrue(result["evidence"]["title_changed"])
        page.locator.assert_called_with("a.result")

    def test_observation_script_is_read_only_and_omits_input_values(self):
        from app.sources.browser_agent import OBSERVE_SCRIPT
        self.assertIn("input,textarea,select", OBSERVE_SCRIPT)
        self.assertNotIn("el.value", OBSERVE_SCRIPT)
        self.assertNotIn("localStorage", OBSERVE_SCRIPT)
        self.assertNotIn("document.cookie", OBSERVE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
