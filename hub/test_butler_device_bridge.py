# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""HTTP boundary tests only: simulated Hub, never a real device PASS."""
import unittest
import httpx
from attention import EventInput, AckInput
from butler_device_bridge import ExistingIsolatedHub
from butler_bridge import ButlerHubBridge

class DeviceBridgeTests(unittest.TestCase):
    def test_authenticated_existing_hub_contract_and_narrow_paths(self):
        calls=[]
        def respond(request):
            calls.append(request)
            if request.url.path == '/health':
                return httpx.Response(200,json={'environment':'attention-m3-isolated','instance_id':'one'})
            if request.url.path == '/':
                return httpx.Response(200,headers={'set-cookie':'hub_session=local-test; HttpOnly; SameSite=strict'})
            self.assertIn('hub_session=local-test', request.headers['cookie'])
            self.assertEqual(request.headers['origin'],'http://127.0.0.1:8000')
            self.assertEqual(request.headers['x-hub-action'],'1')
            return httpx.Response(200,json={'status':'active'})
        client=ExistingIsolatedHub(transport=httpx.MockTransport(respond))
        self.addCleanup(client.close)
        client.publish(EventInput(id='device-test',revision=1,title='Check',message='One thing',kind='service'))
        client.acknowledge('device-test',AckInput(revision=1,command_id='ack-one'))
        client.overview()
        self.assertEqual([r.url.path for r in calls if r.method=='POST'], ['/api/events','/api/events/device-test/ack'])
        self.assertFalse(hasattr(client,'sync_workspace'))

    def test_wrong_environment_and_restarted_instance_fail_closed(self):
        state={'environment':'production','instance_id':'one'}
        writes=[]
        def respond(request):
            if request.method=='POST': writes.append(request)
            if request.url.path=='/': return httpx.Response(200,headers={'set-cookie':'hub_session=test'})
            return httpx.Response(200,json=state)
        transport=httpx.MockTransport(respond)
        with self.assertRaises(ValueError): ExistingIsolatedHub(transport=transport)
        state['environment']='attention-m3-isolated'
        client=ExistingIsolatedHub(transport=transport)
        self.addCleanup(client.close)
        state['instance_id']='different'
        with self.assertRaises(ValueError):
            client.acknowledge('device-test',AckInput(revision=1,command_id='ack-one'))
        self.assertEqual(writes,[])

    def test_event_only_projection_preserves_existing_workspace(self):
        class Service:
            event_only=True
            def reevaluate(self): pass
            def sync_workspace(self,*args): raise AssertionError('must not modify existing workspace')
        bridge=ButlerHubBridge.__new__(ButlerHubBridge)
        bridge.service=Service()
        result=bridge.project({'revision':1,'suggestions':[{'id':'a','text':'Advice'}]})
        self.assertEqual(result['status'],'projected')
        self.assertEqual(result['unprojected_suggestions'][0]['reason'],'existing_hub_workspace_preserved')
