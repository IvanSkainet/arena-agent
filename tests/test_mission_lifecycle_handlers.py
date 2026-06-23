"""Mission family/schedule handler regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import MissionLifecycleHandlerContext  # noqa: E402
from arena.resources.mission_lifecycle_handlers import make_mission_lifecycle_handlers  # noqa: E402



def test_mission_lifecycle_handlers_support_family_and_schedules():
    ctx = MissionLifecycleHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        mission_family_sync=lambda name: {"ok": True, "root": {"id": name}, "members": [], "stats": {"total": 1}},
        mission_schedules_sync=lambda data: {"ok": True, "count": 1, "total": 1, "schedules": [{"id": "sched", "action": data.get("action", "iterate")}]},
        mission_schedule_save_sync=lambda data: {"ok": True, "schedule": {"id": data.get("schedule_id", "sched"), "mission_id": data.get("mission_id", "demo")}},
        mission_schedule_delete_sync=lambda data: {"ok": True, "schedule_id": data.get("schedule_id", "sched")},
        mission_schedule_tick_sync=lambda data: {"ok": True, "executed": 1, "results": [{"schedule": {"id": data.get("schedule_id", "sched")}}]},
    )
    handlers = make_mission_lifecycle_handlers(ctx)

    family_req = make_mocked_request("GET", "/v1/mission/family?name=demo", headers={"Authorization": "Bearer t"})
    family_resp = asyncio.run(handlers.mission_family(family_req))
    family_data = json.loads(family_resp.text)
    assert family_data["ok"] is True
    assert family_data["root"]["id"] == "demo"

    list_req = make_mocked_request("GET", "/v1/mission/schedules?action=iterate", headers={"Authorization": "Bearer t"})
    list_resp = asyncio.run(handlers.mission_schedules(list_req))
    list_data = json.loads(list_resp.text)
    assert list_data["ok"] is True
    assert list_data["schedules"][0]["action"] == "iterate"

    save_req = make_mocked_request("POST", "/v1/mission/schedules", headers={"Authorization": "Bearer t"})

    async def _save_json():
        return {"mission_id": "demo", "action": "iterate", "schedule_id": "sched"}

    save_req.json = _save_json
    save_resp = asyncio.run(handlers.mission_schedules(save_req))
    save_data = json.loads(save_resp.text)
    assert save_data["ok"] is True
    assert save_data["schedule"]["id"] == "sched"

    delete_req = make_mocked_request("DELETE", "/v1/mission/schedules", headers={"Authorization": "Bearer t"})

    async def _delete_json():
        return {"schedule_id": "sched"}

    delete_req.json = _delete_json
    delete_resp = asyncio.run(handlers.mission_schedules(delete_req))
    delete_data = json.loads(delete_resp.text)
    assert delete_data["ok"] is True
    assert delete_data["schedule_id"] == "sched"

    tick_req = make_mocked_request("POST", "/v1/mission/schedules/tick", headers={"Authorization": "Bearer t"})

    async def _tick_json():
        return {"schedule_id": "sched", "force": True}

    tick_req.json = _tick_json
    tick_resp = asyncio.run(handlers.mission_schedules_tick(tick_req))
    tick_data = json.loads(tick_resp.text)
    assert tick_data["ok"] is True
    assert tick_data["executed"] == 1
