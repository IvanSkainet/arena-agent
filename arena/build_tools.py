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
            for source in sorted((root / name).iterdir()):
                if source.is_file() and not source.is_symlink():
                    target = destination / name / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self.copy_file(str(source), str(target))
                    if name == "bin" and source.name == "sd-exec":
                        target.chmod(target.stat().st_mode | 0o111)
