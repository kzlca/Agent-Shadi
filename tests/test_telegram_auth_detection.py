import unittest
from pathlib import Path
from app.collectors.telegram_auth import login_screen_state


TELEGRAM_SELECTORS = {
    "logged_in_indicator": "div.input-search, .sidebar-header",
    "login_screen_indicator": "button:has-text('Log in by QR Code'), .auth-form",
}


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    @property
    def first(self):
        return self

    def is_visible(self, timeout=150):
        return bool(self.page.visible.get(self.selector, False))


class FakePage:
    def __init__(self, visible):
        self.visible = visible

    def locator(self, selector):
        return FakeLocator(self, selector)


class TelegramAuthDetectionTests(unittest.TestCase):
    def test_bare_canvas_is_not_mistaken_for_sign_in_screen(self):
        page = FakePage({"canvas": True})
        state = login_screen_state(page, "Telegram", TELEGRAM_SELECTORS)
        self.assertFalse(state["visible"])

    def test_collector_configuration_does_not_use_unscoped_canvas(self):
        source = Path(__file__).parents[1].joinpath("app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertNotIn('"login_screen_indicator": "canvas,', source)
        self.assertIn('from .telegram_auth import first_visible_selector, login_screen_state', source)

    def test_explicit_qr_login_button_without_app_shell_is_sign_in(self):
        selector = "button:has-text('Log in by QR Code')"
        page = FakePage({selector: True})
        state = login_screen_state(page, "Telegram", TELEGRAM_SELECTORS)
        self.assertTrue(state["visible"])
        self.assertEqual(state["evidence"], selector)

    def test_auth_form_without_app_shell_is_sign_in(self):
        page = FakePage({".auth-form": True})
        state = login_screen_state(page, "Telegram", TELEGRAM_SELECTORS)
        self.assertTrue(state["visible"])

    def test_stale_login_form_does_not_override_visible_authenticated_shell(self):
        page = FakePage({".auth-form": True, ".sidebar-header": True})
        state = login_screen_state(page, "Telegram", TELEGRAM_SELECTORS)
        self.assertFalse(state["visible"])
        self.assertTrue(state["app_shell_visible"])


if __name__ == "__main__":
    unittest.main()
