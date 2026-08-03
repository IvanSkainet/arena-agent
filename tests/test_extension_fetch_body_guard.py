"""Gate: the extension must never hand fetch() a body on GET/HEAD.

`bridgeFetch(path, {method = 'GET', body})` defaults to GET, and
`bridgeFetchOnce` used to serialise `body` whenever it was truthy. The WHATWG
spec makes `fetch(url, {method: 'GET', body})` throw
`TypeError: Request with GET/HEAD method cannot have body`, which in the
service worker surfaces as an opaque "network error" with no route to the
cause. Every caller today passes `method: 'POST'` explicitly, so this guards
the next one.

Found by oxlint (unicorn/no-invalid-fetch-options) — the first finding from
linting the 17k lines of JavaScript that no tool had been looking at.

The behaviour is verified by *executing* the real function under Node when it
is available (source-level assertions alone would not prove the runtime
contract); the structural checks run everywhere.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKGROUND = ROOT / "chat_extension" / "background.js"


def _source() -> str:
    # Newline-normalised: Windows runners check the tree out with CRLF, and
    # every assertion here is about content, never about line terminators.
    return BACKGROUND.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_fetch_call_is_guarded_against_get_with_body():
    src = _source()
    assert "sendsBody" in src, "the GET/HEAD body guard is gone from bridgeFetchOnce"
    # The guard must exclude both bodyless methods, not just GET.
    guard = re.search(r"const sendsBody = [^;]+;", src)
    assert guard, "sendsBody is no longer a single-expression guard"
    assert "'GET'" in guard.group(0) and "'HEAD'" in guard.group(0)
    # And the fetch() call must actually consult it.
    assert "body: sendsBody ?" in src


def test_no_bare_body_ternary_remains():
    """The original shape (`body ? JSON.stringify(body) : undefined`) is the bug."""
    assert "body: body ? JSON.stringify(body) : undefined" not in _source()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_get_with_body_does_not_throw_and_post_still_sends(tmp_path):
    """Execute the real bridgeFetchOnce against a fetch() that enforces the spec."""
    harness = tmp_path / "harness.mjs"
    harness.write_text(textwrap.dedent(f"""
        import {{ readFileSync }} from 'node:fs';
        const calls = [];
        globalThis.fetch = async (url, opts) => {{
          calls.push(opts);
          if ((opts.method === 'GET' || opts.method === 'HEAD') && opts.body !== undefined) {{
            throw new TypeError('Request with GET/HEAD method cannot have body.');
          }}
          return {{ ok: true, status: 200, text: async () => '{{"ok":true}}' }};
        }};
        // Normalise line endings first: Windows runners check the tree out
        // with CRLF, so a `\\n}}\\n` terminator would never match there.
        const src = readFileSync({json.dumps(str(BACKGROUND))}, 'utf8').replace(/\\r\\n/g, '\\n');
        const m = src.match(/async function bridgeFetchOnce[\\s\\S]*?\\n}}\\n/);
        if (!m) {{ console.error('bridgeFetchOnce not found in source'); process.exit(2); }}
        const bridgeFetchOnce = new Function('return ' + m[0].trim())();
        await bridgeFetchOnce('http://x', '/p', {{}}, 'GET', {{a: 1}});
        await bridgeFetchOnce('http://x', '/p', {{}}, 'HEAD', {{a: 1}});
        await bridgeFetchOnce('http://x', '/p', {{}}, 'POST', {{a: 1}});
        console.log(JSON.stringify(calls.map(c => c.body ?? null)));
    """), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(harness)], cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 2, (
        "the harness could not locate bridgeFetchOnce -- it was renamed or "
        f"reshaped:\n{proc.stderr}")
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    bodies = json.loads(proc.stdout.strip().splitlines()[-1])
    assert bodies[0] is None, "GET must not carry a body"
    assert bodies[1] is None, "HEAD must not carry a body"
    assert bodies[2] == '{"a":1}', "POST must still send its body"


def test_every_body_carrying_caller_names_an_explicit_method():
    """A `bridgeFetch(..., {body})` without a method would silently be a GET."""
    src = _source()
    offenders = [
        call for call in re.findall(r"bridgeFetch\((?:[^()]|\([^()]*\))*\)", src)
        if "body:" in call and "method:" not in call
    ]
    assert offenders == [], f"bridgeFetch called with a body but no method: {offenders}"
