import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.collectors import browser_runtime


class FakeChromium:
    def __init__(self, executable_path):
        self.executable_path = str(executable_path)
        self.calls = []

    def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class BrowserRuntimeTests(unittest.TestCase):
    def test_explicit_browser_path_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "chromium"
            executable.write_text("fake browser")
            executable.chmod(0o755)
            fake = FakeChromium(Path(tmp) / "missing-playwright-browser")
            with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {"STRUCTURA_CHROMIUM_EXECUTABLE": str(executable)}):
                result = browser_runtime.launch_persistent_context(fake, user_data_dir="profile", headless=False)
            self.assertEqual(result["executable_path"], str(executable.resolve()))
            self.assertEqual(result["user_data_dir"], "profile")
            self.assertIs(result["chromium_sandbox"], True)

    def test_invalid_explicit_path_has_actionable_error(self):
        fake = FakeChromium("/missing/playwright/chromium")
        with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {"STRUCTURA_CHROMIUM_EXECUTABLE": "/missing/system/chromium"}):
            with self.assertRaisesRegex(browser_runtime.BrowserUnavailableError, "points to a missing file"):
                browser_runtime.launch_persistent_context(fake, user_data_dir="profile")

    def test_existing_bundled_browser_is_used_when_no_system_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "pw-chromium"
            executable.write_text("fake browser")
            fake = FakeChromium(executable)
            with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {}, clear=True), patch.object(browser_runtime.shutil, "which", return_value=None):
                result = browser_runtime.launch_persistent_context(fake, user_data_dir="profile")
            self.assertNotIn("executable_path", result)
            self.assertEqual(result["user_data_dir"], "profile")
            self.assertIs(result["chromium_sandbox"], True)


    def test_sandbox_is_enabled_even_when_caller_does_not_set_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "chromium"
            executable.write_text("fake browser")
            executable.chmod(0o755)
            fake = FakeChromium(Path(tmp) / "missing-playwright-browser")
            with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {"STRUCTURA_CHROMIUM_EXECUTABLE": str(executable)}):
                result = browser_runtime.launch_persistent_context(fake, user_data_dir="profile")
            self.assertTrue(result["chromium_sandbox"])
            self.assertNotIn("--no-sandbox", result.get("args", []))



    def test_caller_cannot_disable_chromium_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "chromium"
            executable.write_text("fake browser")
            executable.chmod(0o755)
            fake = FakeChromium(Path(tmp) / "missing-playwright-browser")
            with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {"STRUCTURA_CHROMIUM_EXECUTABLE": str(executable)}):
                result = browser_runtime.launch_persistent_context(fake, user_data_dir="profile", chromium_sandbox=False)
            self.assertIs(result["chromium_sandbox"], True)

    def test_root_launch_is_rejected_in_shared_browser_runtime(self):
        fake = FakeChromium("/missing/playwright/chromium")
        with patch.object(browser_runtime.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(browser_runtime.BrowserUnavailableError, "cannot launch.*as root"):
                browser_runtime.launch_persistent_context(fake, user_data_dir="profile")

    def test_missing_browsers_gives_manjaro_install_command(self):
        fake = FakeChromium("/missing/playwright/chromium")
        with patch.object(browser_runtime.os, "geteuid", return_value=1000), patch.dict(os.environ, {}, clear=True), patch.object(browser_runtime.shutil, "which", return_value=None):
            with self.assertRaisesRegex(browser_runtime.BrowserUnavailableError, "sudo pacman -S --needed chromium"):
                browser_runtime.launch_persistent_context(fake, user_data_dir="profile")


if __name__ == "__main__":
    unittest.main(verbosity=2)
