"""Adaptive PID Autotuner based on Engineering Cybernetics.

钱学森工程控制论核心原理:
- 自适应控制：根据系统运行状态动态调整控制器参数
- 最优控制：在约束条件下找到最优控制策略
- 系统辨识：通过输入输出数据识别系统特性

This module implements:
1. Ziegler-Nichols autotuning method
2. Relay feedback autotuning
3. Gradient-based parameter optimization
4. Performance-based adaptive tuning
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TuningMethod(Enum):
    """PID tuning method."""
    ZIEGLER_NICHOLS = "ziegler_nichols"
    RELAY_FEEDBACK = "relay_feedback"
    GRADIENT_BASED = "gradient_based"
    PERFORMANCE_ADAPTIVE = "performance_adaptive"


@dataclass
class PIDParameters:
    """PID controller parameters."""
    kp: float = 1.0
    ki: float = 0.1
    kd: float = 0.05
    integral_limit: float = 10.0
    output_min: float = -1.0
    output_max: float = 1.0

    def to_dict(self) -> dict[str, float]:
        return {"kp": self.kp, "ki": self.ki, "kd": self.kd}


@dataclass
class TuningResult:
    """Result of a PID tuning operation."""
    parameters: PIDParameters
    tuning_method: TuningMethod
    performance_score: float
    settling_time: float
    overshoot: float
    steady_state_error: float
    convergence_iterations: int
    recommendations: list[str] = field(default_factory=list)


class ZieglerNicholsTuner:
    """Ziegler-Nichols tuning method.

    齐格勒-尼科尔斯整定法:
    1. 增大Kp直到系统出现等幅振荡
    2. 记录临界增益Ku和振荡周期Pu
    3. 根据公式计算PID参数
    """

    @classmethod
    def tune_pid(cls, critical_gain: float, oscillation_period: float,
                 controller_type: str = "pid") -> PIDParameters:
        if critical_gain <= 0 or oscillation_period <= 0:
            return PIDParameters()

        if controller_type == "pid":
            kp = 0.6 * critical_gain
            ki = (2.0 * kp) / oscillation_period
            kd = (kp * oscillation_period) / 8.0
        elif controller_type == "pi":
            kp = 0.45 * critical_gain
            ki = (1.2 * kp) / oscillation_period
            kd = 0.0
        else:
            kp = 0.5 * critical_gain
            ki = 0.0
            kd = 0.0

        return PIDParameters(kp=kp, ki=ki, kd=kd)


class RelayFeedbackTuner:
    """Relay feedback autotuning.

    继电器反馈自整定:
    通过施加继电器控制输入，使系统产生极限环振荡，
    从振荡幅值和周期提取系统参数。
    """

    def __init__(self, relay_amplitude: float = 1.0):
        self.relay_amplitude = relay_amplitude
        self._output_history: list[float] = []
        self._input_history: list[float] = []
        self._t_start: float | None = None
        self._peak_times: list[float] = []
        self._peak_values: list[float] = []

    def step(self, measurement: float, dt: float = 1.0) -> float:
        self._output_history.append(measurement)

        if len(self._output_history) < 4:
            return 0.0

        relay_output = self._relay_decision()
        self._input_history.append(relay_output)

        self._detect_peaks()

        return relay_output

    def compute_parameters(self) -> PIDParameters | None:
        if len(self._peak_times) < 2 or len(self._peak_values) < 2:
            return None

        oscillation_period = sum(
            self._peak_times[i] - self._peak_times[i - 1]
            for i in range(1, len(self._peak_times))
        ) / (len(self._peak_times) - 1)

        amplitude = sum(abs(v) for v in self._peak_values) / len(self._peak_values)

        if amplitude <= 0 or oscillation_period <= 0:
            return None

        ultimate_gain = (4.0 * self.relay_amplitude) / (math.pi * amplitude)

        return ZieglerNicholsTuner.tune_pid(ultimate_gain, oscillation_period)

    def reset(self) -> None:
        self._output_history = []
        self._input_history = []
        self._t_start = None
        self._peak_times = []
        self._peak_values = []

    def _relay_decision(self) -> float:
        if len(self._output_history) < 2:
            return 0.0
        current = self._output_history[-1]
        if current > 0:
            return -self.relay_amplitude
        return self.relay_amplitude

    def _detect_peaks(self) -> None:
        if len(self._output_history) < 3:
            return

        for i in range(1, len(self._output_history) - 1):
            prev_val = self._output_history[i - 1]
            curr_val = self._output_history[i]
            next_val = self._output_history[i + 1]

            if curr_val > prev_val and curr_val > next_val:
                if self._t_start is None:
                    self._t_start = 0.0
                t = (i - 1) * 1.0
                self._peak_times.append(t)
                self._peak_values.append(curr_val)


class GradientBasedTuner:
    """Gradient-based PID parameter optimization.

    基于梯度的参数优化:
    使用性能指标对PID参数的梯度，通过梯度下降优化参数。
    """

    def __init__(self, learning_rate: float = 0.01, perturbation: float = 0.01):
        self.learning_rate = learning_rate
        self.perturbation = perturbation
        self._current_params = PIDParameters()
        self._best_params = PIDParameters()
        self._best_score = float("inf")
        self._iteration = 0

    def optimize_step(self, performance_score: float,
                      evaluate_params: Callable) -> PIDParameters:
        self._iteration += 1

        if performance_score < self._best_score:
            self._best_score = performance_score
            self._best_params = PIDParameters(**self._current_params.to_dict())

        gradient = self._estimate_gradient(performance_score, evaluate_params)

        self._current_params.kp -= self.learning_rate * gradient["kp"]
        self._current_params.ki -= self.learning_rate * gradient["ki"]
        self._current_params.kd -= self.learning_rate * gradient["kd"]

        self._current_params.kp = max(0.01, min(10.0, self._current_params.kp))
        self._current_params.ki = max(0.0, min(5.0, self._current_params.ki))
        self._current_params.kd = max(0.0, min(2.0, self._current_params.kd))

        decay = 0.995
        self.learning_rate *= decay

        return PIDParameters(**self._current_params.to_dict())

    def _estimate_gradient(self, current_score: float,
                           evaluate_params: Callable) -> dict[str, float]:
        gradient = {}

        for param_name in ["kp", "ki", "kd"]:
            original_value = getattr(self._current_params, param_name)

            perturbed_params = PIDParameters(**self._current_params.to_dict())
            setattr(perturbed_params, param_name, original_value + self.perturbation)

            perturbed_score = evaluate_params(perturbed_params)

            grad = (perturbed_score - current_score) / self.perturbation
            gradient[param_name] = grad

        return gradient

    def get_best_parameters(self) -> PIDParameters:
        return self._best_params

    def reset(self) -> None:
        self._current_params = PIDParameters()
        self._best_params = PIDParameters()
        self._best_score = float("inf")
        self._iteration = 0
        self.learning_rate = 0.01


class AdaptivePIDTuner:
    """Master adaptive PID tuner combining multiple methods.

    自适应PID调参器:
    根据系统运行状态自动选择最佳整定策略。
    """

    def __init__(self):
        self._current_params = PIDParameters()
        self._tuning_history: list[dict[str, Any]] = []
        self._performance_history: list[float] = []
        self._system_type = "unknown"

        self._relay_tuner = RelayFeedbackTuner()
        self._gradient_tuner = GradientBasedTuner()
        self._active_method: TuningMethod = TuningMethod.PERFORMANCE_ADAPTIVE

        self._error_history: list[float] = []
        self._consecutive_oscillations = 0
        self._tuning_cooldown = 0

    def tune(self, error: float, dt: float = 1.0,
             performance_score: float = 0.0) -> PIDParameters:
        self._error_history.append(error)
        if len(self._error_history) > 20:
            self._error_history.pop(0)

        if self._tuning_cooldown > 0:
            self._tuning_cooldown -= 1
            return self._current_params

        self._performance_history.append(performance_score)
        if len(self._performance_history) > 50:
            self._performance_history.pop(0)

        if self._should_switch_method():
            self._switch_tuning_method()

        if self._active_method == TuningMethod.RELAY_FEEDBACK:
            params = self._tune_relay(error, dt)
        elif self._active_method == TuningMethod.GRADIENT_BASED:
            params = self._tune_gradient(performance_score)
        else:
            params = self._tune_adaptive(error, dt)

        if params:
            self._current_params = params

        self._tuning_history.append({
            "timestamp": time.time(),
            "method": self._active_method.value,
            "parameters": self._current_params.to_dict(),
            "error": error,
            "performance": performance_score,
        })

        if len(self._tuning_history) > 100:
            self._tuning_history.pop(0)

        return self._current_params

    def get_parameters(self) -> PIDParameters:
        return PIDParameters(**self._current_params.to_dict())

    def get_tuning_status(self) -> dict[str, Any]:
        return {
            "active_method": self._active_method.value,
            "current_params": self._current_params.to_dict(),
            "tuning_history_size": len(self._tuning_history),
            "avg_performance": (
                sum(self._performance_history) / len(self._performance_history)
                if self._performance_history else 0.0
            ),
            "consecutive_oscillations": self._consecutive_oscillations,
        }

    def _should_switch_method(self) -> bool:
        if len(self._performance_history) < 10:
            return False

        recent = self._performance_history[-10:]
        avg_recent = sum(recent) / len(recent)

        if len(self._performance_history) >= 20:
            older = self._performance_history[-20:-10]
            avg_older = sum(older) / len(older)

            if avg_recent > avg_older * 1.2:
                return True

        oscillation_count = self._count_oscillations()
        if oscillation_count > 5:
            return True

        return False

    def _switch_tuning_method(self) -> None:
        methods = list(TuningMethod)
        methods.remove(self._active_method)

        if self._consecutive_oscillations > 3:
            self._active_method = TuningMethod.RELAY_FEEDBACK
        elif len(self._performance_history) >= 20:
            self._active_method = TuningMethod.GRADIENT_BASED
        else:
            self._active_method = TuningMethod.PERFORMANCE_ADAPTIVE

        self._consecutive_oscillations = 0
        self._tuning_cooldown = 5

    def _tune_relay(self, error: float, dt: float = 1.0) -> PIDParameters | None:
        self._relay_tuner.step(error, dt)
        params = self._relay_tuner.compute_parameters()
        if params:
            self._relay_tuner.reset()
        return params

    def _tune_gradient(self, performance_score: float) -> PIDParameters:
        def evaluate(p: PIDParameters) -> float:
            return abs(1.0 - performance_score)

        return self._gradient_tuner.optimize_step(
            abs(1.0 - performance_score), evaluate
        )

    def _tune_adaptive(self, error: float, dt: float = 1.0) -> PIDParameters:
        error_magnitude = abs(error)
        error_trend = self._compute_error_trend()

        params = PIDParameters(**self._current_params.to_dict())

        if error_magnitude > 0.5:
            params.kp *= 1.1
            params.kd *= 1.05
        elif error_magnitude < 0.1:
            params.ki *= 1.05
            params.kd *= 0.95

        if error_trend > 0.3:
            params.kd *= 1.2
            params.kp *= 0.9
        elif error_trend < -0.3:
            params.ki *= 1.1

        params.kp = max(0.1, min(5.0, params.kp))
        params.ki = max(0.01, min(2.0, params.ki))
        params.kd = max(0.01, min(1.0, params.kd))

        return params

    def _count_oscillations(self) -> int:
        if len(self._error_history) < 4:
            return 0

        direction_changes = 0
        for i in range(2, len(self._error_history)):
            prev_delta = self._error_history[i - 1] - self._error_history[i - 2]
            curr_delta = self._error_history[i] - self._error_history[i - 1]
            if prev_delta * curr_delta < 0:
                direction_changes += 1

        self._consecutive_oscillations = direction_changes
        return direction_changes

    def _compute_error_trend(self) -> float:
        if len(self._error_history) < 3:
            return 0.0

        recent = self._error_history[-5:]
        n = len(recent)
        x_mean = (n - 1) / 2.0
        y_mean = sum(recent) / n

        numerator = sum((i - x_mean) * (recent[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return 0.0

        return numerator / denominator

    def reset(self) -> None:
        self._current_params = PIDParameters()
        self._tuning_history = []
        self._performance_history = []
        self._error_history = []
        self._consecutive_oscillations = 0
        self._tuning_cooldown = 0
        self._relay_tuner.reset()
        self._gradient_tuner.reset()
