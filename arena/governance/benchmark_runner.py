"""T74: explicit, single-run pytest measurement; never a replacement CI gate."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import signal
import stat
import subprocess
import sys
import tempfile
import time

# nosemgrep: use-defused-xml -- own pytest UTF-8 report; read_junit rejects DTD/ENTITY declarations before parsing
import xml.etree.ElementTree as element_tree  # nosec B405 -- own pytest UTF-8 report, DTD/ENTITY rejected by read_junit
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import current_thread, main_thread
from typing import IO

from coverage.exceptions import CoverageException

ROOT = Path(__file__).resolve().parents[2]


def fingerprint(root: Path) -> dict[str, str]:
    """Include tracked and unignored new files, not the environment or Git config."""
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True, timeout=30,
    )
    return {
        name: source_digest(root, name)
        for name in sorted(set(listing.stdout.decode().split("\0")))
        if name
    }


def source_digest(root: Path, name: str) -> str:
    """Hash content and source identity; never silently omit a Git entry."""
    path = root / name
    info = path.lstat()  # A deleted tracked entry invalidates the inventory.
    metadata: dict[str, object] = {"mode": stat.S_IMODE(info.st_mode)}
    if stat.S_ISLNK(info.st_mode):
        try:
            resolved = path.resolve()  # path.stat below also rejects dangling targets.
        except RuntimeError as error:  # pathlib on Python 3.10–3.12
            raise ValueError("source symlink cannot be resolved") from error
        if root not in resolved.parents:
            raise ValueError("source symlink escapes the checkout")
        metadata["target"] = os.readlink(path)
        info = path.stat()
        metadata["target_mode"] = stat.S_IMODE(info.st_mode)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("source inventory contains a non-file entry")
    # Keys are inserted in canonical mode/target/target_mode order.
    header = json.dumps(metadata).encode("utf-8")
    return hashlib.sha256(header + b"\0" + path.read_bytes()).hexdigest()


def junit_case(case: element_tree.Element) -> dict:
    """Decode one report item without coupling it to suite counter validation."""
    outcome = "passed"
    reason = ""
    for tag in ("error", "failure", "skipped"):
        node = case.find(tag)
        if node is not None:
            outcome = tag
            reason = node.get("message", "")
            break
    seconds = float(case.get("time", "0"))
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("JUnit duration must be finite and nonnegative")
    return {"id": [case.get("classname", ""), case.get("name", "")],
            "outcome": outcome, "reason": reason, "seconds": seconds}


def read_report_xml(path: Path) -> element_tree.Element:
    """Parse only UTF-8 reports without any DTD or entity declarations."""
    text = path.read_text(encoding="utf-8")
    if not text:
        raise ValueError("XML report is empty")
    reject_junit_declarations(text)
    return element_tree.fromstring(text)  # nosec B314 -- UTF-8 only; DTD/ENTITY declarations rejected above


def read_junit(path: Path) -> dict:
    cases, declared = junit_inventory(read_report_xml(path))
    # pytest-subtests contributes to summary counters without emitting a new
    # testcase element. Preserve both counts; never equate them silently.
    return {"cases": cases, "count": len(cases),
            "declared_tests": sum(declared) if declared else None}


def reject_junit_declarations(text: str) -> None:
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("JUnit declarations are not allowed")


def junit_inventory(root: element_tree.Element) -> tuple[list[dict], list[int]]:
    cases = [junit_case(case) for case in root.iter("testcase")]
    if not cases:
        raise ValueError("JUnit contains no cases")
    declared = [int(s.attrib["tests"]) for s in root.iter("testsuite") if "tests" in s.attrib]
    if declared and sum(declared) < len(cases):
        raise ValueError("JUnit counters contradict the case inventory")
    return cases, declared


def read_coverage(path: Path) -> dict:
    # Read actual recorded arcs, not rounded percentages alone.
    from coverage import CoverageData

    if not path.is_file():
        raise ValueError("coverage database missing")
    data = CoverageData(basename=str(path))
    data.read()
    if not data.has_arcs():
        raise ValueError("branch coverage missing")
    files = {name: coverage_file(data, name) for name in sorted(data.measured_files())}
    if not files:
        raise ValueError("coverage contains no measured files")
    return files


def coverage_file(data, name: str) -> dict:
    """Normalize one file's optional coverage arrays without rounding arcs."""
    return {"lines": sorted(data.lines(name) or []), "arcs": sorted(data.arcs(name) or [])}


