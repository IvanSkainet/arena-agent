#!/usr/bin/env python3
"""Live Windows contract between Arena Bridge and The Book of Eternity: Reborn.

The game owns ConPTY hosting, prompt dispatch, and the file protocol. Arena owns
its HTTP relay and the persistent ``arena-relay terminal`` adapter. This harness
starts both real implementations and proves their transport contract without
copying game rules into Arena.
"""
from __future__ import annotations

import argparse
import http.client
import importlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

PROTOCOL_REVISION = "boe-gm-terminal-relay-v1"
EXPECTED_DISPATCH_COUNT = 3
STARTUP_TIMEOUT_SECONDS = 45.0
DISPATCH_TIMEOUT_SECONDS = 75.0


class ContractFailure(RuntimeError):
    """Raised when an observable cross-repository invariant fails."""


@dataclass(frozen=True)
class DispatchSpec:
    kind: str
    session_id: str
    request_id: str
    turn_number: int
    prompt: str


class BridgeHttp:
    def __init__(self, port: int, token: str) -> None:
        self.port = port
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float = 35.0,
    ) -> dict[str, Any]:
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Connection": "close",
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            connection.request(method, path, body=payload, headers=headers)
            response = connection.getresponse()
            raw = response.read()
        finally:
            connection.close()
        try:
            decoded = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ContractFailure(
                f"bridge returned non-JSON HTTP {response.status} for {path}"
            ) from exc
        if response.status != 200 or not isinstance(decoded, dict) or not decoded.get("ok"):
            raise ContractFailure(
                f"bridge request failed: {method} {path} -> {response.status}: {decoded}"
            )
        return decoded


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ContractFailure(f"expected JSON object: {path}")
    return value


