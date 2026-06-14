"""Handlers for non-CDP browser endpoints and high-level browser routing."""
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import BrowserBrowseHandlerContext, BrowserFetchHandlerContext


@dataclass(frozen=True)
class BrowserFetchHandlers:
    search: object
    read: object
    dump: object
    fetch: object
    head: object


@dataclass(frozen=True)
class BrowserBrowseHandlers:
    browse: object


def make_browser_fetch_handlers(ctx: BrowserFetchHandlerContext) -> BrowserFetchHandlers:
    async def handle_v1_browser_search(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        qs = parse_qs(request.query_string)
        query = qs.get("q", [""])[0]
        try:
            n = int(qs.get("n", ["5"])[0])
        except ValueError:
            n = 5
        if not query:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.browser_search_sync, query, n)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    def make_url_handler(sync_fn, missing_error: str):
        async def handler(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            qs = parse_qs(request.query_string)
            url = qs.get("url", [""])[0]
            if not url:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": missing_error}, status=400)
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(ctx.executor, sync_fn, url)
                return ctx.cors_json_response(result)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)
        return handler

    return BrowserFetchHandlers(
        search=handle_v1_browser_search,
        read=make_url_handler(ctx.browser_read_sync, "missing url parameter"),
        dump=make_url_handler(ctx.browser_dump_sync, "missing url parameter"),
        fetch=make_url_handler(ctx.browser_fetch_sync, "missing url parameter"),
        head=make_url_handler(ctx.browser_head_sync, "missing url parameter"),
    )


def make_browser_browse_handlers(ctx: BrowserBrowseHandlerContext) -> BrowserBrowseHandlers:
    async def handle_v1_browser_browse(request: web.Request) -> web.Response:
        """POST /v1/browser/browse — unified browser endpoint with auto backend switching.

        Automatically selects the best browser backend:
        - If stealth=true or captcha=true: use BrowserAct (Camoufox-based, anti-detection)
        - Otherwise: use CDP (headless Chromium, faster)
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        url = body.get("url")
        if not url:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)

        action = body.get("action", "extract")
        stealth = body.get("stealth", False)
        captcha = body.get("captcha", False)
        wait_for = body.get("wait_for")
        timeout = body.get("timeout", 15)
        width = body.get("width", 1280)
        height = body.get("height", 720)

        # Auto-switch logic: BrowserAct for stealth/captcha, CDP for everything else.
        use_browseract = stealth or captcha

        if use_browseract:
            try:
                ba_skill = Path(ctx.app_dir) / "skills" / "browseract" / "run.sh"
                if not ba_skill.exists():
                    ctx.record_request(is_error=True, count_request=False)
                    return ctx.cors_json_response({"ok": False, "error": "BrowserAct skill not installed"}, status=503)

                cmd = [shutil.which("bash") or "bash", str(ba_skill), action, url]
                if wait_for:
                    cmd.extend(["--wait-for", wait_for])
                if action == "shot":
                    cmd.extend(["--width", str(width), "--height", str(height)])

                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)

                if proc.returncode == 0 and stdout:
                    try:
                        result = json.loads(stdout.decode("utf-8", errors="replace"))
                        result["backend"] = "browseract"
                        result["stealth"] = True
                        return ctx.cors_json_response(result)
                    except json.JSONDecodeError:
                        text = stdout.decode("utf-8", errors="replace")
                        return ctx.cors_json_response({"ok": True, "backend": "browseract", "stealth": True, "output": text[:50000]})

                err = stderr.decode("utf-8", errors="replace")[:2000] if stderr else "unknown error"
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"BrowserAct failed (rc={proc.returncode}): {err}"}, status=500)
            except asyncio.TimeoutError:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"BrowserAct timed out ({timeout}s)"}, status=408)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

        # Use CDP (headless Chromium — faster).
        cdp_state = ctx.cdp_state
        if not cdp_state["connected"]:
            try:
                cdp = ctx.get_cdp_module()
                if cdp:
                    mgr = cdp.CDPTabManager(
                        port=cdp_state["port"],
                        headless=cdp_state["headless"],
                        auto_launch=True,
                    )
                    await asyncio.wait_for(mgr.connect(), timeout=60)
                    cdp_state["manager"] = mgr
                    cdp_state["connected"] = True
                    cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                    ctx.start_cdp_watcher()
                else:
                    ctx.record_request(is_error=True, count_request=False)
                    return ctx.cors_json_response({"ok": False, "error": "CDP module not available"}, status=503)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"CDP auto-connect failed: {e}"}, status=503)

        mgr = cdp_state.get("manager")
        if not mgr or not mgr.active_tab or not mgr.active_tab.connected:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "No active CDP tab"}, status=503)

        try:
            if action == "extract":
                browser = mgr.active_tab._browser
                await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
                if wait_for:
                    safe_selector = json.dumps(wait_for)
                    expr = (
                        "new Promise((resolve, reject) => { const check = () => { "
                        f"if (document.querySelector({safe_selector})) resolve(true); "
                        "else setTimeout(check, 200); }; "
                        f"setTimeout(() => reject('timeout'), {(timeout - 2) * 1000}); check(); }})"
                    )
                    await asyncio.wait_for(browser.eval_js(expr), timeout=timeout)
                text_content = await asyncio.wait_for(
                    browser.eval_js("document.body ? document.body.innerText.substring(0, 50000) : ''"),
                    timeout=10,
                )
                title = await asyncio.wait_for(browser.eval_js("document.title"), timeout=5)
                return ctx.cors_json_response({
                    "ok": True,
                    "backend": "cdp",
                    "stealth": False,
                    "url": url,
                    "title": title,
                    "text": (text_content or "")[:20000],
                    "text_len": len(text_content or ""),
                })

            if action == "shot":
                browser = mgr.active_tab._browser
                await asyncio.wait_for(
                    browser.send(
                        "Emulation.setDeviceMetricsOverride",
                        {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
                    ),
                    timeout=5,
                )
                await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
                res = await asyncio.wait_for(browser.send("Page.captureScreenshot", {"format": "png"}), timeout=15)
                if res and "result" in res and "data" in res["result"]:
                    return ctx.cors_json_response({
                        "ok": True,
                        "backend": "cdp",
                        "stealth": False,
                        "format": "png",
                        "data": res["result"]["data"],
                        "width": width,
                        "height": height,
                    })

                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)

            if action == "click":
                selector = body.get("selector")
                if not selector:
                    return ctx.cors_json_response({"ok": False, "error": "missing 'selector' for click action"}, status=400)
                await asyncio.wait_for(mgr.active_tab.click(selector), timeout=timeout)
                return ctx.cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "click", "selector": selector})

            if action == "type":
                selector = body.get("selector")
                text = body.get("text")
                if not selector or not text:
                    return ctx.cors_json_response({"ok": False, "error": "missing 'selector' and 'text' for type action"}, status=400)
                await asyncio.wait_for(mgr.active_tab.type_text(selector, text), timeout=timeout)
                return ctx.cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "type", "selector": selector})

            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Unknown action: {action}. Supported: extract, shot, click, type"}, status=400)

        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"CDP {action} timed out ({timeout}s)"}, status=408)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return BrowserBrowseHandlers(browse=handle_v1_browser_browse)
