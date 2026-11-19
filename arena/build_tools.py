"""Include executable compatibility resources in wheels as well as source ZIPs."""
from __future__ import annotations

from pathlib import Path

from setuptools.command.build_py import build_py


class BuildWithTools(build_py):
    def run(self) -> None:
        super().run()
        root = Path(__file__).resolve().parent.parent
        destination = Path(self.build_lib) / "arena" / "_executables"
        for name in ("bin", "scripts"):
            self._copy_tools(root / name, destination / name)

    def _copy_tools(self, source_directory: Path, destination: Path) -> None:
        for source in sorted(source_directory.iterdir()):
            if not source.is_file() or source.is_symlink():
                continue
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / source.name
            self.copy_file(str(source), str(target))
            if self.dry_run:
                continue
            if (source_directory.name, source.name) == ("bin", "sd-exec"):
                target.chmod(target.stat().st_mode | 0o111)
