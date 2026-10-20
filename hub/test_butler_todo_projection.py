# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Display projection regression tests; never evidence of real device delivery."""
import copy
from pathlib import Path
import tempfile
import unittest
import httpx

from attention import AttentionService
from butler_todo_projection import project_state, ProjectionHub
from hub_models import WorkspaceSync


class ProjectionTests(unittest.TestCase):
    def test_mapping_unicode_preservation_idempotency_and_hub_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            service = AttentionService(path)
            service.sync_workspace(WorkspaceSync(revision=1, command_id='fixture', project='Preserve project',
                suggestions=[{'id':'advice','text':'Preserve advice'}]))
            state = {'authority':'shadow','revision':15,'current_item_id':'a'*32,
                'todos':[{'todo_id':'b'*32,'title':'D6-GROK-HW','status':'done','position':1},
                         {'todo_id':'a'*32,'title':'中文待办','status':'pending','position':0}]}
            before = copy.deepcopy(state)
            first = project_state(state, service)
            self.assertEqual(state, before)
            self.assertEqual(first['changed'], ['todos','current'])
            view = service.overview()
            self.assertEqual(view['workspace']['project'], 'Preserve project')
            self.assertEqual(view['workspace']['suggestions'][0]['text'],'Preserve advice')
            self.assertEqual(view['workspace']['current_item']['id'], view['todos']['tasks'][0]['id'])
            self.assertEqual(view['todos']['tasks'][1]['title'], 'D6-GROK-HW')
            self.assertTrue(view['todos']['tasks'][0]['title'].isascii())
            self.assertNotIn('display_title', service.scene()['todos'][0])
            unicode_scene = service.scene(utf8_supported=True)
            self.assertEqual(unicode_scene['todos'][0]['display_title'], '中文待办')
            self.assertEqual(unicode_scene['workspace']['display_title'], '中文待办')
            restarted = AttentionService(path)
            self.assertEqual(project_state(state,restarted)['changed'], [])
            after = restarted.overview()
            self.assertEqual(view['todos'],after['todos'])
            self.assertEqual(view['workspace'],after['workspace'])

    def test_restart_session_reacquired_but_other_environment_rejected(self):
        state={'environment':'attention-m3-isolated','instance_id':'one'}
        boots=[]
        def respond(request):
            if request.url.path == '/health': return httpx.Response(200,json=state)
            if request.url.path == '/':
                boots.append(state['instance_id'])
                return httpx.Response(200,headers={'set-cookie':'hub_session='+state['instance_id']})
            self.assertIn('hub_session='+state['instance_id'],request.headers['cookie'])
            return httpx.Response(200,json={})
        client=ProjectionHub(transport=httpx.MockTransport(respond))
        self.addCleanup(client.close)
        client.overview()
        state['instance_id']='two'
        client.overview()
        self.assertEqual(boots,['one','two'])
        state['environment']='production'
        with self.assertRaises(ValueError): client.overview()
        self.assertEqual(boots,['one','two'])


if __name__=='__main__': unittest.main()
