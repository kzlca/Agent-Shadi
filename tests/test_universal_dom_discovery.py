import shutil
import unittest

from app.collectors.web_inspector import WebInspectorManager, _CAPTURE_SCRIPT, _SCAN_PAGE_SCRIPT

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional in minimal CI images
    sync_playwright = None


EITAA_DOM = '''
<section class="chat-history">
  <div class="message spoilers-container mt-shorter"><span class="translatable-message">آپارتمان ۱۰۰ متری دو خواب در مرکز شهر با پارکینگ و آسانسور</span><span class="time"><span class="time-inner" title="11 November 2026, 00:20:59">۰۰:۲۰</span></span></div>
  <div class="message spoilers-container mt-shorter"><span class="translatable-message">خانه ویلایی ۱۵۰ متری سه خواب، حیاط دار و نوساز</span><span class="time"><span class="time-inner" title="10 November 2026, 19:20:59">۱۹:۲۰</span></span></div>
</section>'''

GENERIC_SEMANTIC_DOM = '''
<div class="chat-history">
  <div class="msg-row generated-a"><div class="msg-body"><span class="text-content">First generic messenger message body with enough useful text.</span><time datetime="2026-11-10T10:20:00Z"></time></div></div>
  <div class="msg-row generated-b"><div class="msg-body"><span class="text-content">Second generic messenger message body with enough useful text.</span><time datetime="2026-11-10T10:21:00Z"></time></div></div>
</div>'''

GENERIC_STRUCTURAL_DOM = '''
<div class="timeline">
  <div class="sc-a01 sc-x22"><p>Third party message with no useful class names, but a long readable body.</p><time datetime="2026-11-10T10:20:00Z"></time></div>
  <div class="sc-a01 sc-x22"><p>Another third party message with no useful class names, but a long readable body.</p><time datetime="2026-11-10T10:21:00Z"></time></div>
  <div class="sc-a01 sc-x22"><p>Yet another third party message with no useful class names, but a long readable body.</p><time datetime="2026-11-10T10:22:00Z"></time></div>
</div>'''


SIDEBAR_PLUS_MAIN_DOM = '''
<aside class="left-sidebar chatlist-panel">
  <a class="chatlist-chat chatlist-chat-bigger _Item_5idej_1" href="#chat-1"><span class="preview">آپارتمان فروشی در مرکز شهر با دو خواب</span><span class="time" title="۱۴۰۵/۰۸/۱۹">۱۹ آبان</span></a>
  <a class="chatlist-chat chatlist-chat-bigger _Item_5idej_1" href="#chat-2"><span class="preview">اجاره خانه با پارکینگ و آسانسور</span><span class="time" title="۱۴۰۵/۰۸/۱۸">۱۸ آبان</span></a>
  <a class="chatlist-chat chatlist-chat-bigger _Item_5idej_1" href="#chat-3"><span class="preview">مغازه تجاری نزدیک بازار</span><span class="time" title="۱۴۰۵/۰۸/۱۷">۱۷ آبان</span></a>
</aside>
<main class="active-conversation-panel">
  <div class="scroll-window">
    <div class="sc-a-message_1 sc-random_72"><p>پیام واقعی اول در گفتگوی فعال با جزئیات کافی برای تشخیص محتوای مستقل</p><time title="۱۴۰۵/۰۸/۱۹ ۱۰:۲۰:۳۰">۱۰:۲۰</time></div>
    <div class="sc-a-message_1 sc-random_73"><p>پیام واقعی دوم در گفتگوی فعال با متن متفاوت و جزئیات مستقل</p><time title="۱۴۰۵/۰۸/۱۹ ۱۰:25:30">۱۰:۲۵</time></div>
    <div class="sc-a-message_1 sc-random_74"><p>پیام واقعی سوم در گفتگوی فعال و شامل توضیحی درباره فایل ملک</p><time title="۱۴۰۵/۰۸/۱۹ ۱۰:30:30">۱۰:۳۰</time></div>
  </div>
</main>
'''


