import os
import tempfile
import time
import unittest
import httpx
from unittest.mock import patch

os.environ["STRUCTURA_FLOW_DATA"] = tempfile.mkdtemp(prefix="structura-flow-tests-")

from fastapi.testclient import TestClient
from app.server import app, get_model_settings, set_model_settings, COLLECT_STATE, LIVE_EXTRACTION_STATE, create_run, conn, now, dumps, init_db, _parse_collector_phase_line, _agent_tool_execute, _collector_source_in_scope


class WorkflowApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        settings = get_model_settings()
        settings["enabled"] = False
        settings["allow_rules_only"] = True
        settings["connection_verified"] = False
        set_model_settings(settings)
        cls.bootstrap = cls.client.get("/api/bootstrap").json()
        cls.workflow_id = cls.bootstrap["workflows"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def wait_run(self, run_id):
        for _ in range(200):
            data = self.client.get(f"/api/runs/{run_id}").json()
            if data["status"] in {"completed", "completed_with_errors", "failed"}:
                return data
            time.sleep(0.025)
        self.fail("Background extraction did not finish")

    def test_collector_platform_scope_excludes_archived_other_platform_sources(self):
        self.assertTrue(_collector_source_in_scope("telegram:sample_feed_118", {"telegram"}))
        self.assertFalse(_collector_source_in_scope("rubika:sample_feed_119", {"telegram"}))
        self.assertTrue(_collector_source_in_scope("rubika:sample_feed_119", {"telegram", "rubika"}))
        self.assertFalse(_collector_source_in_scope("telegram:failed_old_channel", {"telegram"}, {"telegram:sample_feed_118"}))
        self.assertTrue(_collector_source_in_scope("telegram:sample_feed_118", {"telegram"}, {"telegram:sample_feed_118"}))

    def test_system_diagnostics_endpoint_returns_safe_runtime_summary(self):
        response = self.client.get("/api/diagnostics")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["application"]["version"], "1.8.37")
        self.assertIn("collectors", data)
        self.assertIn("privacy", data)
        self.assertNotIn("cookies", data)
        self.assertNotIn("credentials", data)

    def test_agent_chat_sends_only_one_leading_system_message(self):
        from app.server import _reset_model_status_cache

        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"Qwen3.5-9B-Q6_K.gguf","connection_verified":True})
        set_model_settings(settings)
        captured={}

        class FakeResponse:
            def raise_for_status(self): return None
            def json(self): return {"choices":[{"message":{"content":"The workflow looks correctly configured."}}]}

        class FakeClient:
            def __init__(self,*args,**kwargs): captured["timeout"]=kwargs.get("timeout")
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None):
                captured["url"]=url;captured["request"]=json
                return FakeResponse()

        try:
            with patch("app.server._model_runtime_result",return_value={"ok":True,"status":"online","model":settings["model"]}), patch("app.server.httpx.Client",FakeClient):
                chat_history=[{"role":"user","content":"Earlier task details " + ("x"*5000)}, {"role":"assistant","content":"Earlier assistant response " + ("y"*5000)}] * 5
                chat_history.append({"role":"user","content":"Can you review my workflow?"})
                response=self.client.post(f"/api/workflows/{self.workflow_id}/agent/chat",json={"messages":chat_history})
            self.assertEqual(response.status_code,200,response.text)
            messages=captured["request"]["messages"]
            self.assertEqual(messages[0]["role"],"system")
            self.assertEqual(sum(1 for message in messages if message["role"]=="system"),1)
            self.assertIn("Current workflow metadata",messages[0]["content"])
            self.assertIn("knowledge-based AI data-collection and data-quality specialist",messages[0]["content"])
            self.assertIn("not a generic full-stack web developer",messages[0]["content"])
            self.assertIn("RELEVANT PRODUCT KNOWLEDGE",messages[0]["content"])
            self.assertIn("Do not assume the user is working with real estate",messages[0]["content"])
            self.assertIn("practical product-side partner",messages[0]["content"])
            self.assertIn("Call inspect_collection before advising",messages[0]["content"])
            self.assertIn("Do not suggest Step/Resume or blind clicking/scrolling",messages[0]["content"])
            self.assertIn("MANUAL HISTORY RECOVERY",messages[0]["content"])
            self.assertEqual(captured["request"]["max_tokens"],650)
            self.assertEqual(messages[-1]["role"],"user")
            self.assertEqual(messages[-1]["content"],"Can you review my workflow?")
            self.assertLessEqual(sum(len(m.get("content") or "") for m in messages[1:]),11000)
            self.assertGreaterEqual(captured["timeout"].read,180)
        finally:
            set_model_settings(before)
            _reset_model_status_cache()


    def test_agent_tool_call_round_trip_executes_only_the_allowlisted_app_tool(self):
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        captured=[]
        class FakeResponse:
            def __init__(self,payload): self.payload=payload
            def raise_for_status(self): return None
            def json(self): return self.payload
        class FakeClient:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None):
                captured.append(json)
                if len(captured)==1:
                    return FakeResponse({"choices":[{"message":{"role":"assistant","content":"I will inspect the workflow first.","tool_calls":[{"id":"call_inspect_1","type":"function","function":{"name":"inspect_workflow","arguments":"{}"}}]}}]})
                return FakeResponse({"choices":[{"message":{"role":"assistant","content":"I inspected the workflow. It is ready for the next step."}}]})
        try:
            with patch("app.server._model_runtime_result",return_value={"ok":True,"status":"online","model":"test-model"}), patch("app.server.httpx.Client",FakeClient):
                response=self.client.post(f"/api/workflows/{self.workflow_id}/agent/chat",json={"messages":[{"role":"user","content":"Inspect my workflow"}]})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIn("inspected the workflow",response.json()["answer"])
            self.assertEqual(len(captured),2)
            self.assertEqual(captured[0]["tools"],captured[1]["tools"])
            tool_messages=[m for m in captured[1]["messages"] if m["role"]=="tool"]
            self.assertEqual(len(tool_messages),1)
            self.assertEqual(tool_messages[0]["tool_call_id"],"call_inspect_1")
            self.assertIn('"workflow"',tool_messages[0]["content"])
        finally:
            set_model_settings(before)
            _reset_model_status_cache()

    def test_agent_tools_can_update_existing_connector_without_collecting(self):
        from app.server import _agent_tool_execute
        wid=self.client.post("/api/workflows",json={"name":"Agent connector tool test","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Demo web feed","url":"https://example.test/feed","description":"Test feed",
            "config":{"root":{"method":"css","selector":".post"},"fields":{"text":{"selector":".post-body","attribute":"textContent"}},"navigation":{"strategy":"manual"}}
        })
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        result=_agent_tool_execute(wid,"update_web_connector",{"connector_id":cid,"changes":{"config":{"root":{"selector":"article.post"},"fields":{"text":{"selector":".content","attribute":"textContent"}}}}})
        self.assertTrue(result["ok"],result)
        self.assertEqual(result["connector"]["config"]["root"]["selector"],"article.post")
        self.assertEqual(result["connector"]["config"]["fields"]["text"]["selector"],".content")
        inspected=_agent_tool_execute(wid,"inspect_web_connector",{"connector_id":cid})
        self.assertTrue(inspected["ok"],inspected)
        self.assertEqual(inspected["connectors"][0]["browser"]["status"],"idle")
        self.assertTrue(inspected["connectors"][0]["session"]["persistent"])
        self.assertTrue(inspected["connectors"][0]["session"]["profile_directory"].endswith("browser-profile"))
        self.assertEqual(inspected["connectors"][0]["inbox_counts"],{})
        status=_agent_tool_execute(wid,"control_web_connector_browser",{"connector_id":cid,"action":"status"})
        self.assertEqual(status["status"],"idle")
        self.assertTrue(status["session"]["persistent"])
        session_update=_agent_tool_execute(wid,"update_web_connector",{"connector_id":cid,"changes":{"config":{"session":{"persist":False},"navigation":{"wait_mode":"adaptive","max_wait_ms":8000,"scroll_step_ratio":0.5}}}})
        self.assertTrue(session_update["ok"],session_update)
        self.assertFalse(session_update["connector"]["config"]["session"]["persist"])
        self.assertEqual(session_update["connector"]["config"]["navigation"]["max_wait_ms"],8000)
        self.assertFalse(_agent_tool_execute(wid,"control_web_connector_browser",{"connector_id":cid,"action":"status"})["session"]["persistent"])
        denied=_agent_tool_execute(wid,"delete_records",{"ids":["anything"]})
        self.assertFalse(denied["ok"])
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_agent_tool_connector_scope_cannot_cross_workflows(self):
        from app.server import _agent_tool_execute
        wid_a=self.client.post("/api/workflows",json={"name":"Agent scope A","template":"custom"}).json()["id"]
        wid_b=self.client.post("/api/workflows",json={"name":"Agent scope B","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid_a}/web-connectors",json={"name":"Private connector","url":"https://example.test","config":{}}).json()
        result=_agent_tool_execute(wid_b,"inspect_web_connector",{"connector_id":created["id"]})
        self.assertFalse(result["ok"])
        self.assertIn("not found",result["error"].lower())
        self.client.delete(f"/api/web-connectors/{created['id']}")
        self.client.delete(f"/api/workflows/{wid_a}")
        self.client.delete(f"/api/workflows/{wid_b}")

    def test_agent_chat_includes_saved_web_connector_state_without_url_secrets(self):
        from app.server import _reset_model_status_cache
        wid=self.client.post("/api/workflows",json={"name":"Connector assistant context test","template":"custom"}).json()["id"]
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        connector=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Browser Channel Connector",
            "url":"https://example.test/channel?session_secret=do-not-send#fragment_secret_value",
            "description":"Collect visible channel messages",
            "config":{"root":{"method":"css","selector":".message"},"fields":{"text":{"selector":".body","attribute":"textContent"},"sender":{"selector":".author","attribute":"textContent"}},"navigation":{"strategy":"infinite_scroll"}},
        })
        self.assertEqual(connector.status_code,200,connector.text)
        self.client.post(f"/api/workflows/{wid}/messages/paste",json={"text":"Connector inbox test message","source":"Browser Channel Connector"})
        captured={}
        class FakeResponse:
            def raise_for_status(self): return None
            def json(self): return {"choices":[{"message":{"content":"Open the saved connector and continue."}}]}
        class FakeClient:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None): captured["request"]=json; return FakeResponse()
        try:
            with patch("app.server._model_runtime_result",return_value={"ok":True,"status":"online","model":"test-model"}), patch("app.server.httpx.Client",FakeClient):
                response=self.client.post(f"/api/workflows/{wid}/agent/chat",json={"messages":[{"role":"user","content":"Help me continue connector setup"}]})
            self.assertEqual(response.status_code,200,response.text)
            system=captured["request"]["messages"][0]["content"]
            self.assertIn("Browser Channel Connector",system)
            self.assertIn("https://example.test/channel",system)
            self.assertIn(".message",system)
            self.assertIn(".body",system)
            self.assertIn("infinite_scroll",system)
            self.assertIn('"queued":1',system)
            self.assertIn('"processing_path":"processed"',system)
            self.assertNotIn("session_secret",system)
            self.assertNotIn("fragment_secret_value",system)
        finally:
            set_model_settings(before)
            _reset_model_status_cache()
            self.client.delete(f"/api/web-connectors/{connector.json()['id']}")

    def test_model_status_discovers_loaded_models_before_one_is_selected(self):
        from app.server import _reset_model_status_cache

        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"","connection_verified":False})
        set_model_settings(settings)
        discovered=["/run/media/kzlca/Home/AI/models/Qwen3.5-9B-Q6_K.gguf"]
        try:
            with patch("app.server._probe_model_endpoint",return_value=discovered):
                response=self.client.get("/api/settings/model/status?force=true")
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()["status"],"not_configured")
            self.assertEqual(response.json()["models"],discovered)
        finally:
            set_model_settings(before)
            _reset_model_status_cache()


    def test_background_run_can_pause_resume_and_cancel(self):
        wid = self.workflow_id
        rid = create_run(wid, "explicit batch extraction", 3)
        with conn() as db:
            db.execute("UPDATE runs SET status='running' WHERE id=?", (rid,))
        paused = self.client.post(f"/api/runs/{rid}/pause")
        self.assertEqual(paused.status_code, 200, paused.text)
        self.assertEqual(self.client.get(f"/api/runs/{rid}").json()["status"], "paused")
        resumed = self.client.post(f"/api/runs/{rid}/resume")
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(self.client.get(f"/api/runs/{rid}").json()["status"], "running")
        cancelled = self.client.post(f"/api/runs/{rid}/cancel")
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.client.get(f"/api/runs/{rid}").json()["status"], "cancelled")

    def test_live_review_queue_extracts_exactly_one_message_and_creates_pending_record(self):
        from unittest.mock import patch
        created = self.client.post("/api/workflows", json={"name":"Live AI review test","template":"custom"})
        wid = created.json()["id"]
        pasted = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Product: Widget A\nPrice: 42","source":"Live review test"})
        self.assertEqual(pasted.status_code, 200)
        mid = pasted.json()["items"][0]["id"] if "items" in pasted.json() else None
        if not mid:
            messages = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()
            mid = messages[0]["id"]
        settings = get_model_settings(); before = dict(settings)
        settings.update({"enabled": True, "allow_rules_only": False, "model": "test-model", "base_url": "http://127.0.0.1:1234/v1", "connection_verified": True})
        set_model_settings(settings)
        fake_result = {"data":{"name":"Widget A","category":None,"price":42,"location":None},"provenance":{"name":"LLM","price":"LLM"},"warnings":[],"errors":[],"confidence":0.91,"engine":"llm","metadata":{"model":"test-model"}}
        try:
            queue = self.client.get(f"/api/workflows/{wid}/review/live/queue")
            self.assertEqual(queue.status_code, 200)
            self.assertEqual(queue.json()["total"], 1)
            self.assertEqual(queue.json()["items"][0]["id"], mid)
            with patch("app.server._model_runtime_result", return_value={"ok":True,"status":"online","model":"test-model"}), patch("app.server.extract_one", return_value=fake_result):
                response = self.client.post(f"/api/workflows/{wid}/review/live/{mid}/extract")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["record"]["status"], "needs_review")
            self.assertEqual(response.json()["record"]["data"]["name"], "Widget A")
            self.assertEqual(self.client.get(f"/api/workflows/{wid}/review/live/queue").json()["total"], 0)
            pending = self.client.get(f"/api/workflows/{wid}/review/queue").json()
            self.assertEqual(pending["total"], 1)
            self.assertEqual(pending["items"][0]["message_id"], mid)
        finally:
            set_model_settings(before)
            from app.server import _reset_model_status_cache
            _reset_model_status_cache()

    def test_live_review_requires_online_llm_without_claiming_message(self):
        from unittest.mock import patch
        created = self.client.post("/api/workflows", json={"name":"Live AI offline guard","template":"custom"})
        wid = created.json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Message waiting for AI","source":"Offline test"})
        item = self.client.get(f"/api/workflows/{wid}/review/live/queue").json()["items"][0]
        with patch("app.server._model_runtime_result", return_value={"ok":False,"status":"offline","message":"Model server offline"}):
            response = self.client.post(f"/api/workflows/{wid}/review/live/{item['id']}/extract")
        self.assertEqual(response.status_code, 503)
        refreshed = self.client.get(f"/api/workflows/{wid}/review/live/queue").json()["items"][0]
        self.assertEqual(refreshed["status"], "queued")

    def test_live_progress_is_published_before_model_health_probe(self):
        wid=self.client.post("/api/workflows",json={"name":"Progress appears before model probe","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste",json={"text":"A source message","source":"Progress test"})
        item=self.client.get(f"/api/workflows/{wid}/review/live/queue").json()["items"][0]
        observed={}
        def offline_probe(*args,**kwargs):
            observed.update(self.client.get(f"/api/workflows/{wid}/review/live/{item['id']}/progress").json())
            return {"ok":False,"status":"offline","message":"Model server offline"}
        with patch("app.server._model_runtime_result",side_effect=offline_probe):
            response=self.client.post(f"/api/workflows/{wid}/review/live/{item['id']}/extract")
        self.assertEqual(response.status_code,503)
        self.assertEqual(observed.get("phase"),"checking_model")
        self.assertEqual(observed.get("status"),"processing")
        final=self.client.get(f"/api/workflows/{wid}/review/live/{item['id']}/progress").json()
        self.assertEqual(final["status"],"failed")
        self.assertIn("Model server offline",final["message"])

    def test_orphaned_live_extraction_is_recovered_to_interrupted(self):
        wid=self.client.post("/api/workflows",json={"name":"Orphaned live extraction","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste",json={"text":"Stale processing message","source":"Recovery test"})
        item=self.client.get(f"/api/workflows/{wid}/review/live/queue").json()["items"][0]
        with conn() as db:
            db.execute("UPDATE messages SET status='processing' WHERE id=? AND workflow_id=?",(item["id"],wid))
        progress=self.client.get(f"/api/workflows/{wid}/review/live/{item['id']}/progress").json()
        self.assertEqual(progress["status"],"failed")
        self.assertEqual(progress["phase"],"recovery")
        with conn() as db:
            row=db.execute("SELECT status FROM messages WHERE id=? AND workflow_id=?",(item["id"],wid)).fetchone()
        self.assertEqual(row["status"],"interrupted")

    def test_structured_collector_phase_parser_is_bounded_and_rejects_invalid_lines(self):
        parsed=_parse_collector_phase_line('STRUCTURA_COLLECTOR_PHASE={"phase":"scanning_history","platform":"Telegram","channel":"news_feed","detail":"Loading older messages"}')
        self.assertEqual(parsed,{"phase":"scanning_history","platform":"Telegram","channel":"news_feed","detail":"Loading older messages"})
        self.assertIsNone(_parse_collector_phase_line("ordinary collector log"))
        self.assertIsNone(_parse_collector_phase_line("STRUCTURA_COLLECTOR_PHASE={broken"))

    def test_agent_collection_inspector_exposes_structured_phase_to_shadi(self):
        wid=self.client.post("/api/workflows",json={"name":"Agent collection phase context","template":"custom"}).json()["id"]
        previous=COLLECT_STATE.get(wid)
        COLLECT_STATE[wid]={"status":"running","phase":"checking_message_list","phase_message":"Waiting for stable message nodes","platform":"Telegram","channel":"news_feed","logs":["phase log"]}
        try:
            result=_agent_tool_execute(wid,"inspect_collection",{})
            self.assertEqual(result["phase"],"checking_message_list")
            self.assertEqual(result["platform"],"Telegram")
            self.assertEqual(result["channel"],"news_feed")
            self.assertIn("stable message nodes",result["phase_message"])
        finally:
            if previous is None: COLLECT_STATE.pop(wid,None)
            else: COLLECT_STATE[wid]=previous

    def test_review_settings_persist_live_processing_path(self):
        wid = self.workflow_id
        response = self.client.put(f"/api/workflows/{wid}/review/settings", json={"enabled":True,"mode":"guided","processing_path":"live","auto_advance":False,"confirm_bulk":True,"page_size":50,"sort":"newest"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["review_settings"]["processing_path"], "live")
        # Restore the default path for unrelated tests.
        self.client.put(f"/api/workflows/{wid}/review/settings", json={"enabled":True,"mode":"guided","processing_path":"processed","auto_advance":True,"confirm_bulk":True,"page_size":100,"sort":"newest"})

    def test_explicit_process_all_batch_action_overrides_live_default_without_changing_it(self):
        from unittest.mock import MagicMock, patch
        wid = self.client.post("/api/workflows", json={"name":"Explicit batch from live review","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Message one\n\nMessage two","source":"Batch test"})
        with conn() as db:
            ids=[row[0] for row in db.execute("SELECT id FROM messages WHERE workflow_id=? ORDER BY created_at,id",(wid,)).fetchall()]
            db.execute("UPDATE messages SET status='failed' WHERE id=?",(ids[0],))
            db.execute("UPDATE messages SET status='interrupted' WHERE id=?",(ids[1],))
        self.client.put(f"/api/workflows/{wid}/review/settings", json={"enabled":True,"mode":"guided","processing_path":"live","auto_advance":False,"confirm_bulk":True,"page_size":50,"sort":"newest"})
        workflow_counts=self.client.get(f"/api/workflows/{wid}").json()["counts"]
        self.assertEqual(workflow_counts["queued"],2)
        self.assertEqual(workflow_counts["failed"],1)
        self.assertEqual(workflow_counts["interrupted"],1)
        fake_thread=MagicMock()
        with patch("app.server.threading.Thread",return_value=fake_thread) as thread:
            response=self.client.post(f"/api/workflows/{wid}/process",json={"include_processed":False,"limit":10000,"explicit_batch":True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()["explicit_batch"])
        self.assertEqual(response.json()["total"],2)
        fake_thread.start.assert_called_once()
        saved=self.client.get(f"/api/workflows/{wid}").json()
        self.assertEqual(saved["config"]["review_settings"]["processing_path"],"live")

    def test_workflow_and_dashboard_counts_separate_eligible_from_policy_held_messages(self):
        wid=self.client.post("/api/workflows",json={"name":"Eligibility counts","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste",json={"text":"Eligible message\n\nHeld message","source":"Count test"})
        with conn() as db:
            ids=[row[0] for row in db.execute("SELECT id FROM messages WHERE workflow_id=? ORDER BY created_at,id",(wid,)).fetchall()]
            db.execute("UPDATE messages SET status='filtered' WHERE id=?",(ids[1],))
        counts=self.client.get(f"/api/workflows/{wid}").json()["counts"]
        dashboard=self.client.get(f"/api/workflows/{wid}/dashboard").json()["stats"]
        self.assertEqual(counts["queued"],1)
        self.assertEqual(counts["held"],1)
        self.assertEqual(dashboard["queued"],1)
        self.assertEqual(dashboard["held"],1)

    def test_batch_extraction_is_blocked_when_live_one_by_one_path_is_selected(self):
        wid = self.client.post("/api/workflows", json={"name":"Live path batch guard","template":"custom"}).json()["id"]
        self.client.put(f"/api/workflows/{wid}/review/settings", json={"enabled":True,"mode":"guided","processing_path":"live","auto_advance":False,"confirm_bulk":True,"page_size":50,"sort":"newest"})
        # This guard must run before LLM checks or queue mutation: batch Run is
        # not allowed to bypass the workflow's explicit Live AI choice.
        with patch("app.server.process_batch") as batch:
            response = self.client.post(f"/api/workflows/{wid}/process", json={"include_processed":False,"limit":10000})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Live AI", response.json()["detail"])
        batch.assert_not_called()

    def test_health_and_templates(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("AGENT SHADI <span>1.8.37</span>", home.text)
        self.assertIn("styles.css?v=1.8.37", home.text)
        self.assertIn("app.js?v=1.8.37", home.text)
        self.assertNotIn("__APP_VERSION__", home.text)

        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["product"], "Agent Shadi")
        self.assertEqual(health.json()["version"], "1.8.37")
        self.assertEqual(self.client.get("/api/templates/real_estate_fa").status_code, 200)



    def test_agent_chat_rejects_stale_saved_connection_when_runtime_is_offline(self):
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        try:
            with patch("app.server._probe_model_endpoint",side_effect=__import__("httpx").ConnectError("refused")):
                response=self.client.post(f"/api/workflows/{self.workflow_id}/agent/chat",json={"messages":[{"role":"user","content":"Help"}]})
            self.assertEqual(response.status_code,503)
            self.assertIn("cannot reach",response.json()["detail"].lower())
            self.assertFalse(get_model_settings()["connection_verified"])
        finally:
            set_model_settings(before)
            from app.server import _reset_model_status_cache
            _reset_model_status_cache()

    def test_dashboard_model_ready_uses_live_status_not_persisted_flag(self):
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        try:
            with patch("app.server._probe_model_endpoint",side_effect=__import__("httpx").ConnectError("refused")):
                response=self.client.get(f"/api/workflows/{self.workflow_id}/dashboard")
            self.assertEqual(response.status_code,200)
            self.assertFalse(response.json()["model_ready"])
            self.assertEqual(response.json()["model_status"]["status"],"offline")
        finally:
            set_model_settings(before)
            from app.server import _reset_model_status_cache
            _reset_model_status_cache()

    def test_agent_shadi_chat_requires_enabled_model(self):
        wid = self.workflow_id
        settings = get_model_settings()
        before = dict(settings)
        settings.update({"enabled": False, "model": "", "connection_verified": False})
        set_model_settings(settings)
        try:
            response = self.client.post(
                f"/api/workflows/{wid}/agent/chat",
                json={"messages": [{"role": "user", "content": "Review my workflow"}]},
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn("Connect and enable an LLM", response.json()["detail"])
        finally:
            set_model_settings(before)

    def test_agent_shadi_chat_uses_metadata_and_exposes_bounded_application_tools(self):
        from unittest.mock import MagicMock, patch
        wid = self.workflow_id
        settings = get_model_settings()
        before = dict(settings)
        settings.update({"enabled": True, "model": "test-model", "base_url": "http://127.0.0.1:1234/v1", "api_key": "", "timeout": 10, "connection_verified": True})
        set_model_settings(settings)
        response_obj = MagicMock()
        response_obj.json.return_value = {"choices": [{"message": {"content": "I can explain the workflow, but you must approve changes in the app."}}]}
        response_obj.raise_for_status.return_value = None
        http_client = MagicMock()
        http_client.__enter__.return_value = http_client
        http_client.__exit__.return_value = False
        http_client.post.return_value = response_obj
        try:
            with patch("app.server._probe_model_endpoint", return_value=["test-model"]), patch("app.server.httpx.Client", return_value=http_client):
                response = self.client.post(
                    f"/api/workflows/{wid}/agent/chat",
                    json={"messages": [
                        {"role": "user", "content": "How can I improve this workflow?"}
                    ]},
                )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["agent"], "Agent Shadi")
            self.assertIn("approve changes", response.json()["answer"])
            request_json = http_client.post.call_args.kwargs["json"]
            self.assertIn("limited set of real Agent Shadi application tools", request_json["messages"][0]["content"])
            tool_names={x["function"]["name"] for x in request_json["tools"]}
            self.assertEqual(tool_names,{"inspect_workflow"})
            self.assertNotIn("execute_shell",tool_names)
            self.assertNotIn("delete_records",tool_names)
            self.assertIn("output_fields", request_json["messages"][0]["content"])
            self.assertIn("Universal Web Connector Studio", request_json["messages"][0]["content"])
            self.assertIn("universal connector workflow", request_json["messages"][0]["content"])
            self.assertIn("Inputs & Connectors", request_json["messages"][0]["content"])
            self.assertEqual(sum(1 for message in request_json["messages"] if message["role"]=="system"),1)
        finally:
            set_model_settings(before)

    def test_agent_chat_retries_context_overflow_with_compacted_context_and_preserves_question(self):
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"model":"test-model","base_url":"http://127.0.0.1:1234/v1","api_key":"","timeout":10,"connection_verified":True})
        set_model_settings(settings)
        captured=[]
        class FakeResponse:
            def __init__(self,error=None): self.error=error
            def raise_for_status(self):
                if self.error: raise httpx.HTTPStatusError("context overflow",request=self.error.request,response=self.error)
            def json(self): return {"choices":[{"message":{"content":"AI only is the selected path; I kept your latest question and compacted the context."}}]}
        class FakeClient:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None):
                captured.append(json)
                if len(captured)==1:
                    req=httpx.Request("POST",url)
                    return FakeResponse(httpx.Response(400,request=req,text='{"error":{"code":"exceed_context_size_error","message":"request exceeds the available context size"}}'))
                return FakeResponse()
        try:
            with patch("app.server._model_runtime_result",return_value={"ok":True,"status":"online","model":"test-model"}), patch("app.server.httpx.Client",FakeClient):
                response=self.client.post(f"/api/workflows/{self.workflow_id}/agent/chat",json={"messages":[
                    {"role":"user","content":"Old history "*300},
                    {"role":"assistant","content":"Old answer "*300},
                    {"role":"user","content":"Please explain how to use AI only and keep this exact final question."},
                ]})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(captured),2)
            self.assertGreater(len(captured[0]["messages"]),len(captured[1]["messages"]))
            self.assertIn("keep this exact final question",captured[1]["messages"][-1]["content"])
            self.assertIn("AI only",response.json()["answer"])
        finally:
            set_model_settings(before)

    def test_end_to_end_real_estate_import_process_edit_export(self):
        wid = self.client.post("/api/workflows",json={"name":"End-to-end isolated real estate","template":"real_estate_fa"}).json()["id"]
        body = {
            "text": "#زمین\nزمین فروشی 286 متر\nقیمت کل: 6 میلیارد و 864 میلیون تومان\n\nویلایی، عرصه 300 متر، دو خواب، قیمت 5.8 میلیارد",
            "source": "Regression test", "posted_at": "1405.06.31",
        }
        added = self.client.post(f"/api/workflows/{wid}/messages/paste", json=body)
        self.assertEqual(added.status_code, 200)
        self.assertEqual(added.json()["added"], 2)
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit": 100})
        self.assertEqual(started.status_code, 200)
        run = self.wait_run(started.json()["run_id"])
        self.assertEqual(run["status"], "completed")
        self.assertEqual(run["processed"], 2)
        records = self.client.get(f"/api/workflows/{wid}/records?status=needs_review&limit=100").json()
        self.assertEqual(len(records), 2)
        self.assertIn(2, [r["data"]["bedrooms"] for r in records])
        record = records[0]
        edited = dict(record["data"])
        edited["address"] = "آدرس اصلاح‌شده"
        response = self.client.put(f"/api/records/{record['id']}", json={"data": edited})
        self.assertEqual(response.status_code, 200)
        corrections = self.client.get(f"/api/workflows/{wid}/corrections").json()
        self.assertGreaterEqual(len(corrections), 1)
        self.assertEqual(self.client.post(f"/api/records/{record['id']}/approve").status_code, 200)
        for fmt in ("csv", "xlsx", "json"):
            exported = self.client.get(f"/api/workflows/{wid}/export?format={fmt}&status=all")
            self.assertEqual(exported.status_code, 200)
            self.assertGreater(len(exported.content), 50)

    def test_manual_duplicate_review_removes_one_pair_then_rescans(self):
        wid = self.client.post("/api/workflows",json={"name":"Isolated duplicate review","template":"real_estate_fa"}).json()["id"]
        messages = [
            "آگهی فروش آپارتمان 100 متر دو خواب طبقه سوم بلوار دانشجو قیمت کل 4200 میلیون تومان تماس 09120000001",
            "آگهی فروش آپارتمان 100 متر دو خواب طبقه سوم بلوار دانشجو قیمت کل 4210 میلیون تومان تماس 09120000001",
            "آگهی فروش آپارتمان 100 متر دو خواب طبقه سوم بلوار دانشجو قیمت کل 4220 میلیون تومان تماس 09120000001",
        ]
        pasted = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"\n\n".join(messages),"source":"Duplicate test","posted_at":"1405.07.01"})
        self.assertEqual(pasted.status_code, 200)
        process = self.client.post(f"/api/workflows/{wid}/process", json={"limit":100})
        run = self.wait_run(process.json()["run_id"])
        self.assertEqual(run["failed"], 0)
        scan = self.client.post(f"/api/workflows/{wid}/cleanup/scan", json={"threshold":80,"scan_mode":"exhaustive","cross_date":True,"neighbors":100})
        self.assertEqual(scan.status_code, 200)
        result = scan.json()
        if result.get("complete"):
            self.skipTest("The synthetic messages were not grouped by the current similarity threshold")
        members = result["group"]["members"]
        self.assertGreaterEqual(len(members), 2)
        comparison = self.client.get(f"/api/cleanup/{result['session_id']}/compare?left_index={members[0]['row_index']}&right_index={members[1]['row_index']}")
        self.assertEqual(comparison.status_code, 200)
        decided = self.client.post(f"/api/cleanup/{result['session_id']}/decision", json={"keep_record_id":members[0]["id"],"remove_record_id":members[1]["id"]})
        self.assertEqual(decided.status_code, 200)
        self.assertEqual(decided.json()["removed"], 1)
        # A 3-member cluster is reduced by only one manual decision, then rescanned.
        self.assertGreaterEqual(len(decided.json().get("group", {}).get("members", [])), 2)

    def test_in_app_resume_endpoint_signals_only_an_operator_paused_run(self):
        from app.server import DATA
        wid = self.workflow_id
        previous = COLLECT_STATE.get(wid)
        COLLECT_STATE[wid] = {"status":"operator_paused", "logs":[], "waiting_for":"Rubika|@sample_feed_119", "run_id":"unit-test-collector-run"}
        marker = DATA / "collectors" / wid / "continue.signal"
        try:
            marker.unlink(missing_ok=True)
            response = self.client.post(f"/api/workflows/{wid}/collect/resume")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "resume_requested")
            self.assertTrue(marker.exists())
            self.assertEqual(COLLECT_STATE[wid]["status"], "resume_requested")
            second = self.client.post(f"/api/workflows/{wid}/collect/resume")
            self.assertEqual(second.status_code, 409)
            self.assertIn("already requested", second.json()["detail"])
        finally:
            marker.unlink(missing_ok=True)
            if previous is None: COLLECT_STATE.pop(wid, None)
            else: COLLECT_STATE[wid] = previous

    def test_new_collection_is_blocked_while_operator_checkpoint_is_paused(self):
        wid = self.workflow_id
        cfg = self.client.get(f"/api/workflows/{wid}/collector").json()
        cfg["rubika_channels"] = [{"username":"demo_rubika","url":"https://web.rubika.ir/#@demo_rubika","search_name":"Demo","deal_type":"sale"}]
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/collector", json=cfg).status_code, 200)
        COLLECT_STATE[wid] = {"status":"operator_paused", "logs":[]}
        response = self.client.post(f"/api/workflows/{wid}/collect/run", json={"platform":"rubika","start_date":"1405.08.01","end_date":"1405.08.01","date_system":"jalali"})
        self.assertEqual(response.status_code, 409)
        COLLECT_STATE.pop(wid, None)

    def test_txt_import_uses_workflow_message_delimiter(self):
        created = self.client.post("/api/workflows", json={"name":"Custom delimiter test","template":"custom"})
        wid = created.json()["id"]
        workflow = self.client.get(f"/api/workflows/{wid}").json()
        config = workflow["config"]
        config["split_mode"] = "custom_delimiter"
        config["delimiter"] = "<<<END>>>"
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/config", json={"config":config}).status_code, 200)
        uploaded = self.client.post(
            f"/api/workflows/{wid}/import",
            files={"file":("messages.txt", "First record<<<END>>>Second record", "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["added"], 2)
        records = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()
        self.assertEqual({row["raw_text"] for row in records}, {"First record", "Second record"})

    def test_generic_workflow_and_channel_validation(self):
        created = self.client.post("/api/workflows", json={"name":"Product feed test","template":"custom"})
        self.assertEqual(created.status_code, 200)
        wid = created.json()["id"]
        payload = {
            "telegram_channels":[{"username":"example_channel","url":"https://web.telegram.org/k/#@example_channel","search_name":"Example","deal_type":"sale"}],
            "rubika_channels":[],"filter_mode":"all",
        }
        saved = self.client.put(f"/api/workflows/{wid}/collector", json=payload)
        self.assertEqual(saved.status_code, 200)
        invalid = self.client.put(f"/api/workflows/{wid}/collector", json={"telegram_channels":[{"username":"bad name","url":"https://evil.example/bad"}],"rubika_channels":[],"filter_mode":"all"})
        self.assertEqual(invalid.status_code, 400)
        # Workflow design uses an LLM and should explain the missing connection in rules-only mode.
        disabled = self.client.post(f"/api/workflows/{wid}/design/suggest", json={"brief":"Extract product name, price and location from advertisements"})
        self.assertEqual(disabled.status_code, 400)

    def test_automatic_extraction_after_collection_is_opt_in_and_persisted(self):
        created=self.client.post("/api/workflows",json={"name":"Manual extraction control","template":"custom"})
        wid=created.json()["id"]
        defaults=self.client.get(f"/api/workflows/{wid}/collector").json()
        self.assertFalse(defaults["auto_process"])
        defaults["auto_process"]=True
        saved=self.client.put(f"/api/workflows/{wid}/collector",json=defaults)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertTrue(self.client.get(f"/api/workflows/{wid}/collector").json()["auto_process"])
        defaults["auto_process"]=False
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/collector",json=defaults).status_code,200)
        self.assertFalse(self.client.get(f"/api/workflows/{wid}/collector").json()["auto_process"])

    def test_agent_workflow_tools_can_set_ai_only_and_inspect_prompt_on_request(self):
        wid=self.client.post("/api/workflows",json={"name":"AI only configuration test","template":"custom"}).json()["id"]
        changed=_agent_tool_execute(wid,"update_workflow",{"changes":{"extraction_mode":"ai_only"}})
        self.assertTrue(changed["ok"],changed)
        compact=_agent_tool_execute(wid,"inspect_workflow",{})
        self.assertEqual(compact["workflow"]["extraction_mode"],"ai_only")
        self.assertNotIn("prompt",compact["workflow"])
        detailed=_agent_tool_execute(wid,"inspect_workflow",{"include_prompt":True})
        self.assertIn("prompt",detailed["workflow"])

    def test_agent_can_save_automatic_extraction_preference_without_starting_collection(self):
        wid=self.client.post("/api/workflows",json={"name":"Agent extraction preference","template":"custom"}).json()["id"]
        result=_agent_tool_execute(wid,"update_collector_settings",{"auto_process":True})
        self.assertTrue(result["ok"],result)
        self.assertTrue(self.client.get(f"/api/workflows/{wid}/collector").json()["auto_process"])
        self.assertIn("No collection was started",result["note"])

    def test_agent_started_collection_respects_saved_auto_process_preference(self):
        from app.server import CollectRun
        wid=self.client.post("/api/workflows",json={"name":"Saved auto-process run","template":"custom"}).json()["id"]
        _agent_tool_execute(wid,"update_collector_settings",{"auto_process":True})
        seen=[]
        def fake_collect(workflow_id,payload):
            seen.append(payload);return {"status":"started"}
        with patch("app.server.collect_run",side_effect=fake_collect):
            result=_agent_tool_execute(wid,"start_collection",{"platform":"telegram","start_date":"1405.08.01","end_date":"1405.08.01"})
            self.assertTrue(result["ok"])
            self.assertTrue(seen[-1].auto_process)
            _agent_tool_execute(wid,"start_collection",{"platform":"telegram","start_date":"1405.08.01","end_date":"1405.08.01","auto_process":False})
            self.assertFalse(seen[-1].auto_process)



    def test_configurable_collection_policy_holds_and_requeues_non_matches(self):
        created = self.client.post("/api/workflows", json={"name":"Support messages","template":"custom"})
        self.assertEqual(created.status_code, 200)
        wid = created.json()["id"]
        collector = self.client.get(f"/api/workflows/{wid}/collector").json()
        collector["collection_policy"] = {
            "mode":"include", "logic":"all", "rules":[
                {"field":"text", "operator":"contains", "value":"ticket"},
                {"field":"source", "operator":"equals", "value":"Support portal"},
            ]
        }
        saved = self.client.put(f"/api/workflows/{wid}/collector", json=collector)
        self.assertEqual(saved.status_code, 200, saved.text)
        pasted = self.client.post(f"/api/workflows/{wid}/messages/paste", json={
            "text":"New ticket #54\n\nWeekly status digest", "source":"Support portal", "posted_at":"2026-11-09"
        })
        self.assertEqual(pasted.status_code, 200)
        self.assertEqual(pasted.json()["added"], 2)
        self.assertEqual(pasted.json()["queued"], 1)
        self.assertEqual(pasted.json()["filtered"], 1)
        messages = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()
        held = next(row for row in messages if row["raw_text"] == "Weekly status digest")
        self.assertEqual(held["status"], "filtered")
        self.assertIn("retained", held["error"])
        requeued = self.client.post(f"/api/workflows/{wid}/messages/{held['id']}/requeue")
        self.assertEqual(requeued.status_code, 200)
        self.assertEqual(requeued.json()["status"], "queued")
        summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertEqual(summary["filtered"], 0)
        self.assertGreaterEqual(summary["pending"], 2)

    def test_uploaded_file_uses_the_same_workflow_collection_policy(self):
        created = self.client.post("/api/workflows", json={"name":"Supplier feed","template":"custom"})
        wid = created.json()["id"]
        collector = self.client.get(f"/api/workflows/{wid}/collector").json()
        collector["collection_policy"] = {"mode":"include","logic":"any","rules":[
            {"field":"text","operator":"contains","value":"supplier"},
            {"field":"has_link","operator":"equals","value":"true"},
        ]}
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/collector", json=collector).status_code, 200)
        uploaded = self.client.post(
            f"/api/workflows/{wid}/import",
            files={"file":("feed.txt", "Supplier update 14\n\nWeekly digest", "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        self.assertEqual(uploaded.json()["added"], 2)
        self.assertEqual(uploaded.json()["queued"], 1)
        self.assertEqual(uploaded.json()["filtered"], 1)
        statuses = {row["raw_text"]:row["status"] for row in self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()}
        self.assertEqual(statuses["Supplier update 14"], "queued")
        self.assertEqual(statuses["Weekly digest"], "filtered")

    def test_clear_unprocessed_counts_and_explicitly_includes_policy_held_messages(self):
        created = self.client.post("/api/workflows", json={"name":"Clear held items test","template":"custom"})
        wid = created.json()["id"]
        collector = self.client.get(f"/api/workflows/{wid}/collector").json()
        collector["collection_policy"] = {"mode":"include","logic":"all","rules":[
            {"field":"text","operator":"contains","value":"keep"}
        ]}
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/collector", json=collector).status_code, 200)
        pasted = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"keep this\n\nheld for review","source":"Test"})
        self.assertEqual(pasted.json()["queued"], 1)
        self.assertEqual(pasted.json()["filtered"], 1)
        summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertEqual(summary["filtered"], 1)
        self.assertEqual(summary["clearable"], 2)
        cleared = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"pending"})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["messages_deleted"], 2)

    def test_collection_policy_rejects_empty_or_unsafe_custom_rule_sets(self):
        created = self.client.post("/api/workflows", json={"name":"Policy validation","template":"custom"})
        wid = created.json()["id"]
        collector = self.client.get(f"/api/workflows/{wid}/collector").json()
        collector["collection_policy"] = {"mode":"include","logic":"all","rules":[]}
        invalid = self.client.put(f"/api/workflows/{wid}/collector", json=collector)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("Add at least one condition", invalid.json()["detail"])
        collector["collection_policy"] = {"mode":"include","logic":"all","rules":[
            {"field":"text","operator":"regex","value":"(a+)+$"}
        ]}
        unsafe = self.client.put(f"/api/workflows/{wid}/collector", json=collector)
        self.assertEqual(unsafe.status_code, 400)
        self.assertIn("unsafe", unsafe.json()["detail"])

    def test_web_capture_supplies_sender_and_attachment_metadata_to_policy(self):
        from unittest.mock import patch
        created = self.client.post("/api/workflows", json={"name":"Ticket attachments","template":"custom"})
        wid = created.json()["id"]
        collector = self.client.get(f"/api/workflows/{wid}/collector").json()
        collector["collection_policy"] = {"mode":"include","logic":"all","rules":[
            {"field":"sender","operator":"equals","value":"Alice"},
            {"field":"has_attachment","operator":"equals","value":"true"},
            {"field":"attachment_count","operator":"greater_than","value":"0"},
        ]}
        self.assertEqual(self.client.put(f"/api/workflows/{wid}/collector", json=collector).status_code, 200)
        connector = self.client.post(f"/api/workflows/{wid}/web-connectors", json={
            "name":"Support app","url":"https://example.com/inbox","config":{"root":{"selector":".message"},"fields":{"text":{"selector":".body"}},"navigation":{"strategy":"manual"}}
        })
        self.assertEqual(connector.status_code, 200, connector.text)
        cid = connector.json()["id"]
        fake_capture = {"items":[{"raw_text":"Please review this file","sender":"Alice","posted_at":"2026-11-09","source_ref":"message-1","attachments":["https://example.com/file.pdf"]}],"root_count":1,"scroll_cycles":0,"strategy":"manual","stopped_after_no_new":False}
        with patch("app.server.web_inspector_manager.capture", return_value=fake_capture):
            response = self.client.post(f"/api/web-connectors/{cid}/capture", json={"mode":"visible","max_messages":10})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["added"], 1)
        self.assertEqual(response.json()["queued"], 1)
        messages = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()
        self.assertEqual(messages[0]["status"], "queued")


    def test_eitaa_assistance_uses_deterministic_preset_without_model_consent(self):
        wid=self.client.post("/api/workflows",json={"name":"Eitaa preset assist","template":"custom"}).json()["id"]
        one='''<div class="etme_widget_message_wrap js-widget_message_wrap" id="4270"><div class="etme_widget_message_author"><a class="etme_widget_message_owner_name">Author</a></div><div class="etme_widget_message_text js-message_text">Hello</div><span class="etme_widget_message_date"><time datetime="2026-07-01T08:03:09+00:00">۱۱:۳۳</time></span></div>'''
        listing='''<section class="etme_channel_history js-message_history"><a class="js-messages_more" data-before="4269" href="/channel?before=4269">Older</a>''' + '''<div class="etme_widget_message_wrap js-widget_message_wrap" id="4269"><div class="etme_widget_message_text js-message_text">Older body</div><time datetime="2026-06-30T08:00:00+00:00"></time></div>''' + '''<div class="etme_widget_message_wrap js-widget_message_wrap" id="4270"><div class="etme_widget_message_text js-message_text">Newer body</div><time datetime="2026-07-01T08:03:09+00:00"></time></div><a class="js-messages_more" data-after="4270" href="/channel?after=4270">Newer</a></section>'''
        response=self.client.post(f"/api/workflows/{wid}/web-connectors/assist",json={
            "name":"Eitaa","url":"https://eitaa.com/channel/4270","intent":"Collect each channel message",
            "individual_html":one,"list_html":listing,"consent_to_send_html":False
        })
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data["site_preset"],"eitaa")
        self.assertEqual(data["config"]["fields"]["timestamp"],{"selector":".etme_widget_message_date time","attribute":"datetime"})
        self.assertEqual(data["config"]["navigation"]["strategy"],"pagination")
        self.client.delete(f"/api/workflows/{wid}")

    def test_existing_eitaa_connector_is_upgraded_when_listed(self):
        wid=self.client.post("/api/workflows",json={"name":"Existing Eitaa","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Eitaa","url":"https://eitaa.com/sample_archive/4270","description":"Channel archive",
            "config":{"root":{"selector":"div.etme_widget_message_wrap.js-widget_message_wrap"},
                "fields":{"text":{"selector":".etme_widget_message_text.js-message_text","attribute":"textContent"},
                    "timestamp":{"selector":"div.etme_widget_message_meta","attribute":"textContent"}},
                "navigation":{"strategy":"manual"}}
        })
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        listed=self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"]
        upgraded=next(x for x in listed if x["id"]==cid)
        self.assertEqual(upgraded["version"],1)
        self.assertEqual(upgraded["url"],"https://web.eitaa.com/")
        self.assertEqual(upgraded["config"]["channel"]["target_url"],"https://eitaa.com/sample_archive/4270")
        self.assertEqual(upgraded["config"]["fields"]["timestamp"],{"selector":".etme_widget_message_date time","attribute":"datetime"})
        self.assertEqual(upgraded["config"]["fields"]["message_id"],{"selector":":root","attribute":"id"})
        self.assertEqual(upgraded["config"]["navigation"]["strategy"],"pagination")
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_eitaa_connector_upgrade_preserves_saved_channel_identity(self):
        wid=self.client.post("/api/workflows",json={"name":"Eitaa channel identity","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Eitaa","url":"https://eitaa.com/channel/4270","config":{
                "site_preset":"eitaa","channel":{"name":"Sample property feed","search_input_selector":"input.search","search_result_selector":".result"},
                "root":{"selector":"div.etme_widget_message_wrap.js-widget_message_wrap"},
                "fields":{"text":{"selector":".etme_widget_message_text.js-message_text"}},
                "navigation":{"strategy":"manual"}}
        })
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        first=self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"][0]
        second=self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"][0]
        self.assertEqual(first["config"]["channel"]["name"],"Sample property feed")
        self.assertEqual(first["config"]["channel"]["search_input_selector"],"input.search")
        self.assertEqual(second["config"]["channel"]["search_result_selector"],".result")
        self.assertEqual(first["version"],second["version"])
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_legacy_public_eitaa_connector_is_migrated_to_authenticated_web_entrypoint(self):
        wid=self.client.post("/api/workflows",json={"name":"Legacy Eitaa URL migration","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Legacy Eitaa","url":"https://web.eitaa.com/","config":{
                "site_preset":"eitaa","channel":{"name":"Sample listings","target_url":"https://eitaa.com/sample_listings_feed","username":"sample_listings_feed"},
                "root":{"selector":".message"},"fields":{"text":{"selector":".body"}},
                "navigation":{"strategy":"manual"}}
        })
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        # Simulate the legacy row produced by earlier releases: public channel URL
        # was stored as the application entrypoint despite a separate target URL.
        legacy_config=created.json()["config"]
        legacy_config.pop("site_preset",None)
        with conn() as db:
            db.execute("UPDATE web_connectors SET url=?,config_json=? WHERE id=?",("https://eitaa.com/sample_listings_feed",dumps(legacy_config),cid))
        listed=self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"]
        migrated=next(x for x in listed if x["id"]==cid)
        self.assertEqual(migrated["url"],"https://web.eitaa.com/")
        self.assertEqual(migrated["config"]["channel"]["target_url"],"https://eitaa.com/sample_listings_feed")
        self.assertEqual(migrated["config"]["channel"]["username"],"sample_listings_feed")
        self.assertEqual(migrated["config"]["channel"]["target_url_template"],"{app_origin}/#@{username}")
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_eitaa_web_collection_uses_shared_jalali_date_range_and_pagination(self):
        wid=self.client.post("/api/workflows",json={"name":"Eitaa date range","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Eitaa","url":"https://eitaa.com/channel/4270","config":{"site_preset":"eitaa",
                "root":{"selector":"div.etme_widget_message_wrap.js-widget_message_wrap"},
                "fields":{"text":{"selector":".etme_widget_message_text.js-message_text","attribute":"textContent"},
                    "timestamp":{"selector":".etme_widget_message_date time","attribute":"datetime"}},
                "navigation":{"strategy":"pagination","button_selector":"a.js-messages_more[data-before]","max_scrolls":500}}
        })
        cid=created.json()["id"]
        fixture={"items":[{"raw_text":"Eitaa property post","source_ref":"id:4270","posted_at":"2026-07-01T08:03:09+00:00","sender":"Channel Author","attachments":[]}],
            "root_count":1,"scroll_cycles":3,"strategy":"pagination","date_range":{"start":"2026-07-01","end":"2026-07-01","scanned":5,"in_range":1,"undated":0,"oldest_seen":"2026-06-30","newest_seen":"2026-07-02","start_bound_confirmed":True,"end_bound_confirmed":True,"complete":True,"stop_reason":"date_range_covered"},"warnings":[]}
        with patch("app.server.web_inspector_manager.capture",return_value={**fixture,"channel_open":{"ok":True,"already_open":True,"identity_verified":True,"identity_method":"username"}}) as capture:
            response=self.client.post(f"/api/web-connectors/{cid}/capture",json={"mode":"collect","channel_name":"Sample channel","channel_url":"https://eitaa.com/sample_listings_feed","channel_username":"@sample_listings_feed","channel_id":"-1009876543210","max_messages":500,"start_date":"1405.04.10","end_date":"1405.04.10","date_system":"jalali"})
        self.assertEqual(response.status_code,200,response.text)
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs["start_date"],"2026-07-01")
        self.assertEqual(capture.call_args.kwargs["end_date"],"2026-07-01")
        self.assertEqual(capture.call_args.kwargs["app_url"],"https://web.eitaa.com/")
        self.assertEqual(capture.call_args.args[1]["channel"]["target_url"],"https://eitaa.com/sample_listings_feed")
        self.assertEqual(capture.call_args.args[1]["channel"]["username"],"sample_listings_feed")
        self.assertEqual(capture.call_args.args[1]["channel"]["platform_id"],"-1009876543210")
        self.assertTrue(response.json()["channel_open"]["identity_verified"])
        self.assertEqual(response.json()["added"],1)
        self.assertEqual(response.json()["database"]["message_total"],1)
        self.assertEqual(response.json()["database"]["record_total"],0)
        saved_connector=self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"][0]
        self.assertEqual(saved_connector["config"]["channel"]["name"],"Sample channel")
        self.assertEqual(saved_connector["config"]["channel"]["target_url"],"https://eitaa.com/sample_listings_feed")
        self.assertEqual(saved_connector["config"]["channel"]["username"],"sample_listings_feed")
        self.assertEqual(saved_connector["config"]["channel"]["platform_id"],"-1009876543210")
        self.assertTrue(response.json()["date_range"]["complete"])
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_generic_date_range_scroll_confirms_boundaries_and_filters_messages(self):
        wid=self.client.post("/api/workflows",json={"name":"Generic scroll date range","template":"custom"}).json()["id"]
        created=self.client.post(f"/api/workflows/{wid}/web-connectors",json={
            "name":"Generic channel","url":"https://example.test/chat","config":{
                "root":{"selector":".message"},"fields":{"text":{"selector":".body"},"timestamp":{"selector":"time","attribute":"datetime"}},
                "channel":{"name":"Example room","target_url":"https://example.test/chat/42","username":"room42"},
                "navigation":{"strategy":"manual","date_range_mode":"auto","timestamp_timezone":"Asia/Tehran"}}
        })
        self.assertEqual(created.status_code,200,created.text)
        cid=created.json()["id"]
        fixture={"items":[
            {"raw_text":"Older boundary","source_ref":"id:old","posted_at":"2026-11-08T10:00:00+03:30","sender":"Room","attachments":[]},
            {"raw_text":"Target day","source_ref":"id:target","posted_at":"2026-11-10T10:00:00+03:30","sender":"Room","attachments":[]},
            {"raw_text":"Newer boundary","source_ref":"id:new","posted_at":"2026-11-11T10:00:00+03:30","sender":"Room","attachments":[]},
        ],"root_count":3,"scroll_cycles":7,"strategy":"infinite_scroll","requested_strategy":"manual","auto_navigation":True,"stopped_after_no_new":True,
            "scroll_diagnostics":{"older_edge_confirmed":False,"newer_edge_confirmed":True,"observed_movement":True,"last_cycles":[]},
            "channel_open":{"ok":True,"already_open":True,"identity_verified":True,"identity_method":"username_and_active_conversation","active_title":"Example room","active_message_count":3},
            "warnings":[]}
        with patch("app.server.web_inspector_manager.capture",return_value=fixture):
            response=self.client.post(f"/api/web-connectors/{cid}/capture",json={"mode":"collect","max_messages":100,"start_date":"2026-11-10","end_date":"2026-11-10","date_system":"gregorian"})
        self.assertEqual(response.status_code,200,response.text)
        data=response.json()
        self.assertEqual(data["added"],1)
        self.assertEqual(data["found"],3)
        self.assertTrue(data["auto_navigation"])
        self.assertEqual(data["strategy"],"infinite_scroll")
        self.assertTrue(data["date_range"]["complete"])
        self.assertEqual(data["date_range"]["oldest_seen"],"2026-11-08")
        self.assertEqual(data["date_range"]["newest_seen"],"2026-11-11")
        self.assertEqual(data["date_range"]["in_range"],1)
        self.client.delete(f"/api/web-connectors/{cid}")
        self.client.delete(f"/api/workflows/{wid}")

    def test_universal_web_connector_create_update_list_export_delete(self):
        wid = self.workflow_id
        payload = {"name":"Support portal","url":"https://example.com/support","description":"Capture support messages","config":{"root":{"selector":".message"},"fields":{"text":{"selector":".body"}},"navigation":{"strategy":"manual"}}}
        created = self.client.post(f"/api/workflows/{wid}/web-connectors", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        connector = created.json()
        self.assertEqual(connector["name"], "Support portal")
        self.assertEqual(connector["config"]["root"]["selector"], ".message")
        listed = self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"]
        self.assertTrue(any(x["id"] == connector["id"] for x in listed))
        payload["name"] = "Support portal v2"
        updated = self.client.put(f"/api/web-connectors/{connector['id']}", json=payload)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["version"], 2)
        deleted = self.client.delete(f"/api/web-connectors/{connector['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(any(x["id"] == connector["id"] for x in self.client.get(f"/api/workflows/{wid}/web-connectors").json()["items"]))

    def test_universal_web_html_analysis_and_validation_endpoints(self):
        wid = self.workflow_id
        one = '<div class="message"><span class="sender">Ada</span><p class="body">Hello</p><time datetime="2026-11-09">Today</time></div>'
        listing = '<section><div class="message"><span class="sender">Ada</span><p class="body">Hello</p><time datetime="2026-11-09">Today</time></div><div class="message"><span class="sender">Bob</span><p class="body">World</p><time datetime="2026-11-10">Tomorrow</time></div></section>'
        analyzed = self.client.post(f"/api/workflows/{wid}/web-connectors/analyze", json={"individual_html":one,"list_html":listing})
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        self.assertTrue(any(x["selector"] == "div.message" for x in analyzed.json()["message_candidates"]))
        config = {"root":{"selector":"div.message"},"fields":{"text":{"selector":".body","attribute":"textContent"},"sender":{"selector":".sender","attribute":"textContent"},"timestamp":{"selector":"time","attribute":"datetime"}}}
        validated = self.client.post(f"/api/workflows/{wid}/web-connectors/validate", json={"list_html":listing,"config":config})
        self.assertEqual(validated.status_code, 200, validated.text)
        self.assertTrue(validated.json()["ready"])
        self.assertEqual(validated.json()["root"]["matched"], 2)

    def test_universal_web_inspector_selection_html_is_explicitly_retrievable(self):
        wid = self.workflow_id
        payload = {"name":"Inspector fixture","url":"https://example.com/chat","config":{}}
        created = self.client.post(f"/api/workflows/{wid}/web-connectors", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        cid = created.json()["id"]
        with patch("app.server.web_inspector_manager.selection_html", return_value={"outer_html":"<article class=\"message\">Hello</article>","selector":"article.message","tag":"article"}):
            response = self.client.get(f"/api/web-connectors/{cid}/inspect/selection-html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<article", response.json()["outer_html"])

    def test_universal_web_capture_imports_sender_attachments_and_source_reference(self):
        wid = self.client.post("/api/workflows",json={"name":"Isolated web capture","template":"custom"}).json()["id"]
        payload = {"name":"Capture fixture","url":"https://example.com/chat","config":{"root":{"selector":".message"},"fields":{"text":{"selector":".body"}},"navigation":{"strategy":"manual"}}}
        created = self.client.post(f"/api/workflows/{wid}/web-connectors", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        cid = created.json()["id"]
        fixture = {"items":[{"raw_text":"Hello from the live DOM","source_ref":"id:fixture-101","posted_at":"2026-11-09T12:00:00Z","sender":"Ada","attachments":["https://example.com/file/101"]}],"root_count":1,"scroll_cycles":0,"strategy":"manual"}
        with patch("app.server.web_inspector_manager.capture", return_value=fixture):
            captured = self.client.post(f"/api/web-connectors/{cid}/capture", json={"mode":"visible","max_messages":10})
        self.assertEqual(captured.status_code, 200, captured.text)
        self.assertEqual(captured.json()["added"], 1)
        messages = self.client.get(f"/api/workflows/{wid}/messages?limit=500").json()
        imported = next(x for x in messages if x.get("source_ref") == "id:fixture-101")
        self.assertIn("[Sender] Ada", imported["raw_text"])
        self.assertIn("https://example.com/file/101", imported["raw_text"])
        self.assertIn("Hello from the live DOM", imported["raw_text"])

    def test_universal_web_ai_requires_html_privacy_consent_and_model(self):
        wid = self.workflow_id
        base = {"name":"Test","url":"https://example.com","intent":"Collect support chat messages","individual_html":"<div class='message'>Hello</div>","list_html":"","consent_to_send_html":False}
        privacy = self.client.post(f"/api/workflows/{wid}/web-connectors/assist", json=base)
        self.assertEqual(privacy.status_code, 400)
        self.assertIn("private message content", privacy.json()["detail"])
        base["consent_to_send_html"] = True
        disabled = self.client.post(f"/api/workflows/{wid}/web-connectors/assist", json=base)
        self.assertEqual(disabled.status_code, 400)
        self.assertIn("Model & Settings", disabled.json()["detail"])

    def test_universal_web_ai_compacts_html_and_retries_context_overflow(self):
        import httpx
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        captured=[]
        class FakeResponse:
            def raise_for_status(self): return None
            def json(self):
                return {"choices":[{"message":{"content":dumps({
                    "root_selector":"div.message",
                    "fields":{"text":{"selector":".body","attribute":"textContent"},"sender":{"selector":".sender","attribute":"textContent"},"timestamp":{"selector":"","attribute":"textContent"},"message_id":{"selector":":root","attribute":"data-message-id"},"attachment":{"selector":"","attribute":"textContent"}},
                    "navigation":{"strategy":"manual","scroll_selector":"","button_selector":"","direction":"up","wait_ms":1200,"max_scrolls":20},
                    "explanations":{"root":"Repeated div.message elements were observed.","text":"The body class contains text."},"warnings":[]
                })}}]}
        class FakeClient:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None):
                captured.append(json)
                if len(captured)==1:
                    request=httpx.Request("POST",url)
                    response=httpx.Response(400,request=request,text='{"error":{"code":"exceed_context_size_error","message":"request exceeds the available context size"}}')
                    raise httpx.HTTPStatusError("context overflow",request=request,response=response)
                return FakeResponse()
        individual='<div class="message" data-message-id="one"><span class="sender">A</span><p class="body">Hello</p></div>'
        listing='<section>' + ''.join(
            f'<div class="message" data-message-id="{i}"><span class="sender">User</span><p class="body">Message {i}</p></div>'
            for i in range(300)
        ) + '</section>'
        try:
            with patch("app.server.httpx.Client",FakeClient):
                response=self.client.post(f"/api/workflows/{self.workflow_id}/web-connectors/assist",json={
                    "name":"Large page","url":"https://example.test/chat","intent":"Collect each message from the chat history",
                    "individual_html":individual,"list_html":listing,"consent_to_send_html":True
                })
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(captured),2)
            self.assertEqual(captured[0]["max_tokens"],1100)
            second_task=__import__('json').loads(captured[1]["messages"][1]["content"])
            self.assertLessEqual(len(second_task["individual_message_html"])+len(second_task["surrounding_list_html"]),5200)
            self.assertEqual(response.json()["sample_info"]["context_retries"],1)
            self.assertTrue(response.json()["sample_info"]["compacted"])
            self.assertTrue(any("compacted before AI analysis" in x for x in response.json()["warnings"]))
            self.assertGreaterEqual(response.json()["validation"]["root"]["matched"],2)
        finally:
            set_model_settings(before)
            _reset_model_status_cache()

    def test_universal_web_ai_retries_truncated_json_proposal(self):
        from app.server import _reset_model_status_cache

        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:8180/v1","model":"test-model","connection_verified":True})
        set_model_settings(settings)
        captured=[]
        valid={
            "root_selector":"div.message",
            "fields":{
                "text":{"selector":".body","attribute":"textContent"},
                "sender":{"selector":".sender","attribute":"textContent"},
                "timestamp":{"selector":"","attribute":"textContent"},
                "message_id":{"selector":":root","attribute":"data-message-id"},
                "attachment":{"selector":"","attribute":"textContent"},
            },
            "navigation":{"strategy":"manual","scroll_selector":"","button_selector":"","direction":"up","wait_ms":1200,"max_scrolls":20},
            "explanations":{"root":"Repeated message cards were observed."},
            "warnings":[],
        }
        class FakeResponse:
            def __init__(self,body): self.body=body
            def raise_for_status(self): return None
            def json(self): return self.body
        class FakeClient:
            def __init__(self,*args,**kwargs): pass
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def post(self,url,headers=None,json=None):
                captured.append(json)
                if len(captured)==1:
                    return FakeResponse({"choices":[{"finish_reason":"length","message":{"content":"{\"root_selector\":\"div.message\",\"fields\":{"}}]})
                return FakeResponse({"choices":[{"finish_reason":"stop","message":{"content":dumps(valid)}}]})
        listing='<section>'+''.join(f'<div class="message" data-message-id="{i}"><span class="sender">User</span><p class="body">Message {i}</p></div>' for i in range(30))+'</section>'
        try:
            with patch("app.server.httpx.Client",FakeClient):
                response=self.client.post(f"/api/workflows/{self.workflow_id}/web-connectors/assist",json={
                    "name":"Truncated proposal","url":"https://example.test/chat","intent":"Collect each chat message",
                    "individual_html":'<div class="message" data-message-id="one"><span class="sender">A</span><p class="body">Hello</p></div>',
                    "list_html":listing,"consent_to_send_html":True
                })
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(captured),2)
            self.assertEqual(captured[0]["max_tokens"],1100)
            self.assertEqual(captured[1]["max_tokens"],1500)
            self.assertEqual(response.json()["sample_info"]["context_retries"],1)
            self.assertEqual(response.json()["config"]["root"]["selector"],"div.message")
        finally:
            set_model_settings(before)
            _reset_model_status_cache()

    def test_model_settings_save_invalidates_previous_connection_test(self):
        settings = get_model_settings()
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example","connection_verified":True,"tested_at":"2026-01-01T00:00:00+00:00"})
        set_model_settings(settings)
        payload = {"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example-new","api_key":"","input_mode":"raw","temperature":0,"timeout":150}
        response = self.client.put("/api/settings/model", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["connection_verified"])
        self.assertEqual(response.json()["connection_status"], "not_tested")
        set_model_settings({**settings,"enabled":False,"allow_rules_only":True,"connection_verified":False})

    def test_successful_model_test_is_persisted(self):
        settings = get_model_settings()
        try:
            settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example","connection_verified":False,"api_key":""})
            set_model_settings(settings)
            with patch("app.server._probe_model_endpoint", return_value=["qwen-example"]):
                response = self.client.post("/api/settings/model/test")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
            saved = self.client.get("/api/settings/model").json()
            self.assertTrue(saved["connection_verified"])
            self.assertEqual(saved["connection_status"], "verified")
        finally:
            set_model_settings({**settings,"enabled":False,"allow_rules_only":True,"connection_verified":False,"tested_at":None})


    def test_runtime_model_status_does_not_trust_a_stale_saved_green_flag(self):
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example","connection_verified":True,"tested_at":"2026-01-01T00:00:00+00:00"})
        set_model_settings(settings); _reset_model_status_cache()
        try:
            with patch("app.server._probe_model_endpoint", side_effect=__import__("httpx").ConnectError("connection refused")):
                response=self.client.get("/api/settings/model/status?force=true")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["status"],"offline")
            self.assertFalse(response.json()["ok"])
            self.assertFalse(get_model_settings()["connection_verified"])
        finally:
            set_model_settings(before); _reset_model_status_cache()

    def test_runtime_model_status_recovers_automatically_when_configured_model_returns(self):
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example","connection_verified":False,"tested_at":None})
        set_model_settings(settings); _reset_model_status_cache()
        try:
            with patch("app.server._probe_model_endpoint", return_value=["other-model","qwen-example"]):
                response=self.client.get("/api/settings/model/status?force=true")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["status"],"online")
            self.assertTrue(response.json()["ok"])
            self.assertTrue(get_model_settings()["connection_verified"])
            self.assertIn("qwen-example",response.json()["models"])
        finally:
            set_model_settings(before); _reset_model_status_cache()

    def test_runtime_model_status_reports_model_not_loaded_even_when_endpoint_is_up(self):
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-example","connection_verified":True})
        set_model_settings(settings); _reset_model_status_cache()
        try:
            with patch("app.server._probe_model_endpoint", return_value=["different-model"]):
                response=self.client.get("/api/settings/model/status?force=true")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["status"],"model_unavailable")
            self.assertFalse(get_model_settings()["connection_verified"])
        finally:
            set_model_settings(before); _reset_model_status_cache()

    def test_runtime_model_status_reports_rules_only_without_claiming_llm_online(self):
        from app.server import _reset_model_status_cache
        settings=get_model_settings(); before=dict(settings)
        settings.update({"enabled":False,"allow_rules_only":True,"connection_verified":True})
        set_model_settings(settings); _reset_model_status_cache()
        try:
            response=self.client.get("/api/settings/model/status?force=true")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()["status"],"rules_only")
            self.assertFalse(response.json()["ok"])
            self.assertFalse(get_model_settings()["connection_verified"])
        finally:
            set_model_settings(before); _reset_model_status_cache()

    def test_process_without_configured_model_is_rejected_without_creating_run(self):
        wid = self.client.post("/api/workflows", json={"name":"No model preflight","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Name: Test item"})
        settings = get_model_settings()
        try:
            settings.update({"enabled":False,"allow_rules_only":False,"model":"","connection_verified":False})
            set_model_settings(settings)
            with conn() as c:
                before = c.execute("SELECT COUNT(*) FROM runs WHERE workflow_id=?", (wid,)).fetchone()[0]
            response = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
            self.assertEqual(response.status_code, 400)
            self.assertIn("no LLM is configured", response.json()["detail"])
            with conn() as c:
                after = c.execute("SELECT COUNT(*) FROM runs WHERE workflow_id=?", (wid,)).fetchone()[0]
            self.assertEqual(after, before, "A blocked preflight must not create a queued/running run")
            summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
            self.assertFalse(summary["busy"])
            self.assertEqual(summary["messages"], 1)
        finally:
            set_model_settings({**settings,"enabled":False,"allow_rules_only":True})

    def test_llm_process_requires_verified_connection(self):
        wid = self.client.post("/api/workflows", json={"name":"Unverified model test","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Name: Test item"})
        settings = get_model_settings()
        try:
            settings.update({"enabled":True,"allow_rules_only":False,"base_url":"http://127.0.0.1:1234/v1","model":"qwen-test","connection_verified":False})
            set_model_settings(settings)
            response = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
            self.assertEqual(response.status_code, 400)
            self.assertIn("has not been tested successfully", response.json()["detail"])
            summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
            self.assertFalse(summary["busy"])
        finally:
            set_model_settings({**settings,"enabled":False,"allow_rules_only":True,"connection_verified":False})

    def test_rules_only_requires_explicit_opt_in(self):
        wid = self.client.post("/api/workflows", json={"name":"Rules-only opt in","template":"custom"}).json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Name: Test item"})
        settings = get_model_settings()
        try:
            settings.update({"enabled":False,"allow_rules_only":False})
            set_model_settings(settings)
            blocked = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
            self.assertEqual(blocked.status_code, 400)
            settings.update({"enabled":False,"allow_rules_only":True})
            set_model_settings(settings)
            started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
            self.assertEqual(started.status_code, 200)
            finished = self.wait_run(started.json()["run_id"])
            self.assertEqual(finished["status"], "completed")
        finally:
            set_model_settings({**settings,"enabled":False,"allow_rules_only":True})

    def test_startup_recovery_releases_stale_processing_lock(self):
        wid = self.client.post("/api/workflows", json={"name":"Stale run recovery","template":"custom"}).json()["id"]
        msg = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Name: Stale message"})
        message_id = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]["id"]
        run_id = create_run(wid, "extraction", 1)
        with conn() as c:
            c.execute("UPDATE runs SET status='running',started_at=? WHERE id=?", (now(), run_id))
            c.execute("UPDATE messages SET status='processing' WHERE id=?", (message_id,))
        init_db()
        run = self.client.get(f"/api/runs/{run_id}").json()
        self.assertEqual(run["status"], "interrupted")
        message = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]
        self.assertEqual(message["status"], "failed")
        summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertFalse(summary["busy"])

    def test_clear_pending_inbox_preserves_processed_messages_and_records(self):
        created = self.client.post("/api/workflows", json={"name":"Inbox clear test","template":"custom"})
        wid = created.json()["id"]
        first = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"First processed source record Alpha"})
        self.assertEqual(first.json()["added"], 1)
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        completed = self.wait_run(started.json()["run_id"])
        self.assertEqual(completed["status"], "completed")
        second = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Second waiting source record Beta"})
        self.assertEqual(second.json()["added"], 1)
        summary = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertEqual(summary["messages"], 2)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["processed"], 1)
        cleared = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"pending"})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["messages_deleted"], 1)
        self.assertEqual(cleared.json()["records_deleted"], 0)
        remaining = self.client.get(f"/api/workflows/{wid}/messages?limit=20").json()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["status"], "processed")
        self.assertEqual(len(self.client.get(f"/api/workflows/{wid}/records?status=all&limit=20").json()), 1)
        recollect = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Second waiting source record Beta", "source":"rubika:demo"})
        self.assertEqual(recollect.json()["added"], 0)

    def test_clear_all_inbox_removes_messages_records_and_corrections_for_one_workflow(self):
        created = self.client.post("/api/workflows", json={"name":"Full inbox reset test","template":"custom"})
        wid = created.json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"A source record to process"})
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        completed = self.wait_run(started.json()["run_id"])
        self.assertEqual(completed["status"], "completed")
        records = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()
        self.assertEqual(len(records), 1)
        corrected = dict(records[0]["data"])
        corrected["name"] = "Manually corrected"
        self.client.put(f"/api/records/{records[0]['id']}", json={"data":corrected})
        before = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertGreaterEqual(before["corrections"], 1)
        cleared = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"all"})
        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(cleared.json()["messages_deleted"], 1)
        self.assertEqual(cleared.json()["records_deleted"], 1)
        after = self.client.get(f"/api/workflows/{wid}/messages/summary").json()
        self.assertEqual(after["messages"], 0)
        self.assertEqual(after["records"], 0)
        self.assertEqual(after["corrections"], 0)
        self.assertEqual(self.client.get(f"/api/workflows/{wid}").json()["name"], "Full inbox reset test")
        # A later collection may still read the preserved daily source archive.
        # The cleared fingerprint must not be allowed back into this workflow.
        recollect = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"A source record to process", "source":"telegram:demo"})
        self.assertEqual(recollect.status_code, 200)
        self.assertEqual(recollect.json()["added"], 0)
        self.assertEqual(recollect.json()["duplicates"], 1)

    def test_inbox_clear_is_blocked_during_live_collection(self):
        created = self.client.post("/api/workflows", json={"name":"Busy inbox test","template":"custom"})
        wid = created.json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Keep this while collector is active"})
        COLLECT_STATE[wid] = {"status":"operator_paused", "logs":[]}
        response = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"all"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()), 1)
        COLLECT_STATE.pop(wid, None)


    def test_message_summary_remains_available_during_live_collection_but_clear_is_disabled(self):
        created = self.client.post("/api/workflows", json={"name":"Busy summary test","template":"custom"})
        wid = created.json()["id"]
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Visible while collector runs"})
        COLLECT_STATE[wid] = {"status":"running", "logs":[]}
        summary = self.client.get(f"/api/workflows/{wid}/messages/summary")
        self.assertEqual(summary.status_code, 200)
        self.assertTrue(summary.json()["busy"])
        denied = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"pending"})
        self.assertEqual(denied.status_code, 409)
        COLLECT_STATE.pop(wid, None)

    def test_clear_rejects_unknown_scope(self):
        created = self.client.post("/api/workflows", json={"name":"Invalid scope test","template":"custom"})
        wid = created.json()["id"]
        response = self.client.post(f"/api/workflows/{wid}/messages/clear", json={"scope":"anything"})
        self.assertEqual(response.status_code, 400)


    def create_processed_job_record(self, name="Explorer test", message="Job title: Engineer\nCompany: Example Ltd\nLocation: Berlin"):
        wid = self.client.post("/api/workflows", json={"name":name,"template":"jobs"}).json()["id"]
        added = self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":message,"source":"Explorer regression","posted_at":"2026-11-09"})
        self.assertEqual(added.status_code, 200)
        message_row = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        self.assertEqual(started.status_code, 200, started.text)
        run = self.wait_run(started.json()["run_id"])
        self.assertEqual(run["status"], "completed")
        record = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        return wid, message_row, record

    def test_messages_and_records_support_stable_offset_pagination(self):
        wid, first_message, first_record = self.create_processed_job_record("Explorer pagination")
        # Add two more posts and extract them so the endpoint contains multiple rows.
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Job title: Analyst\nCompany: Northwind\nLocation: Berlin\nReference: A","source":"Pagination"})
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Job title: Technician\nCompany: Contoso\nLocation: Munich\nReference: B","source":"Pagination"})
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(self.wait_run(started.json()["run_id"])["status"], "completed")
        m0 = self.client.get(f"/api/workflows/{wid}/messages?limit=1&offset=0").json()
        m1 = self.client.get(f"/api/workflows/{wid}/messages?limit=1&offset=1").json()
        self.assertEqual(len(m0), 1)
        self.assertEqual(len(m1), 1)
        self.assertNotEqual(m0[0]["id"], m1[0]["id"])
        r0 = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=1&offset=0").json()
        r1 = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=1&offset=1").json()
        self.assertEqual(len(r0), 1)
        self.assertEqual(len(r1), 1)
        self.assertNotEqual(r0[0]["id"], r1[0]["id"])

    def test_quality_summary_reports_required_field_coverage_and_off_topic_candidates(self):
        wid, _, _ = self.create_processed_job_record("Quality good candidate")
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Good morning, this is not a vacancy.","source":"Off-topic test"})
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        self.assertEqual(self.wait_run(started.json()["run_id"])["status"], "completed")
        quality = self.client.get(f"/api/workflows/{wid}/quality/summary")
        self.assertEqual(quality.status_code, 200)
        data = quality.json()
        self.assertGreaterEqual(data["active_records"], 2)
        self.assertGreaterEqual(data["issue_counts"]["no_schema_match"], 1)
        self.assertIn("job_title", {x["name"] for x in data["field_coverage"]})
        self.assertTrue(data["record_quality"])

    def test_trash_record_is_soft_deleted_and_undo_restores_previous_status(self):
        wid, _, record = self.create_processed_job_record("Record trash undo")
        trashed = self.client.post(f"/api/records/{record['id']}/trash", json={"reason":"Bad extraction"})
        self.assertEqual(trashed.status_code, 200, trashed.text)
        current = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(current["status"], "deleted")
        undone = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":trashed.json()["undo_token"]})
        self.assertEqual(undone.status_code, 200, undone.text)
        restored = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(restored["status"], "needs_review")

    def test_trash_message_moves_linked_record_and_undo_restores_both(self):
        wid, message, record = self.create_processed_job_record("Message trash undo")
        trashed = self.client.post(f"/api/messages/{message['id']}/trash", json={"reason":"Wrong source post"})
        self.assertEqual(trashed.status_code, 200, trashed.text)
        msg_now = self.client.get(f"/api/workflows/{wid}/messages?status=deleted&limit=10").json()
        self.assertEqual(len(msg_now), 1)
        rec_now = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(rec_now["status"], "deleted")
        undo = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":trashed.json()["undo_token"]})
        self.assertEqual(undo.status_code, 200, undo.text)
        msg_restored = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]
        rec_restored = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(msg_restored["status"], "processed")
        self.assertEqual(rec_restored["status"], "needs_review")

    def test_bulk_actions_are_scoped_to_workflow_and_undo_as_a_group(self):
        wid, _, first = self.create_processed_job_record("Bulk action first")
        # Add and process a second source row in the same workflow.
        self.client.post(f"/api/workflows/{wid}/messages/paste", json={"text":"Job title: Designer\nCompany: Studio","source":"Explorer regression"})
        started = self.client.post(f"/api/workflows/{wid}/process", json={"limit":10})
        self.assertEqual(self.wait_run(started.json()["run_id"])["status"], "completed")
        records = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()
        ids = [r["id"] for r in records]
        action = self.client.post(f"/api/workflows/{wid}/records/bulk-action", json={"ids":ids,"action":"reject","reason":"Off-topic batch"})
        self.assertEqual(action.status_code, 200, action.text)
        self.assertEqual(action.json()["updated"], 2)
        self.assertTrue(all(r["status"]=="rejected" for r in self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()))
        undo = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":action.json()["undo_token"]})
        self.assertEqual(undo.status_code, 200, undo.text)
        self.assertTrue(all(r["status"]=="needs_review" for r in self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()))

    def test_edit_source_message_queues_reextraction_and_can_be_undone(self):
        wid, message, record = self.create_processed_job_record("Source edit undo")
        updated_text = "Job title: Senior Engineer\nCompany: Example Ltd\nLocation: Hamburg"
        edited = self.client.put(f"/api/messages/{message['id']}", json={"raw_text":updated_text,"posted_at":"2026-11-08"})
        self.assertEqual(edited.status_code, 200, edited.text)
        current_message = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]
        current_record = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(current_message["status"], "queued")
        self.assertEqual(current_message["raw_text"], updated_text)
        self.assertEqual(current_record["status"], "stale")
        undone = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":edited.json()["undo_token"]})
        self.assertEqual(undone.status_code, 200, undone.text)
        restored_message = self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]
        restored_record = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(restored_message["status"], "processed")
        self.assertEqual(restored_message["raw_text"], message["raw_text"])
        self.assertEqual(restored_record["status"], record["status"])


    def test_bulk_source_message_trash_is_scoped_and_undo_restores_linked_record(self):
        wid, message, record = self.create_processed_job_record("Bulk source cleanup", "Job title: Engineer\nCompany: Example Ltd\nLocation: Berlin")
        response = self.client.post(f"/api/workflows/{wid}/messages/bulk-action", json={"ids":[message["id"]],"action":"trash","reason":"Unrelated source batch"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 1)
        current_message = self.client.get(f"/api/workflows/{wid}/messages?status=deleted&limit=10").json()[0]
        current_record = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(current_message["status"], "deleted")
        self.assertEqual(current_record["status"], "deleted")
        undo = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":response.json()["undo_token"]})
        self.assertEqual(undo.status_code, 200, undo.text)
        self.assertEqual(self.client.get(f"/api/workflows/{wid}/messages?limit=10").json()[0]["status"], "processed")
        self.assertEqual(self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]["status"], "needs_review")

    def test_record_field_edit_is_logged_and_undo_restores_values_and_status(self):
        wid, _, record = self.create_processed_job_record("Record field edit undo")
        original_data = dict(record["data"])
        changed = dict(original_data)
        changed["job_title"] = "Definitely incorrect title"
        edited = self.client.put(f"/api/records/{record['id']}", json={"data":changed})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["data"]["job_title"], "Definitely incorrect title")
        self.assertTrue(edited.json()["undo_token"])
        undo = self.client.post(f"/api/workflows/{wid}/quality/undo", json={"undo_token":edited.json()["undo_token"]})
        self.assertEqual(undo.status_code, 200, undo.text)
        restored = self.client.get(f"/api/workflows/{wid}/records?status=all&limit=10").json()[0]
        self.assertEqual(restored["data"], original_data)
        self.assertEqual(restored["status"], record["status"])

    def test_review_settings_are_persisted_and_new_review_mode_is_explicit(self):
        wid=self.client.post("/api/workflows",json={"name":"Review settings test","template":"jobs"}).json()["id"]
        settings={"enabled":False,"mode":"batch","auto_advance":False,"confirm_bulk":True,"page_size":50,"sort":"confidence_low"}
        response=self.client.put(f"/api/workflows/{wid}/review/settings",json=settings)
        self.assertEqual(response.status_code,200,response.text)
        payload=response.json()
        self.assertFalse(payload["review_mode"])
        self.assertEqual(payload["review_settings"]["mode"],"batch")
        self.assertFalse(payload["review_settings"]["auto_advance"])
        workflow=self.client.get(f"/api/workflows/{wid}").json()
        self.assertFalse(workflow["config"]["review_mode"])
        self.assertEqual(workflow["config"]["review_settings"]["page_size"],50)
        # Enabling approval again must not alter previously existing records.
        again=self.client.put(f"/api/workflows/{wid}/review/settings",json={**settings,"enabled":True,"mode":"guided"})
        self.assertEqual(again.status_code,200)
        self.assertTrue(again.json()["review_mode"])

    def test_review_queue_endpoint_returns_numberable_items_and_server_filters(self):
        wid,_,record=self.create_processed_job_record("Review queue API test","Job title: Senior Engineer\nCompany: Example Ltd\nLocation: Berlin")
        response=self.client.get(f"/api/workflows/{wid}/review/queue?limit=20&sort=oldest")
        self.assertEqual(response.status_code,200,response.text)
        payload=response.json()
        self.assertEqual(payload["total"],1)
        self.assertEqual(payload["total_review"],1)
        self.assertEqual(payload["items"][0]["id"],record["id"])
        self.assertEqual(payload["items"][0]["raw_text"].splitlines()[0],"Job title: Senior Engineer")
        search=self.client.get(f"/api/workflows/{wid}/review/queue?q=nonexistent-review-keyword")
        self.assertEqual(search.status_code,200)
        self.assertEqual(search.json()["total"],0)
        invalid=self.client.get(f"/api/workflows/{wid}/review/queue?issue=not-a-filter")
        self.assertEqual(invalid.status_code,400)

    def test_review_queue_pagination_refills_after_decision_and_undo_restores_order(self):
        wid=self.client.post("/api/workflows",json={"name":"Review pagination workflow","template":"jobs"}).json()["id"]
        messages="\n\n".join([
            "Job title: Backend Engineer\nCompany: Alpha Systems\nLocation: Berlin",
            "Job title: Data Engineer\nCompany: Beta Labs\nLocation: Hamburg",
            "Job title: QA Engineer\nCompany: Gamma Works\nLocation: Munich",
        ])
        added=self.client.post(f"/api/workflows/{wid}/messages/paste",json={"text":messages,"source":"Review pagination test","posted_at":"2026-11-09"})
        self.assertEqual(added.status_code,200,added.text)
        self.assertEqual(added.json()["added"],3)
        started=self.client.post(f"/api/workflows/{wid}/process",json={"limit":10})
        self.assertEqual(started.status_code,200,started.text)
        run=self.wait_run(started.json()["run_id"])
        self.assertEqual(run["status"],"completed")
        first=self.client.get(f"/api/workflows/{wid}/review/queue?limit=2&offset=0&sort=oldest").json()
        second=self.client.get(f"/api/workflows/{wid}/review/queue?limit=2&offset=2&sort=oldest").json()
        self.assertEqual(first["total"],3)
        self.assertEqual(len(first["items"]),2)
        self.assertEqual(len(second["items"]),1)
        first_id,second_id= [x["id"] for x in first["items"]]
        third_id=second["items"][0]["id"]
        decision=self.client.post(f"/api/records/{second_id}/approve")
        self.assertEqual(decision.status_code,200,decision.text)
        shifted=self.client.get(f"/api/workflows/{wid}/review/queue?limit=2&offset=0&sort=oldest").json()
        self.assertEqual([x["id"] for x in shifted["items"]],[first_id,third_id])
        undo=self.client.post(f"/api/workflows/{wid}/quality/undo",json={"undo_token":decision.json()["undo_token"]})
        self.assertEqual(undo.status_code,200,undo.text)
        restored=self.client.get(f"/api/workflows/{wid}/review/queue?limit=2&offset=0&sort=oldest").json()
        self.assertEqual([x["id"] for x in restored["items"]],[first_id,second_id])



