# SPDX-FileCopyrightText: 2026 Tkkdy
# SPDX-License-Identifier: MIT
"""Validate user-authorized structured exports and report parity without repairing data.

No client database access and no production authority switch is implemented.
"""
from datetime import datetime
from pydantic import Field, field_validator, model_validator
from butler_models import Input, Identifier, Create
from typing import Literal

class ShadowTodo(Input):
    todo_id: Identifier
    title: str = Field(min_length=1, max_length=2000)
    status: Literal['pending', 'done', 'cancelled']
    position: int = Field(ge=0)
    due_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator('title')
    @classmethod
    def title_valid(cls, value):
        return Create.meaningful(value)

    @field_validator('due_at', 'created_at', 'updated_at')
    @classmethod
    def date_valid(cls, value):
        return Create.timestamp(value)

class ShadowSnapshot(Input):
    todos: list[ShadowTodo] = Field(max_length=10000)
    current_item_id: Identifier | None

    @model_validator(mode='after')
    def consistency(self):
        ids = [t.todo_id for t in self.todos]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate IDs')
        if [t.position for t in self.todos] != list(range(len(ids))):
            raise ValueError('export must explicitly contain contiguous ordered positions')
        if self.current_item_id is not None and self.current_item_id not in ids:
            raise ValueError('current item is missing')
        return self

FIELDS = ('title', 'status', 'position', 'due_at', 'created_at', 'updated_at')

def parity(snapshot: ShadowSnapshot, state: dict):
    """Report all requested migration dimensions; never mutate either side."""
    original = snapshot.model_dump()
    expected = {t['todo_id']: t for t in original['todos']}
    actual = {t['todo_id']: t for t in state['todos']}
    differences = []
    if len(expected) != len(actual):
        differences.append({'field': 'count', 'expected': len(expected), 'actual': len(actual)})
    for todo_id in sorted(set(expected) | set(actual)):
        if todo_id not in expected or todo_id not in actual:
            differences.append({'field': 'todo_id', 'todo_id': todo_id,
                                'status': 'extra' if todo_id not in expected else 'missing'})
            continue
        for field in FIELDS:
            if expected[todo_id][field] != actual[todo_id].get(field):
                differences.append({'todo_id': todo_id, 'field': field,
                                    'expected': expected[todo_id][field], 'actual': actual[todo_id].get(field)})
    if original['current_item_id'] != state['current_item_id']:
        differences.append({'field': 'current_item_id', 'expected': original['current_item_id'],
                            'actual': state['current_item_id']})
    return {'match': not differences, 'differences': differences, 'authority': 'shadow',
            'canonical_cutover': False}
