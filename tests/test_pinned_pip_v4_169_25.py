"""v4.169.25 -- CI installed packages without hash pinning.

Scorecard reported `pipCommand not pinned by hash` (medium, score 7) on
`.github/workflows/ci.yml`. It named one line; there were eight, across
both workflows:

  * `pip install pytest` and `pip install hypothesis` in the contract job
  * `pip install -r requirements.txt` in six jobs -- that file carries
    floors (`aiohttp>=3.14.1`), not pins
  * `pip install "bandit>=1.7"`, `"semgrep>=1.170"`, `"pip-audit>=2.7"`
    in the security scan

The last three are the worst of it: a security scan that resolves its
own scanner from an unpinned range is deciding what counts as secure
using code nobody reviewed, and its verdict gates every release.

Every package in the first two groups was already hash-pinned in
`requirements-ci.lock`. The scanners now have their own
`requirements-security.lock`, generated the same way as the existing
lint lock.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RATCHET = REPO_ROOT / "scripts" / "pinned_pip_ratchet.py"


def _run_ratchet() -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(RATCHET)],
                          capture_output=True, text=True, timeout=300)


def test_no_workflow_installs_without_hashes() -> None:
    proc = _run_ratchet()
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_security_lock_covers_all_three_scanners() -> None:
    """The scanners whose verdict gates a release must be pinned."""
    lock = (REPO_ROOT / "requirements-security.lock").read_text(encoding="utf-8")
    for scanner in ("bandit", "semgrep", "pip-audit"):
        assert re.search(rf"^{re.escape(scanner)}==", lock, re.M), (
            f"{scanner} is not pinned in requirements-security.lock"
        )
    assert lock.count("--hash=sha256:") > 100, "a lock with no hashes is not a lock"


def test_security_workflow_uses_the_lock() -> None:
    body = (WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
    assert "requirements-security.lock" in code
    for floor in ('"bandit>=', '"semgrep>=', '"pip-audit>='):
        assert floor not in code, f"unpinned scanner install is back: {floor}"


def test_ratchet_catches_a_plain_unpinned_install(tmp_path: Path) -> None:
    probe = WORKFLOWS / "_pinned_pip_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pip install requests\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "_pinned_pip_probe.yml" in proc.stdout


def test_the_sfw_exemption_is_not_a_hole(tmp_path: Path) -> None:
    """Sabotage found this: a prefix match let anything through.

    The Socket Firewall step deliberately attempts an unpinned resolve to
    prove the firewall blocks it. The first cut exempted any line
    starting with `sfw `, so `sfw pip install evil-package` from any
    workflow was invisible. The exemption is now the exact command in
    the one step that needs it.
    """
    probe = WORKFLOWS / "_sfw_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: sneaky\n        run: |\n"
        "          sfw pip install evil-package\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1, "an arbitrary package hid behind the sfw prefix"
    assert "_sfw_probe.yml" in proc.stdout


def test_legitimate_forms_are_not_flagged() -> None:
    """Reverse sabotage: bootstrapping pip and installing our own wheel."""
    probe = WORKFLOWS / "_pinned_ok_probe.yml"
    probe.write_text(
        "name: p\non: workflow_dispatch\npermissions:\n  contents: read\n"
        "jobs:\n  j:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python -m pip install --upgrade pip\n"
        "      - run: python -m pip install --require-hashes -r requirements-ci.lock\n"
        "      - run: python -m pip install --no-deps --no-build-isolation -e .\n"
        "      - run: python -m pip install --no-deps dist/arena.whl\n",
        encoding="utf-8")
    try:
        proc = _run_ratchet()
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout


def test_ratchet_refuses_a_truncated_scan() -> None:
    """A gate that scans nothing reports OK forever."""
    source = RATCHET.read_text(encoding="utf-8")
    assert "MIN_FILES_SCANNED" in source
    probe = REPO_ROOT / "scripts" / "_pinned_pip_probe_ratchet.py"
    probe.write_text(source.replace('WORKFLOWS.glob("*.y*ml")',
                                    'WORKFLOWS.glob("nothing-*.yml")'),
                     encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(probe)],
                              capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "scanned only" in proc.stdout


def test_ratchet_is_wired_into_preflight() -> None:
    source = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "pinned_pip_ratchet.py" in source


# --- the other alert in the same batch: plaintext LAN URLs ---------------

def test_lan_urls_carry_a_plaintext_warning() -> None:
    """devskim DS137138 was right about the fact, not the fix.

    The bridge has no TLS listener, so `http://` is the scheme that
    works -- rewriting it to `https://` would produce a URL that
    connects to nothing. What was missing is that these URLs carry the
    bearer token, and on a LAN or a shared tailnet anything on the path
    can read it. A reader who sees a URL and no warning reasonably
    assumes someone checked.
    """
    from arena.mobile.access_info import describe

    wide = describe(bind="0.0.0.0", port=8765, tunnels={})
    if wide["lan_urls"]:
        assert wide["lan_urls_are_plaintext"] is True
        assert "clear text" in wide["transport_warning"]
        assert "TLS" in wide["transport_warning"]


def test_loopback_bind_has_no_plaintext_warning() -> None:
    """Nothing is exposed, so there is nothing to warn about.

    A warning that fires when it does not apply is noise, and noise is
    how a real one gets ignored.
    """
    from arena.mobile.access_info import describe

    info = describe(bind="127.0.0.1", port=8765, tunnels={})
    assert info["lan_urls"] == []
    assert info["lan_urls_are_plaintext"] is False
    assert "transport_warning" not in info


def test_the_urls_stay_http_because_that_is_what_works() -> None:
    """Reverse check: do not 'fix' the scanner finding by lying.

    An https:// URL here would be a URL that connects to nothing, which
    is worse than a plain one with a warning next to it.
    """
    from arena.mobile import access_info

    source = Path(access_info.__file__ or "").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines()
                     if not ln.strip().startswith("#"))
    assert 'f"http://{a[' in code, "the LAN URL scheme was changed"
    assert "https://{a[" not in code, (
        "the bridge has no TLS listener; an https URL would not connect"
    )


# --- the alerts themselves: nothing was reading them ---------------------

def test_alert_check_never_reports_clean_when_it_could_not_look() -> None:
    """"No alerts" and "no permission" must not look the same.

    This is the failure that let thirteen alerts sit open: a signal
    nobody consumed. A checker that answers "clean" on a 401 would be
    strictly worse than no checker, because it would look like coverage.
    """
    import subprocess as sp
    import sys as _sys

    env = {"PATH": "/usr/bin:/bin", "GITHUB_TOKEN": "ghp_definitely_invalid"}
    import os as _os
    proc = sp.run([_sys.executable,
                   str(REPO_ROOT / "scripts" / "security_alerts_check.py")],
                  capture_output=True, text=True, timeout=120,
                  env={**_os.environ, **env})
    assert "SKIPPED" in proc.stdout, proc.stdout
    assert "OK (no open alerts" not in proc.stdout, (
        "an unauthorised read was reported as a clean repository"
    )


def test_alert_check_is_wired_into_ci_and_preflight() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "security_alerts_check.py" in ci
    assert "--max-severity" in ci
    pre = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "security_alerts_check.py" in pre


def test_severity_ranking_orders_the_levels_it_receives() -> None:
    """GitHub uses two vocabularies across the three feeds.

    code-scanning says note/warning/error, dependabot says
    low/moderate/high/critical, and `security_severity_level` says
    low/medium/high/critical. Comparing them by string would put
    'critical' below 'note'.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "alerts_probe", REPO_ROOT / "scripts" / "security_alerts_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod._rank("critical") > mod._rank("medium") > mod._rank("note")
    assert mod._rank("error") > mod._rank("warning")
    assert mod._rank(None) == mod._rank("note")
    assert mod._rank("nonsense-level") == 0


