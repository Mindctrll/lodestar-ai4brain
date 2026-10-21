"""Najma's readable notes: `memory/<user_id>/core.md` and `journal/<date>.md` (docs/plan/04).

The only files Najma writes. Users can read and edit them in Memory & data; writes are atomic
(temp file, then rename).
"""

import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from uuid import UUID

CORE_HEADER = "# Core memory\n"


class Notes:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _dir(self, user_id: UUID) -> Path:
        return self.root / str(user_id)

    def core_path(self, user_id: UUID) -> Path:
        return self._dir(user_id) / "core.md"

    def journal_path(self, user_id: UUID, day: date) -> Path:
        return self._dir(user_id) / "journal" / f"{day.isoformat()}.md"

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def read_core(self, user_id: UUID) -> list[str]:
        path = self.core_path(user_id)
        if not path.exists():
            return []
        return [
            line[2:].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("- ")
        ]

    def write_core(self, user_id: UUID, lines: list[str]) -> None:
        body = "".join(f"- {line.strip()}\n" for line in lines if line.strip())
        self._atomic_write(self.core_path(user_id), CORE_HEADER + body)

    def remove_core_line(self, user_id: UUID, line: str) -> bool:
        lines = self.read_core(user_id)
        kept = [x for x in lines if x != line.strip()]
        if len(kept) == len(lines):
            return False
        self.write_core(user_id, kept)
        return True

    def append_journal(self, user_id: UUID, day: date, entry: str) -> None:
        path = self.journal_path(user_id, day)
        existing = (
            path.read_text(encoding="utf-8") if path.exists() else f"# Journal, {day.isoformat()}\n"
        )
        self._atomic_write(path, existing + f"\n{entry.strip()}\n")

    def read_journal(self, user_id: UUID, day: date) -> str | None:
        path = self.journal_path(user_id, day)
        return path.read_text(encoding="utf-8") if path.exists() else None

    def delete_user(self, user_id: UUID) -> int:
        """Remove all of a user's notes. Returns how many files were deleted."""
        folder = self._dir(user_id)
        if not folder.exists():
            return 0
        count = sum(1 for p in folder.rglob("*") if p.is_file())
        shutil.rmtree(folder)
        return count
