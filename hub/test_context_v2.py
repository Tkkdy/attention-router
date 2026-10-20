# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from work_context import WorkContext, WorkSessionConfig
from context_monitor import ForegroundSample
from attention import AttentionService
from hub_models import ContextOverride
from router_api import create_router_app
from tibo_attention import TiboAttentionPolicy

class ContextV2Tests(unittest.TestCase):
    def test_session_continuity_expiry_and_privacy(self):
        c=WorkContext()
        def sample(app, t, title="private text", idle=0):
            return c.update(ForegroundSample(app,title,idle),now=t)
        for t in range(0,121,5): r=sample("Codex.exe",t)
        self.assertEqual(r["automatic"],"CODING")
        identity=r["session_id"]
        self.assertEqual(sample("msedge.exe",125,"ChatGPT - Microsoft Edge")["session_id"],identity)
        for t in range(130,426,5): r=sample("WeChat.exe",t)
        self.assertEqual(r["session_id"],identity)
        self.assertEqual(sample("Codex.exe",430)["session_id"],identity)
        for t in range(435,1331,5): r=sample("WeChat.exe",t)
        self.assertEqual(r["automatic"],"IDLE")
        self.assertNotIn("private text",str(r))
        self.assertEqual(r["reason"],"no_strong_signal_timeout")

    def active_context(self):
        c=WorkContext()
        for t in range(0,121,5):
            initial=c.update(ForegroundSample("Codex.exe","",0),now=t,sampled_at="initial")
        return c, initial

    def test_transient_retains_session_and_original_deadline(self):
        c, initial=self.active_context()
        failed=c.update(None,now=125,error="WINDOW_CHANGED_DURING_SAMPLE",sampled_at="failure")
        self.assertEqual(failed["session_id"],initial["session_id"])
        self.assertEqual(failed["automatic"],"CODING")
        self.assertEqual(failed["last_successful_sample"],"initial")
        self.assertEqual(failed["last_strong_work_signal"]["at"],"initial")
        self.assertEqual(failed["last_strong_work_signal"]["age_seconds"],5)
        weak=c.update(ForegroundSample("Weixin.exe","",0),now=130)
        self.assertEqual(weak["session_id"],initial["session_id"])
        self.assertEqual(weak["automatic"],"CODING")
        self.assertIsNone(weak["error_category"])
        # Large sample gap also cannot reset the true deadline.
        self.assertEqual(c.update(None,now=1019)["session_id"],initial["session_id"])
        expired=c.update(None,now=1020)
        self.assertIsNone(expired["session_id"])
        self.assertEqual(expired["automatic"],"IDLE")
        self.assertEqual(expired["reason"],"no_strong_signal_timeout")

    def test_strong_before_deadline_preserves_identity_but_late_strong_does_not(self):
        c, initial=self.active_context()
        c.update(None,now=125)
        resumed=c.update(ForegroundSample("Codex.exe","",0),now=1019)
        self.assertEqual(resumed["session_id"],initial["session_id"])
        self.assertEqual(resumed["last_strong_work_signal"]["age_seconds"],0)
        self.assertEqual(c.update(ForegroundSample("Weixin.exe","",0),now=1918)["automatic"],"CODING")
        self.assertEqual(c.update(ForegroundSample("Weixin.exe","",0),now=1919)["automatic"],"IDLE")
        late, initial=self.active_context()
        self.assertIsNone(late.update(ForegroundSample("Codex.exe","",0),now=1020)["session_id"])

    def test_sampling_error_categories_and_privacy(self):
        import asyncio
        from unittest.mock import patch
        from context_monitor import SamplingError, process_failure
        self.assertEqual(process_failure(5).category,"ACCESS_DENIED")
        self.assertEqual(process_failure(87).category,"PROCESS_DISAPPEARED")
        with tempfile.TemporaryDirectory() as d:
            service=AttentionService(Path(d))
            for error, expected in [(SamplingError("WINDOW_CHANGED_DURING_SAMPLE"),"WINDOW_CHANGED_DURING_SAMPLE"),
                    (RuntimeError("sensitive content"),"SAMPLER_INTERNAL_ERROR")]:
                with patch("attention.read_foreground",side_effect=error):
                    asyncio.run(service.sample_context())
                context=service.context()
                self.assertEqual(context["error_category"],expected)
                self.assertEqual(context["monitor_status"],"Degraded")
                self.assertNotIn("sensitive content",str(context))

    def test_degraded_scene_stable_and_manual_override_wins(self):
        from runtime_view import RuntimeView
        with tempfile.TemporaryDirectory() as d:
            service=AttentionService(Path(d))
            c, initial=self.active_context()
            service.record_context(initial)
            before=service.scene(tibo_supported=True)
            service.record_context(c.update(None,now=125,error="WINDOW_CHANGED_DURING_SAMPLE"))
            context=service.context()
            self.assertEqual(context["monitor_status"],"Degraded")
            self.assertEqual(context["page"],"WORKSPACE")
            self.assertEqual(RuntimeView().view(context,{})["context_monitor"]["last_successful_sample"],"initial")
            self.assertEqual(service.scene(tibo_supported=True),before)
            service.record_context(c.update(ForegroundSample("Weixin.exe","",0),now=127))
            self.assertEqual(service.scene(tibo_supported=True),before)
            for mode, page in [("IDLE","home"),("CODING","workspace")]:
                service.set_context(ContextOverride(mode=mode))
                service.record_context(c.update(None,now=130,error="FOREGROUND_UNAVAILABLE"))
                self.assertEqual(service.scene(tibo_supported=True)["page"],page)
            service.set_context(ContextOverride(mode="AUTO"))
            service.record_context(c.update(None,now=1020))
            self.assertEqual(service.scene(tibo_supported=True)["page"],"home")

    def test_browser_marker_without_brand_title(self):
        from work_context import classify
        self.assertEqual(classify(ForegroundSample("msedge.exe","private conversation title",0,site_marker="chatgpt_web")),("ChatGPT Web","strong"))
        self.assertEqual(classify(ForegroundSample("msedge.exe","private conversation title",0)),("Browser","continuation"))
        self.assertEqual(classify(ForegroundSample("Weixin.exe","ChatGPT",0,site_marker="chatgpt_web"))[1],"continuation")

    def test_weak_idle_gap(self):
        c=WorkContext(enter_seconds=5)
        c.update(ForegroundSample("Codex.exe","",0),now=0)
        self.assertEqual(c.update(ForegroundSample("Codex.exe","",0),now=5)["automatic"],"CODING")
        self.assertEqual(c.update(ForegroundSample("Codex.exe","",901),now=10)["automatic"],"IDLE")
        self.assertEqual(c.update(ForegroundSample("WeChat.exe","",0),now=15)["automatic"],"IDLE")
        self.assertEqual(c.update(None,now=20)["automatic"],"UNKNOWN")
        self.assertEqual(c.update(ForegroundSample("Codex.exe","",0),now=50)["unknown_reason"],"sample_gap")

    def test_tibo_lifecycle_and_todo_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            s=AttentionService(Path(d)); before=s.task_store.read()
            prefs=s.tibo.preferences()
            s.tibo_lifecycle.show("manual")
            self.assertFalse(s.scene(tibo_supported=True)["attention_required"])
            self.assertEqual(s.tibo_lifecycle.view()["events"],[])
            s.db.write("tibo_detail",{})
            event=s.tibo_lifecycle.test_event()
            scene=s.scene(tibo_supported=True)
            self.assertEqual(scene["page"],"tibo")
            s.served(scene)
            view=s.tibo_lifecycle.view()["events"][0]
            self.assertEqual(view["acknowledgment"],"unacknowledged")
            self.assertEqual(view["device_displayed"],"unknown")
            # Restart re-evaluates the persisted event, not a cached Scene.
            s=AttentionService(Path(d));s.set_context(ContextOverride(mode="CODING"))
            self.assertEqual(s.scene(tibo_supported=True)["page"],"tibo")
            s.tibo_lifecycle.acknowledge(event["id"],1,"ack")
            self.assertEqual(s.scene(tibo_supported=True)["page"],"workspace")
            self.assertEqual(before,s.task_store.read())
            self.assertEqual(prefs,s.tibo.preferences())
            self.assertFalse(s.tibo_lifecycle.view()["events"][0]["attention_required"])
            s.tibo_lifecycle.show("later-manual")
            s.tibo_lifecycle.acknowledge(event["id"],1,"ack")
            self.assertEqual(s.tibo_lifecycle.detail()["request_id"],"later-manual")
            with self.assertRaises(ValueError):s.tibo_lifecycle.configure(TiboAttentionPolicy(automatic_enabled=True))

    def test_gateway_tibo_never_calls_todo_and_permissions_remain_narrow(self):
        from butler_gateway import ButlerGateway
        from butler_models import Command
        from todo_core import ButlerError
        class NoTodo:
            def execute(self,*args): raise AssertionError("Tibo reached Todo Core")
        seen=[]
        g=ButlerGateway(NoTodo(),attention_port=lambda c: seen.append(c.action) or {"ack_required": False},
            action_permissions={"grok":{"show_tibo_page","ack_tibo_attention","get_tibo_attention"}})
        c=Command(source="grok",action="show_tibo_page",request_id="show",expected_revision=0,arguments={})
        self.assertFalse(g.execute(c,principal="grok")["ack_required"])
        with self.assertRaises(ButlerError):g.execute(Command(source="grok",action="create_todo",request_id="bad",expected_revision=0,arguments={"title":"forbidden"}),principal="grok")
        self.assertEqual(seen,["show_tibo_page"])

    def test_detail_expiry_forecast_freeze_and_manual_override(self):
        with tempfile.TemporaryDirectory() as d:
            s=AttentionService(Path(d))
            s.tibo_lifecycle.show("manual")
            detail=s.db.read("tibo_detail")
            detail["expires_at"]=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
            s.db.write("tibo_detail",detail)
            s.record_context({"automatic":"CODING"})
            s.set_context(ContextOverride(mode="IDLE"))
            self.assertEqual(s.scene(tibo_supported=True)["page"],"home")
            self.assertEqual(s.context()["automatic"],"CODING")
            s.set_context(ContextOverride(mode="AUTO"))
            self.assertEqual(s.scene(tibo_supported=True)["page"],"workspace")
            snapshot={"data":{"status":"FRESH","forecast_status":"FRESH","p24":10,"p48":20,"p72":30},
                "sources":{"forecast":{"expires_at":"2000-01-01T00:00:00+00:00"}}}
            self.assertIsNone(s.tibo_lifecycle.display_data(snapshot)["p24"])

    def test_api_override_config_and_manual(self):
        with tempfile.TemporaryDirectory() as d:
            app=create_router_app(Path(d),start_monitor=False,environment="attention-m3-isolated",api_token="test-token")
            with TestClient(app,base_url="http://127.0.0.1") as c:
                c.headers["Authorization"]="Bearer test-token"; h={}
                self.assertEqual(c.post("/api/tibo/show",json={"request_id":"test"},headers=h).status_code,200)
                self.assertEqual(c.get("/api/overview").json()["runtime"]["context_monitor"]["status"],"Stopped")
                self.assertEqual(c.post("/api/context",json={"mode":"CODING"},headers=h).json()["effective"],"CODING")
                self.assertEqual(c.post("/api/tibo/attention-policy",json={"automatic_enabled":True},headers=h).status_code,409)
                self.assertEqual(c.post("/api/context/config",json=WorkSessionConfig(enter_seconds=10).model_dump(),headers=h).status_code,200)
            self.assertEqual(AttentionService(Path(d)).context_detector.enter_seconds,10)

if __name__=="__main__":unittest.main()