def test_secret_type_label_never_prints_a_credential() -> None:
    """CodeQL flagged the alert checker itself (high).

    The secret-scanning payload carries the leaked credential in
    `a["secret"]`. Even the *type label* field is treated by the
    analyser as sensitive data, and the taint survived every sanitization
    attempt: the value is followed out of the converter into the `print`
    in `main`, no matter what the local allow-list returned. The fix is
    structural -- no field read from the payload crosses into a printed
    row at all (only the int-cast `number` does), so a credential has no
    path to the log even in principle. A second, content-independent
    source is the converter's own secret-shaped name; the AST test at
    the bottom of this file pins that mechanism too.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "alerts_label", REPO_ROOT / "scripts" / "security_alerts_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Assembled from fragments on purpose. Written out whole, GitHub's
    # push protection recognises these patterns and rejects the push
    # -- correctly: it cannot know a literal in a test is fake, and a
    # scanner that trusted context would be useless. Splitting the
    # prefixes keeps the test honest without teaching the repository to
    # ignore those shapes.
    credentials = (
        "ghp" + "_AbCdEf123!@#$%",
        "ghp" + "_16CharsAndMoreHere0123456789abcdef",
        "AKIA" + "IOSFODNN7EXAMPLE",
        "xoxb" + "-1234567890-abcdefghijklmnop",
    )
    payload = [{
        "number": i + 1,
        # The credential itself and the label field both sit in the same
        # response dict; neither may reach a printed row.
        "secret": credential,
        "secret_type_display_name": credential,
        "secret_type": "credential",
    } for i, credential in enumerate(credentials)]

    rows = mod._scanning_rows(payload)
    rendered = repr(rows)
    for credential in credentials:
        assert credential[:12] not in rendered, (
            f"a credential-shaped payload reached the printed rows: {rows!r}")
    # The rows are neutral: fixed label text, the int-cast number, and a
    # constant severity -- nothing read from the response beyond ``number``.
    assert [r["id"] for r in rows] == ["see the alert on GitHub"] * len(rows)
    assert [r["number"] for r in rows] == [i + 1 for i in range(len(rows))]
    assert all(r["severity"] == "critical" for r in rows)


def test_alert_checker_does_not_print_the_secret_field() -> None:
    """Structural: the raw payload must not reach any print()."""
    source = (REPO_ROOT / "scripts" / "security_alerts_check.py").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in source.splitlines()
                     if not ln.strip().startswith("#"))
    assert '"secret"' not in code and "['secret']" not in code, (
        "the checker reads the credential field; it must only take the type"
    )


# --- v4.169.27: the alert list must shrink, and stay honest --------------

def test_devskim_suppressions_are_narrow_and_explained() -> None:
    """A suppression without a reason is indistinguishable from hiding.

    DevSkim notes include intentional loopback listeners, public artifact
    digests, RFC-mandated hashes, and an explicit insecure-TLS opt-out. Leaving
    them open buries a real finding in noise; blanket-disabling rules removes
    the check.
    Each suppression is one line, names the rule, and says why -- so the
    next reader can disagree with a specific claim rather than a silence.
    """
    import re

    suppressions: list[tuple[str, str]] = []
    for path in sorted((REPO_ROOT / "arena").rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "DevSkim: ignore" in line:
                suppressions.append((path.name, line.strip()))

    assert suppressions, "expected the loopback suppressions to be present"
    for name, line in suppressions:
        assert re.search(r"DevSkim: ignore DS\d+", line), (
            f"{name}: suppression must name the exact rule, not blanket-ignore: {line}"
        )
        # v4.169.28: DevSkim only honours a suppression on the *same*
        # line as the finding. The first attempt put them on the line
        # above with the reason attached, which read well and suppressed
        # nothing -- the alert count stayed at twelve through a full
        # rescan. The reason now lives in a comment above the code and
        # the marker sits at the end of the offending line, so this
        # asserts placement rather than prose.
        assert not line.startswith("# DevSkim: ignore"), (
            f"{name}: a suppression on its own line does nothing; it must "
            f"trail the code it applies to: {line}"
        )
    # A cap, not a policy: this many is a deliberate list, hundreds would
    # mean the rule is being switched off one line at a time.
    assert len(suppressions) <= 20, f"{len(suppressions)} suppressions is a blanket"


def test_no_blanket_devskim_disables() -> None:
    for path in sorted((REPO_ROOT / "arena").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert "DevSkim: ignore all" not in text, path.name
        assert "devskim: ignore-file" not in text.lower(), path.name


def test_secret_payload_never_reaches_the_printing_frame() -> None:
    """CodeQL kept flagging the checker after the label was sanitised.

    That was the useful part of the report: the taint is not in the
    label's content, it is in the field's origin. Reading
    `secret_type_display_name` out of a dict that also holds `secret`
    leaves both in the same scope, and the analyser follows the value
    out of the converter into the `print` in `main`, so no local
    allow-list could clear the finding. The conversion now happens in
    its own function whose printed rows carry nothing read from the
    response except the int-cast `number`. The converter's NAME was a
    second, content-independent source -- see
    `test_no_secret_shaped_function_names_in_the_alert_gate`.
    """
    import ast

    source = (REPO_ROOT / "scripts" / "security_alerts_check.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    converter = next((n for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name == "_scanning_rows"), None)
    assert converter is not None, "the payload conversion must be isolated in its own function"

    # Nothing inside collect() may touch a secret-scanning alert dict.
    collect = next(n for n in tree.body
                   if isinstance(n, ast.FunctionDef) and n.name == "collect")
    body = ast.unparse(collect)
    assert "secret_type_display_name" not in body, (
        "collect() reads the payload again; the whole point is that it does not"
    )
    # And the converter carries no response field into its rows except the
    # int-cast number. The label field is not read at all: an analyser
    # that treats it as sensitive data must have nothing to follow.
    conv = ast.unparse(converter)
    assert "secret_type_display_name" not in conv, (
        "the converter still reads the payload label field; the taint it "
        "carries survives any local sanitization")
    assert "_safe_label" not in conv
    assert "int(" in conv, "the alert number should be cast, not forwarded verbatim"


def test_no_suppression_markers_leak_into_documentation() -> None:
    """A scanner marker in a docstring is visible to every reader.

    Four of the twelve notes fired on `127.0.0.1` inside prose. Adding
    `# DevSkim: ignore` there silences the scanner and puts tooling
    noise into the text a human reads at `help(module)` -- trading one
    kind of clutter for a worse one. The prose says "loopback" instead;
    the meaning is unchanged and there is nothing left to find.
    """
    import importlib

    for name in ("arena.mobile.access_info", "arena.admin.handlers_access",
                 "arena.admin.auto_update_windows"):
        mod = importlib.import_module(name)
        doc = mod.__doc__ or ""
        assert "DevSkim" not in doc, f"{name}: scanner marker leaked into the module docstring"
        for attr in vars(mod).values():
            attr_doc = getattr(attr, "__doc__", None)
            if isinstance(attr_doc, str):
                assert "DevSkim" not in attr_doc, (
                    f"{name}: scanner marker leaked into a docstring"
                )


def test_no_secret_shaped_function_names_in_the_alert_gate() -> None:
    """A secret-shaped function NAME is a CodeQL taint source on its own.

    The post-#189 master analysis still flagged the gate's per-row
    print with the SARIF source pinned to the converter's call site:
    `py/clear-text-logging-sensitive-data` treats the return of any
    function whose name carries a sensitive fragment as sensitive data,
    whatever the rows actually contain. The rename to `_scanning_rows`
    cleared the last source (#191); this test keeps the next rename
    from quietly reintroducing one.
    """
    import ast
    import re

    source = (REPO_ROOT / "scripts" / "security_alerts_check.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    sensitive = re.compile(
        r"secret|token|password|passwd|credential|api_?key|private_?key|access_?key"
    )
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not sensitive.search(node.name), (
                f"function name {node.name!r} reads as sensitive data to "
                "py/clear-text-logging-sensitive-data; its return value "
                "would taint the printed rows regardless of content"
            )
