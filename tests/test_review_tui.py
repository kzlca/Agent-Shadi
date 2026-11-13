from types import SimpleNamespace
from unittest.mock import patch

from review_tui import ReviewDesk


def make_desk(path="processed", auto_advance=True):
    desk = ReviewDesk.__new__(ReviewDesk)
    desk.session = SimpleNamespace(
        wid="wf1", path=path, items=[{"id": "r1", "data": {"title": "one"}}, {"id": "r2", "data": {"title": "two"}}],
        offset=0, limit=50, query="", source="all", total=2, has_more=False,
        review_settings={"auto_advance": auto_advance, "sort": "newest"}, undo_token=None,
    )
    desk.index = 0
    desk.selected = set()
    desk.awaiting_advance = False
    desk.live_record = None
    desk.issue = "all"
    desk.detail_scroll = 0
    desk.extract_scroll = 0
    desk.pane_tab = "extraction" if path == "processed" else "message"
    desk.status = ""
    desk.error = False
    desk.batch = False
    desk.confirm_bulk = False
    desk.screen = None
    desk.running = True
    desk.message = lambda text, error=False: setattr(desk, "status", text)
    return desk


def test_extracted_record_approve_is_single_record_and_advances():
    desk = make_desk("processed", True)
    calls = []

    def fake_api(method, path, payload=None):
        calls.append((method, path, payload))
        return {"ok": True, "undo_token": "undo-1"}

    def fake_refresh(preserve=True):
        desk.session.items = [{"id": "r2", "data": {"title": "two"}}]
        desk.session.total = 1
        desk.index = min(desk.index, 0)

    desk.refresh = fake_refresh
    with patch("review_tui.api", side_effect=fake_api):
        desk.approve()

    assert calls == [("POST", "/api/records/r1/approve", None)]
    assert desk.session.undo_token == "undo-1"
    assert desk.current_id() == "r2"
    assert desk.awaiting_advance is False


def test_extracted_record_manual_advance_pauses_after_decision():
    desk = make_desk("processed", False)

    def fake_refresh(preserve=True):
        desk.session.items = [{"id": "r2", "data": {"title": "two"}}]
        desk.session.total = 1
        desk.index = 0

    desk.refresh = fake_refresh
    with patch("review_tui.api", return_value={"ok": True, "undo_token": "undo-2"}):
        desk.approve()

    assert desk.awaiting_advance is True
    assert desk.current_id() == "r2"  # next row is loaded but hidden behind the decision gate
    desk.move(1)
    assert desk.awaiting_advance is False
    assert desk.current_id() == "r2"


def test_live_extract_sends_only_the_focused_message():
    desk = make_desk("live", True)
    desk.screen = SimpleNamespace(getmaxyx=lambda: (24, 100))
    desk.draw = lambda: None
    desk.refresh = lambda preserve=True: None
    desk.session.items = [{"id": "m1", "raw_text": "one raw message"}, {"id": "m2", "raw_text": "not sent"}]
    result_record = {"id": "r-live-1", "data": {"title": "one"}}
    with patch("review_tui.api", return_value={"record": result_record}) as mocked:
        desk.extract()
    mocked.assert_called_once_with("POST", "/api/workflows/wf1/review/live/m1/extract")
    assert desk.live_record == result_record


def test_reject_confirmation_is_required():
    desk = make_desk("processed", True)
    desk.confirm = lambda prompt: False
    with patch("review_tui.api") as mocked:
        desk.reject()
    mocked.assert_not_called()
    assert "cancelled" in desk.status.lower()


def test_native_review_launcher_is_separate_from_webapp():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "review.sh").read_text(encoding="utf-8")
    web = (root / "app/static/app.js").read_text(encoding="utf-8")
    assert "review_tui.py" in launcher
    assert "konsole" in launcher
    assert "id=\"reviewCommandForm\"" not in web
    assert "renderStandaloneReviewLaunchCard" in web


def test_versioned_app_is_1818_and_desktop_launcher_can_be_installed():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    server = (root / "app/server.py").read_text(encoding="utf-8")
    installer = (root / "install_review_launcher.sh").read_text(encoding="utf-8")
    assert 'version=__version__' in server
    assert "agent-shadi-review-desk.desktop" in installer


