"""Additional mission family and schedule wiring."""
from __future__ import annotations

from arena.resources.mission_schedule_runtime import tick_mission_schedules_runtime



def build_mission_lifecycle_registry(env, registry: dict) -> None:
    rr = env._resource_runtime

    def _mission_schedule_tick_sync(data: dict):
        return tick_mission_schedules_runtime(
            env.ROOT_AGENT / "mission_schedules",
            data,
            run_sync=rr.mission_run_sync,
            rerun_sync=rr.mission_rerun_sync,
            iterate_sync=registry["_mission_iterate_sync"],
        )

    registry.update({
        "_mission_family_sync": rr.mission_family_sync,
        "_mission_schedules_sync": rr.mission_schedules_sync,
        "_mission_schedule_save_sync": rr.mission_schedule_save_sync,
        "_mission_schedule_delete_sync": rr.mission_schedule_delete_sync,
        "_mission_schedule_tick_sync": _mission_schedule_tick_sync,
    })
    ctx = env.MissionLifecycleHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        mission_family_sync=registry["_mission_family_sync"],
        mission_schedules_sync=registry["_mission_schedules_sync"],
        mission_schedule_save_sync=registry["_mission_schedule_save_sync"],
        mission_schedule_delete_sync=registry["_mission_schedule_delete_sync"],
        mission_schedule_tick_sync=registry["_mission_schedule_tick_sync"],
    )
    handlers = env.make_mission_lifecycle_handlers(ctx)
    env.export_handler_attrs(registry, handlers, {
        "handle_v1_mission_family": "mission_family",
        "handle_v1_mission_schedules": "mission_schedules",
        "handle_v1_mission_schedules_tick": "mission_schedules_tick",
    })
    registry.update({"_mission_lifecycle_handler_ctx": ctx, "_mission_lifecycle_handlers": handlers})


__all__ = ["build_mission_lifecycle_registry"]
