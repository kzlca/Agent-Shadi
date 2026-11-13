import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import app.server as server


class ReviewLaunchCommandTests(unittest.TestCase):
    def test_linux_prefers_konsole_and_passes_arguments_without_shell(self):
        env = {"DISPLAY": ":0"}
        with patch.dict(os.environ, env, clear=False), \
             patch.object(server.sys, "platform", "linux"), \
             patch.object(server.shutil, "which", side_effect=lambda name: "/usr/bin/konsole" if name == "konsole" else None):
            command, extra, label = server._review_terminal_launch_spec()
        self.assertEqual(label, "Konsole")
        self.assertEqual(command[:4], ["/usr/bin/konsole", "--nofork", "--workdir", str(server.ROOT)])
        self.assertIn(str(server.ROOT / "review_launcher.py"), command[-1])
        self.assertIn("Press Enter to close this window", command[-1])
        self.assertNotIn("shell", extra)

    def test_linux_launcher_spawns_window_and_waits_for_ui_readiness(self):
        import json
        import tempfile
        from pathlib import Path
        process = MagicMock(pid=9876)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(server, "DATA", Path(temp)), \
             patch.object(server, "_review_terminal_launch_spec", return_value=(["/usr/bin/konsole","--separate","--workdir",str(server.ROOT),"-e","/bin/bash","-lc","python review_launcher.py"], {"start_new_session":True}, "Konsole")), \
             patch.object(server.subprocess, "Popen", return_value=process) as popen:
            def launched(*args, **kwargs):
                Path(kwargs["env"]["AGENT_SHADI_REVIEW_HANDSHAKE"]).write_text(json.dumps({"state":"ready","pid":9876}),encoding="utf-8")
                return process
            popen.side_effect = launched
            result = server._launch_review_terminal()
        self.assertTrue(result["verified"])
        self.assertEqual(result["terminal"], "Konsole")
        kwargs = popen.call_args.kwargs
        self.assertEqual(kwargs["cwd"], str(server.ROOT))
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(popen.call_args.args[0][0], "/usr/bin/konsole")

    def test_launcher_waits_for_ui_handshake_when_terminal_client_returns_zero(self):
        import json
        import tempfile
        from pathlib import Path
        process=MagicMock(pid=9878)
        process.poll.side_effect=[0,0,0]
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(server,"DATA",Path(temp)), \
             patch.object(server,"_review_terminal_launch_spec",return_value=(["/usr/bin/konsole","--nofork"],{},"Konsole")), \
             patch.object(server.subprocess,"Popen",return_value=process) as popen:
            handshake_path=None
            original_poll=process.poll.side_effect
            calls={"count":0}
            def poll_then_write():
                calls["count"]+=1
                if calls["count"]==2:
                    Path(popen.call_args.kwargs["env"]["AGENT_SHADI_REVIEW_HANDSHAKE"]).write_text(json.dumps({"state":"ready"}),encoding="utf-8")
                return 0
            process.poll.side_effect=poll_then_write
            result=server._launch_review_terminal()
        self.assertTrue(result["verified"])
        self.assertEqual(calls["count"],2)

    def test_launcher_does_not_report_success_if_review_ui_reports_error(self):
        import json
        import tempfile
        from pathlib import Path
        process = MagicMock(pid=9877)
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(server, "DATA", Path(temp)), \
             patch.object(server, "_review_terminal_launch_spec", return_value=(["/usr/bin/konsole"], {"start_new_session":True}, "Konsole")), \
             patch.object(server.subprocess, "Popen", side_effect=lambda *a, **kw: (Path(kw["env"]["AGENT_SHADI_REVIEW_HANDSHAKE"]).write_text(json.dumps({"state":"error","detail":"curses failed"}),encoding="utf-8") and process)):
            with self.assertRaisesRegex(RuntimeError,"curses failed"):
                server._launch_review_terminal()
            self.assertEqual(list((Path(temp)/"review_launches").glob("*.json")),[])

    def test_linux_headless_session_has_clear_error(self):
        with patch.object(server.sys, "platform", "linux"), patch.dict(os.environ, {"DISPLAY":"", "WAYLAND_DISPLAY":""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "No graphical desktop session"):
                server._review_terminal_launch_spec()

    def test_ui_has_one_click_action_and_no_manual_install_instruction(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn('id="launchReviewDesk"', js)
        self.assertIn("/api/review/launch", js)
        self.assertIn("Open Review Desk", js)
        card = js[js.index("function renderStandaloneReviewLaunchCard()") : js.index("async function renderReview()")]
        self.assertNotIn("install_review_launcher.sh", card)
        self.assertNotIn("copyReviewDeskCommand", card)
        tui=(Path(__file__).resolve().parents[1]/"review_tui.py").read_text(encoding="utf-8")
        self.assertIn('notify_launch_state("ready")',tui)
        self.assertIn("self.draw()\n            if not self._launch_ready_reported",tui)


if __name__ == "__main__":
    unittest.main()
