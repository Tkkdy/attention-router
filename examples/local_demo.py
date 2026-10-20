# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Create one sample Todo/current item/reminder through the local console session.
No models or devices are contacted by this script. It preserves existing Todos.
"""
import argparse
import http.cookiejar
import json
import uuid
import urllib.request
from urllib.parse import urlsplit

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    args = parser.parse_args()
    origin = args.url.rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('use the loopback Hub origin')
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(path, data=None):
        request = urllib.request.Request(origin+path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Content-Type':'application/json','Origin':origin,'X-Hub-Action':'1'})
        with client.open(request,timeout=10) as response:
            body=response.read()
            return json.loads(body) if 'application/json' in response.headers.get('Content-Type','') else body
    call('/')
    overview=call('/api/overview')
    identity=uuid.uuid4().hex[:12]
    created = call('/api/mcp/todos/upsert',{'request_id':'demo-todo-'+identity,
         'expected_revision':overview['todos'].get('revision',0),'title':'Review demo task'})
    overview=call('/api/overview')
    todo = created['result']['todo']
    call('/api/workspace/sync',{'command_id':'demo-current-'+identity,
         'revision':overview['workspace'].get('revision',0)+1,
         'current_item':{'id':todo['id'],'title':todo['title']},
         'project':'Preview demo','provenance':'USER'})
    call('/api/events',{'id':'demo-reminder-'+identity,'revision':1,'title':'Preview reminder',
         'message':'Please review the demo','kind':'reminder','authorization':'user_reminder','provenance':'USER'})
    print('Created demo Todo/current item/reminder. Open the Web Console and ACK the reminder.')
    print('ACK acknowledges the reminder; completing the Todo is a separate action.')

if __name__ == '__main__':
    main()
