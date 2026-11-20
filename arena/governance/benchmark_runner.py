"""T74: explicit, single-run pytest measurement; never a replacement CI gate."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import time

# nosemgrep: use-defused-xml -- own pytest UTF-8 report; read_junit rejects DTD/ENTITY declarations before parsing
import xml.etree.ElementTree as ET  # nosec B405 -- own pytest UTF-8 report, DTD/ENTITY rejected by read_junit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fingerprint(root: Path) -> dict[str, str]:
    """Include tracked and unignored new files, not the environment or Git config."""
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=True, timeout=30,
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in sorted(set(listing.stdout.decode().split("\0")))
        if name and (root / name).is_file()
    }


def read_junit(path: Path) -> dict:
    # Pytest emits UTF-8. Reject DTD/entity declarations before parsing, rather
    # than accepting alternate encodings or expanding an embedded entity graph.
    text = path.read_text(encoding="utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("JUnit declarations are not allowed")
    root = ET.fromstring(text)  # nosec B314 -- own pytest UTF-8 report; DTD/ENTITY declarations rejected above
    cases = []
    for case in root.iter("testcase"):
        outcome = "passed"
        reason = ""
        for tag in ("error", "failure", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = tag
                reason = node.get("message", "")
                break
        cases.append({"id": [case.get("classname", ""), case.get("name", "")],
                      "outcome": outcome, "reason": reason,
                      "seconds": float(case.get("time", "0"))})
    if not cases:
        raise ValueError("JUnit contains no cases")
    suites = list(root.iter("testsuite"))
    declared = [int(s.attrib["tests"]) for s in suites if "tests" in s.attrib]
    if declared and sum(declared) < len(cases):
        raise ValueError("JUnit counters contradict the case inventory")
    # pytest-subtests contributes to summary counters without emitting a new
    # testcase element. Preserve both counts; never equate them silently.
    return {"cases": cases, "count": len(cases),
            "declared_tests": sum(declared) if declared else None}


def read_coverage(path: Path) -> dict:
    # Read actual recorded arcs, not rounded percentages alone.
    from coverage import CoverageData

    if not path.is_file():
        raise ValueError("coverage database missing")
    data = CoverageData(basename=str(path))
    data.read()
    if not data.has_arcs():
        raise ValueError("branch coverage missing")
    files = {}
    for name in sorted(data.measured_files()):
        files[name] = {"lines": sorted(data.lines(name) or []),
                       "arcs": sorted(data.arcs(name) or [])}
    if not files:
        raise ValueError("coverage contains no measured files")
    return files


def save(path: Path, result: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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


def execute(argv: list[str], *, root: Path, env: dict[str, str], log, timeout: int) -> int:
    """Own a Linux process group; a timeout must not leave xdist workers alive."""
    proc = subprocess.Popen(argv, cwd=root, env=env, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return proc.wait(timeout=timeout)
    finally:
        # Also clean up descendants after normal exit; a surviving grandchild
        # must not contaminate the following serial/parallel measurement.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()


def run(root: Path, output: Path, *, mode: str, seed: int, timeout: int) -> int:
    if mode not in {"serial", "n2"} or timeout <= 0:
        raise ValueError("invalid mode or timeout")
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("output must be outside the checkout")
    if platform.system() != "Linux":
        raise ValueError("measurement process cleanup is validated only on Linux")
    runner = "Linux"
    before = fingerprint(root)
    if not before:
        raise ValueError("source inventory is empty")
    # Exclusive directory creation prevents overwriting failed or partial evidence.
    output.mkdir(parents=True, exist_ok=False)
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
    config = config.replace(marker, marker + f'data_file = {json.dumps(str(output / ".coverage"))}\n')
    (output / "coverage.toml").write_text(config, encoding="utf-8")
    argv = command(mode, seed, output, runner)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                          capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    versions = dict[str, str | None]()
    for name in ("pytest", "pytest-xdist", "pytest-cov", "pytest-randomly", "coverage", "execnet",
                 "mutmut", "pyrefly", "ruff"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    result = {"schema": 1, "state": "running", "source_head": head,
              "source_manifest": before, "mode": mode, "seed": seed,
              "command": argv, "platform": platform.platform(), "python": sys.version,
              "versions": versions, "logical_cpus": os.cpu_count(),
              "started_unix": time.time(), "peak_memory_bytes": None,
              "peak_memory_note": "not measured; no RSS estimate presented as physical peak",
              "locks": {n: before.get(n) for n in ("requirements-ci.txt", "requirements-mutation.lock")}}
    destination = output / "result.json"
    save(destination, result)
    started, cpu = time.monotonic(), cpu_seconds()
    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix="arena-benchmark-") as directory:
            scratch = Path(directory)
            env = dict(os.environ)
            for key in ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                        "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE"):
                path = scratch / key.lower()
                path.mkdir()
                env[key] = str(path)
            env.pop("COVERAGE_FILE", None)
            env.update(ARENA_TEST_EXECUTION_GUARD="1", RUNNER_OS=runner)
            # Do not set CI/GITHUB_ACTIONS: that can enable physical input tests.
            with (output / "pytest.log").open("w", encoding="utf-8") as log:
                status = execute(argv, root=root, env=env, log=log, timeout=timeout)
            code = status if status >= 0 else 1
        result["pytest_exit"] = code
        result["junit"] = read_junit(output / "junit.xml")
        result["coverage"] = read_coverage(output / ".coverage")
        if any(c["outcome"] in {"failure", "error"} for c in result["junit"]["cases"]):
            code = code or 1
    except subprocess.TimeoutExpired:
        result["error"] = "pytest timeout; partial evidence retained, no retry"
        code = 124
    except KeyboardInterrupt:
        result["error"] = "interrupted; partial evidence retained"
        code = 130
    except (OSError, ValueError, ET.ParseError) as error:
        result["error"] = f"incomplete measurement: {type(error).__name__}"
        code = 1
    finally:
        result["wall_seconds"] = time.monotonic() - started
        end_cpu = cpu_seconds()
        result["child_cpu_seconds"] = end_cpu - cpu if cpu is not None and end_cpu is not None else None
        try:
            result["source_unchanged"] = fingerprint(root) == before
        except (OSError, subprocess.SubprocessError):
            result["source_unchanged"] = False
        if not result["source_unchanged"]:
            code = code or 1
        result.update(state="passed" if code == 0 else "failed", exit=code,
                      completed_unix=time.time())
        save(destination, result)
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
        return run(ROOT, args.output, mode=args.mode, seed=args.seed, timeout=args.timeout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.error(f"cannot start measurement: {type(error).__name__}")
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
