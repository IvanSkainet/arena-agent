"""Scenario orchestration for Arena Chat Bridge.

Scenarios are declarative documents that describe a linear
sequence of tool calls. Each step's result is available to
subsequent steps via ``{{ steps.<id>.result.<path> }}`` template
expressions, plus ``{{ env.VAR }}`` and ``{{ now }}`` helpers.

Introduced as its own module in v4.54.0 with a private
``~/.arena/scenarios/`` storage. v4.55.0 moved storage into the
existing mission filesystem — scenarios are now missions with
``template='scenario'``. Same authoring experience, one storage
system, mission.* tools work on scenarios out of the box.

Storage: ``<ARENA_AGENT_HOME>/missions/scenario-<slug>/mission.json``
(default ``<ARENA_AGENT_HOME>`` = ``~/arena-bridge``).
"""
from __future__ import annotations

from arena.scenarios.storage import (
    InvalidScenario,
    ScenarioNotFound,
    parse_scenario_source,
    render_scenario_source,
    validate_name,
)
from arena.scenarios.mission_bridge import (
    SCENARIO_TEMPLATE_ID,
    ScenarioMissionStore,
    resolve_missions_dir,
)
from arena.scenarios.runtime import (
    ScenariosRuntime,
    ScenarioRunResult,
    ScenarioStepResult,
    build_scenarios_runtime,
    derive_scenario_risk,
    render_template,
)

__all__ = [
    # storage (schema validation only)
    "InvalidScenario",
    "ScenarioNotFound",
    "parse_scenario_source",
    "render_scenario_source",
    "validate_name",
    # mission-bridge (physical storage on top of missions dir)
    "ScenarioMissionStore",
    "SCENARIO_TEMPLATE_ID",
    "resolve_missions_dir",
    # runtime
    "ScenariosRuntime",
    "ScenarioRunResult",
    "ScenarioStepResult",
    "build_scenarios_runtime",
    "derive_scenario_risk",
    "render_template",
]
