"""`make lint-language`: scan UI copy, prompts and templates for banned clinical words."""

import sys
from pathlib import Path

from backend.coach.language import find_banned

# User-facing text lives here. Tests are skipped because they quote banned words on purpose.
SCAN_ROOTS = (
    Path("frontend/src"),
    Path("backend/generation/prompts"),
    Path("backend/coach/templates"),
    Path("backend/coach/personas"),
)
SUFFIXES = {".ts", ".tsx", ".md", ".txt", ".yaml", ".yml", ".json", ".html"}


def _is_test(path: Path) -> bool:
    return ".test." in path.name or ".spec." in path.name or "__tests__" in path.parts


def scan(roots: tuple[Path, ...] = SCAN_ROOTS) -> int:
    count = 0
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES or _is_test(path):
                continue
            for v in find_banned(path.read_text(encoding="utf-8")):
                print(f"{path}:{v.line}:{v.column}: '{v.word}' is banned; use '{v.replacement}'")
                count += 1
    return count


def main() -> None:
    count = scan()
    if count:
        print(f"{count} banned word(s) found.")
        sys.exit(1)
    print("lint-language: ok")


if __name__ == "__main__":
    main()
