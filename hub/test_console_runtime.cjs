// SPDX-FileCopyrightText: 2026 Tkkdy
// SPDX-License-Identifier: MIT
// Exercise the actual console script with a small mock DOM and fixture transport. No browser/network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Node_ {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.listeners = {}; this._text = '';
    this.className = ''; this.disabled = false; this.hidden = false; this.value = '';
    this.classList = { set: new Set(), toggle: (c, on) => on ? this.classList.set.add(c) : this.classList.set.delete(c),
      contains: c => this.classList.set.has(c) }; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  append(...v) { this.children.push(...v); }
  replaceChildren(...v) { this._text = ''; this.children = [...v]; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(ev, f) { (this.listeners[ev] ||= []).push(f); }
  matches(selector) { return selector === ":focus" && !!this.focused; }
  find(pred) { if (pred(this)) return this; for (const c of this.children) { const r = c.find && c.find(pred); if (r) return r; } return null; }
  async click() { for (const f of this.listeners.click || []) await f(); }
}
const ids = new Map();
const html = fs.readFileSync(path.join(__dirname, 'console.html'), 'utf8');
for (const m of html.matchAll(/id="([^"]+)"/g)) ids.set(m[1], new Node_('x'));
const body = new Node_('body');
const document = { body, getElementById: id => { assert.ok(ids.has(id), 'unknown id ' + id); return ids.get(id); },
  createElement: t => new Node_(t), createTextNode: t => { const n = new Node_('#text'); n._text = String(t); return n; } };
const $ = id => ids.get(id);
const text = id => $(id).textContent;

let overview, snapshot, failOverview = false, posts = [], postReply = null;
const base = () => ({hub: 'READY', environment: 'ISOLATED_FIXTURE', instance_id: 'fixture0001',
  runtime: {personal_hub: {status: 'Running'}, context_monitor: {status: 'Active'}, deepseek: {status: 'Unknown', business_connection: 'Unknown'},
    grokbot: {status: 'Unknown'}, esp32: {status: 'Unknown', fresh_for_seconds: 45, device_requested_version: null},
    display: {status: 'NOT_IMPLEMENTED', received_scene: 'UNKNOWN', display_complete: 'UNKNOWN', pending_refresh: 'UNKNOWN'}, claims: {}},
  context_evidence: {effective: 'CODING', manual_override: 'AUTO', session_state: 'ACTIVE', work_session_seconds: 600},
  codex: {status: 'UNKNOWN', collection: 'NOT_CONNECTED', windows: [], display_policy: {plan: 'pro', five_hour_override: null, five_hour: {visible: false, reason: 'PLAN_PRESET_DISABLED'}}},
  todos: {snapshot_known: true, revision: 2, provenance: 'SIMULATED', tasks: Array.from({length: 5}, (_, i) => ({id: 'todo-' + i, title: 'Task ' + i, status: 'pending'}))},
  desired_scene: {page: 'workspace', version: 99, preview_only: true}, events: [], tibo_lifecycle: {automatic_strategy: 'unconfigured', policy: {detail_seconds: 60}, events: []}});
const snapOf = scene => ({profile: 'bitmap-titles-v1,tibo-v1', kind: 'canonical_snapshot', status: 'available', reason: null, read_at: '2026-10-16T01:00:05+00:00',
  snapshot: {snapshot_id: 'abc', profile: 'bitmap-titles-v1,tibo-v1', published_at: '2026-10-16T01:00:00+00:00', scene_version: scene.version, requester: 'lan_device_capability_marker', scene}});
overview = base();
snapshot = snapOf({version: 4, page: 'workspace', workspace: {project: 'Hub', current_item: 'Wire it', suggestion: 'NONE / UNKNOWN'}, codex: {show_5h: false}, simulated: true, stale: false});

const json = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
async function fetch(url, opts = {}) {
  const u = new URL(url, 'http://127.0.0.1');
  if (opts.method === 'POST') { posts.push({path: u.pathname, body: JSON.parse(opts.body), headers: opts.headers}); return postReply ? postReply() : json({}); }
  if (u.pathname === '/api/overview') { if (failOverview) throw Error('network unavailable'); return json(overview); }
  if (u.pathname === '/api/scene/snapshot') return json(snapshot);
  if (u.pathname === '/api/tibo') return json({preferences: {enabled: false}, events: {status: 'OFF'}, forecast: {status: 'OFF'}});
  if (u.pathname.startsWith('/api/events/')) return json({event: overview.events[0], decisions: [], actions: []});
  throw Error('unexpected ' + url);
}
let uuid = 0;
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1].replace('load(true);setInterval(load,10000);', '');
const ctx = vm.createContext({document, fetch, URL, Date, Intl, JSON, Promise, Map, Set, Symbol, Object, Array, String, Number, Math, isNaN, console,
  setInterval: () => {}, crypto: {randomUUID: () => 'cmd-' + (++uuid)}});
vm.runInContext(script, ctx);
const load = () => vm.runInContext('load(true)', ctx);

