"""Task Object - Stable task representation layer.

Deepened work chain:
  Raw Input -> Intent Parser -> Task Object -> Pipeline -> Execution -> Result
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from minicode.intent_parser import ParsedIntent
from minicode.logging_config import get_logger

logger = get_logger("task_object")


class TaskState(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConstraintType(str, Enum):
    MUST_INCLUDE = "must_include"
    MUST_NOT_MODIFY = "must_not_modify"
    MAX_TOKENS = "max_tokens"
    TIMEOUT = "timeout"
    REQUIRES_REVIEW = "requires_review"
    TEST_REQUIRED = "test_required"
    BACKUP_REQUIRED = "backup_required"


@dataclass
class Constraint:
    type: ConstraintType
    target: str = ""
    value: Any = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "target": self.target,
                "value": self.value, "reason": self.reason}


@dataclass
class ExpectedOutput:
    type: str = ""
    path: str = ""
    format: str = ""
    validation: str = ""
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "path": self.path, "format": self.format,
                "validation": self.validation, "examples": self.examples}


@dataclass
class TaskObject:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    raw_input: str = ""
    parsed_intent: ParsedIntent | None = None
    title: str = ""
    description: str = ""
    goal: str = ""
    relevant_files: list[str] = field(default_factory=list)
    relevant_code: list[str] = field(default_factory=list)
    context_notes: list[str] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    expected_outputs: list[ExpectedOutput] = field(default_factory=list)
    state: TaskState = TaskState.DRAFT
    plan_id: str = ""
    result_summary: str = ""
    error_message: str = ""
    tags: list[str] = field(default_factory=list)
    priority: int = 0
    estimated_effort: str = "moderate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "created_at": self.created_at, "updated_at": self.updated_at,
            "raw_input": self.raw_input,
            "parsed_intent": self.parsed_intent.to_dict() if self.parsed_intent else None,
            "title": self.title, "description": self.description, "goal": self.goal,
            "relevant_files": self.relevant_files, "relevant_code": self.relevant_code,
            "context_notes": self.context_notes,
            "constraints": [c.to_dict() for c in self.constraints],
            "expected_outputs": [o.to_dict() for o in self.expected_outputs],
            "state": self.state.value, "plan_id": self.plan_id,
            "result_summary": self.result_summary, "error_message": self.error_message,
            "tags": self.tags, "priority": self.priority,
            "estimated_effort": self.estimated_effort,
        }

    def add_constraint(self, type: ConstraintType, target: str = "", value: Any = None, reason: str = "") -> None:
        self.constraints.append(Constraint(type=type, target=target, value=value, reason=reason))
        self.updated_at = time.time()

    def add_expected_output(self, type: str, path: str = "", format: str = "", validation: str = "") -> None:
        self.expected_outputs.append(ExpectedOutput(type=type, path=path, format=format, validation=validation))
        self.updated_at = time.time()

    def set_state(self, state: TaskState) -> None:
        self.state = state
        self.updated_at = time.time()

    def is_read_only(self) -> bool:
        return self.parsed_intent.is_read_only() if self.parsed_intent else False

    def requires_write(self) -> bool:
        return not self.is_read_only()


class TaskBuilder:
    def build(self, intent: ParsedIntent, raw_input: str = "") -> TaskObject:
        task = TaskObject(raw_input=raw_input or intent.raw_input, parsed_intent=intent)
        task.title = self._generate_title(intent)
        task.goal = self._generate_goal(intent)
        task.description = self._generate_description(intent)
        task.relevant_files = intent.entities.get("files", [])
        task.estimated_effort = intent.complexity_hint
        task.priority = self._calculate_priority(intent)
        task.tags = [intent.intent_type.value, intent.action_type.value] + intent.keywords[:3]
        self._add_default_constraints(task, intent)
        self._add_expected_outputs(task, intent)
        logger.debug("Built TaskObject %s: %s", task.id, task.title)
        return task

    def _generate_title(self, intent: ParsedIntent) -> str:
        return f"{intent.action_type.value} {intent.intent_type.value}: {' '.join(intent.keywords[:3])}".strip()

    def _generate_goal(self, intent: ParsedIntent) -> str:
        return intent.raw_input[:120]

    def _generate_description(self, intent: ParsedIntent) -> str:
        lines = [f"Intent: {intent.intent_type.value} / {intent.action_type.value}",
                 f"Confidence: {intent.confidence:.2f}"]
        for key in ("files", "functions", "classes"):
            if intent.entities.get(key):
                lines.append(f"{key.capitalize()}: {', '.join(intent.entities[key])}")
        return "\n".join(lines)

    def _calculate_priority(self, intent: ParsedIntent) -> int:
        base = 50
        if intent.intent_type.value in ("debug", "system"):
            base += 20
        if intent.complexity_hint == "complex":
            base += 10
        if intent.confidence < 0.5:
            base -= 10
        return max(0, min(100, base))

    def _add_default_constraints(self, task: TaskObject, intent: ParsedIntent) -> None:
        if intent.is_read_only():
            task.add_constraint(ConstraintType.MUST_NOT_MODIFY, reason="Read-only intent")
        if intent.is_code_related() and intent.action_type.value in ("create", "update"):
            task.add_constraint(ConstraintType.TEST_REQUIRED, reason="Code modification requires tests")
        if intent.action_type.value in ("delete", "update"):
            task.add_constraint(ConstraintType.BACKUP_REQUIRED, reason="Destructive action")

    def _add_expected_outputs(self, task: TaskObject, intent: ParsedIntent) -> None:
        itype, action = intent.intent_type.value, intent.action_type.value
        if itype == "code" and action == "create":
            task.add_expected_output(type="code_block", validation="Valid runnable code")
        elif itype == "debug":
            task.add_expected_output(type="explanation", validation="Identify root cause")
        elif itype == "explain":
            task.add_expected_output(type="explanation", validation="Clear and accurate")
        elif itype == "search":
            task.add_expected_output(type="file_list", validation="Relevant files with context")
        elif itype == "review":
            task.add_expected_output(type="review_comments", validation="Issues with severity")


_builder: TaskBuilder | None = None


def get_task_builder() -> TaskBuilder:
    global _builder
    if _builder is None:
        _builder = TaskBuilder()
    return _builder


def build_task(intent: ParsedIntent, raw_input: str = "") -> TaskObject:
    return get_task_builder().build(intent, raw_input)
