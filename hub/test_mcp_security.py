# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""S1 matrix: isolated credentials, local policy, HTTP gateway and real temporary Hub."""
import asyncio
from copy import deepcopy
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from test_mcp import ROOT, process, free_port
from mcp_auth import load_credential, provision_credential, rotate_credential
from mcp_policy import (DEFAULTS, PRINCIPAL, TOOL_POLICIES, AccessPolicy, PolicyError, Denied,
                        RateLimiter, atomic_write, control, read_policy, utc_now, utc_text, validate_registry)
from mcp_readonly import create_server

class PolicyUnitTests(unittest.TestCase):
    def test_registry_exact_no_generic_or_unmapped_tool(self):
        self.assertEqual(set(TOOL_POLICIES), {'get_hub_state','upsert_todo','set_current_item'})
        for names in ([*TOOL_POLICIES,'execute_action'],['get_hub_state'],[]):
            with self.assertRaises(PolicyError): validate_registry(names)
        server=create_server()
        def execute_action(): return 'forbidden'
        with self.assertRaises(ValueError): server.add_tool(execute_action)
        result=asyncio.run(server.call_tool('submit_event',{}))
        self.assertEqual(result.structured_content['status'],'insufficient_scope')

    def test_policy_local_controls_expiry_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'policy.json'
            with self.assertRaises(PolicyError): AccessPolicy(path).start()
            control('read-only',path)
            for minutes in ('0','-1','1.5','abc','1441','99999999999','',1,True):
                before=path.read_bytes()
                with self.assertRaises(PolicyError): control('arm-write',path,minutes)
                self.assertEqual(before,path.read_bytes())
            control('arm-write',path,'120'); policy=AccessPolicy(path)
            self.assertEqual(policy.snapshot()['mode'],'WRITE_ARMED')
            self.assertEqual(policy.snapshot(utc_now()+timedelta(minutes=121))['mode'],'READ_ONLY')
            policy.start(); self.assertIsNone(read_policy(path)['write_armed_until'])
            control('off',path);policy.start();self.assertEqual(policy.snapshot()['mode'],'OFF')
            path.write_text('broken')
            with self.assertRaises(PolicyError): policy.snapshot()
            control('read-only',path)
            raw=read_policy(path);raw['write_armed_until']=utc_text(utc_now()+timedelta(hours=25))
            with self.assertRaises(PolicyError): atomic_write(path,raw)

    def test_exact_sliding_tool_and_global_limits(self):
        self.assertEqual(DEFAULTS['rate_limits'],{'principal':60,'get_hub_state':30,'upsert_todo':5,'set_current_item':5})
        now=[0.0]
        for tool,threshold in (('get_hub_state',30),('upsert_todo',5),('set_current_item',5),(None,60)):
            now[0]=0;limiter=RateLimiter(lambda:now[0])
            for _ in range(threshold): limiter.consume(PRINCIPAL,tool,DEFAULTS['rate_limits'])
            with self.assertRaises(Denied) as caught:limiter.consume(PRINCIPAL,tool,DEFAULTS['rate_limits'])
            self.assertEqual(caught.exception.code,'rate_limited');self.assertEqual(caught.exception.retry_after,60)
            now[0]=60;limiter.consume(PRINCIPAL,tool,DEFAULTS['rate_limits'])