def require_coverage_xml(path: Path) -> None:
    """A completed measurement must retain a readable nonempty XML report."""
    root = read_report_xml(path)
    if root.tag != "coverage":
        raise ValueError("coverage XML has an invalid root")


def save(path: Path, result: dict) -> None:
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(result, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    except BaseException:
        # os.open succeeded exclusively: only this invocation owns this temp.
        temporary.unlink(missing_ok=True)
        raise


def private_evidence(output: Path) -> None:
    """Finalize retained evidence permissions without following source links."""
    for path in output.rglob("*"):
        kind = path.lstat().st_mode
        if stat.S_ISLNK(kind):
            raise ValueError("evidence contains a symlink")
        path.chmod(0o700 if stat.S_ISDIR(kind) else 0o600)


def cpu_seconds() -> float | None:
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        return usage.ru_utime + usage.ru_stime
    except ImportError:  # Windows: no fabricated cross-platform metric
        return None


def command(mode: str, seed: int, output: Path, runner: str) -> list[str]:
    argv = [sys.executable, "-m", "pytest", "-q", "-p",
            "arena.governance.pytest_execution_guard", f"--randomly-seed={seed}",
            f"--cov-fail-under={51 if runner == 'Linux' else 46}",
            f"--junitxml={output / 'junit.xml'}", "--cov-report=term",
            f"--cov-report=xml:{output / 'coverage.xml'}",
            f"--cov-config={output / 'coverage.toml'}"]
    if mode == "n2":
        argv += ["-n", "2", "--max-worker-restart=0"]
    else:
        argv += ["-p", "no:xdist"]
    return argv


def wait_unreaped(pid: int, timeout: float | None) -> None:
    """Observe exit without releasing the PID/PGID ownership reservation."""
    started = time.monotonic()
    while os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
        if timeout is not None and time.monotonic() - started >= timeout:
            raise subprocess.TimeoutExpired(str(pid), timeout)
        time.sleep(0.02)


def signal_group(pid: int, sig: signal.Signals) -> None:
    """Signal a still-owned group; an already-empty group is harmless."""
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


@contextmanager
def defer_cancellation():
    """Finish group teardown before delivering another process cancellation."""
    pending = []
    previous = {}

    def remember(signum, frame):
        pending.append(signum)

    if current_thread() is main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, remember)
    try:
        yield
    finally:
        restore_cancellation(previous, pending)


def restore_cancellation(previous: dict, pending: list) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, handler)
    if not pending:
        return
    sig = pending[0]
    handler = previous[sig]
    if callable(handler):
        handler(sig, None)
    elif handler == signal.SIG_DFL:
        signal.raise_signal(sig)


def live_group_member(pid: int) -> bool:
    """Linux procfs distinguishes live descendants from the reserved zombie leader."""
    for entry in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = entry.read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) == pid and fields[0] not in {"Z", "X"}:
                return True
        except (OSError, ValueError, IndexError):
            # A process may disappear while scanning; never signal it by PID.
            continue
    return False


def wait_group_grace(pid: int, deadline: float) -> None:
    while time.monotonic() < deadline and live_group_member(pid):
        time.sleep(0.02)


def cleanup_owned_process(proc: subprocess.Popen) -> int:
    # A zombie leader still reserves its PID. Never reap it before the last
    # group signal: an unrelated group could otherwise reuse that number.
    # ECHILD means ownership was lost: propagate, without signaling that PGID.
    with defer_cancellation():
        os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        deadline = time.monotonic() + 5
        signal_group(proc.pid, signal.SIGTERM)
        try:
            wait_unreaped(proc.pid, 5)
        except subprocess.TimeoutExpired:
            pass
        wait_group_grace(proc.pid, deadline)
        signal_group(proc.pid, signal.SIGKILL)
        return proc.wait()


@dataclass(frozen=True)
class ProcessContext:
    """The explicit checkout and child environment for one owned invocation."""

    root: Path
    env: dict[str, str]

    def start(self, argv: list[str], log: IO | None) -> subprocess.Popen:
        return subprocess.Popen(argv, cwd=self.root, env=self.env, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)


def execute(argv: list[str], *, context: ProcessContext, log, timeout: float | None) -> int:
    """Own a Linux process group until cleanup, including on interruption."""
    proc = None
    try:
        # Publish the child handle before a pending cancellation is delivered.
        with defer_cancellation():
            proc = context.start(argv, log)
        wait_unreaped(proc.pid, timeout)
        with defer_cancellation():
            return cleanup_owned_process(proc)
    except BaseException:
        if proc is not None and getattr(proc, "returncode", None) is None:
            try:
                cleanup_owned_process(proc)
            except KeyboardInterrupt:
                pass  # Teardown finished; preserve the original cancellation.
        raise