def test_manual_advance_blocks_approve_until_operator_continues():
    desk = make_desk("processed", False)
    desk.awaiting_advance = True
    desk.screen = SimpleNamespace(getmaxyx=lambda: (24, 100), erase=lambda: None, refresh=lambda: None,
                                  keypad=lambda value: None, addnstr=lambda *args: None)
    # No decision API may be called while the explicit continue gate is active.
    with patch("review_tui.api") as mocked:
        desk.handle("a")
    mocked.assert_not_called()
    assert desk.awaiting_advance is True
    assert "paused" in desk.status.lower()
    desk.handle("\n")
    assert desk.awaiting_advance is False


def test_live_review_automatically_extracts_next_message_after_approval():
    desk = make_desk("live", True)
    desk.live_record = {"id": "record-1", "data": {"title": "one"}}
    desk.session.items = [{"id": "m2", "raw_text": "second raw message"}]
    desk.screen = SimpleNamespace(getmaxyx=lambda: (24, 100))
    desk.draw = lambda: None
    calls = []
    def fake_api(method, path, payload=None):
        calls.append((method, path, payload))
        if path == "/api/records/record-1/approve":
            return {"ok": True, "undo_token": "u"}
        if path.endswith("/m2/extract"):
            return {"record": {"id": "record-2", "data": {"title": "two"}}}
        raise AssertionError(path)
    def refresh(preserve=True):
        desk.session.items = [{"id": "m2", "raw_text": "second raw message"}]
        desk.session.total = 1
        desk.index = 0
    desk.refresh = refresh
    with patch("review_tui.api", side_effect=fake_api):
        desk.approve()
    assert calls[0][1] == "/api/records/record-1/approve"
    assert calls[1][1].endswith("/m2/extract")
    assert desk.live_record["id"] == "record-2"


def test_live_manual_advance_extracts_only_after_operator_continues():
    desk = make_desk("live", False)
    desk.live_record = {"id": "record-1", "data": {"title": "one"}}
    desk.session.items = [{"id": "m2", "raw_text": "second raw message"}]
    desk.screen = SimpleNamespace(getmaxyx=lambda: (24, 100))
    desk.draw = lambda: None
    desk.refresh = lambda preserve=True: None
    with patch("review_tui.api", return_value={"ok": True, "undo_token": "u"}):
        desk.approve()
    assert desk.awaiting_advance is True
    with patch("review_tui.api", return_value={"record": {"id": "record-2", "data": {}}}) as mocked:
        desk.move(1)
    mocked.assert_called_once_with("POST", "/api/workflows/wf1/review/live/m2/extract")
    assert desk.live_record["id"] == "record-2"


def test_extraction_inspector_tab_shows_fields_independently_of_long_message():
    desk = make_desk("processed", True)
    desk.session.workflow = {"name":"Long message review","config":{"fields":[
        {"name":"company","label":"Company name"},
        {"name":"role","label":"Job title"},
        {"name":"salary","label":"Salary"},
    ]}}
    desk.session.items = [{
        "id":"r-long",
        "source":"Long source",
        "posted_at":"2026-11-09",
        "raw_text":"Original message " * 1000,
        "data":{"company":"Northwind","role":"Analyst","salary":125000},
        "provenance":{"company":"LLM","role":"LLM","salary":"LLM"},
        "warnings":[],"errors":[],"confidence":0.95,
    }]
    desk.pane_tab = "extraction"
    calls=[]

    class Screen:
        def erase(self): pass
        def getmaxyx(self): return (30,120)
        def addnstr(self,y,x,text,width,attr=0): calls.append((y,x,str(text)[:width],attr))
        def refresh(self): pass

    desk.screen=Screen()
    with patch("review_tui.curses.color_pair",side_effect=lambda value:value*10):
        desk.draw()
    rendered="\n".join(row[2] for row in calls)
    assert "Company name" in rendered
    assert "Northwind" in rendered
    assert "Job title" in rendered
    assert "Analyst" in rendered
    assert "Salary" in rendered
    assert "125000" in rendered
    assert "[company]" not in rendered
    assert "[role]" not in rendered
    assert "source:" not in rendered
    assert "CONFIDENCE" not in rendered
    assert "EXTRACTED FIELDS" not in rendered
    field_attrs=[row[3] for row in calls if any(label in row[2] for label in ("Company name","Job title","Salary"))]
    assert len(set(field_attrs)) == 3
    # Both verification surfaces must be visible at the same time.
    assert any("ORIGINAL MESSAGE" in row[2] for row in calls)
    assert any("Original message" in row[2] for row in calls)


