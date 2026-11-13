from pathlib import Path
import unittest


class TelegramPointerActivationTests(unittest.TestCase):
    def test_search_result_uses_real_pointer_coordinates(self):
        source = Path(__file__).parents[1].joinpath("app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertIn("click_x:Math.round(box.left+box.width/2)", source)
        self.assertIn("a.chatlist-chat[data-peer-id=", source)
        self.assertIn("locator.click(timeout=7000)", source)
        self.assertIn("page.mouse.click(int(x), int(y))", source)
        self.assertNotIn("target.click();", source)

    def test_telegram_message_discovery_is_not_limited_to_div_message(self):
        source = Path(__file__).parents[1].joinpath("app/collectors/telegram_collector.py").read_text(encoding="utf-8")
        self.assertIn("#column-center .bubble", source)
        self.assertIn("#column-center [data-message-id]", source)


if __name__ == "__main__":
    unittest.main()