def write_coverage_config(root: Path, output: Path) -> None:
    # Snapshot all existing coverage options, changing only the top-level
    # invocation's data destination. COVERAGE_FILE would leak into nested
    # pytest contract subprocesses and mix their statement/branch databases.
    config = (root / "pyproject.toml").read_text(encoding="utf-8")
    marker = "[tool.coverage.run]\n"
    if config.count(marker) != 1:
        raise ValueError("coverage configuration section is missing or ambiguous")
    section = config.partition(marker)[2].partition("\n[")[0]
    if any(line.strip().startswith("data_file") for line in section.splitlines()):
        raise ValueError("explicit coverage data_file requires review")
    # coverage parses this value as TOML and then expands $NAME from the
    # environment.  JSON's \ud83d-style surrogate escapes are not TOML, so the
    # path is written as UTF-8 text, and a literal dollar sign is doubled.
    destination = json.dumps(str(output / ".coverage").replace("$", "$$"), ensure_ascii=False)
    config = config.replace(marker, marker + f"data_file = {destination}\n")
    (output / "coverage.toml").write_text(config, encoding="utf-8")


def tool_version(name: str) -> str | None:
    """Retain unknown versions as unknown rather than inventing a tool."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def tool_versions() -> dict[str, str | None]:
    return {name: tool_version(name) for name in (
        "pytest", "pytest-xdist", "pytest-cov", "pytest-randomly", "coverage", "execnet",
        "mutmut", "pyrefly", "ruff",
    )}


def private_environment(scratch: Path, runner: str) -> dict[str, str]:
    # Carry OS/tool lookup, locale and the account name only, not operator
    # credentials, live endpoints, pytest filters/plugins, or CI-only
    # physical-input controls.  USERNAME is the one identity Windows offers:
    # without it getpass.getuser() raises there instead of falling back.  The
    # two PROGRAMFILES roots are where Windows keeps installed tools that are
    # not on PATH, Git's POSIX shell among them.
    allowed = {"PATH", "LANG", "LANGUAGE", "TZ", "TERM", "SHELL", "SYSTEMROOT",
               "WINDIR", "PATHEXT", "COMSPEC", "SSL_CERT_FILE", "SSL_CERT_DIR",
               "USERNAME", "PROGRAMFILES", "PROGRAMFILES(X86)"}
    env = {key: value for key, value in os.environ.items()
           if key in allowed or key.startswith("LC_")}
    if "ARENA_SKIP_BROWSER_E2E" in os.environ:
        env["ARENA_SKIP_BROWSER_E2E"] = os.environ["ARENA_SKIP_BROWSER_E2E"]
    # A program that finds no per-user directory in the environment falls back
    # to the working directory, which is the checkout: APPDATA and LOCALAPPDATA
    # are private for the same reason HOME is (#376).
    for key in ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE", "APPDATA",
                "LOCALAPPDATA"):
        path = scratch / key.lower()
        path.mkdir(mode=0o700)
        env[key] = str(path)
    # The Windows Python install manager answers `python3`, `pip` and `pip3`.
    # With an empty per-user directory it sees no runtime and downloads one;
    # a measurement must not install software (#376).
    env.update(ARENA_TEST_EXECUTION_GUARD="1", RUNNER_OS=runner,
               PYTHON_MANAGER_AUTOMATIC_INSTALL="false")
    return env


def source_unchanged(root: Path, before: dict[str, str]) -> bool:
    try:
        return fingerprint(root) == before
    except (OSError, ValueError, subprocess.SubprocessError):
        return False


def validate_output_location(root: Path, output: Path) -> None:
    if output == root or root in output.parents:
        raise ValueError("output must be outside the checkout")


def validate_request(root: Path, output: Path, mode: str, timeout: int) -> tuple[Path, Path]:
    """Refuse unsupported measurement requests before creating any evidence."""
    if mode not in {"serial", "n2"} or timeout <= 0:
        raise ValueError("invalid mode or timeout")
    root, output = root.resolve(), output.resolve()
    validate_output_location(root, output)
    if platform.system() != "Linux":
        raise ValueError("measurement process cleanup is validated only on Linux")
    return root, output


def initialize_measurement(root: Path, output: Path, *,
                           mode: str, seed: int) -> tuple[dict, list[str]]:
    """Persist startup evidence even when configuration or metadata fails."""
    destination = output / "result.json"
    result = {"schema": 1, "state": "running", "started_unix": time.time()}
    save(destination, result)
    try:
        before = fingerprint(root)
        if not before:
            raise ValueError("source inventory is empty")
        write_coverage_config(root, output)
        argv = command(mode, seed, output, "Linux")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                              capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        result = {"schema": 1, "state": "running", "source_head": head,
                  "source_manifest": before, "mode": mode, "seed": seed,
                  "command": argv, "platform": platform.platform(), "python": sys.version,
                  "versions": tool_versions(), "logical_cpus": os.cpu_count(),
                  "started_unix": result["started_unix"], "peak_memory_bytes": None,
                  "peak_memory_note": "not measured; no RSS estimate presented as physical peak",
                  "locks": {n: before.get(n) for n in ("requirements-ci.txt", "requirements-mutation.lock")}}
        save(destination, result)
    except BaseException as error:
        # Record startup interruption and unexpected faults, then preserve the
        # original exception; a partial startup must never look still running.
        result.update(state="failed", exit=130 if isinstance(error, KeyboardInterrupt) else 1,
                      error=f"initialization failed: {type(error).__name__}",
                      completed_unix=time.time())
        try:
            private_evidence(output)
        finally:
            save(destination, result)
        raise
    return result, argv


@dataclass(frozen=True)
class MeasurementClock:
    started: float
    cpu: float | None


@dataclass(frozen=True)
class MeasurementOptions:
    mode: str
    seed: int
    timeout: int


def finalize_measurement(root: Path, output: Path, result: dict, clock: MeasurementClock) -> int:
    """Validate immutable source identity and persist the final verdict."""
    destination = output / "result.json"
    code = result["exit"]
    result["wall_seconds"] = time.monotonic() - clock.started
    end_cpu = cpu_seconds()
    result["child_cpu_seconds"] = end_cpu - clock.cpu if clock.cpu is not None and end_cpu is not None else None
    result["source_unchanged"] = source_unchanged(root, result["source_manifest"])
    if not result["source_unchanged"]:
        code = code or 1
    result.update(state="passed" if code == 0 else "failed", exit=code,
                  completed_unix=time.time())
    try:
        private_evidence(output)
    except (OSError, ValueError) as error:
        code = code or 1
        result.update(state="failed", exit=code,
                      error=f"evidence finalization failed: {type(error).__name__}")
    save(destination, result)
    return code


def run(root: Path, output: Path, *, options: MeasurementOptions) -> int:
    root, output = validate_request(root, output, options.mode, options.timeout)
    runner = "Linux"
    # Exclusive directory creation prevents overwriting failed or partial evidence.
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    output.chmod(0o700)
    result, argv = initialize_measurement(root, output, mode=options.mode, seed=options.seed)
    clock = MeasurementClock(time.monotonic(), cpu_seconds())
    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix="arena-benchmark-") as directory:
            env = private_environment(Path(directory), runner)
            # Do not set CI/GITHUB_ACTIONS: that can enable physical input tests.
            with (output / "pytest.log").open("w", encoding="utf-8") as log:
                status = execute(argv, context=ProcessContext(root=root, env=env), log=log, timeout=options.timeout)
            pytest_code = status if status >= 0 else 1
        result["pytest_exit"] = pytest_code
        result["junit"] = read_junit(output / "junit.xml")
        result["coverage"] = read_coverage(output / ".coverage")
        require_coverage_xml(output / "coverage.xml")
        evidence_failed = any(c["outcome"] in {"failure", "error"} for c in result["junit"]["cases"])
        # Promote success only after every evidence reader has completed.
        code = (pytest_code or 1) if evidence_failed else pytest_code
    except subprocess.TimeoutExpired:
        result["error"] = "pytest timeout; partial evidence retained, no retry"
        code = 124
    except KeyboardInterrupt:
        result["error"] = "interrupted; partial evidence retained"
        code = 130
    except (OSError, ValueError, element_tree.ParseError, CoverageException) as error:
        result["error"] = f"incomplete measurement: {type(error).__name__}"
        code = 1
    finally:
        result["exit"] = code
        code = finalize_measurement(root, output, result, clock)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("serial", "n2"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    # Background shells can inherit SIGINT=ignore. Explicit handlers let the
    # CLI retain a failed record and clean up its owned process group on stop.
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, signal.default_int_handler)
        return run(ROOT, args.output, options=MeasurementOptions(mode=args.mode, seed=args.seed, timeout=args.timeout))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(f"cannot start measurement: {type(error).__name__}")
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