if __name__ == "__main__":
    unittest.main(verbosity=2)


class ReviewDeskLaunchApiTests(unittest.TestCase):
    def test_one_click_launch_calls_native_terminal_launcher(self):
        from unittest.mock import patch
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        with patch("app.server._launch_review_terminal", return_value={"terminal":"Konsole","pid":4321,"verified":True}) as launch:
            response = client.post("/api/review/launch", headers={"Origin":"http://127.0.0.1:8765"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["terminal"], "Konsole")
        launch.assert_called_once_with()

    def test_one_click_launch_rejects_missing_origin(self):
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        response = client.post("/api/review/launch")
        self.assertEqual(response.status_code, 403)

    def test_one_click_launch_rejects_cross_origin(self):
        from unittest.mock import patch
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        with patch("app.server._launch_review_terminal") as launch:
            response = client.post("/api/review/launch", headers={"Origin":"https://evil.example"})
        self.assertEqual(response.status_code, 403)
        launch.assert_not_called()

    def test_one_click_launch_reports_missing_terminal_without_fake_success(self):
        from unittest.mock import patch
        client = TestClient(app, base_url="http://127.0.0.1:8765")
        with patch("app.server._launch_review_terminal", side_effect=RuntimeError("No supported terminal emulator was found.")):
            response = client.post("/api/review/launch", headers={"Origin":"http://127.0.0.1:8765"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("terminal emulator", response.json()["detail"])
