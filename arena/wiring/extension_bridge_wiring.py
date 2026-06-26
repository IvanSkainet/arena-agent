"""Browser chat extension bridge wiring."""
from __future__ import annotations


def build_extension_bridge_registry(env, registry: dict) -> None:
    runtime_ctx = env.ExtensionBridgeRuntimeContext(
        call_tool=env.call_tool,
        audit=env.audit,
    )
    runtime = env.make_extension_bridge_runtime(runtime_ctx)
    registry.update({
        "_extension_bridge_runtime_ctx": runtime_ctx,
        "_extension_bridge_runtime": runtime,
        "_extension_policies_sync": runtime.policies_sync,
        "_extension_preview_sync": runtime.preview_sync,
        "_extension_execute_sync": runtime.execute_sync,
        "_extension_instructions_sync": runtime.instructions_sync,
    })
    handler_ctx = env.ExtensionBridgeHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        policies_sync=registry["_extension_policies_sync"],
        preview_sync=registry["_extension_preview_sync"],
        execute_sync=registry["_extension_execute_sync"],
        instructions_sync=registry["_extension_instructions_sync"],
    )
    handlers = env.make_extension_bridge_handlers(handler_ctx)
    env.export_handler_attrs(registry, handlers, {
        "handle_v1_extension_policies": "policies",
        "handle_v1_extension_preview": "preview",
        "handle_v1_extension_execute": "execute",
        "handle_v1_extension_instructions": "instructions",
    })
    registry.update({"_extension_bridge_handler_ctx": handler_ctx, "_extension_bridge_handlers": handlers})


__all__ = ["build_extension_bridge_registry"]
