"""T57: Dependabot relock must be able to update the resolver's own lock."""
from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/relock-dependabot.yml"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_relock_uses_untrusted_pr_event_with_narrow_bot_gate() -> None:
    text = source()
    lines = [line.strip() for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert "pull_request_target:" not in lines
    assert "pull_request:" in lines
    assert "github.event.pull_request.user.login == 'dependabot[bot]'" in text
    assert "contents: write" in text


def test_old_hash_locked_uv_regenerates_every_pair_including_itself() -> None:
    text = source()
    install = "pip install --require-hashes -r requirements-relock.lock"
    loop = "for in_file in requirements-*.in; do"
    compile_call = 'uv pip compile --universal --generate-hashes --strip-extras'
    assert text.index(install) < text.index(loop) < text.index(compile_call)
    assert '[ "$in_file" = "requirements-relock.in" ] && continue' not in text
    assert 'lock_file="${in_file%.in}.lock"' in text
    assert '--output-file="$lock_file" "$in_file"' in text


def test_every_generated_lock_is_verified_before_any_push() -> None:
    text = source()
    verify = text.index("python scripts/check_lock_freshness.py")
    commit = text.index("git commit -m")
    push = text.index('git push origin "HEAD:$HEAD_REF"')
    assert text.index("python scripts/check_ci_lock.py") < verify < commit < push
    assert "if git diff --quiet -- 'requirements-*.lock'" in text