def test_tab_switches_scroll_focus_while_both_inspector_panels_remain_visible():
    desk=make_desk("processed",True)
    desk.screen=SimpleNamespace(getmaxyx=lambda:(30,120))
    desk.pane_tab="message"
    desk.handle("\t")
    assert desk.pane_tab=="extraction"
    desk.handle(__import__("curses").KEY_NPAGE)
    assert desk.extract_scroll>0
    desk.handle("\t")
    assert desk.pane_tab=="message"


def test_review_text_wrapping_respects_terminal_cells_for_rtl_and_long_tokens():
    from wcwidth import wcswidth
    cases = [
        ("متن فارسی برای بررسی مرز پنل و جلوگیری از سرریز", 12),
        ("https://example.test/" + "verylongtoken" * 12, 13),
        ("مرحبا بالعالم EnglishMixedWithفارسی 123456789", 15),
    ]
    for source, width in cases:
        lines = ReviewDesk._wrap(source, width)
        assert lines
        assert all(wcswidth(line) <= width for line in lines)


def test_review_put_clips_by_display_cells_before_writing():
    from wcwidth import wcswidth
    calls = []
    class Screen:
        def getmaxyx(self): return (24, 100)
        def addnstr(self, y, x, text, count, attr=0): calls.append((y, x, text, count, attr))
    desk = ReviewDesk.__new__(ReviewDesk)
    desk.screen = Screen()
    desk._put(5, 10, "این یک عبارت فارسی بسیار طولانی است", width=9)
    assert calls
    assert wcswidth(calls[-1][2]) <= 9


def test_review_draw_places_a_hard_vertical_divider_between_message_and_extraction():
    desk=make_desk("processed",True)
    desk.session.workflow={"name":"RTL","config":{"fields":[{"name":"title","label":"عنوان"}]}}
    desk.session.items=[{"id":"rtl-1","source":"Test","posted_at":"2026-11-10","raw_text":"پیام فارسی " + ("longenglishword" * 40),"data":{"title":"نمونه"}}]
    desk.screen=None
    calls=[]
    class Screen:
        def erase(self): pass
        def getmaxyx(self): return (30,120)
        def addnstr(self,y,x,text,width,attr=0): calls.append((y,x,str(text)[:width],attr))
        def refresh(self): pass
    desk.screen=Screen()
    with patch("review_tui.curses.color_pair",side_effect=lambda value:value*10):
        desk.draw()
    left_w=max(28,min(36,int(120*.30)))
    message_x=left_w+2
    available=120-message_x-3
    message_w=max(30,int(available*.56))
    extract_x=message_x+message_w+1
    divider_x=extract_x-1
    assert any(x==divider_x and text=="│" for _,x,text,_ in calls)
    assert any("EXTRACTED VALUES" in text for _,_,text,_ in calls)


def test_edit_mode_uses_numbered_inline_field_selection_and_saves_one_correction():
    desk=make_desk("processed",True)
    desk.session.workflow={"config":{"fields":[
        {"name":"title","label":"Title","type":"string"},
        {"name":"price","label":"Price","type":"integer"},
    ]}}
    desk.session.items=[{"id":"r-edit","data":{"title":"Old title","price":10}}]
    class Screen:
        def __init__(self): self.keys=iter(["2","e","s"])
        def getmaxyx(self): return (30,120)
        def erase(self): pass
        def refresh(self): pass
        def addnstr(self,*args): pass
        def get_wch(self): return next(self.keys)
    desk.screen=Screen()
    desk._prompt_edit_value=lambda label,current:"250"
    desk.refresh=lambda preserve=False:None
    calls=[]
    def fake_api(method,path,payload=None):
        calls.append((method,path,payload));return {"changed":{"price":{}},"data":payload["data"]}
    with patch("review_tui.api",side_effect=fake_api), patch("review_tui.curses.color_pair",side_effect=lambda value:value*10):
        desk._edit_record(desk.session.items[0])
    assert calls[0][0:2]==("PUT","/api/records/r-edit")
    assert calls[0][2]["data"]=={"title":"Old title","price":250}
    assert "Saved correction" in desk.status


def test_review_editor_coerces_types_and_json_values():
    assert ReviewDesk._coerce_review_value("42","integer")==42
    assert ReviewDesk._coerce_review_value("3.5","number")==3.5
    assert ReviewDesk._coerce_review_value("بله","boolean") is True
    assert ReviewDesk._coerce_review_value('[1,2]','array')==[1,2]
    assert ReviewDesk._coerce_review_value('{"x":1}','object')=={"x":1}
    assert ReviewDesk._coerce_review_value("", "string") is None
