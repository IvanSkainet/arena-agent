"""HTTP handlers for the agent-proposal surface (v4.19.0).

Three endpoints, all under the ``@authed`` gate:

  POST /v1/admin/proposal/submit    (create + kick off apply+test)
  GET  /v1/admin/proposal/status    (read latest state for one id)
  GET  /v1/admin/proposal/list      (recent proposals, newest first)

The actual apply/test pipeline runs in the shared executor so a
long pytest run doesn't block the event loop. Every state
transition writes a JSONL row to the ledger, which is the
single source of truth for the status endpoint. Handlers never
call subprocess directly -- everything git-related lives in
``arena.admin.proposal``.

Isolation: each proposal gets its own git worktree UNDER the
bridge home, NOT the running repo. The bridge process itself
never touches an unmerged patch on disk.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from aiohttp import web

from arena.admin import proposal as _prop
from arena.handler_helpers import authed, err_json, parse_json_body


# The ledger + worktrees + branch are all rooted here so an
# operator can find everything in one place. Default lives under
# BRIDGE_DIR (the repo root, where the running bridge is checked
# out) so paths are relative to the code being modified. When we
# add opt-in for a per-user home in a future release this will
# become configurable via ctx.
def _proposal_home(repo: Path) -> Path:
    return repo / ".arena_proposals"


def _ledger_path(repo: Path) -> Path:
    return _proposal_home(repo) / "proposals.jsonl"


def _pick_pytest_python() -> str:
    """Pick a Python interpreter that has ``pytest`` importable
    (v4.20.0 fix). v4.19.0 hard-coded ``sys.executable`` -- but
    on hosts where the bridge is running under a uv-managed
    Python (PEP 668 externally-managed environment) pytest is
    typically absent from ``sys.executable`` and available from
    a system ``python3`` instead. We try each candidate in order
    until one loads pytest cleanly, falling back to
    ``sys.executable`` so the historical behaviour survives when
    no other interpreter has pytest either. The ledger's
    ``tests_tail`` still records "ModuleNotFoundError" so
    operators see the real reason a proposal failed.
    """
    candidates = ["python3", "/usr/bin/python3", sys.executable or "python3"]
    for py in candidates:
        try:
            r = subprocess.run(
                [py, "-c", "import pytest"],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return py
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return sys.executable or "python3"


def _run_tests_in_worktree(worktree: Path, timeout: int
                           ) -> tuple[int, str]:
    """Run pytest inside the worktree and return
    ``(exit_code, tail_of_output)``. Picks a Python interpreter
    that has pytest via ``_pick_pytest_python()`` -- v4.19.0
    hard-coded ``sys.executable`` and failed on hosts where the
    bridge ran under a uv-managed Python without pytest. Tail
    is capped at 8 KiB so a huge stdout doesn't blow the ledger
    up."""
    py = _pick_pytest_python()
    try:
        proc = subprocess.run(
            [py, "-m", "pytest", "--tb=no", "-q"],
            cwd=str(worktree),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        tail = (e.stdout or b"")[-8000:].decode("utf-8", "replace")
        return -9, tail + "\n[pytest timeout]"
    stdout = proc.stdout or b""
    stderr = proc.stderr or b""
    combined = stdout + b"\n" + stderr
    tail = combined[-8000:].decode("utf-8", "replace")
    return proc.returncode, tail


def _execute_proposal(repo: Path, proposal_home: Path, store: _prop.ProposalStore,
                      p: _prop.Proposal, diff: str, timeout: int) -> None:
    """State-machine driver. Called from a worker thread; must
    only touch the store + the worktree + subprocess -- no
    aiohttp / no event loop calls here."""
    p.state = _prop.STATE_APPLYING
    p.updated_at = time.time()
    store.append(p)

    wt, err = _prop.create_worktree(repo, proposal_home, p.request_id)
    if err is not None or wt is None:
        p.state = _prop.STATE_REJECTED
        p.reason = f"worktree creation failed: {err}"
        p.updated_at = time.time()
        store.append(p)
        return

    try:
        ok, err = _prop.apply_diff(wt, diff)
        if not ok:
            p.state = _prop.STATE_REJECTED
            p.reason = f"patch did not apply: {err}"
            p.updated_at = time.time()
            store.append(p)
            _prop.cleanup_worktree(repo, proposal_home, p.request_id)
            return

        ok, err = _prop.commit_proposal(
            wt, p.title, p.rationale, p.request_id
        )
        if not ok:
            p.state = _prop.STATE_REJECTED
            p.reason = f"commit failed: {err}"
            p.updated_at = time.time()
            store.append(p)
            _prop.cleanup_worktree(repo, proposal_home, p.request_id)
            return

        p.state = _prop.STATE_TESTING
        p.updated_at = time.time()
        store.append(p)

        exit_code, tail = _run_tests_in_worktree(wt, timeout=timeout)
        p.exit_code = exit_code
        p.tests_tail = tail
        p.state = _prop.STATE_PASSED if exit_code == 0 else _prop.STATE_FAILED
        p.updated_at = time.time()
        store.append(p)
    except Exception as e:   # noqa: BLE001
        p.state = _prop.STATE_REJECTED
        p.reason = f"internal error: {e!r}"
        p.updated_at = time.time()
        store.append(p)
    # NB: we DO NOT cleanup_worktree on pass/fail. The worktree
    # is the reviewable artifact -- a human runs ``git worktree
    # list`` on the bridge host to see and inspect. Cleanup only
    # happens on rejected/failed-early paths where the tree is
    # useless anyway.


def make_proposal_handlers(ctx, bridge_dir: Path):
    """Build the three proposal handlers. ``bridge_dir`` is the
    repo root -- passed in explicitly so tests can point at a
    scratch dir without touching the real bridge home."""
    repo = bridge_dir
    proposal_home = _proposal_home(repo)
    store = _prop.ProposalStore(_ledger_path(repo))

    @authed(ctx)
    async def handle_v1_admin_proposal_submit(request: web.Request) -> web.Response:
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            return jerr

        title = str(data.get("title") or "").strip()
        rationale = str(data.get("rationale") or "").strip()
        diff = str(data.get("diff") or "")
        # Optional; default to HEAD. Sanitised: only bare ref
        # names accepted, no ``--`` or shell metacharacters. Any
        # slash-separated ref (e.g. origin/master) refused -- we
        # only branch off local refs the bridge knows about.
        base_ref = str(data.get("base_ref") or "HEAD").strip()
        import re
        if not re.fullmatch(r"[A-Za-z0-9_.\-/]+", base_ref):
            return err_json(ctx, "invalid base_ref (bad chars)", status=400)

        ok, reason = _prop.validate_metadata(title, rationale)
        if not ok:
            return err_json(ctx, f"metadata rejected: {reason}", status=400)

        ok, reason = _prop.validate_diff(diff)
        if not ok:
            # Log the rejection too so the audit trail has it. But
            # we return 400, not 200 with state=rejected -- the
            # request was invalid, no proposal was created.
            ctx.audit({
                "type": "proposal_rejected_preflight",
                "reason": reason,
                "title": title[:120],
                "client": request.remote or "127.0.0.1",
            })
            return err_json(ctx, f"diff rejected: {reason}", status=400)

        request_id = uuid.uuid4().hex
        sha = hashlib.sha256(diff.encode("utf-8", "replace")).hexdigest()
        p = _prop.Proposal(
            request_id=request_id,
            title=title,
            rationale=rationale,
            diff_bytes=len(diff.encode("utf-8", "replace")),
            diff_sha256=sha,
            branch=f"{_prop.BRANCH_PREFIX}{request_id[:8]}",
            state=_prop.STATE_QUEUED,
            client=request.remote or "127.0.0.1",
        )
        store.append(p)
        ctx.audit({
            "type": "proposal_submitted",
            "request_id": request_id,
            "title": title[:120],
            "diff_bytes": p.diff_bytes,
            "diff_sha256": sha,
            "branch": p.branch,
            "client": p.client,
        })

        # Kick off the apply+test pipeline in the shared executor
        # so we can return the request_id immediately -- pytest
        # takes minutes, we can't block the event loop.
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            ctx.executor,
            functools.partial(
                _execute_proposal, repo, proposal_home, store, p,
                diff, timeout=300,   # pytest cap; matches other long ops
            ),
        )

        return ctx.cors_json_response({
            "ok": True,
            "request_id": request_id,
            "state": _prop.STATE_QUEUED,
            "branch": p.branch,
            "diff_sha256": sha,
        })

    @authed(ctx)
    async def handle_v1_admin_proposal_status(request: web.Request) -> web.Response:
        request_id = request.query.get("id", "").strip()
        if not request_id:
            return err_json(ctx, "missing id", status=400)
        loop = asyncio.get_running_loop()
        latest = await loop.run_in_executor(
            ctx.executor, store.load_latest, request_id
        )
        if latest is None:
            return err_json(ctx, "unknown request_id", status=404)
        return ctx.cors_json_response({"ok": True, "proposal": latest})

    @authed(ctx)
    async def handle_v1_admin_proposal_list(request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit", "20"))
        except (TypeError, ValueError):
            limit = 20
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(
            ctx.executor, functools.partial(store.list_recent, limit=limit)
        )
        return ctx.cors_json_response({
            "ok": True, "count": len(rows), "proposals": rows,
        })

    return {
        "proposal_submit": handle_v1_admin_proposal_submit,
        "proposal_status": handle_v1_admin_proposal_status,
        "proposal_list":   handle_v1_admin_proposal_list,
    }


__all__ = ["make_proposal_handlers"]
