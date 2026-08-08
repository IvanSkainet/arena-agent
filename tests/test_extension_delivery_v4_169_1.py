"""Getting the extension onto a machine must not require a shell.

The operator's report: *"I can't install the extension yet, the needed
files aren't there. Installing through Termux is really inconvenient."*

Two defects behind one sentence.

**The files really were absent.** `auto_update` copies a hand-maintained
tuple of directory names. `chat_extension_firefox` shipped inside the
v4.169.0 release zip and reached nobody, because nobody added it to that
tuple. Measured on his Windows machine after a clean update:

    chat_extension          18 files
    chat_extension_firefox  MISSING

`chat_extension` was absent from the tuple too, so the extension had
never been updated by auto-update at all -- only by a fresh install.

**Even present, they are unreachable on a phone.** They sit inside
Termux's private directory tree; no browser can browse there.

So the list is discovered from the payload, and the bridge serves the
extension as a ZIP over HTTP.

The discovery half is the risky one. Windows copies with
`robocopy /MIR`, which *deletes* anything at the destination missing
from the source -- so a directory that both ships in the release and
accumulates the operator's own work (`skills`, `projects`) must never be
replaced wholesale. Losing their work to an update is far worse than
shipping a stale bundled example.
"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from arena.admin import auto_update as au
from arena.admin.handlers_extension_download import build_zip

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------- discovery of what to copy

def test_the_extension_directories_are_copied_by_updates(tmp_path):
    """The exact bug: shipped in the zip, never reached the disk."""
    payload = tmp_path / "payload"
    for name in ("arena", "dashboard", "chat_extension",
                 "chat_extension_firefox"):
        (payload / name).mkdir(parents=True)

    targets = au.replace_targets(payload)
    assert "chat_extension" in targets, (
        "the Chromium extension is still not copied by auto-update")
    assert "chat_extension_firefox" in targets, (
        "the Firefox build ships in the release and still reaches nobody")


@pytest.mark.parametrize("protected", ["skills", "projects", "subagents",
                                       "hooks", "mcp", "queue", "memory"])
def test_operator_owned_directories_are_never_replaced(tmp_path, protected):
    """`robocopy /MIR` deletes what is not in the source.

    These directories ship with the release *and* collect the operator's
    own skills, projects and agents. Replacing them wholesale would
    delete work an update has no business touching.
    """
    payload = tmp_path / "payload"
    (payload / "arena").mkdir(parents=True)
    (payload / protected).mkdir(parents=True)

    assert protected not in au.replace_targets(payload), (
        f"{protected!r} would be mirrored over, deleting operator content")


def test_a_new_product_directory_ships_without_anyone_remembering(tmp_path):
    """The point of discovery: no second place to update.

    Adding a directory to the release should be enough. Requiring a
    matching edit here is what caused the original miss.
    """
    payload = tmp_path / "payload"
    (payload / "arena").mkdir(parents=True)
    (payload / "brand_new_feature").mkdir(parents=True)

    assert "brand_new_feature" in au.replace_targets(payload)


def test_discovery_falls_back_when_the_payload_is_unreadable():
    """A bad path must degrade to the old list, not copy nothing."""
    assert au.replace_targets(None) == au._STATIC_REPLACE_TARGETS
    assert au.replace_targets(Path("/nonexistent/xyz")) == au._STATIC_REPLACE_TARGETS


def test_dotfiles_and_caches_are_not_copied(tmp_path):
    payload = tmp_path / "payload"
    for name in ("arena", ".git", "__pycache__", ".ruff_cache"):
        (payload / name).mkdir(parents=True)
    targets = au.replace_targets(payload)
    for junk in (".git", "__pycache__", ".ruff_cache"):
        assert junk not in targets


def test_the_windows_mover_uses_the_discovered_list(tmp_path):
    """Windows has its own copy step and had its own hand-maintained list.

    Fixing only the POSIX path would leave every Windows operator --
    including this one -- exactly where they started.
    """
    payload = tmp_path / "payload"
    for name in ("arena", "chat_extension", "chat_extension_firefox", "skills"):
        (payload / name).mkdir(parents=True)
        (payload / name / "f.txt").write_text("x", encoding="utf-8")
    install = tmp_path / "install"
    install.mkdir()

    from arena.admin.auto_update_windows import _write_windows_installer
    script = _write_windows_installer(payload, install, install / "done.txt")
    text = script.read_text(encoding="utf-8")

    assert "chat_extension_firefox" in text
    assert "chat_extension" in text
    assert "skills" not in text, "the mover would mirror over operator skills"


# --------------------------------------------------------- serving it as a zip

def _fixture_install(tmp_path, *, with_firefox: bool) -> Path:
    root = tmp_path / "install"
    root.mkdir()
    shutil.copytree(ROOT / "chat_extension", root / "chat_extension")
    if with_firefox:
        shutil.copytree(ROOT / "chat_extension_firefox",
                        root / "chat_extension_firefox")
    return root


def test_the_bridge_serves_the_chromium_extension(tmp_path):
    root = _fixture_install(tmp_path, with_firefox=True)
    payload, name, info = build_zip(root, firefox=False)

    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert "manifest.json" in archive.namelist()
    assert info["files"] > 10
    assert name.endswith(".zip")
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["background"].get("service_worker"), "not the Chromium build"


def test_the_bridge_serves_the_firefox_extension(tmp_path):
    root = _fixture_install(tmp_path, with_firefox=True)
    payload, name, info = build_zip(root, firefox=True)

    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(payload)).read("manifest.json"))
    assert manifest["background"].get("scripts"), "not the Firefox build"
    assert "service_worker" not in manifest["background"]
    assert "sidePanel" not in manifest["permissions"]
    assert manifest["browser_specific_settings"]["gecko"]["id"]
    assert "firefox" in name


def test_an_install_without_the_firefox_directory_still_gets_a_firefox_build(tmp_path):
    """The operator's actual machine right now.

    His install predates `chat_extension_firefox`. Returning 404 would
    be technically honest and useless -- "that folder does not exist on
    your computer" is not something he can act on. The manifest is
    translated on the fly instead.
    """
    root = _fixture_install(tmp_path, with_firefox=False)
    payload, _name, info = build_zip(root, firefox=True)

    assert info["manifest_generated"] is True
    manifest = json.loads(
        zipfile.ZipFile(io.BytesIO(payload)).read("manifest.json"))
    assert manifest["background"].get("scripts")
    assert "sidePanel" not in manifest["permissions"]
    assert manifest["browser_specific_settings"]["gecko"]["id"]


def test_a_missing_extension_directory_is_an_explicit_error(tmp_path):
    """Fail with a sentence that names the fix, not a bare 404."""
    with pytest.raises(FileNotFoundError) as caught:
        build_zip(tmp_path, firefox=False)
    assert "chat_extension" in str(caught.value)
    assert "installer" in str(caught.value) or "update" in str(caught.value)


def test_secrets_are_never_packed(tmp_path):
    """Someone debugging will eventually drop a token in that folder."""
    root = _fixture_install(tmp_path, with_firefox=False)
    (root / "chat_extension" / "token.txt").write_text("qaz_secret",
                                                       encoding="utf-8")
    (root / "chat_extension" / "debug.log").write_text("noise", encoding="utf-8")

    payload, _name, _info = build_zip(root, firefox=False)
    names = zipfile.ZipFile(io.BytesIO(payload)).namelist()
    assert "token.txt" not in names
    assert "debug.log" not in names


def test_the_endpoints_are_registered():
    text = (ROOT / "arena" / "route_registry" / "registry.py").read_text(
        encoding="utf-8")
    assert "handle_v1_extension_download" in text
    assert "handle_v1_extension_status" in text


def test_the_dashboard_offers_both_downloads():
    assets = ROOT / "dashboard" / "assets"
    body = (assets / "body-15-settings.html").read_text(encoding="utf-8")
    assert "extensionDownload('chromium')" in body
    assert "extensionDownload('firefox')" in body

    script = (assets / "17e-settings-extension.js").read_text(encoding="utf-8")
    # The first draft spliced a token onto a URL that had no query yet,
    # producing a malformed link -- a 401 that looks like a broken
    # download button.
    #
    # Checked against CODE lines only: the comment explaining the bug
    # necessarily contains the broken form, and a gate that trips on its
    # own documentation is a false positive. (Same rake as the psutil
    # header in v4.167.6.)
    code_lines = [ln for ln in script.splitlines()
                  if not ln.lstrip().startswith("//")]
    code = "\n".join(code_lines)
    assert "URLSearchParams" in code, "query string is built by splicing"
    assert "download&" not in code


def test_android_firefox_limitation_is_stated_not_hidden():
    """Firefox for Android cannot side-load from a file, at all.

    Offering a download without saying so would send the operator into
    a dead end and make the bridge look broken. The honest answer is
    that the phone does not need the extension -- the Dashboard works
    in its browser.
    """
    script = (ROOT / "dashboard" / "assets"
              / "17e-settings-extension.js").read_text(encoding="utf-8")
    assert "Firefox for Android" in script
    assert "Dashboard" in script

    handler = (ROOT / "arena" / "admin"
               / "handlers_extension_download.py").read_text(encoding="utf-8")
    assert "android_firefox" in handler


# ------------------------------- v4.169.2: discovery must read the PAYLOAD

def test_an_install_root_is_never_mistaken_for_a_payload(tmp_path):
    """v4.169.2, found by watching the fix fail on the real machine.

    The first version compared names against a deny-list of operator
    state. A deny-list enumerates the half that keeps growing: measured
    on the operator's install root, discovery returned `relay`,
    `code-sessions`, `code-runs`, `flight-records`, `autonomy`,
    `autopilot`, `ship-chain`, `out`, `runtime`, `tools`, `mcp-ext` and
    `mcp-servers` -- twelve runtime directories created since that list
    was written, every one of which `robocopy /MIR` would have deleted.

    The right question is not "is this operator state?" but "did this
    arrive in the release?", and only the payload can answer it.
    """
    install = tmp_path / "install"
    (install / "arena").mkdir(parents=True)
    for runtime_dir in ("relay", "code-sessions", "flight-records",
                        "autopilot", "ship-chain"):
        (install / runtime_dir).mkdir()
    (install / "token.txt").write_text("qaz_x", encoding="utf-8")

    targets = au.replace_targets(install)
    for runtime_dir in ("relay", "code-sessions", "flight-records",
                        "autopilot", "ship-chain"):
        assert runtime_dir not in targets, (
            f"{runtime_dir!r} would be handed to robocopy /MIR and deleted")
    assert targets == au._STATIC_REPLACE_TARGETS


def test_the_install_markers_are_things_a_release_never_ships():
    """The second mistake, and the more instructive one.

    `queue/` and `memory/` looked like obvious "this is an install root"
    markers. Both are wrong: the release ships them, with a `.gitkeep`
    and an empty `facts.db`. Keying on them made every real payload look
    like an install root, so the fix compiled, passed its own tests, and
    did nothing.

    Checked against the actual release tree rather than assumed.
    """
    release_dirs = {"queue", "memory", "skills", "projects", "hooks"}
    from arena.admin import update_targets

    source = Path(update_targets.__file__).read_text(encoding="utf-8")
    marker_block = source.split("looks_like_install", 1)[1].split(")", 1)[0]
    for shipped in release_dirs:
        assert f'"{shipped}"' not in marker_block, (
            f"{shipped!r} is used as an install-root marker but the release "
            f"ships it -- every payload would be misread as an install root")


def test_a_real_payload_is_recognised(tmp_path):
    """The other half: a genuine payload must still be discovered."""
    payload = tmp_path / "payload"
    (payload / "arena").mkdir(parents=True)
    (payload / "chat_extension_firefox").mkdir()
    (payload / "queue" / "inbox").mkdir(parents=True)
    (payload / "queue" / "inbox" / ".gitkeep").write_text("", encoding="utf-8")
    (payload / "memory").mkdir()

    targets = au.replace_targets(payload)
    assert "chat_extension_firefox" in targets, (
        "a real payload was misread as an install root")
    assert "queue" not in targets and "memory" not in targets


# ------------------------------------- v4.169.3: the extension had no icon

ICON_SIZES = ("16", "32", "48", "128")


def test_the_extension_ships_icons():
    """The operator installed it and reported: "only there's no icon".

    The manifest had no `icons` block and no `action.default_icon`, and
    not a single PNG existed in the directory -- so Chromium drew a grey
    puzzle piece and Firefox drew the first letter of the name. The
    extension worked; it just looked like something half-finished, which
    is its own kind of broken when the point is that other people try
    this project.
    """
    ext = ROOT / "chat_extension"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))

    assert manifest.get("icons"), "no icons block: browsers show a placeholder"
    assert (manifest.get("action") or {}).get("default_icon"), (
        "no action.default_icon: the toolbar button is blank")

    for size in ICON_SIZES:
        assert size in manifest["icons"], f"no {size}px icon declared"
        path = ext / manifest["icons"][size]
        assert path.is_file(), f"{path.name} is declared but missing"


def test_every_declared_icon_is_a_real_png_of_the_right_size():
    """Declaring a file is not shipping it, and a 16px slot needs 16px.

    Checked by parsing the IHDR rather than trusting the filename: the
    icons are generated, and a generator bug that wrote every size at
    128px would pass a name check and look wrong in the toolbar.
    """
    import struct

    ext = ROOT / "chat_extension"
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))

    for size, name in manifest["icons"].items():
        blob = (ext / name).read_bytes()
        assert blob[:8] == b"\x89PNG\r\n\x1a\n", f"{name} is not a PNG"
        width, height = struct.unpack(">II", blob[16:24])
        assert width == height == int(size), (
            f"{name} is {width}x{height}, declared as {size}px")


def test_the_firefox_build_carries_the_icons_too():
    """Including the sidebar, which Firefox draws separately.

    The toolbar icon and the sidebar icon are different manifest keys;
    fixing only the first leaves a blank row in the sidebar -- the same
    complaint one level down.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ff", ROOT / "scripts" / "build_firefox_extension.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = json.loads(
        (ROOT / "chat_extension" / "manifest.json").read_text(encoding="utf-8"))
    generated = module.build_manifest(source)

    assert generated.get("icons") == source["icons"]
    assert (generated.get("action") or {}).get("default_icon")
    assert (generated.get("sidebar_action") or {}).get("default_icon"), (
        "the Firefox sidebar entry has no icon")
    assert module.verify(generated) == []


def test_the_builder_refuses_an_iconless_manifest():
    """The gate that would have caught this before the operator did."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_ff2", ROOT / "scripts" / "build_firefox_extension.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    naked = {
        "manifest_version": 3,
        "name": "x",
        "background": {"scripts": ["b.js"]},
        "permissions": [],
        "browser_specific_settings": {"gecko": {"id": "a@b"}},
    }
    problems = module.verify(naked)
    assert any("icons" in p for p in problems), (
        "a manifest with no icons passes verification")


def test_the_download_includes_the_icons(tmp_path):
    """The zip the operator actually receives must contain them."""
    root = _fixture_install(tmp_path, with_firefox=True)
    for firefox in (False, True):
        payload, _name, _info = build_zip(root, firefox=firefox)
        names = zipfile.ZipFile(io.BytesIO(payload)).namelist()
        for size in ICON_SIZES:
            assert f"icon{size}.png" in names, (
                f"icon{size}.png missing from the "
                f"{'firefox' if firefox else 'chromium'} download")
