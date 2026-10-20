# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""UX contract tests: real isolated Core/Gateway, MOCK DeepSeek HTTP responses.

These tests establish deterministic safeguards, never real Bot/model compatibility.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import httpx
from pydantic import ValidationError

from butler_gateway import ButlerGateway
from butler_models import Command
from semantic_resolver import DeepSeekSemanticResolver, PROMPT_VERSION
from todo_core import ButlerError, TodoCore


class SemanticResolverTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='butler-ux-mock-')
        self.addCleanup(temporary.cleanup)
        self.core = TodoCore(Path(temporary.name) / 'todo-shadow.sqlite3')
        self.responses, self.requests, self.evidence = [], [], []
        self.sequence = 0
        self.resolver = DeepSeekSemanticResolver(
            'https://api.deepseek.com', 'mock-credential-not-real', 'mock-model',
            transport=httpx.MockTransport(self.provider), evidence_sink=self.evidence.append,
            clock=lambda: datetime(2026, 10, 11, 19, 0, tzinfo=timezone.utc))
        self.addCleanup(self.resolver.close)
        self.gateway = ButlerGateway(self.core, self.resolver)

    def provider(self, request):
        self.requests.append(json.loads(request.content))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, httpx.Response):
            return response
        return httpx.Response(200, json={
            'model': 'mock-served-model', 'choices': [{'finish_reason': 'stop',
                'message': {'content': json.dumps(response, ensure_ascii=False)}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})

    def command(self, action, arguments):
        self.sequence += 1
        return Command(source='deepseek', request_id=f'ux-{self.sequence}',
                       expected_revision=self.core.snapshot()['revision'],
                       action=action, arguments=arguments)

    def execute(self, action, arguments):
        return self.gateway.execute(self.command(action, arguments), principal='deepseek')

    def natural(self, message, decision):
        self.responses.append(decision)
        return self.execute('resolve_intent', {'original_user_message': message})

    @staticmethod
    def decision(action, arguments, evidence, **extra):
        return {'outcome': 'execute', 'action': action, 'arguments': arguments,
                'message': '已处理。', 'explicit_intent': True, 'evidence': evidence, **extra}

    def assert_error(self, code, callback):
        with self.assertRaises(ButlerError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_small_talk_noop_preserves_complete_state_and_sends_original(self):
        original = '今天真累，不想做事情。'
        before = self.core.snapshot()
        result = self.natural(original, {'outcome': 'noop', 'message': '先歇一会儿。'})
        self.assertEqual(self.core.snapshot(), before)
        self.assertEqual(result['semantic']['outcome'], 'noop')
        sent = json.loads(self.requests[0]['messages'][1]['content'])
        self.assertEqual(sent['original_user_message'], original)
        self.assertIsNone(sent['default_reminder_time'])
        self.assertEqual(sent['timezone'], 'America/Los_Angeles')
        self.assertEqual(self.evidence[0]['prompt_version'], PROMPT_VERSION)
        self.assertNotIn(original, json.dumps(self.evidence, ensure_ascii=False))
        self.assertNotIn('mock-credential-not-real', json.dumps(self.evidence))

    def test_no_time_todo_only_enters_list(self):
        result = self.natural('记一下交报告', self.decision(
            'create_todo', {'title': '交报告'}, '记一下交报告'))
        self.assertIsNone(result['todos'][0]['remind_at'])
        self.assertIsNone(result['todos'][0]['due_at'])
        self.assertIsNone(result['current_item_id'])

    def test_invented_default_time_becomes_question_then_exact_answer_executes(self):
        original = '明天提醒我交报告'
        guessed = self.decision('create_todo', {
            'title': '交报告', 'remind_at': '2026-10-12T09:00:00-07:00'}, original,
            time_precision='exact', time_expression='9点')
        first = self.natural(original, guessed)
        self.assertEqual(first['todos'], [])
        self.assertEqual(first['semantic']['outcome'], 'clarification')
        self.assertEqual(first['context']['pending_question'], '具体几点提醒你？')
        second = self.natural('下午3点', self.decision('create_todo', {
            'title': '交报告', 'remind_at': '2026-10-12T15:00:00-07:00'}, original,
            time_precision='exact', time_expression='3点'))
        self.assertEqual(len(second['todos']), 1)
        self.assertEqual(second['todos'][0]['remind_at'], '2026-10-12T15:00:00-07:00')
        self.assertIsNone(second['context']['pending_question'])
        self.assertEqual(second['context']['pending_intent_summary'], '')

    def test_explicit_no_reminder_creates_todo_without_time_question(self):
        original = '帮我记一下：完成物联网课程实验报告。不设置提醒时间。'
        result = self.natural(original, self.decision('create_todo',
            {'title': '完成物联网课程实验报告'}, '帮我记一下：完成物联网课程实验报告'))
        self.assertEqual(result['semantic']['outcome'], 'applied')
        self.assertEqual(len(result['todos']), 1)
        self.assertIsNone(result['todos'][0]['remind_at'])
        self.assertIsNone(result['context']['pending_question'])

    def test_cancel_reminder_clears_time_without_followup_question(self):
        todo_id = self.execute('create_todo', {'title': '报告',
            'remind_at': '2026-10-12T15:00:00-07:00'})['todos'][0]['todo_id']
        result = self.natural('取消报告的提醒', self.decision('update_todo',
            {'todo_id': todo_id, 'remind_at': None}, '取消报告的提醒'))
        self.assertEqual(result['semantic']['outcome'], 'applied')
        self.assertIsNone(result['todos'][0]['remind_at'])
        self.assertEqual(result['todos'][0]['status'], 'pending')
        self.assertIsNone(result['context']['pending_question'])
    def test_pending_reminder_can_be_changed_to_untimed_todo(self):
        self.natural('明天提醒我交报告', {
            'outcome': 'clarify', 'message': '几点提醒？', 'intent_summary': '明天提醒我交报告'})
        original = '不用提醒，直接记到待办就行'
        result = self.natural(original, self.decision('create_todo', {'title': '交报告'}, original))
        self.assertEqual(result['semantic']['outcome'], 'applied')
        self.assertEqual(len(result['todos']), 1)
        self.assertEqual(result['todos'][0]['title'], '交报告')
        self.assertIsNone(result['todos'][0]['remind_at'])
        self.assertIsNone(result['context']['pending_question'])
        self.assertEqual(result['context']['pending_intent_summary'], '')

    def test_resolved_read_noop_and_write_retry_restore_response_without_model(self):
        cases = [
            ('今天好累', {'outcome': 'noop', 'message': '先休息一下。'}, 0),
            ('看看待办', {'outcome': 'execute', 'action': 'list_todos',
                       'arguments': {}, 'message': '这是待办。'}, 0),
            ('记一下报告', self.decision('create_todo', {'title': '报告'}, '记一下报告'), 1),
        ]
        for original, decision, revision_delta in cases:
            with self.subTest(outcome=decision['outcome'], action=decision.get('action')):
                before = self.core.snapshot()
                command = self.command('resolve_intent', {'original_user_message': original})
                self.responses.append(decision)
                first = self.gateway.execute(command, principal='deepseek')
                calls_after_first = len(self.requests)
                self.assertEqual(self.core.snapshot()['revision'], before['revision'] + revision_delta)
                if revision_delta == 0:
                    self.assertEqual(self.core.snapshot(), before)
                self.assertEqual(first['semantic']['message'], decision['message'])
                self.assertNotIn('semantic', self.core.snapshot())
                # Later unrelated writes must not make an identical retry re-resolve intent.
                self.execute('create_todo', {'title': 'Later unrelated item'})
                after = self.core.snapshot()
                restarted = ButlerGateway(TodoCore(self.core.path), self.resolver)
                retry = restarted.execute(command, principal='deepseek')
                self.assertEqual(retry, first)
                self.assertEqual(len(self.requests), calls_after_first)
                self.assertEqual(self.core.snapshot(), after)
    def test_pending_time_question_does_not_block_unrelated_read(self):
        self.natural('明天提醒我交报告', {
            'outcome': 'clarify', 'message': '几点提醒？', 'intent_summary': '明天提醒我交报告'})
        before = self.core.snapshot()
        result = self.natural('看看我的待办', {
            'outcome': 'execute', 'action': 'list_todos', 'arguments': {}, 'message': '这是待办。'})
        self.assertEqual(result['semantic']['outcome'], 'applied')
        self.assertEqual(self.core.snapshot(), before)

    def test_ambiguous_target_asks_once_without_mutating_todos(self):
        self.execute('create_todo', {'title': '交课程报告'})
        self.execute('create_todo', {'title': '交实习报告'})
        before = self.core.snapshot()
        result = self.natural('把报告勾掉', {
            'outcome': 'clarify', 'message': '课程报告还是实习报告？', 'intent_summary': '勾掉报告'})
        self.assertEqual(result['todos'], before['todos'])
        self.assertIsNone(result['current_item_id'])
        self.assertEqual(result['context']['pending_question'], '课程报告还是实习报告？')

    def test_suggestion_is_separate_and_rejects_todo_side_effect_fields(self):
        first = self.execute('create_todo', {'title': 'A'})['todos'][0]['todo_id']
        second = self.execute('create_todo', {'title': 'B'})['todos'][1]['todo_id']
        self.execute('set_current_item', {'todo_id': first})
        before = self.core.snapshot()
        result = self.execute('publish_suggestion', {'text': '不如先做 B，并把 A 勾掉。'})
        self.assertEqual(result['todos'], before['todos'])
        self.assertEqual(result['current_item_id'], first)
        self.assertEqual(result['context']['current_item_id'], first)
        self.assertEqual(len(result['suggestions']), 1)
        after = self.core.snapshot()
        for forbidden in ({'todo_ids': [second, first]}, {'status': 'done'},
                          {'current_item_id': second}, {'action': 'complete_todo'}):
            with self.subTest(forbidden=forbidden), self.assertRaises(ValidationError):
                self.execute('publish_suggestion', {'text': '建议', **forbidden})
        self.assertEqual(self.core.snapshot(), after)
        self.assertEqual(self.requests, [])

    def test_overdue_reminder_and_no_time_item_survive_reads_and_restart(self):
        self.execute('create_todo', {'title': 'Past', 'due_at': '2020-01-01T09:00:00+00:00',
                                     'remind_at': '2020-01-01T08:00:00+00:00'})
        self.execute('create_todo', {'title': 'Someday'})
        before = self.core.snapshot()
        self.execute('list_todos', {})
        restored = TodoCore(self.core.path).snapshot()
        self.assertEqual(restored, before)
        self.assertEqual([todo['status'] for todo in restored['todos']], ['pending', 'pending'])

    def test_structured_calls_bypass_resolver_including_current_item(self):
        todo_id = self.execute('create_todo', {'title': 'Direct'})['todos'][0]['todo_id']
        self.execute('update_todo', {'todo_id': todo_id, 'title': 'Updated'})
        self.execute('reorder_todos', {'todo_ids': [todo_id]})
        self.execute('set_current_item', {'todo_id': todo_id})
        self.assertEqual(self.execute('get_current_item', {})['current_item_id'], todo_id)
        self.execute('complete_todo', {'todo_id': todo_id})
        self.assertEqual(self.requests, [])

    def test_mutation_without_explicit_literal_evidence_is_rejected(self):
        before = self.core.snapshot()
        for explicit, evidence in [(False, '今天好累'), (True, '记一下买咖啡')]:
            with self.subTest(explicit=explicit, evidence=evidence):
                self.assert_error('explicit_intent_required', lambda: self.natural('今天好累', {
                    'outcome': 'execute', 'action': 'create_todo', 'arguments': {'title': '买咖啡'},
                    'message': '已记录。', 'explicit_intent': explicit, 'evidence': evidence}))
        self.assertEqual(self.core.snapshot(), before)

    def test_due_time_does_not_authorize_an_unrequested_reminder(self):
        self.assert_error('explicit_reminder_required', lambda: self.natural('记一下明天下午3点交报告',
            self.decision('create_todo', {'title': '交报告', 'remind_at': '2026-10-12T15:00:00-07:00'},
                '记一下明天下午3点交报告', time_precision='exact', time_expression='3点')))
        self.assertEqual(self.core.snapshot()['revision'], 0)

    def test_provider_failure_and_invalid_output_never_write_or_retry(self):
        failures = [
            (httpx.Response(429, text='private-provider-detail'), 'semantic_provider_error'),
            (httpx.ReadTimeout('private-provider-detail'), 'semantic_resolver_unavailable'),
            (httpx.Response(200, json={'choices': [{'finish_reason': 'length',
                'message': {'content': '{}'}}]}), 'invalid_resolution'),
            ({'outcome': 'noop', 'message': 'No change', 'action': 'delete_todo',
              'arguments': {'todo_id': 'invented'}}, 'invalid_resolution'),
        ]
        before = self.core.snapshot()
        for response, code in failures:
            with self.subTest(code=code):
                self.responses.append(response)
                error = self.assert_error(code, lambda: self.execute(
                    'resolve_intent', {'original_user_message': '记一下报告'}))
                self.assertNotIn('private-provider-detail', str(error))
        self.assertEqual(len(self.requests), len(failures))
        self.assertEqual(self.core.snapshot(), before)


if __name__ == '__main__':
    unittest.main()


