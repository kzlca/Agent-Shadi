import contextlib
import io
import os
import unittest
from unittest.mock import patch

from app.collectors.inspector_control import enable_inspector_environment, pause_in_inspector


class FakePage:
    def __init__(self):
        self.pause_calls = 0

    def pause(self):
        self.pause_calls += 1


class InspectorControlTests(unittest.TestCase):
    def test_environment_uses_app_resume_gate_without_debugger(self):
        env = {"STRUCTURA_COLLECTOR_RESUME_FILE": "/tmp/old.signal", "OTHER": "keep"}
        result = enable_inspector_environment(env)
        self.assertNotIn("PWDEBUG", result)
        self.assertEqual(result["STRUCTURA_COLLECTOR_DEBUG_PAUSE"], "1")
        self.assertNotIn("STRUCTURA_COLLECTOR_RESUME_FILE", result)
        self.assertEqual(result["OTHER"], "keep")

    def test_page_pause_is_called_and_markers_are_printed(self):
        page = FakePage()
        out = io.StringIO()
        with patch.dict(os.environ, {"STRUCTURA_COLLECTOR_DEBUG_PAUSE": "1"}):
            with contextlib.redirect_stdout(out):
                self.assertTrue(pause_in_inspector(page, "Rubika", "sample_channel"))
        self.assertEqual(page.pause_calls, 1)
        self.assertIn("STRUCTURA_INSPECTOR_PAUSED=Rubika|sample_channel", out.getvalue())
        self.assertIn("STRUCTURA_INSPECTOR_RESUMED=Rubika|sample_channel", out.getvalue())

    def test_application_run_uses_one_shot_continue_signal_not_page_pause(self):
        import tempfile
        from pathlib import Path
        page = FakePage()
        marker = Path(tempfile.mkdtemp()) / "continue.signal"
        out = io.StringIO()
        def write_continue(milliseconds):
            marker.write_text("continue", encoding="utf-8")
        page.wait_for_timeout = write_continue
        with patch.dict(os.environ, {
            "STRUCTURA_COLLECTOR_DEBUG_PAUSE": "1",
            "STRUCTURA_COLLECTOR_RESUME_FILE": str(marker),
        }):
            with contextlib.redirect_stdout(out):
                self.assertTrue(pause_in_inspector(page, "Rubika", "@sample_feed_119"))
        self.assertFalse(marker.exists())
        self.assertEqual(page.pause_calls, 0)
        self.assertIn("STRUCTURA_OPERATOR_PAUSED=Rubika|@sample_feed_119", out.getvalue())
        self.assertIn("STRUCTURA_OPERATOR_RESUMED=Rubika|@sample_feed_119", out.getvalue())

    def test_explicit_disable_skips_inspector(self):
        page = FakePage()
        with patch.dict(os.environ, {"STRUCTURA_COLLECTOR_DEBUG_PAUSE": "0"}):
            self.assertFalse(pause_in_inspector(page, "Telegram", "sample"))
        self.assertEqual(page.pause_calls, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