def _tail(path: Path, limit: int = 8_000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _wait_until(description: str, predicate, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:  # noqa: BLE001 - retry an external boundary
            last_error = exc
        time.sleep(0.2)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise ContractFailure(f"timed out waiting for {description}{suffix}")


def _powershell() -> str:
    for candidate in ("powershell.exe", "pwsh.exe"):
        try:
            probe = subprocess.run(
                [candidate, "-NoLogo", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if probe.returncode == 0:
            return candidate
    raise ContractFailure("PowerShell is required for the game control script")


def _powershell_literal(value: str) -> str:
    """Quote one literal for the PowerShell command hosted by the game bridge."""
    return "'" + value.replace("'", "''") + "'"


def _run_control(
    powershell: str,
    control_script: Path,
    session: Path,
    action: str,
    *,
    environment: dict[str, str],
    prompt_path: Path | None = None,
    timeout: float = 30.0,
) -> str:
    env = dict(environment)
    env["BOE_CONTRACT_CONTROL"] = str(control_script)
    env["BOE_CONTRACT_SESSION"] = str(session)
    if prompt_path is None:
        command = (
            "& $env:BOE_CONTRACT_CONTROL "
            + action
            + " -SessionPath $env:BOE_CONTRACT_SESSION"
        )
    else:
        env["BOE_CONTRACT_PROMPT"] = str(prompt_path)
        command = (
            "$prompt=[IO.File]::ReadAllText($env:BOE_CONTRACT_PROMPT,"
            "[Text.Encoding]::UTF8); "
            "& $env:BOE_CONTRACT_CONTROL dispatchPrompt $prompt "
            "-SessionPath $env:BOE_CONTRACT_SESSION"
        )
    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise ContractFailure(
            f"game control action {action!r} failed with {result.returncode}: "
            f"{(result.stderr + result.stdout)[-3000:]}"
        )
    return result.stdout.strip()


def _control_json(*args, **kwargs) -> dict[str, Any]:
    output = _run_control(*args, **kwargs)
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ContractFailure(f"game control returned non-JSON: {output[-2000:]}") from exc
    if not isinstance(value, dict) or value.get("ok") is False:
        raise ContractFailure(f"game control returned failure: {value}")
    return value


def _dispatches() -> list[DispatchSpec]:
    first_body = "A" * 2_048
    second_body = "Б" * 1_024
    return [
        DispatchSpec(
            kind="turn",
            session_id="boe-contract-session",
            request_id="boe-contract-turn-1",
            turn_number=101,
            prompt=(
                "Process Book of Eternity turn #101 contract\n"
                "sessionId: boe-contract-session\n"
                "requestId: boe-contract-turn-1\n"
                "Read input/turn_request.json.\n"
                "Reply through the correlated Arena relay message.\n"
                f"Multiline payload A:\n{first_body}"
            ),
        ),
        DispatchSpec(
            kind="turn",
            session_id="boe-contract-session",
            request_id="boe-contract-turn-2",
            turn_number=102,
            prompt=(
                "Process Book of Eternity turn #102 contract\n"
                "sessionId: boe-contract-session\n"
                "requestId: boe-contract-turn-2\n"
                "This is the second consecutive ConPTY dispatch.\n"
                f"Multiline payload B:\n{second_body}"
            ),
        ),
        DispatchSpec(
            kind="repair",
            session_id="boe-contract-session",
            request_id="boe-contract-turn-2",
            turn_number=102,
            prompt=(
                "VALIDATION REPAIR MODE for turn #102\n"
                "sessionId: boe-contract-session\n"
                "requestId: boe-contract-turn-2\n"
                "turnNumber: 102\n"
                "Read game_state/control/validation_repair_request.json.\n"
                "Fix only the requested artifact and complete the repair protocol."
            ),
        ),
    ]


def _install_artifact_package(arena_root: Path) -> ModuleType:
    sys.path.insert(0, str(arena_root))
    module = importlib.import_module("arena.game.boe_relay")
    module_file = module.__file__
    if module_file is None:
        raise ContractFailure("boe_relay module has no filesystem origin")
    module_path = Path(module_file).resolve()
    try:
        module_path.relative_to(arena_root.resolve())
    except ValueError as exc:
        raise ContractFailure(
            f"boe_relay loaded outside extracted artifact: {module_path}"
        ) from exc
    return module


def _start_agent(
    client: BridgeHttp,
    session: Path,
    dispatches: list[DispatchSpec],
    boe_relay,
    records: list[dict[str, Any]],
    completed: list[threading.Event],
    errors: list[str],
) -> threading.Thread:
    def run() -> None:
        try:
            for index, expected in enumerate(dispatches, start=1):
                response = client.request(
                    "GET",
                    "/v1/relay/poll?wait=25",
                    timeout=35,
                )
                message = response.get("message")
                if not isinstance(message, dict):
                    raise ContractFailure(f"agent poll {index} returned no message")
                body = message.get("body")
                meta = message.get("meta")
                if body != expected.prompt:
                    raise ContractFailure(f"dispatch {index} body changed across ConPTY")
                if not isinstance(meta, dict) or meta != {
                    "transport": "terminal",
                    "source": "boe-cross-repo-ci",
                    "sequence": index,
                }:
                    raise ContractFailure(f"dispatch {index} metadata mismatch: {meta}")

                if expected.kind == "repair":
                    terminal = boe_relay.repair_ready(
                        session,
                        session_id=expected.session_id,
                        request_id=expected.request_id,
                        turn_number=expected.turn_number,
                    )
                else:
                    terminal = boe_relay.complete_turn(
                        session,
                        session_id=expected.session_id,
                        request_id=expected.request_id,
                        turn_number=expected.turn_number,
                        files_modified=["output/narrative_response.json"],
                    )

                message_id = str(message.get("id") or "")
                reply = client.request(
                    "POST",
                    "/v1/relay/reply",
                    {
                        "in_reply_to": message_id,
                        "body": (
                            f"contract reply sequence={index} "
                            f"requestId={expected.request_id}"
                        ),
                        "sender": "boe-contract-agent",
                    },
                )
                records.append(
                    {
                        "sequence": index,
                        "kind": expected.kind,
                        "requestId": expected.request_id,
                        "turnNumber": expected.turn_number,
                        "promptCharacters": len(expected.prompt),
                        "promptUtf8Bytes": len(expected.prompt.encode("utf-8")),
                        "messageId": message_id,
                        "replyId": str(reply.get("id") or ""),
                        "terminalStatus": terminal.get("status"),
                    }
                )
                completed[index - 1].set()
        except Exception as exc:  # noqa: BLE001 - preserve thread failure
            errors.append(str(exc))
            for event in completed:
                event.set()

    thread = threading.Thread(target=run, name="boe-contract-agent", daemon=True)
    thread.start()
    return thread


def _prepare_request(session: Path, dispatch: DispatchSpec) -> None:
    if dispatch.kind == "repair":
        _write_json(
            session / "game_state" / "control" / "validation_repair_request.json",
            {
                "sessionId": dispatch.session_id,
                "requestId": dispatch.request_id,
                "turnNumber": dispatch.turn_number,
                "metadataDiagnosticOnly": False,
                "errors": [
                    {
                        "code": "narrative_response_unknown_field",
                        "path": "output/narrative_response.json.extra",
                    }
                ],
            },
        )
        return
    _write_json(
        session / "input" / "turn_request.json",
        {
            "sessionId": dispatch.session_id,
            "requestId": dispatch.request_id,
            "turnNumber": dispatch.turn_number,
            "playerAction": "Cross-repository transport contract probe",
        },
    )


def _assert_correlated_signal(session: Path, dispatch: DispatchSpec) -> dict[str, Any]:
    path = (
        session / "game_state" / "control" / "validation_repair_ready.json"
        if dispatch.kind == "repair"
        else session / "ready" / "turn_complete.json"
    )
    value = _read_json(path)
    expected = {
        "sessionId": dispatch.session_id,
        "requestId": dispatch.request_id,
        "turnNumber": dispatch.turn_number,
        "status": "success",
    }
    for key, wanted in expected.items():
        if value.get(key) != wanted:
            raise ContractFailure(f"{path.name} correlation mismatch for {key}: {value}")
    return {key: value[key] for key in expected}


def _wait_for_terminal_ready(
    powershell: str,
    control_script: Path,
    session: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    last_value: dict[str, Any] | None = None

    def probe() -> dict[str, Any] | None:
        nonlocal last_value
        value = _control_json(
            powershell,
            control_script,
            session,
            "diagnostics",
            environment=environment,
            timeout=10,
        )
        last_value = value
        status = value.get("status") or {}
        diagnostics = value.get("diagnostics") or {}
        output = str(diagnostics.get("recentOutputTail") or "")
        if status.get("ready") and "Arena Terminal Relay" in output:
            return value
        return None

    try:
        return _wait_until("Arena terminal relay READY state", probe, STARTUP_TIMEOUT_SECONDS)
    except ContractFailure as exc:
        value = last_value or {}
        status = value.get("status") or {}
        diagnostics = value.get("diagnostics") or {}
        summary = {
            key: status.get(key)
            for key in ("state", "ready", "lastError", "shellPid", "cliProcessId")
        }
        output = str(diagnostics.get("recentOutputTail") or "")[-2_000:]
        raise ContractFailure(
            f"{exc}; status={json.dumps(summary, ensure_ascii=False)}; "
            f"recentOutputTail={output!r}"
        ) from exc


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    command = (
        f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) "
        "{ exit 0 } else { exit 1 }"
    )
    result = subprocess.run(
        [_powershell(), "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        timeout=10,
    )
    return result.returncode == 0


def run_contract(args: argparse.Namespace) -> int:
    if os.name != "nt":
        raise ContractFailure("the live ConPTY contract must run on Windows")

    arena_root = args.arena_root.resolve()
    game_root = args.game_root.resolve()
    evidence_path = args.evidence_out.resolve()
    control_script = game_root / "BookOfEternityClient" / "Launcher" / "bookofeternity.ps1"
    server_script = arena_root / "unified_bridge.py"
    terminal_script = arena_root / "bin" / "arena-relay"
    for required in (control_script, server_script, terminal_script):
        if not required.is_file():
            raise ContractFailure(f"required contract artifact is missing: {required}")

    evidence: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "running",
        "protocolRevision": PROTOCOL_REVISION,
        "arenaCommit": args.arena_commit,
        "gameRepository": args.game_repository,
        "gameCommit": args.game_commit,
        "dispatches": [],
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    token = "boe-contract-" + secrets.token_urlsafe(24)
    port = _free_port()
    powershell = _powershell()
    temp = Path(tempfile.mkdtemp(prefix="boe-cross-repo-"))
    session = temp / "game_session"
    server_log = temp / "bridge-server.log"
    status_path = session / "game_state" / "control" / "gm_bridge_status.json"
    environment = dict(os.environ)
    environment.update(
        {
            "ARENA_TOKEN": token,
            "ARENA_BRIDGE_URL": f"http://127.0.0.1:{port}",
            "PYTHONUTF8": "1",
        }
    )

    server: subprocess.Popen[str] | None = None
    server_log_handle = None
    agent: threading.Thread | None = None
    helper_pids: list[int] = []
    status: dict[str, Any] = {}
    diagnostics: dict[str, Any] = {}
    shutdown: dict[str, Any] = {}
    bridge_shutdown = False
    primary_error: Exception | None = None
    cleanup_errors: list[str] = []

    def record_diagnostics(value: dict[str, Any]) -> None:
        diagnostic_status = value.get("status") or {}
        diagnostic_body = value.get("diagnostics") or {}
        recent_output = str(diagnostic_body.get("recentOutputTail") or "")
        evidence["gmBridge"] = {
            "helperPid": diagnostic_status.get("helperPid") or status.get("helperPid"),
            "shellPid": diagnostic_status.get("shellPid") or status.get("shellPid"),
            "state": diagnostic_status.get("state"),
            "ready": diagnostic_status.get("ready"),
            "lastError": diagnostic_status.get("lastError"),
            "lastOutputVersion": diagnostic_body.get("outputVersion"),
            "recentOutputTail": recent_output.replace(token, "<redacted>")[-3_000:],
        }

    try:
        boe_relay = _install_artifact_package(arena_root)
        from arena.constants import VERSION  # noqa: PLC0415

        evidence["arenaVersion"] = VERSION
        session.mkdir()
        server_log_handle = server_log.open("w", encoding="utf-8")
        launch_command = (
            f"& {_powershell_literal(sys.executable)} "
            f"{_powershell_literal(str(terminal_script))} "
            f"--url http://127.0.0.1:{port} terminal "
            "--sender boe-game-daemon --source boe-cross-repo-ci "
            "--reply-timeout 60"
        )
        _write_json(
            session / "config.json",
            {
                "GmBridgeEnabled": True,
                "GmBridgeBackend": "ConPTYBridge",
                "GmCliLaunchCommand": launch_command,
                "GmBridgeShellWorkingDirectory": str(session),
                "GmBridgeAutoStart": False,
                "GmBridgePipeNameOverride": "boe-contract-" + secrets.token_hex(8),
                "GmWorkerBridgeProfiles": [],
            },
        )

        server = subprocess.Popen(
            [
                sys.executable,
                str(server_script),
                "serve",
                "--bind",
                "127.0.0.1",
                "--port",
                str(port),
                "--token",
                token,
                "--root",
                str(temp / "bridge-root"),
            ],
            cwd=arena_root,
            stdout=server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        client = BridgeHttp(port, token)

        def healthy() -> bool:
            if server is not None and server.poll() is not None:
                raise ContractFailure(
                    f"Arena Bridge exited during startup: {_tail(server_log)}"
                )
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                connection.request("GET", "/health")
                response = connection.getresponse()
                value = json.loads(response.read())
                return response.status == 200 and value.get("ok") is True
            finally:
                connection.close()

        _wait_until("Arena Bridge health", healthy, STARTUP_TIMEOUT_SECONDS)

        dispatches = _dispatches()
        records: list[dict[str, Any]] = []
        completed = [threading.Event() for _ in dispatches]
        agent_errors: list[str] = []
        agent = _start_agent(
            client,
            session,
            dispatches,
            boe_relay,
            records,
            completed,
            agent_errors,
        )

        _run_control(
            powershell,
            control_script,
            session,
            "start-bridge",
            environment=environment,
            timeout=30,
        )
        status = _wait_until(
            "GM bridge status file",
            lambda: _read_json(status_path) if status_path.exists() else None,
            STARTUP_TIMEOUT_SECONDS,
        )
        helper_pids = [
            int(value)
            for value in (status.get("helperPid"), status.get("shellPid"))
            if isinstance(value, int) and value > 0
        ]
        _control_json(
            powershell,
            control_script,
            session,
            "ready",
            environment=environment,
        )
        diagnostics = _wait_for_terminal_ready(
            powershell,
            control_script,
            session,
            environment,
        )

        signals: list[dict[str, Any]] = []
        for index, dispatch in enumerate(dispatches):
            _prepare_request(session, dispatch)
            prompt_path = temp / f"prompt-{index + 1}.txt"
            prompt_path.write_text(dispatch.prompt, encoding="utf-8")
            _run_control(
                powershell,
                control_script,
                session,
                "dispatchPrompt",
                environment=environment,
                prompt_path=prompt_path,
                timeout=DISPATCH_TIMEOUT_SECONDS,
            )
            if not completed[index].wait(DISPATCH_TIMEOUT_SECONDS):
                raise ContractFailure(f"agent did not complete dispatch {index + 1}")
            if agent_errors:
                raise ContractFailure(agent_errors[0])
            signals.append(_assert_correlated_signal(session, dispatch))
            diagnostics = _wait_for_terminal_ready(
                powershell,
                control_script,
                session,
                environment,
            )

        agent.join(timeout=10)
        if agent.is_alive():
            raise ContractFailure("agent consumer did not exit after three dispatches")
        if len(records) != EXPECTED_DISPATCH_COUNT:
            raise ContractFailure(f"expected three dispatch records, got {len(records)}")

        relay_status = client.request("GET", "/v1/relay/status")
        if relay_status.get("inbox_depth") != 0 or relay_status.get("reply_depth") != 0:
            raise ContractFailure(f"relay mailbox did not drain: {relay_status}")

        leftovers = [
            str(path.relative_to(session))
            for path in session.rglob("*")
            if path.is_file()
            and (path.name.endswith(".partial") or path.name.startswith(".tmp_boe_"))
        ]
        if leftovers:
            raise ContractFailure(f"atomic temporary files survived: {leftovers}")

        diagnostics = _control_json(
            powershell,
            control_script,
            session,
            "diagnostics",
            environment=environment,
        )
        shutdown = _control_json(
            powershell,
            control_script,
            session,
            "shutdown-bridge",
            environment=environment,
            timeout=45,
        )
        remaining = list(shutdown.get("remainingProcessIds") or [])
        if remaining:
            raise ContractFailure(f"GM bridge left processes alive: {remaining}")
        for pid in helper_pids:
            _wait_until(
                f"GM bridge process {pid} exit",
                lambda pid=pid: not _process_exists(pid),
                15,
            )
        bridge_shutdown = True

        record_diagnostics(diagnostics)
        evidence["gmBridge"].update(
            {
                "shutdownStatus": shutdown.get("status"),
                "remainingProcessIds": remaining,
            }
        )
        if server_log_handle is not None:
            server_log_handle.flush()
        evidence.update(
            {
                "status": "success",
                "dispatches": records,
                "terminalSignals": signals,
                "mailbox": {
                    "inboxDepth": relay_status["inbox_depth"],
                    "replyDepth": relay_status["reply_depth"],
                },
                "atomicTemporaryFiles": leftovers,
                "bridgeLogTail": _tail(server_log, 4_000),
            }
        )
    except Exception as exc:  # noqa: BLE001 - preserve exact live failure
        primary_error = exc
        evidence["status"] = "failure"
        evidence["error"] = str(exc).replace(token, "<redacted>")[-4_000:]
        if status_path.exists():
            try:
                diagnostics = _control_json(
                    powershell,
                    control_script,
                    session,
                    "diagnostics",
                    environment=environment,
                    timeout=15,
                )
                record_diagnostics(diagnostics)
            except Exception as diagnostic_exc:  # noqa: BLE001 - bounded evidence only
                evidence["gmBridge"] = {
                    "helperPid": status.get("helperPid"),
                    "shellPid": status.get("shellPid"),
                    "diagnosticsError": str(diagnostic_exc).replace(token, "<redacted>")[-1_000:],
                }
    finally:
        if not bridge_shutdown and status_path.exists():
            try:
                shutdown = _control_json(
                    powershell,
                    control_script,
                    session,
                    "shutdown-bridge",
                    environment=environment,
                    timeout=45,
                )
                remaining = list(shutdown.get("remainingProcessIds") or [])
                if remaining:
                    cleanup_errors.append(
                        f"GM bridge cleanup left processes alive: {remaining}"
                    )
                else:
                    bridge_shutdown = True
                gm_bridge = evidence.setdefault("gmBridge", {})
                gm_bridge["shutdownStatus"] = shutdown.get("status")
                gm_bridge["remainingProcessIds"] = remaining
            except Exception as cleanup_exc:  # noqa: BLE001 - report after all cleanup
                cleanup_errors.append(
                    "GM bridge shutdown failed: "
                    + str(cleanup_exc).replace(token, "<redacted>")[-1_000:]
                )

        for pid in helper_pids:
            try:
                _wait_until(
                    f"GM bridge process {pid} exit",
                    lambda pid=pid: not _process_exists(pid),
                    15,
                )
            except ContractFailure as cleanup_exc:
                cleanup_errors.append(str(cleanup_exc))

        if server is not None and server.poll() is None:
            try:
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired) as cleanup_exc:
                cleanup_errors.append(f"Arena Bridge shutdown failed: {cleanup_exc}")
        evidence["arenaBridge"] = {
            "processId": server.pid if server is not None else None,
            "shutdown": server is None or server.poll() is not None,
        }
        if not evidence["arenaBridge"]["shutdown"]:
            cleanup_errors.append("Arena Bridge server process survived shutdown")

        if server_log_handle is not None:
            server_log_handle.flush()
        evidence["bridgeLogTail"] = _tail(server_log, 4_000).replace(token, "<redacted>")
        if server_log_handle is not None:
            server_log_handle.close()
        if agent is not None and agent.is_alive():
            agent.join(timeout=10)
        agent_stopped = agent is None or not agent.is_alive()
        if not agent_stopped:
            cleanup_errors.append("synthetic agent consumer thread survived shutdown")

        removal_error: OSError | None = None
        for attempt in range(20):
            try:
                shutil.rmtree(temp)
                removal_error = None
                break
            except FileNotFoundError:
                removal_error = None
                break
            except OSError as exc:
                removal_error = exc
                if attempt < 19:
                    time.sleep(0.25)
        if removal_error is not None:
            cleanup_errors.append(f"temporary workspace cleanup failed: {removal_error}")

        evidence["cleanup"] = {
            "agentConsumerStopped": agent_stopped,
            "temporaryDirectoryRemoved": not temp.exists(),
            "errors": cleanup_errors,
        }
        if cleanup_errors and primary_error is None:
            primary_error = ContractFailure("; ".join(cleanup_errors))
            evidence["status"] = "failure"
            evidence["error"] = str(primary_error)[-4_000:]
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if primary_error is not None:
        raise primary_error
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena-root", type=Path, required=True)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--arena-commit", required=True)
    parser.add_argument("--game-repository", required=True)
    parser.add_argument("--game-commit", required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run_contract(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
