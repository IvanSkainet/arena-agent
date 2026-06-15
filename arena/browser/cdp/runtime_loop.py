"""CDP event-loop blockage detector."""
from __future__ import annotations

import asyncio
import logging
import time

from arena.browser.cdp.state import CDP_LOOP_CHECK_INTERVAL, _cdp_loop_healthy_ts

log = logging.getLogger("arena-bridge")


async def _cdp_loop_blockage_detector():
    """Detect when the asyncio event loop is blocked for too long (v2.3.0).

    Uses a simple liveness pattern: schedule a callback from the event loop
    and measure how long it actually takes to run. If the loop is blocked
    (e.g., by a hanging CDP operation), the callback will be delayed.
    Logs a CRITICAL warning if blocked > threshold seconds.
    """
    global _cdp_loop_healthy_ts
    while True:
        try:
            loop = asyncio.get_running_loop()
            start = time.monotonic()

            fut = loop.create_future()
            loop.call_soon(lambda: fut.set_result(None) if not fut.done() else None)
            await asyncio.wait_for(fut, timeout=5.0)

            delay = time.monotonic() - start
            _cdp_loop_healthy_ts = time.time()

            if delay > 2.0:
                log.warning("[CDP-LoopCheck] Event loop delayed %.2fs (threshold: 2s)", delay)

        except asyncio.TimeoutError:
            blocked_for = time.time() - _cdp_loop_healthy_ts
            log.critical(
                "[CDP-LoopCheck] EVENT LOOP APPEARS BLOCKED for %.1fs! "
                "This likely indicates a hanging CDP operation. "
                "Last healthy: %.1fs ago",
                blocked_for, time.time() - _cdp_loop_healthy_ts
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("[CDP-LoopCheck] Unexpected error: %s", e)

        await asyncio.sleep(CDP_LOOP_CHECK_INTERVAL)
