# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Narrow Butler commands. Independent of panel fonts and provider chat history."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')]
Revision = Annotated[int, Field(ge=0, strict=True)]
Title = Annotated[str, Field(min_length=1, max_length=2000)]

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Empty(Input):
    pass

class Create(Input):
    title: Title
    due_at: str | None = None
    remind_at: str | None = None

    @field_validator('title')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('title must contain text')
        return value

    @field_validator('due_at', 'remind_at')
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError('due_at requires timezone')
        return value

class TodoTarget(Input):
    todo_id: Identifier

class Update(TodoTarget):
    title: Title | None = None
    status: Literal['pending', 'done', 'cancelled'] | None = None
    due_at: str | None = None
    remind_at: str | None = None

    @model_validator(mode='after')
    def patch(self):
        fields = self.model_fields_set - {'todo_id'}
        if not fields:
            raise ValueError('empty update')
        for name in fields & {'title', 'status'}:
            if getattr(self, name) is None:
                raise ValueError('null title/status not allowed')
        if 'title' in fields:
            Create.meaningful(self.title)
        for name in fields & {'due_at', 'remind_at'}:
            Create.timestamp(getattr(self, name))
        return self

class Reorder(Input):
    todo_ids: list[Identifier] = Field(max_length=10000)

class Current(Input):
    todo_id: Identifier | None

class Pending(Input):
    question: str | None = Field(max_length=500)
    target_todo_id: Identifier | None

    @model_validator(mode='after')
    def paired(self):
        if (self.question is None) != (self.target_todo_id is None):
            raise ValueError('question and target must be set or cleared together')
        if self.question is not None and not self.question.strip():
            raise ValueError('empty question')
        return self

class DeviceText(Input):
    @staticmethod
    def check(value):
        if value is not None and (not value.strip() or not value.isascii() or len(value) > 47):
            raise ValueError('device projection requires nonblank ASCII up to 47 characters')
        return value

class AttentionInput(Input):
    title: str = Field(min_length=1, max_length=47)
    message: str = Field(min_length=1, max_length=47)
    kind: Literal['service', 'agent_result', 'suggestion', 'reminder'] = 'service'
    todo_id: Identifier | None = None

    @field_validator('title', 'message')
    @classmethod
    def device_text(cls, value):
        return DeviceText.check(value)

class InterruptAck(Input):
    event_id: Identifier
    event_revision: int = Field(ge=1, strict=True)

class SuggestionInput(Input):
    device_text: str | None = None

    @field_validator("device_text")
    @classmethod
    def projection(cls, value):
        return DeviceText.check(value)

    text: str = Field(min_length=1, max_length=500)
    expires_at: str | None = None

    @field_validator('text')
    @classmethod
    def nonblank(cls, value):
        return Create.meaningful(value)

    @field_validator('expires_at')
    @classmethod
    def timestamp(cls, value):
        return Create.timestamp(value)

class Clarification(Input):
    question: str = Field(min_length=1, max_length=200)
    target_todo_id: Identifier | None = None
    intent_summary: str = Field(default='', max_length=500)

    @field_validator('question')
    @classmethod
    def nonblank(cls, value):
        return Create.meaningful(value)

class Intent(Input):
    original_user_message: str = Field(min_length=1, max_length=4000)
    source_hint: str | None = Field(default=None, max_length=500)
    conversation_ref: Identifier | None = None

TIBO_ACTIONS = {'show_tibo_page', 'ack_tibo_attention', 'get_tibo_attention'}

SCHEMAS = {
    'show_tibo_page': Empty, 'ack_tibo_attention': InterruptAck, 'get_tibo_attention': Empty,
    'list_todos': Empty, 'get_current_item': Empty, 'get_context': Empty,
    'create_todo': Create, 'update_todo': Update, 'complete_todo': TodoTarget,
    'delete_todo': TodoTarget, 'reorder_todos': Reorder, 'set_current_item': Current,
    'set_pending_question': Pending, 'resolve_intent': Intent,
    'publish_suggestion': SuggestionInput, 'request_clarification': Clarification,
    'publish_attention_event': AttentionInput, 'ack_interrupt': InterruptAck, 'get_dashboard_state': Empty,
}
READS = {'list_todos', 'get_current_item', 'get_context', 'get_dashboard_state', 'get_tibo_attention'}
BRIDGE_ACTIONS = {'publish_attention_event', 'ack_interrupt', 'get_dashboard_state'}

class Command(Input):
    source: Literal['deepseek', 'grok']
    request_id: Identifier
    expected_revision: Revision | None = None
    action: Literal['list_todos', 'get_current_item', 'get_context', 'create_todo',
                    'update_todo', 'complete_todo', 'delete_todo', 'reorder_todos',
                    'set_current_item', 'set_pending_question', 'resolve_intent',
                    'publish_suggestion', 'request_clarification', 'publish_attention_event', 'ack_interrupt', 'get_dashboard_state',
                    'show_tibo_page', 'ack_tibo_attention', 'get_tibo_attention']
    arguments: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_action(self):
        parsed = SCHEMAS[self.action].model_validate(self.arguments)
        self.arguments = parsed.model_dump(exclude_unset=True)
        if self.action not in READS and self.expected_revision is None:
            raise ValueError('expected_revision required for changes or intent resolution')
        return self
