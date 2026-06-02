from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANONICAL = REPO_ROOT / "skills" / "codex" / "spritecut-pipeline"
DEFAULT_MIRROR = REPO_ROOT / ".claude" / "skills" / "spritecut-pipeline"
DEFAULT_ROOTS = ("SKILL.md", "references", "agents", "assets")


@dataclass(frozen=True)
class SkillPackChange:
    action: str
    path: str

    def __str__(self) -> str:
        return f"{self.action}: {self.path}"


def _iter_files(base: Path, relative_roots: tuple[str, ...]) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for relative_root in relative_roots:
        root = base / relative_root
        if root.is_file():
            files[relative_root.replace("\\", "/")] = root
        elif root.is_dir():
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
                if path.is_file():
                    relative = path.relative_to(base).as_posix()
                    files[relative] = path
    return files


def compare_skill_packs(
    canonical: Path,
    mirror: Path,
    *,
    relative_roots: tuple[str, ...] = DEFAULT_ROOTS,
) -> list[SkillPackChange]:
    canonical_files = _iter_files(canonical, relative_roots)
    mirror_files = _iter_files(mirror, relative_roots)
    changes: list[SkillPackChange] = []
    for relative, source in canonical_files.items():
        target = mirror / relative
        if relative not in mirror_files:
            changes.append(SkillPackChange("add", relative))
        elif source.read_bytes() != target.read_bytes():
            changes.append(SkillPackChange("update", relative))
    for relative in sorted(set(mirror_files) - set(canonical_files)):
        changes.append(SkillPackChange("remove", relative))
    return changes


def sync_skill_pack(
    canonical: Path,
    mirror: Path,
    *,
    relative_roots: tuple[str, ...] = DEFAULT_ROOTS,
    apply: bool = False,
) -> list[SkillPackChange]:
    changes = compare_skill_packs(canonical, mirror, relative_roots=relative_roots)
    if not apply:
        return changes

    canonical_files = _iter_files(canonical, relative_roots)
    mirror_files = _iter_files(mirror, relative_roots)
    mirror.mkdir(parents=True, exist_ok=True)
    for relative, source in canonical_files.items():
        target = mirror / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for relative in sorted(set(mirror_files) - set(canonical_files)):
        target = mirror / relative
        target.unlink()
    return changes


def _parse_roots(raw: str) -> tuple[str, ...]:
    roots = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not roots:
        raise argparse.ArgumentTypeError("At least one relative root is required.")
    return roots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check or mirror the Codex SpriteCut skill pack into the Claude project skill pack.")
    parser.add_argument("--canonical", type=Path, default=DEFAULT_CANONICAL, help="Canonical skill directory. Defaults to skills/codex/spritecut-pipeline.")
    parser.add_argument("--mirror", type=Path, default=DEFAULT_MIRROR, help="Mirror skill directory. Defaults to .claude/skills/spritecut-pipeline.")
    parser.add_argument("--roots", type=_parse_roots, default=DEFAULT_ROOTS, help="Comma-separated relative files/directories to sync.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Return non-zero if the mirror differs.")
    mode.add_argument("--apply", action="store_true", help="Copy canonical files to the mirror and remove stale mirrored files.")
    args = parser.parse_args(argv)

    changes = sync_skill_pack(args.canonical, args.mirror, relative_roots=args.roots, apply=args.apply)
    if not changes:
        print("SpriteCut skill packs are in sync.")
        return 0

    for change in changes:
        print(change)
    if args.apply:
        print(f"Applied {len(changes)} change(s).")
        return 0
    print(f"{len(changes)} change(s) pending. Run with --apply to mirror them.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
