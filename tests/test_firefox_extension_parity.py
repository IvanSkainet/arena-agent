"""T66: the checked-in Firefox tree must remain generated from Chromium."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from arena.governance import firefox_tree_parity as parity

ROOT = Path(__file__).resolve().parents[1]


def _trees(tmp_path: Path):
    source = tmp_path / "chrome"
    target = tmp_path / "firefox"
    source.mkdir()
    target.mkdir()
    (source / "manifest.json").write_text("{}\n", encoding="utf-8")
    (source / "app.js").write_bytes(b"const x = 1;\r\n")
    (source / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (source / "ignored.zip").write_bytes(b"not generated")
    (source / "UPPER.ZIP").write_bytes(b"not generated")
    (source / "archive.zip").mkdir()
    (source / "archive.zip" / "ignored.js").write_text(
        "not generated\n", encoding="utf-8"
    )
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "ignored.py").write_text(
        "not generated\n", encoding="utf-8"
    )
    generated_manifest = {"manifest_version": 3, "name": "Firefox Я"}
    (target / "manifest.json").write_text(
        json.dumps(generated_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (target / "app.js").write_bytes(b"const x = 1;\n")
    (target / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return source, target, generated_manifest


def test_parity_accepts_only_line_ending_differences(tmp_path: Path) -> None:
    source, target, manifest = _trees(tmp_path)
    assert parity.verify_generated_tree(source, target, manifest) == []
    assert parity.tree_files(source) == {
        "app.js", "icon.png", "manifest.json",
    }
    assert parity._TEXT_SUFFIXES == {
        ".css", ".html", ".js", ".json", ".md",
    }
    assert parity.ignored_names(
        str(source),
        ["ignored.zip", "UPPER.ZIP", "archive.zip", "__pycache__", "keep.js"],
    ) == {"ignored.zip", "UPPER.ZIP", "archive.zip", "__pycache__"}


def test_parity_reports_missing_extra_content_and_manifest_drift(
    tmp_path: Path,
) -> None:
    source, target, manifest = _trees(tmp_path)
    (target / "app.js").unlink()
    (target / "extra.js").write_text("extra\n", encoding="utf-8")
    (target / "icon.png").write_bytes(b"different")
    (source / "payload.bin").write_bytes(b"\r\n")
    (target / "payload.bin").write_bytes(b"\n")
    (target / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert parity.verify_generated_tree(source, target, manifest) == [
        "missing generated file: app.js",
        "unexpected generated file: extra.js",
        "generated file drifted: icon.png",
        "generated file drifted: payload.bin",
        "generated Firefox manifest drifted",
    ]


def test_parity_rejects_source_and_generated_symlinks(
    tmp_path: Path, monkeypatch
) -> None:
    source, target, manifest = _trees(tmp_path)
    source_link = source / "link.js"
    target_link = target / "link.js"
    source_link.write_text("source\n", encoding="utf-8")
    target_link.write_text("target\n", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path in {source_link, target_link} or original(path),
    )
    assert parity.verify_generated_tree(source, target, manifest) == [
        "symlink not allowed in Chromium source: link.js",
        "symlink not allowed in generated Firefox tree: link.js",
    ]


def test_parity_reports_absent_target_tree(tmp_path: Path) -> None:
    source, target, manifest = _trees(tmp_path)
    for path in sorted(target.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    target.rmdir()
    assert parity.verify_generated_tree(source, target, manifest) == [
        "missing generated file: app.js",
        "missing generated file: icon.png",
        "missing generated file: manifest.json",
    ]


def test_real_checked_in_firefox_tree_matches_generator() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_firefox_extension.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "firefox build matches Chromium source" in result.stdout
