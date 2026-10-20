# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""M1.1 regressions: synthetic local HTTP only; never device acceptance."""
import runpy,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
from fastapi.testclient import TestClient
from router_api import create_router_app
from hub_models import ContextOverride,TodoUpsert,WorkspaceSync
import device_text

class PreviewRevisionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.app=create_router_app(Path(self.tmp.name),start_monitor=False,api_token='synthetic-token')
  self.service=self.app.state.dashboard
 def test_optional_radar_scope(self):
  s=self.service
  with patch('radar_client.RADAR_URL',''):
   self.assertFalse(s.scene()['stale'])
   state=s.state_store.read();state['radar'].update(updated_at='2020-01-01T00:00:00+00:00',stale=True);s.state_store.write(state)
   self.assertFalse(s.scene()['stale']) # Disabling a previously enabled provider also excludes its cached failure.
  with patch('radar_client.RADAR_URL','https://example.invalid/status.json'):
   self.assertTrue(s.scene()['stale']) # enabled but never successful
   s.set_context(ContextOverride(mode='CODING'))
   self.assertFalse(s.scene()['stale']) # unrelated Home provider
   from attention import EventInput
   s.publish(EventInput(id='fresh',revision=1,title='Review',message='Now',kind='reminder',authorization='user_reminder',provenance='USER'))
   self.assertFalse(s.scene()['stale'])
 def test_device_font_present_and_missing(self):
  s=self.service
  s.upsert_todo(TodoUpsert(request_id='font',expected_revision=0,title='English task'))
  doc=s.task_store.read();doc['tasks'][0]['display_title']='中文待办';s.task_store.write(doc)
  for missing in (False,True):
   device_text.title_font.cache_clear();device_text.title_bitmap.cache_clear()
   ctx=patch.dict('os.environ',{'WINDIR':str(Path(self.tmp.name)/'missing')}) if missing else patch.dict('os.environ',{})
   with ctx,TestClient(self.app) as c:
    for chinese in (True,False):
     doc=s.task_store.read();doc['tasks'][0]['display_title']='中文待办' if chinese else 'English task';s.task_store.write(doc)
     r=c.get('/scene?capabilities=tibo-v1,bitmap-titles-v1');self.assertEqual(r.status_code,200)
     item=r.json()['todos'][0];self.assertEqual(item['title'],'English task')
     self.assertEqual('title_bitmap' in item,not missing)
     if not missing:self.assertEqual(len(item['title_bitmap']),1548)
   device_text.title_font.cache_clear();device_text.title_bitmap.cache_clear()
 def test_lan_access_matrix(self):
  with TestClient(self.app,base_url='http://192.168.1.10:8765',client=('192.168.1.20',1234)) as c:
   for path in ('/','/api/overview'):self.assertEqual(c.get(path).status_code,401)
   for path in ('/scene','/health'):self.assertEqual(c.get(path).status_code,200)
   self.assertEqual(c.get('/api/overview',headers={'Authorization':'Bearer synthetic-token'}).status_code,200)
if __name__=='__main__':unittest.main()
