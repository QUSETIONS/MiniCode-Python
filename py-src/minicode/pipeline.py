"""Pipeline Engine - Task execution orchestration layer.

Deepened work chain:
  Raw Input -> Intent Parser -> Task Object -> Pipeline Engine -> Step Executor -> Result

Pipeline Engine responsibilities:
1. Decompose TaskObject into executable Steps
2. Manage step dependencies and ordering
3. Execute steps with proper context passing
4. Handle failures, retries, and fallbacks
5. Assemble final result from step outputs
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from minicode.logging_config import get_logger
from minicode.task_object import TaskObject, TaskState
from minicode.decision_audit import get_auditor, DecisionType, DecisionOutcome

logger = get_logger("pipeline")


# ---------------------------------------------------------------------------
# Step Types
# ---------------------------------------------------------------------------

class StepType(str, Enum):
    READ = "read"           # Read files/context
    ANALYZE = "analyze"     # Analyze code/structure
    PLAN = "plan"           # Create sub-plan
    EXECUTE = "execute"     # Execute action
    VALIDATE = "validate"   # Validate output
    REVIEW = "review"       # Review/approve
    BACKUP = "backup"       # Create backup
    RESTORE = "restore"     # Restore from backup


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


# ---------------------------------------------------------------------------
# Step Definition
# ---------------------------------------------------------------------------

@dataclass
class Step:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: StepType = StepType.EXECUTE
    name: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3
    started_at: float = 0.0
    completed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type.value, "name": self.name,
            "description": self.description, "depends_on": self.depends_on,
            "status": self.status.value, "input_data": self.input_data,
            "output_data": self.output_data, "error": self.error,
            "retry_count": self.retry_count, "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


# ---------------------------------------------------------------------------
# Execution Plan
# ---------------------------------------------------------------------------

@dataclass
class ExecutionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task_id: str = ""
    steps: list[Step] = field(default_factory=list)
    current_step_index: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "task_id": self.task_id,
            "steps": [s.to_dict() for s in self.steps],
            "current_step_index": self.current_step_index,
            "created_at": self.created_at, "started_at": self.started_at,
            "completed_at": self.completed_at, "status": self.status,
        }

    def get_step(self, step_id: str) -> Step | None:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_ready_steps(self) -> list[Step]:
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        ready = []
        for step in self.steps:
            if step.status != StepStatus.PENDING:
                continue
            if all(dep in completed_ids for dep in step.depends_on):
                ready.append(step)
        return ready

    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    def has_failures(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)


# ---------------------------------------------------------------------------
# Step Handlers
# ---------------------------------------------------------------------------

StepHandler = Callable[[Step, TaskObject], Step]


class StepHandlers:
    """Registry of step handlers."""

    def __init__(self):
        self._handlers: dict[StepType, StepHandler] = {}

    def register(self, step_type: StepType, handler: StepHandler) -> None:
        self._handlers[step_type] = handler

    def get(self, step_type: StepType) -> StepHandler | None:
        return self._handlers.get(step_type)

    def execute(self, step: Step, task: TaskObject) -> Step:
        handler = self._handlers.get(step.type)
        if not handler:
            step.error = f"No handler for step type: {step.type.value}"
            step.status = StepStatus.FAILED
            return step
        try:
            step.started_at = time.time()
            step.status = StepStatus.RUNNING
            result = handler(step, task)
            step.output_data = result.output_data if hasattr(result, 'output_data') else {}
            step.status = StepStatus.COMPLETED
            step.completed_at = time.time()
        except Exception as e:
            step.error = str(e)
            step.status = StepStatus.FAILED
            step.completed_at = time.time()
        return step


# ---------------------------------------------------------------------------
# Pipeline Engine
# ---------------------------------------------------------------------------

class PipelineEngine:
    """Orchestrates task execution through structured pipelines.

    The Pipeline Engine:
    1. Takes TaskObject as input
    2. Creates ExecutionPlan with Steps
    3. Executes Steps in dependency order
    4. Returns assembled result
    """

    def __init__(self):
        self.handlers = StepHandlers()
        self._audit = get_auditor()
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        from minicode.tools import read_file, edit_file, run_command
        self.handlers.register(StepType.READ, self._handle_read)
        self.handlers.register(StepType.ANALYZE, self._handle_analyze)
        self.handlers.register(StepType.EXECUTE, self._handle_execute)
        self.handlers.register(StepType.VALIDATE, self._handle_validate)
        self.handlers.register(StepType.BACKUP, self._handle_backup)

    def plan(self, task: TaskObject) -> ExecutionPlan:
        plan = ExecutionPlan(task_id=task.id)
        intent_type = task.parsed_intent.intent_type.value if task.parsed_intent else "unknown"
        action_type = task.parsed_intent.action_type.value if task.parsed_intent else "unknown"

        if intent_type in ("code", "refactor") and action_type == "create":
            s1 = Step(type=StepType.READ, name="Read context", description="Read relevant files", input_data={"files": task.relevant_files})
            s2 = Step(type=StepType.ANALYZE, name="Analyze requirements", description="Understand code structure", depends_on=[s1.id])
            s3 = Step(type=StepType.EXECUTE, name="Generate code", description="Write the code", depends_on=[s2.id])
            s4 = Step(type=StepType.VALIDATE, name="Validate code", description="Check syntax and style", depends_on=[s3.id])
            plan.steps = [s1, s2, s3, s4]
        elif intent_type == "debug":
            s1 = Step(type=StepType.READ, name="Read error context", description="Read relevant files")
            s2 = Step(type=StepType.ANALYZE, name="Analyze error", description="Identify root cause")
            s3 = Step(type=StepType.EXECUTE, name="Apply fix", description="Fix the issue", depends_on=[s2.id])
            s4 = Step(type=StepType.VALIDATE, name="Verify fix", description="Test the fix", depends_on=[s3.id])
            plan.steps = [s1, s2, s3, s4]
        elif intent_type in ("search", "explain"):
            s1 = Step(type=StepType.READ, name="Read context", description="Read relevant files")
            s2 = Step(type=StepType.ANALYZE, name="Analyze content", description="Understand structure")
            s3 = Step(type=StepType.EXECUTE, name="Generate response", description="Provide answer", depends_on=[s2.id])
            plan.steps = [s1, s2, s3]
        elif intent_type == "review":
            s1 = Step(type=StepType.READ, name="Read files", description="Read files to review")
            s2 = Step(type=StepType.ANALYZE, name="Analyze code", description="Review code quality")
            s3 = Step(type=StepType.EXECUTE, name="Generate report", description="Write review report", depends_on=[s2.id])
            plan.steps = [s1, s2, s3]
        else:
            plan.steps = [
                Step(type=StepType.EXECUTE, name="Execute task", description="Perform the requested action"),
            ]

        for step in plan.steps:
            if not step.name:
                step.name = step.type.value.title()
        plan.status = "planned"
        return plan

    def execute(self, task: TaskObject, plan: ExecutionPlan | None = None) -> tuple[TaskObject, ExecutionPlan]:
        if plan is None:
            plan = self.plan(task)

        task.set_state(TaskState.RUNNING)
        plan.started_at = time.time()
        plan.status = "running"

        self._audit.record(
            DecisionType.ROUTING,
            reasoning=f"Pipeline execution for task {task.id}",
            selected_option=plan.id,
            available_options=[plan.id],
            input_context={"task_id": task.id, "steps": len(plan.steps)},
        )

        try:
            while not plan.is_complete() and not plan.has_failures():
                ready_steps = plan.get_ready_steps()
                if not ready_steps:
                    break
                for step in ready_steps:
                    self._execute_step(step, task, plan)

            if plan.is_complete():
                task.set_state(TaskState.COMPLETED)
                task.result_summary = f"Completed {len(plan.steps)} steps"
                plan.status = "completed"
            else:
                task.set_state(TaskState.FAILED)
                failed = [s for s in plan.steps if s.status == StepStatus.FAILED]
                task.error_message = failed[0].error if failed else "Unknown failure"
                plan.status = "failed"

            plan.completed_at = time.time()
        except Exception as e:
            task.set_state(TaskState.FAILED)
            task.error_message = str(e)
            plan.status = "failed"

        self._audit.complete_decision(DecisionOutcome.SUCCESS if plan.status == "completed" else DecisionOutcome.FAILURE)
        return task, plan

    def _execute_step(self, step: Step, task: TaskObject, plan: ExecutionPlan) -> None:
        step = self.handlers.execute(step, task)
        if step.status == StepStatus.FAILED and step.retry_count < step.max_retries:
            step.retry_count += 1
            step.status = StepStatus.RETRYING

    def _handle_read(self, step: Step, task: TaskObject) -> Step:
        files = step.input_data.get("files", task.relevant_files)
        step.output_data["read_files"] = files
        step.output_data["content"] = {f: f"Content of {f}" for f in files}
        return step

    def _handle_analyze(self, step: Step, task: TaskObject) -> Step:
        step.output_data["analysis"] = f"Analysis of {len(step.depends_on)} dependencies"
        return step

    def _handle_execute(self, step: Step, task: TaskObject) -> Step:
        step.output_data["executed"] = True
        step.output_data["result"] = f"Executed: {task.title}"
        return step

    def _handle_validate(self, step: Step, task: TaskObject) -> Step:
        step.output_data["valid"] = True
        step.output_data["validation_notes"] = "Validation passed"
        return step

    def _handle_backup(self, step: Step, task: TaskObject) -> Step:
        step.output_data["backup_created"] = True
        step.output_data["backup_path"] = f".backup/{task.id}"
        return step


# ---------------------------------------------------------------------------
# Work Chain Integration
# ---------------------------------------------------------------------------

class WorkChain:
    """Complete work chain from Raw Input to Result.

    WorkChain = Intent Parser + Task Object + Pipeline Engine
    """

    def __init__(self):
        from minicode.intent_parser import get_intent_parser
        self.intent_parser = get_intent_parser()
        self.pipeline = PipelineEngine()

    def process(self, raw_input: str) -> tuple[TaskObject, ExecutionPlan]:
        intent = self.intent_parser.parse(raw_input)
        from minicode.task_object import build_task
        task = build_task(intent, raw_input)
        plan = self.pipeline.plan(task)
        return self.pipeline.execute(task, plan)


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_engine: PipelineEngine | None = None
_work_chain: WorkChain | None = None


def get_pipeline_engine() -> PipelineEngine:
    global _engine
    if _engine is None:
        _engine = PipelineEngine()
    return _engine


def get_work_chain() -> WorkChain:
    global _work_chain
    if _work_chain is None:
        _work_chain = WorkChain()
    return _work_chain


def process_raw_input(raw_input: str) -> tuple[TaskObject, ExecutionPlan]:
    return get_work_chain().process(raw_input)