(async () => {
  // First failure: never observed, nothing green.
  failOverview = true; await load();
  assert.match(text('runtime'), /Hub·不可达/); assert.match(text('runtime'), /从未成功观测/);
  assert.doesNotMatch(text('runtime'), /响应正常/);

  // Success: module chips are independent; no global healthy label.
  failOverview = false; await load();
  assert.match(text('runtime'), /Hub·响应正常/); assert.match(text('runtime'), /Context Monitor·Active/);
  assert.match(text('runtime'), /显示完成·UNKNOWN/); assert.doesNotMatch(text('runtime'), /System Healthy/i);
  // Preview, JSON and Meta all come from the same snapshot response.
  assert.match(text('panel-preview'), /WORKSPACE · v4/); assert.match(text('panel-preview'), /SIMULATED/);
  assert.equal(JSON.parse(text('panel-json')).version, 4); assert.match(text('panel-meta'), /abc/);
  assert.match(text('panel-preview'), /todos 字段缺失/); assert.match(text('panel-preview'), /无有效建议/);
  assert.match(text('compute-preview'), /"preview_only": true/);
  assert.equal($('todos').children.length, 5); assert.match(text('todos'), /Task 4/);
  assert.match(html, /来源：overview.todos.tasks/);
  // A focused Tibo control must survive polling before its change event fires.
  for (const id of ['tibo-enabled', 'tibo-forecast']) {
    $(id).focused = true; $(id).value = 'on'; await load();
    assert.equal($(id).value, 'on'); $(id).focused = false;
  }
  await load(); assert.equal($('tibo-enabled').value, 'off');


  // Explicit empty list differs from missing.
  snapshot.snapshot.scene.todos = []; await load();
  assert.match(text('panel-preview'), /清单为空 · todos: \[\]/);

  // Snapshot unavailable: never falls back to the compute preview.
  snapshot = {...snapshot, status: 'unavailable', reason: 'no_snapshot_published_for_profile', snapshot: null}; await load();
  assert.match(text('snap-status'), /没有 canonical 快照/); assert.doesNotMatch(text('panel-preview'), /v99/);

  // Stale after failure: last snapshot is marked, Hub not green.
  failOverview = true; await load();
  assert.ok(body.classList.contains('stale')); assert.match(text('hub-banner'), /上次成功读取/);
  assert.match(text('runtime'), /Context Monitor·未核验/);

  // Recovery with explicit Stopped.
  overview.runtime.context_monitor.status = 'Stopped'; failOverview = false; await load();
  assert.ok(!body.classList.contains('stale')); assert.match(text('runtime'), /Context Monitor·Stopped/);

  // NOW event, ACK revision conflict: re-fetch, no auto retry, integer revision.
  overview.events = [{id: 'e1', revision: 3, title: 'Deploy blocked', message: 'Approve', status: 'active', route: 'NOW', reason: 'explicit_interrupt_authorization', provenance: 'SIMULATED'}];
  await load(); assert.match(text('now'), /Deploy blocked/); assert.match(text('now'), /不完成关联 Todo/);
  postReply = () => json({detail: 'stale ACK cannot close a newer event'}, 409);
  await $('now').find(n => n.tag === 'button' && n.textContent === '确认此版本').click();
  assert.equal(posts.length, 1); assert.deepEqual(posts[0].body, {revision: 3, command_id: 'cmd-1'});
  assert.equal(posts[0].headers['X-Hub-Action'], '1'); assert.match(text('now'), /版本冲突/);

  // Network failure keeps the same command_id on manual retry; success re-reads state.
  postReply = () => { throw Error('offline'); };
  await $('now').find(n => n.tag === 'button' && n.textContent === '确认此版本').click();
  assert.match(text('now'), /重试（同一操作 ID）/);
  postReply = () => json({id: 'e1', revision: 3, status: 'acknowledged'});
  await $('now').find(n => n.tag === 'button' && /重试/.test(n.textContent)).click();
  assert.equal(posts[1].body.command_id, posts[2].body.command_id); assert.notEqual(posts[1].body.command_id, 'cmd-1');

  // Empty NOW wording; cancel uses the cancel endpoint.
  overview.events = [{id: 'e2', revision: 1, title: 'Later', message: 'x', status: 'active', route: 'QUEUE', reason: 'context_busy', provenance: 'USER'}];
  await load(); assert.match(text('now'), /当前没有路由为 NOW 的事件/);
  postReply = () => json({id: 'e2', revision: 1, status: 'cancelled'});
  await $('routes').find(n => n.tag === 'button' && n.textContent === '取消事件').click();
  assert.equal(posts.at(-1).path, '/api/events/e2/cancel');

  // Context override posts only the allowed mode and offers AUTO.
  await $('ov-buttons').find(n => n.tag === 'button' && /^AUTO/.test(n.textContent)).click();
  assert.deepEqual(posts.at(-1), {path: '/api/context', body: {mode: 'AUTO'}, headers: posts.at(-1).headers});
  assert.doesNotMatch(html, /强制 INTERRUPT|稍后提醒|snooze|3\.4h|65%|ETA/);
  console.log('PASS: unreachable/first/stale/recovery, independent runtime, snapshot binding + unavailable, todos missing vs [], ACK conflict + same command_id retry, cancel, override');
})().catch(e => { console.error(e); process.exitCode = 1; });