def _has_real_playwright():
    if not sync_playwright or not shutil.which("chromium"):
        return False
    try:
        manager = sync_playwright()
        return manager is not None and callable(getattr(manager, "start", None))
    except Exception:
        return False


@unittest.skipUnless(_has_real_playwright(), "Requires real Playwright and system Chromium")
class UniversalDomDiscoveryBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True, executable_path=shutil.which("chromium"), args=["--no-sandbox"])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def _scan(self, html, config):
        self.page.set_content(f"<html><head><title>Universal test</title></head><body>{html}</body></html>")
        return self.page.evaluate("(" + _SCAN_PAGE_SCRIPT + ")", {"config": config, "maxMessages": 100})

    def test_eitaa_stale_root_and_text_selectors_recover_in_pagination_scan(self):
        result = self._scan(EITAA_DOM, {
            "site_preset": "eitaa",
            "root": {"selector": "div.message.spoilers-container.old-volatile-class"},
            "fields": {"text": {"selector": ".old-message-content", "attribute": "textContent"}},
            "navigation": {}
        })
        self.assertEqual(result["root_count"], 2)
        self.assertEqual(result["root_selector_diagnostics"]["mode"], "universal_recovery")
        self.assertEqual(result["root_selector_diagnostics"]["used"], "div.message")
        self.assertIn("آپارتمان ۱۰۰ متری", result["items"][0]["raw_text"])
        self.assertEqual(result["items"][0]["posted_at"], "11 November 2026, 00:20:59")
        self.assertEqual(result["message_discovery_diagnostics"]["timestamp_mapped_count"], 2)

    def test_generic_messenger_semantic_blocks_auto_discover_without_saved_selector(self):
        result = self._scan(GENERIC_SEMANTIC_DOM, {"fields": {}, "navigation": {}})
        self.assertEqual(result["root_count"], 2)
        self.assertEqual(result["root_selector_diagnostics"]["mode"], "universal_auto_discovery")
        self.assertEqual(result["root_selector_diagnostics"]["used"], "div.msg-row")
        self.assertEqual(result["items"][1]["posted_at"], "2026-11-10T10:21:00Z")

    def test_generated_class_layout_uses_repeated_structural_fallback(self):
        result = self._scan(GENERIC_STRUCTURAL_DOM, {"root": {"selector": "div.legacy-message"}, "fields": {}, "navigation": {}})
        self.assertEqual(result["root_count"], 3)
        self.assertEqual(result["root_selector_diagnostics"]["mode"], "universal_recovery")
        self.assertTrue(result["message_root_candidates"][0]["generic"])
        self.assertIn("Third party message", result["items"][0]["raw_text"])

    def test_sidebar_chat_rows_are_rejected_and_main_generated_message_blocks_win(self):
        result = self._scan(SIDEBAR_PLUS_MAIN_DOM, {
            "root": {"selector": "div.etme_widget_message_wrap.js-widget_message_wrap"},
            "fields": {"text": {"selector": ".stale-message-text"}},
            "navigation": {}
        })
        self.assertEqual(result["root_count"], 3)
        self.assertIn("active-conversation-panel", result["message_discovery_diagnostics"]["candidate_groups"][0]["parent_context"])
        self.assertIn("پیام واقعی اول", result["items"][0]["raw_text"])
        self.assertNotIn("آپارتمان فروشی", " ".join(x["raw_text"] for x in result["items"]))
        self.assertEqual(result["items"][0]["posted_at"], "۱۴۰۵/۰۸/۱۹ ۱۰:۲۰:۳۰")

    def test_visible_capture_path_uses_same_shared_discovery_engine(self):
        self.page.set_content(f"<html><body>{GENERIC_SEMANTIC_DOM}</body></html>")
        result = self.page.evaluate("(" + _CAPTURE_SCRIPT + ")", {
            "config": {"root": {"selector": ".broken-root"}, "fields": {"text": {"selector": ".broken-text"}}, "navigation": {"strategy": "manual"}},
            "maxMessages": 100, "strategy": "manual", "requestedStrategy": "manual", "autoNavigation": False
        })
        self.assertEqual(result["root_count"], 2)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["root_selector_diagnostics"]["mode"], "universal_recovery")

    def test_upward_scroll_uses_inferred_message_ancestor_when_saved_selector_is_stale(self):
        html = '''
        <style>
          html,body{margin:0;padding:0}
          #history-viewport{height:190px;width:620px;overflow-y:auto;overflow-x:hidden;border:1px solid #aaa}
          #history-content{display:block}
          .message{height:86px;box-sizing:border-box;border-bottom:1px solid #ddd;padding:8px}
        </style>
        <main class="active-conversation-panel">
          <div id="history-viewport" class="new-message-pane">
            <div id="history-content">
              <div class="message"><p>Current message one contains enough meaningful content to be recognized as a post.</p><time datetime="2026-11-10T12:00:00+03:30"></time></div>
              <div class="message"><p>Current message two contains a different body and stable timestamp metadata.</p><time datetime="2026-11-10T11:00:00+03:30"></time></div>
              <div class="message"><p>Current message three contains enough text for reliable discovery in this test.</p><time datetime="2026-11-10T10:00:00+03:30"></time></div>
              <div class="message"><p>Current message four contains independent text with a parseable date attribute.</p><time datetime="2026-11-10T09:00:00+03:30"></time></div>
              <div class="message"><p>Current message five contains further details and must remain captured.</p><time datetime="2026-11-10T08:00:00+03:30"></time></div>
            </div>
          </div>
        </main>
        <script>
          const viewport=document.getElementById('history-viewport');
          const content=document.getElementById('history-content');
          viewport.scrollTop=viewport.scrollHeight;
          let loadedOlder=false;
          viewport.addEventListener('scroll',()=>{
            if(!loadedOlder && viewport.scrollTop<=5){
              loadedOlder=true;
              content.insertAdjacentHTML('afterbegin', `
                <div class="message"><p>Older message six was loaded after the operator moved upward in the message history.</p><time datetime="2026-11-09T23:00:00+03:30"></time></div>
                <div class="message"><p>Older message seven was loaded dynamically by the messenger scroll handler.</p><time datetime="2026-11-09T22:00:00+03:30"></time></div>
                <div class="message"><p>Older message eight was also loaded from the earlier history boundary.</p><time datetime="2026-11-09T21:00:00+03:30"></time></div>
              `);
            }
          });
        </script>
        '''
        self.page.set_content(html)
        result = self.page.evaluate("(" + _CAPTURE_SCRIPT + ")", {
            "config": {
                "root": {"selector": ".obsolete-eitaa-message-root"},
                "fields": {"text": {"selector": ".obsolete-message-text"}},
                "navigation": {
                    "strategy": "infinite_scroll", "direction": "up",
                    "scroll_selector": ".etme_channel_history.js-message_history",
                    "wait_mode": "fixed", "wait_ms": 250, "min_wait_ms": 100,
                    "stable_ms": 50, "scroll_step_ratio": 1.5, "max_idle_cycles": 2
                }
            },
            "maxMessages": 100, "strategy": "infinite_scroll",
            "requestedStrategy": "pagination", "autoNavigation": True,
            "maxScrollCycles": 1
        })
        self.assertEqual(result["scroll_cycles"], 1)
        self.assertEqual(result["root_count"], 8)
        self.assertTrue(result["scroll_diagnostics"]["observed_movement"])
        self.assertEqual(result["scroll_diagnostics"]["scroller_resolution"]["configured_selector_status"], "not_found")
        self.assertEqual(result["scroll_diagnostics"]["scroller_resolution"]["selected_by"], "message_ancestor_inference")
        bodies = " ".join(item["raw_text"] for item in result["items"])
        self.assertIn("Older message six", bodies)
        self.assertIn("Current message one", bodies)

    def test_date_range_scroll_checks_newest_edge_then_older_edge_without_window_resize(self):
        html = r'''
        <style>
          html,body{margin:0;padding:0}
          #chat-scroll{height:190px;width:620px;overflow-y:auto;overflow-x:hidden}
          .message{height:86px;box-sizing:border-box;border-bottom:1px solid #ddd;padding:8px}
        </style>
        <main class="active-conversation">
          <div id="chat-scroll">
            <div class="message"><p>Post one contains a full body for the universal discovery test.</p><time datetime="2026-11-10T08:00:00+03:30"></time></div>
            <div class="message"><p>Post two contains a distinct body and a valid timestamp.</p><time datetime="2026-11-10T09:00:00+03:30"></time></div>
            <div class="message"><p>Post three contains independent text for the active message list.</p><time datetime="2026-11-10T10:00:00+03:30"></time></div>
            <div class="message"><p>Post four contains more useful content and date metadata.</p><time datetime="2026-11-10T11:00:00+03:30"></time></div>
            <div class="message"><p>Post five is the latest currently loaded message in the viewport.</p><time datetime="2026-11-10T12:00:00+03:30"></time></div>
          </div>
        </main>
        <script>
          const scroller=document.getElementById('chat-scroll');
          const list=scroller.firstElementChild;
          let olderAdded=false;
          scroller.scrollTop=260;
          scroller.addEventListener('scroll',()=>{
            if(!olderAdded && scroller.scrollTop<=3){
              olderAdded=true;
              list.insertAdjacentHTML('afterbegin', `
                <div class="message"><p>Older post six loaded only after reaching the older edge.</p><time datetime="2026-11-09T22:00:00+03:30"></time></div>
                <div class="message"><p>Older post seven loaded only after reaching the older edge.</p><time datetime="2026-11-09T21:00:00+03:30"></time></div>
              `);
            }
          });
        </script>
        '''
        self.page.set_content(html)
        config = {
            "root": {"selector": ".message"},
            "fields": {"text": {"selector": "p"}, "timestamp": {"selector": "time", "attribute": "datetime"}},
            "navigation": {"strategy": "infinite_scroll", "direction": "up", "scroll_selector": "#missing-old-selector",
                            "wait_mode": "fixed", "wait_ms": 180, "min_wait_ms": 100, "stable_ms": 40,
                            "scroll_step_ratio": 1.5, "max_idle_cycles": 3, "max_scrolls": 12,
                            "timestamp_timezone": "Asia/Tehran"}
        }
        initial = self.page.evaluate("(" + _SCAN_PAGE_SCRIPT + ")", {"config": config, "maxMessages": 100})
        result = WebInspectorManager()._capture_scrolling_date_range(
            self.page,
            {"config": config, "maxMessages": 100, "dateStart": "2026-11-10", "dateEnd": "2026-11-10", "requestedStrategy": "pagination"},
            initial_page=initial,
            reason="browser fixture bidirectional traversal",
        )
        self.assertTrue(result["date_range"]["complete"], result["date_range"])
        self.assertEqual(result["date_range"]["in_range"], 5)
        self.assertEqual(result["date_range"]["oldest_seen"], "2026-11-09")
        self.assertEqual(result["scroll_diagnostics"]["boundary_traversal"]["newer_direction"], "down")
        self.assertEqual(result["scroll_diagnostics"]["boundary_traversal"]["older_direction"], "up")
        phases = [item["phase"] for item in result["scroll_diagnostics"]["last_cycles"]]
        self.assertIn("newer", phases)
        self.assertIn("older", phases)
        self.assertEqual(result["date_range"]["excluded_before"], 2)

    def test_no_confident_roots_returns_actionable_dom_diagnostics(self):
        result = self._scan('<div class="random-panel"><button>Settings</button><span>Compose</span></div>', {"root": {"selector": ".missing"}, "fields": {}, "navigation": {}})
        self.assertEqual(result["root_count"], 0)
        self.assertIsNotNone(result["dom_diagnostics"])
        self.assertIn("scanned_element_count", result["message_discovery_diagnostics"])
        self.assertEqual(result["message_discovery_diagnostics"]["configured_selector"], ".missing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
