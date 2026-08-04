"""The bridge must refuse to edit itself, and must not refuse everything else.

Found by mutation testing, which was added after an argument worth recording:
the mandatory-sabotage rule that already governs new gates here lives only in
a conversation. Measured -- 406 test files, six of them mention sabotage, and
AGENTS.md does not contain the word. A rule that depends on an agent choosing
to follow it is not a rule; a red CI job is.

So mutmut was pointed at ``arena/files/sandbox.py``: 216 mutants, **95
survived**. Most survivors are harmless -- error-message wording, or the
second line of a defence-in-depth pair (breaking the ``..`` check still leaves
the resolve-and-compare check, which was verified by applying that mutant and
watching traversal stay refused).

One was not harmless. Mutant #174 flips the self-protection comparison:

    -    if target_path.resolve() == bridge_py.resolve():
    +    if target_path.resolve() != bridge_py.resolve():

Applied and driven directly, the meaning inverts completely:

    edit the bridge itself  -> status=200  (allowed!)
    edit an ordinary file   -> status=403  "cannot edit the bridge itself"

An agent could rewrite ``unified_bridge.py`` -- every policy, every guard,
every audit call -- while ordinary work became impossible. The whole test
suite passed. Nothing asserted that the bridge protects itself, in either
direction, so a single inverted operator was invisible.

Both halves matter and both are asserted below. Testing only the refusal
would let the inverted form through, because it does refuse -- just
everything else.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.files import sandbox as S  # noqa: E402

# The validators that take bridge_py, i.e. the ones that can write.
WRITE_VALIDATORS = (
    ("upload", S.validate_upload_target),
    ("edit", S.validate_edit_target),
    ("create", S.validate_create_target),
)


@pytest.fixture
def home(tmp_path):
    (tmp_path / "unified_bridge.py").write_text("# the bridge\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ordinary\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("verb,validator", WRITE_VALIDATORS)
def test_the_bridge_refuses_to_be_written_by_the_agent(home, verb, validator):
    bridge = home / "unified_bridge.py"
    result, err, status = validator(str(bridge), root=home, home=home, bridge_py=bridge)
    assert result is None and status == 403, (
        f"{verb} of the bridge itself returned status={status}; an agent that "
        "can rewrite unified_bridge.py can delete every policy in it")
    assert "bridge" in (err or "").lower()


@pytest.mark.parametrize("verb,validator", WRITE_VALIDATORS)
@pytest.mark.parametrize("rel", ["notes.txt", "src/app.py", "new_file.txt"])
def test_ordinary_files_are_not_mistaken_for_the_bridge(home, verb, validator, rel):
    """The inverted comparison refuses too -- just everything except the bridge.

    Asserting only the refusal above would pass on the mutant. This is the
    half that catches it.
    """
    target = home / rel
    result, err, status = validator(str(target), root=home, home=home,
                                    bridge_py=home / "unified_bridge.py")
    if verb == "edit" and not target.exists():
        pytest.skip("edit requires an existing file")
    if verb == "create" and target.exists():
        pytest.skip("create requires a new path")
    assert "bridge" not in (err or "").lower(), (
        f"{verb} of ordinary file {rel} was refused as if it were the bridge "
        f"({err!r}); the self-protection comparison is inverted")


def test_the_bridge_is_identified_by_resolved_path_not_by_name(home):
    """A file merely *named* unified_bridge.py elsewhere is not the bridge."""
    decoy = home / "src" / "unified_bridge.py"
    decoy.write_text("# not the real one\n", encoding="utf-8")
    result, err, _status = S.validate_edit_target(
        str(decoy), root=home, home=home, bridge_py=home / "unified_bridge.py")
    assert result is not None, (
        f"a same-named file in another directory was treated as the bridge: {err}")


def test_a_symlink_to_the_bridge_is_still_the_bridge(home):
    """Resolution must happen before the comparison, or the guard is bypassable."""
    link = home / "innocent.py"
    try:
        link.symlink_to(home / "unified_bridge.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    result, _err, status = S.validate_edit_target(
        str(link), root=home, home=home, bridge_py=home / "unified_bridge.py")
    assert result is None and status == 403, (
        "a symlink pointing at the bridge was accepted; the comparison must "
        "resolve both sides")
