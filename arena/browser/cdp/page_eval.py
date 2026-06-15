"""CDP page eval handler."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpPageHandlerContext


def make_cdp_eval_handler(ctx: CdpPageHandlerContext):
    async def handle_v1_cdp_eval(request):
        """POST /v1/browser/cdp/eval — Evaluate JavaScript.

        Body JSON:
            expression: string (required)
            tab_id: string (optional)
            timeout: number (optional, default: 14) — CDP-level timeout in seconds (max 60)

        v2.3.0: Added 15s hard timeout to prevent system freezes from
        infinite JS loops or huge DOM serialization. Results >1MB are
        truncated to prevent OOM.
        v2.5.1: Configurable timeout, better error messages for heavy eval,
                and explicit `ok: false` with reason when JS throws.
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        expression = body.get("expression")
        if not expression:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'expression' parameter"}, status=400)

        # v2.5.1: Allow caller to specify a longer timeout for heavy computations
        cdp_timeout = min(body.get("timeout", 14), 60)  # Cap at 60s
        asyncio_timeout = cdp_timeout + 1

        tab_id = body.get("tab_id")
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err

        try:
            # v2.5.1: Use CDP Runtime.evaluate directly so we can distinguish
            # between JS exceptions and transport-level failures.
            eval_result = await asyncio.wait_for(
                tab.send("Runtime.evaluate", {
                    "expression": expression,
                    "returnByValue": True,
                    "timeout": cdp_timeout * 1000,  # CDP expects ms
                }),
                timeout=asyncio_timeout
            )

            if eval_result and "result" in eval_result:
                inner = eval_result["result"]
                # Check for JS exception
                if "exceptionDetails" in inner:
                    exc = inner["exceptionDetails"]
                    exc_text = ""
                    if "exception" in exc and "description" in exc["exception"]:
                        exc_text = exc["exception"]["description"]
                    elif "text" in exc:
                        exc_text = exc["text"]
                    ctx.log_warning("[CDP] eval JS exception: %s", exc_text)
                    return ctx.cors_json_response({
                        "ok": False,
                        "error": f"JavaScript exception: {exc_text}",
                        "exception_details": exc,
                    }, status=400)

                # Successful evaluation
                result_val = inner.get("result", {}).get("value")
                # Convert to string for consistency with eval_js behavior
                if result_val is not None:
                    result_str = str(result_val) if not isinstance(result_val, str) else result_val
                else:
                    result_str = None

                # v2.3.0: Truncate large results to prevent OOM / response bloat
                CDP_EVAL_MAX_RESULT = 1 * 1024 * 1024  # 1MB
                truncated = False
                if isinstance(result_str, str) and len(result_str) > CDP_EVAL_MAX_RESULT:
                    original_len = len(result_str)
                    result_str = result_str[:CDP_EVAL_MAX_RESULT] + f"\n...[truncated, {original_len} total chars]"
                    truncated = True
                    ctx.log_warning("[CDP] eval result truncated: %d -> %d chars", original_len, CDP_EVAL_MAX_RESULT)

                return ctx.cors_json_response({
                    "ok": True,
                    "result": result_str,
                    "truncated": truncated,
                    "tab_id": tab.target_id,
                })

            # v2.5.1: CDP returned no result — likely WebSocket issue
            ctx.log_warning("[CDP] eval returned no result — possible WS issue")
            return ctx.cors_json_response({
                "ok": False,
                "error": "CDP returned empty result — WebSocket may be stale. Try reconnecting.",
            }, status=502)

        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] eval_js timed out (%ds) — expression: %.200s", asyncio_timeout, expression)
            return ctx.cors_json_response(
                {"ok": False, "error": f"JavaScript evaluation timed out ({cdp_timeout}s limit). "
                 "The expression may contain an infinite loop or heavy computation. "
                 "Try a shorter expression or increase the 'timeout' parameter.",
                 "timeout": cdp_timeout},
                status=408
            )
        except ConnectionError as e:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] eval connection error: %s", e)
            return ctx.cors_json_response(
                {"ok": False, "error": f"CDP connection lost during eval: {e}. Try reconnecting."},
                status=502
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)



    return handle_v1_cdp_eval
