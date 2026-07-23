"""Launch/discovery helpers for CDPTabManager.connect()."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.process import _kill_port_processes, launch_browser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tabs_http import list_tabs


class CDPTabManagerConnectLaunchMixin:
    async def _kill_stale_port_processes(self, loop) -> None:
        try:
            killed = await loop.run_in_executor(None, _kill_port_processes, self.port)
            if killed:
                logger.info("[CDPManager] Killed stale processes on port %d: %s", self.port, killed)
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("[CDPManager] Failed to kill stale processes: %s", e)

    async def _list_tabs_safe(self, loop) -> list[dict]:
        try:
            return await loop.run_in_executor(None, list_tabs, self.port)
        except Exception:
            return []

    def _record_existing_tab_diagnostics(self, existing_tabs: list[dict], t0: float) -> None:
        logger.info("[CDPManager] list_tabs=%d tabs (%.1fs)", len(existing_tabs), time.monotonic() - t0)
        self.ws_diagnostics["list_tabs_count"] = len(existing_tabs)
        if not existing_tabs:
            return
        self.ws_diagnostics["tab_ws_urls"] = [t.get("webSocketDebuggerUrl", "NONE")[:60] for t in existing_tabs]
        for i, tab in enumerate(existing_tabs[:5]):
            logger.info(
                "[CDPManager]   raw_tab[%d]: type=%s id=%s wsUrl=%s url=%s",
                i, tab.get("type", "?"), tab.get("id", "?")[:20],
                tab.get("webSocketDebuggerUrl", "NONE")[:60], tab.get("url", "?")[:50],
            )

    def _read_launch_stderr(self, limit: int = 2000) -> tuple[dict, str]:
        launch_diag = getattr(self._browser_proc, "_cdp_launch_diag", {}) if self._browser_proc else {}
        stderr_log = launch_diag.get("stderr_log", "")
        if not stderr_log or not os.path.exists(stderr_log):
            return launch_diag, ""
        try:
            with open(stderr_log, "r") as fh:
                return launch_diag, fh.read().strip()[:limit]
        except Exception:
            return launch_diag, ""

    def _raise_browser_exit(self, prefix: str, stderr_info: str, launch_diag: dict) -> None:
        """Raise ConnectionError with an actionable diagnostic when possible.

        v4.60.20: if diagnose_elevation recognises a known Chromium/Edge
        refusal (e.g. 'running elevated: 1'), the message includes the
        full hint so the user sees the workaround inline. Otherwise we
        fall back to the original behaviour (raw stderr).
        """
        rc = self._browser_proc.returncode if self._browser_proc else None
        logger.error("[CDPManager] %s (rc=%s) stderr=%s", prefix, rc, stderr_info[:300])
        try:
            from arena.browser.diagnose_elevation import diagnose_browser_exit
            diag = diagnose_browser_exit(
                return_code=rc or 0,
                stdout="",
                stderr=stderr_info,
            )
        except Exception as _e:  # pragma: no cover (defensive)
            diag = None
        extra = ""
        if diag is not None:
            extra = "\n\nDiagnostic: " + diag["content"][0]["text"]
        raise ConnectionError(
            f"{prefix} (rc={rc}). stderr: {stderr_info[:500] or '(empty)'}. "
            f"Launch diag: {launch_diag}{extra}"
        )

    async def _launch_if_needed(self, existing_tabs: list[dict], loop, t0: float) -> list[dict]:
        if existing_tabs or not self.auto_launch:
            return existing_tabs
        logger.info("[CDPManager] Launching browser via executor...")
        self._browser_proc = await loop.run_in_executor(None, launch_browser, self.port, self.headless)
        logger.info("[CDPManager] launch_browser returned (%.1fs)", time.monotonic() - t0)
        await asyncio.sleep(1)
        if self._browser_proc and self._browser_proc.poll() is not None:
            diag, stderr_info = self._read_launch_stderr()
            self._raise_browser_exit("Browser process exited", stderr_info, diag)

        for attempt in range(40):
            existing_tabs = await self._list_tabs_safe(loop)
            if existing_tabs:
                logger.info("[CDPManager] Port ready! %d tab(s) after %.1fs", len(existing_tabs), (attempt + 1) * 0.5)
                return existing_tabs
            if self._browser_proc and self._browser_proc.poll() is not None:
                diag, stderr_info = self._read_launch_stderr()
                self._raise_browser_exit("Browser crashed during startup", stderr_info, diag)
            await asyncio.sleep(0.5)

        diag, stderr_info = self._read_launch_stderr()
        is_alive = self._browser_proc and self._browser_proc.poll() is None
        logger.error("[CDPManager] Port NOT ready after 20s. alive=%s stderr=%s diag=%s", is_alive, stderr_info[:200], diag)
        if is_alive:
            raise ConnectionError(
                f"Browser is running (pid={self._browser_proc.pid}) but debug port {self.port} "
                f"is not responding after 20 seconds. stderr: {stderr_info[:300] or '(empty)'}. Launch diag: {diag}"
            )
        raise ConnectionError(
            f"Browser exited and debug port {self.port} never became ready. "
            f"stderr: {stderr_info[:300] or '(empty)'}. Launch diag: {diag}"
        )

    async def _connect_browser_level_events(self, t0: float) -> None:
        logger.info("[CDPManager] Connecting browser-level WebSocket (%.1fs)...", time.monotonic() - t0)
        await self._connect_browser_ws()
        ws_connected = self._browser_ws is not None and not self._browser_ws.closed
        self.ws_diagnostics["browser_ws_connected"] = ws_connected
        if ws_connected:
            logger.info("[CDPManager] Browser-level WS connected (%.1fs)", time.monotonic() - t0)
        else:
            logger.warning("[CDPManager] Browser-level WS NOT connected (tab events disabled) (%.1fs)", time.monotonic() - t0)

    def _register_existing_tabs(self, existing_tabs: list[dict]) -> None:
        logger.info("[CDPManager] Discovering tabs from %d entries...", len(existing_tabs))
        if not self.auto_discover_existing:
            return
        for info in existing_tabs:
            target_id = info.get("id", "")
            tab_type = info.get("type", "?")
            ws_url = info.get("webSocketDebuggerUrl", "")
            tab_url = info.get("url", "")
            logger.info("[CDPManager]   tab: type=%s id=%s ws=%s url=%s", tab_type, target_id[:20] or "?", ws_url[:50] or "NONE", tab_url[:50])
            if tab_type != "page" or not target_id or target_id in self._tabs:
                continue
            if not ws_url:
                ws_url = f"ws://127.0.0.1:{self.port}/devtools/page/{target_id}"
                self.ws_diagnostics.setdefault("constructed_ws_urls", []).append(ws_url)
            self._tabs[target_id] = CDPTab(target_id=target_id, ws_url=ws_url, port=self.port,
                                           timeout=self.timeout, title=info.get("title", ""), url=tab_url)
            if self._active_tab_id is None:
                self._active_tab_id = target_id
