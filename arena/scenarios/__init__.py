"""Scenario orchestration for Arena Chat Bridge.

Scenarios are declarative YAML files that describe a linear
sequence of tool calls. Each step's result is available to
subsequent steps via ``{{ steps.<id>.result.<path> }}`` template
expressions, plus ``{{ env.VAR }}`` and ``{{ now }}`` helpers.

Introduced in v4.54.0 as the backbone for Ivan's "тебе даю
сценарий, а ты его выполняешь" idea. Storage lives at
``$ARENA_SCENARIOS_DIR`` (default ``~/.arena/scenarios/``) —
user-space, not versioned in the bridge repo.

Risk classification for ``scenario.run`` is *derived*: the
runtime scans every step's tool name at run-planning time and
returns the max risk (safe < medium < dangerous). A scenario
that only invokes ``sys.status`` runs as safe; adding a single
``fs.write`` step promotes the whole scenario to dangerous.
This mirrors the Unix "least privilege" idea — a wrapper is
never more permissive than its most permissive contained call.
"""
from __future__ import annotations

from arena.scenarios.storage import (
    ScenariosStorage,
    ScenarioNotFound,
    InvalidScenario,
    resolve_scenarios_dir,
)
from arena.scenarios.runtime import (
    ScenariosRuntime,
    ScenarioRunResult,
    ScenarioStepResult,
    build_scenarios_runtime,
    derive_scenario_risk,
)

__all__ = [
    "ScenariosStorage",
    "ScenarioNotFound",
    "InvalidScenario",
    "resolve_scenarios_dir",
    "ScenariosRuntime",
    "ScenarioRunResult",
    "ScenarioStepResult",
    "build_scenarios_runtime",
    "derive_scenario_risk",
]