@unittest.skipUnless(sys.platform=='win32','CurrentUser DPAPI requires Windows')
class SecurityHTTPTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.data=self.root/'hub'
        self.credential=self.root/'token.dpapi';provision_credential(self.credential);self.token=load_credential(self.credential)
        self.policy=self.root/'policy.json';control('read-only',self.policy);self.audit=self.root/'audit.jsonl';self.logs=[]
        hp,mp=free_port(),free_port()
        while mp==hp or mp==3001:mp=free_port()
        self.endpoint=f'http://127.0.0.1:{mp}/mcp'
        hc=[sys.executable,'-B','-c',"import sys;from pathlib import Path;sys.path.insert(0,'hub');from router_api import create_router_app;import uvicorn;uvicorn.run(create_router_app(Path(sys.argv[1]),start_monitor=False,environment='s1-test'),host='127.0.0.1',port=int(sys.argv[2]),log_level='error')",str(self.data),str(hp)]
        hub=process(hc,f'http://127.0.0.1:{hp}/health');hub.__enter__();self.addCleanup(hub.__exit__,None,None,None)
        self.command=[sys.executable,'-B',str(ROOT/'hub/mcp_readonly.py'),'--port',str(mp),'--hub-url',f'http://127.0.0.1:{hp}','--credential-file',str(self.credential),'--policy-file',str(self.policy),'--audit-file',str(self.audit)]
        self.gateway=None;self.addCleanup(self.stop);self.start()

    def start(self):
        self.gateway=process(self.command,self.endpoint,captured_logs=self.logs);self.gateway.__enter__()

    def stop(self):
        if self.gateway:self.gateway.__exit__(None,None,None);self.gateway=None

    def rpc(self,method,params=None,token='correct'):
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
        if token is not None:headers['Authorization']='Bearer '+(self.token if token=='correct' else token)
        request=urllib.request.Request(self.endpoint,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}}).encode(),headers=headers)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:response=opener.open(request,timeout=8)
        except urllib.error.HTTPError as error:response=error
        with response:return response.status,json.load(response),dict(response.headers)

    def call(self,name,args=None,token='correct'):
        return self.rpc('tools/call',{'name':name,'arguments':args or {}},token)

    def denied(self,result,status,code):
        self.assertEqual(result[0],status);self.assertEqual(result[1]['error']['data']['code'],code)

    def state(self):
        r=self.call('get_hub_state');self.assertEqual(r[0],200);return r[1]['result']['structuredContent']

    def snapshot(self):
        with closing(sqlite3.connect(self.data/'attention.sqlite3')) as db:
            return {t:db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ('documents','actions','commands','events')}

    def test_auth_off_readonly_fail_closed_no_hub_effects(self):
        self.state();before=self.snapshot()
        calls=[('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'s1','version':'1'}}),('tools/list',{}),('tools/call',{'name':'get_hub_state','arguments':{}})]
        for name in ('upsert_todo','set_current_item'):calls.append(('tools/call',{'name':name,'arguments':{'request_id':name,'expected_revision':0,'title':'Blocked'}}))
        control('off',self.policy);wrong=secrets.token_urlsafe(32)
        for method,params in calls:
            self.denied(self.rpc(method,params,None),401,'auth_required')
            self.denied(self.rpc(method,params,wrong),401,'invalid_token')
            self.denied(self.rpc(method,params),403,'remote_access_disabled')
        self.assertEqual(self.snapshot(),before)
        control('read-only',self.policy);self.assertEqual(self.rpc(*calls[0])[0],200)
        self.assertEqual([t['name'] for t in self.rpc('tools/list')[1]['result']['tools']],list(TOOL_POLICIES))
        self.assertEqual(self.state()['remote_access']['mode'],'READ_ONLY');before=self.snapshot()
        for method,params in calls[3:]:self.denied(self.rpc(method,params),403,'remote_write_not_armed')
        self.denied(self.call('upsert_todo'),403,'remote_write_not_armed');self.assertEqual(self.snapshot(),before)
        self.policy.unlink();self.denied(self.call('get_hub_state'),403,'remote_access_disabled')
        self.policy.write_text('corrupt');self.denied(self.rpc('tools/list'),403,'remote_access_disabled')
        self.assertEqual(self.snapshot(),before)
        log=self.audit.read_text();self.assertTrue(self.token not in log and wrong not in log)
        for word in ('Authorization','Cookie','Traceback','dpapi',str(self.root)):self.assertNotIn(word,log)

    def test_armed_replay_conflict_principal_audit_expiry_restart(self):
        control('arm-write',self.policy,'120');self.assertEqual(self.state()['remote_access']['mode'],'WRITE_ARMED')
        args={'request_id':'create','expected_revision':0,'title':'Security task'}
        for name in ('upsert_todo','set_current_item'):
            a={**args,'request_id':name};first=self.call(name,a)[1]['result']['structuredContent'];self.assertTrue(first['ok'])
            self.assertEqual(self.call(name,a)[1]['result']['structuredContent'],first)
            source=first['result']['todo' if name=='upsert_todo' else 'current_item']
            self.assertEqual(source['principal'],PRINCIPAL);self.assertEqual(source['provenance'],'MCP')
            stale=self.call(name,{**a,'request_id':name+'-stale'})[1]['result']['structuredContent'];self.assertEqual(stale['status'],'conflict')
        with closing(sqlite3.connect(self.data/'attention.sqlite3')) as db:actions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM actions')]
        applied=[a for a in actions if a['stage']=='MCP_CAPABILITY_APPLIED'];self.assertEqual(len(applied),2)
        self.assertTrue(all(a['principal']==PRINCIPAL and a['provenance']=='MCP' for a in applied))
        raw=read_policy(self.policy);raw['write_armed_until']=utc_text(utc_now()-timedelta(seconds=1));atomic_write(self.policy,raw);before=self.snapshot()
        for name in ('upsert_todo','set_current_item'):self.denied(self.call(name,args),403,'remote_write_not_armed')
        self.assertEqual(self.snapshot(),before)
        control('arm-write',self.policy,'120');self.stop();self.start()
        self.assertIsNone(read_policy(self.policy)['write_armed_until']);self.denied(self.call('upsert_todo',args),403,'remote_write_not_armed')
        control('off',self.policy);self.stop();self.start();self.denied(self.rpc('tools/list'),403,'remote_access_disabled')
        events=[json.loads(line) for line in self.audit.read_text().splitlines()]
        successes=[e for e in events if e['result_code']=='ok' and e['object_id']];self.assertTrue(successes)

    def test_scope_and_unknown_tool_denials_do_not_reach_hub(self):
        self.state();before=self.snapshot()
        for name,policy in TOOL_POLICIES.items():
            raw=deepcopy(DEFAULTS);raw['scopes'].remove(policy.required_scope);atomic_write(self.policy,raw);control('arm-write',self.policy,'120')
            self.denied(self.call(name,{'title':'invalid schema'}),403,'insufficient_scope')
        for name in ('execute_action','submit_event'):self.denied(self.call(name),403,'insufficient_scope')
        self.assertEqual(self.snapshot(),before)

    def test_audit_unavailable_fails_closed_without_hub_effects(self):
        self.state();before=self.snapshot()
        self.stop()
        # A directory cannot be opened as the JSONL audit file.
        self.audit.unlink();self.audit.mkdir();self.start()
        self.denied(self.call('get_hub_state'),500,'internal_error')
        control('off',self.policy)
        self.denied(self.call('get_hub_state'),403,'remote_access_disabled')
        self.assertEqual(self.snapshot(),before)

    def test_read_write_limits_no_hub_effects(self):
        raw=deepcopy(DEFAULTS);raw['rate_limits'].update(get_hub_state=2,upsert_todo=2,set_current_item=2);atomic_write(self.policy,raw);control('arm-write',self.policy,'120')
        self.state();self.state();before=self.snapshot();r=self.call('get_hub_state');self.denied(r,429,'rate_limited')
        self.assertIn('retry-after',r[2]);self.assertEqual(self.snapshot(),before)
        for name in ('upsert_todo','set_current_item'):
            for rev in range(2):self.assertTrue(self.call(name,{'request_id':name+str(rev),'expected_revision':rev,'title':'Limited task'})[1]['result']['structuredContent']['ok'])
            before=self.snapshot();self.denied(self.call(name,{'request_id':name+'blocked','expected_revision':2,'title':'Blocked'}),429,'rate_limited');self.assertEqual(self.snapshot(),before)

    def test_isolated_rotation_and_restart(self):
        old=self.token;self.assertEqual(self.rpc('tools/list')[0],200);rotate_credential(self.credential);new=load_credential(self.credential);self.assertTrue(old!=new)
        self.assertEqual(self.rpc('tools/list',token=old)[0],200);self.denied(self.rpc('tools/list',token=new),401,'invalid_token')
        self.stop();self.start();self.denied(self.rpc('tools/list',token=old),401,'invalid_token');self.token=new
        self.assertEqual(self.rpc('tools/list')[0],200);self.assertTrue(self.state()['ok'])
        log=self.audit.read_text();self.assertTrue(old not in log and new not in log)
        self.stop();output=b"".join(self.logs);self.assertTrue(old.encode() not in output and new.encode() not in output)

if __name__=='__main__':unittest.main()
