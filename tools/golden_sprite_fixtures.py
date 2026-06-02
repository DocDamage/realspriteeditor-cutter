from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


def _write_animation_sheet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (150, 96), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    for x, y, w, h in [(6, 10, 17, 25), (48, 7, 19, 28), (96, 12, 18, 23)]:
        draw.rectangle((x, y, x + w, y + h), fill=(90, 120, 210, 255))
        draw.rectangle((x + 4, y - 3, x + 9, y + 2), fill=(60, 80, 180, 255))
    for x, y, w, h in [(5, 58, 24, 18), (49, 55, 22, 23), (94, 60, 26, 17)]:
        draw.rectangle((x, y, x + w, y + h), fill=(210, 120, 80, 255))
        draw.rectangle((x + 2, y + h + 1, x + 7, y + h + 4), fill=(140, 70, 50, 255))
    image.save(path)


def _write_dark_props_sheet(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGBA", (140, 96), (20, 20, 20, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 10, 40, 42), fill=(210, 60, 50, 255))
    draw.rectangle((62, 8, 104, 44), fill=(45, 170, 90, 255))
    draw.rectangle((28, 62, 82, 86), fill=(220, 180, 70, 255))
    image.save(path)


def create_golden_pack(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _write_animation_sheet(root / "transparent_animation_rows" / "hero.png")
    _write_dark_props_sheet(root / "packed_props_dark_bg" / "props.png")
    expected = {
        "schema_version": 1,
        "cases": {
            "transparent_animation_rows": {
                "preset": "transparent_animation_rows",
                "summary": {"total_sprites": 6, "sheets_processed": 1, "sheets_failed": 0},
            },
            "packed_props_dark_bg": {
                "preset": "packed_props_dark_bg",
                "summary": {"total_sprites": 3, "sheets_processed": 1, "sheets_failed": 0},
            },
        },
    }
    expected_path = root / "expected_golden.json"
    expected_path.write_text(json.dumps(expected, indent=2), encoding="utf-8")
    return expected_path


def _read_summary(path: Path) -> dict[str, int]:
    summary_path = path / "manifest" / "summary.txt"
    values: dict[str, int] = {}
    for line in summary_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        try:
            values[key] = int(raw_value)
        except ValueError:
            continue
    return values


def verify_golden_output(out_dir: Path, expected_path: Path, case_name: str) -> dict[str, Any]:
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    case = expected.get("cases", {}).get(case_name)
    if not isinstance(case, dict):
        raise ValueError(f"Unknown golden case: {case_name}")
    expected_summary = case.get("summary", {})
    actual_summary = _read_summary(out_dir)
    mismatches = {}
    for key, expected_value in expected_summary.items():
        actual_value = actual_summary.get(str(key))
        if actual_value != expected_value:
            mismatches[str(key)] = {"expected": expected_value, "actual": actual_value}
    return {"status": "pass" if not mismatches else "fail", "case": case_name, "mismatches": mismatches}
