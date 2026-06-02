from __future__ import annotations

import colorsys
import hashlib
import html
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def _safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return re.sub(r"_+", "_", value).strip("_")


def _render_checker(size: tuple[int, int], cell: int = 8) -> Image.Image:
    width, height = size
    checker = Image.new("RGBA", size, (236, 236, 236, 255))
    draw = ImageDraw.Draw(checker)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, min(x + cell - 1, width), min(y + cell - 1, height)), fill=(210, 210, 210, 255))
    return checker


def relative_link(from_dir: Path, target: Path) -> str:
    return Path(os.path.relpath(Path(target).resolve(), start=from_dir.resolve())).as_posix()


def render_main_report_html(
    records: Sequence[Any],
    manifest_dir: Path,
    sheets_processed: int,
    sheet_errors: Sequence[Any],
    animation_clips: list[dict[str, object]] | None = None,
) -> str:
    category_counts = Counter(record.category for record in records)
    kind_counts = Counter(record.kind for record in records)
    sheet_counts = Counter(record.source_sheet for record in records)
    flag_counts = Counter(flag for record in records for flag in record.review_flags)
    partial_count = sum(1 for record in records if record.is_partial)
    needs_review_count = sum(1 for record in records if record.review_status == "needs_review")
    atlased_count = sum(1 for record in records if record.atlas)
    atlas_names = sorted({str(record.atlas["atlas"]) for record in records if record.atlas})
    sample_records = records[:80]

    rows = []
    thumb_cards = []
    clip_cards = []
    for clip in animation_clips or []:
        frames_html = []
        frames = clip.get("frames", [])
        if isinstance(frames, list):
            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                source_file = frame.get("source_file")
                if not source_file:
                    continue
                frame_link = html.escape(relative_link(manifest_dir, Path(str(source_file))))
                frames_html.append(
                    "<a class=\"clip-frame\" href=\"{href}\">"
                    "<img src=\"{href}\" loading=\"lazy\" alt=\"{alt}\">"
                    "<span>{label}</span>"
                    "</a>".format(
                        href=frame_link,
                        alt=html.escape(str(frame.get("sprite", "frame"))),
                        label=html.escape(str(frame.get("frame", frame.get("sprite", "")))),
                    )
                )
        clip_cards.append(
            "<section class=\"card clip-card\" data-clip=\"{clip_name}\">"
            "<h3>{clip_name}</h3>"
            "<p>{frame_count} frames | {frame_rate} fps | loop={loop}</p>"
            "<div class=\"clip-strip\">{frames}</div>"
            "</section>".format(
                clip_name=html.escape(str(clip.get("name", "clip"))),
                frame_count=html.escape(str(clip.get("frame_count", 0))),
                frame_rate=html.escape(str(clip.get("frame_rate", ""))),
                loop=html.escape(str(clip.get("loop", ""))),
                frames="".join(frames_html),
            )
        )
    for record in records:
        preview_link = html.escape(relative_link(manifest_dir, Path(record.output_file)))
        safe_id = html.escape(record.id)
        safe_category = html.escape(record.category)
        safe_flags = html.escape(" ".join(record.review_flags))
        safe_status = html.escape(record.review_status)
        atlas_name = html.escape(str(record.atlas.get("atlas", ""))) if record.atlas else ""
        thumb_cards.append(
            "<a class=\"thumb-card\" href=\"{href}\" data-status=\"{status}\" data-flags=\"{flags}\" data-category=\"{category}\">"
            "<span class=\"thumb-frame\"><img src=\"{href}\" loading=\"lazy\" alt=\"{alt}\"></span>"
            "<span class=\"thumb-name\">{name}</span>"
            "<span class=\"thumb-meta\">{category} | {width}x{height} | {status}</span>"
            "</a>".format(
                href=preview_link,
                alt=safe_id,
                name=html.escape(record.display_name),
                category=safe_category,
                flags=safe_flags,
                width=record.width,
                height=record.height,
                status=safe_status,
            )
        )

    for record in sample_records:
        preview_link = html.escape(relative_link(manifest_dir, Path(record.output_file)))
        safe_category = html.escape(record.category)
        atlas_name = html.escape(str(record.atlas.get("atlas", ""))) if record.atlas else ""
        rows.append(
            "<tr>"
            f"<td><a href=\"{preview_link}\">{html.escape(record.display_name)}</a></td>"
            f"<td>{safe_category}</td>"
            f"<td>{html.escape(record.kind)}</td>"
            f"<td>{record.width}x{record.height}</td>"
            f"<td>{html.escape(str(record.is_partial))}</td>"
            f"<td>{record.confidence:.3f}</td>"
            f"<td>{html.escape(', '.join(record.review_flags) or 'none')}</td>"
            f"<td>{html.escape(str(record.pivot.get('x', '')))}, {html.escape(str(record.pivot.get('y', '')))}</td>"
            f"<td>{atlas_name}</td>"
            "</tr>"
        )

    category_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(category_counts.items()))
    kind_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(kind_counts.items()))
    sheet_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(sheet_counts.items()))
    flag_items = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(flag_counts.items())) or "<li>None</li>"
    atlas_items = "".join(f"<li>{html.escape(name)}</li>" for name in atlas_names) or "<li>None</li>"
    error_items = (
        "".join(f"<li>{html.escape(Path(error.source_file).name)}: {html.escape(error.error)}</li>" for error in sheet_errors)
        or "<li>None</li>"
    )

    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Sprite Sheet Processing Report</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #15171c; color: #e8ebf2; }}
    a {{ color: #80b7ff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }}
    .card {{ background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 14px; }}
    .filters {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 12px 0; }}
    .filters input, .filters select {{ background: #111318; color: #e8ebf2; border: 1px solid #343a46; border-radius: 4px; padding: 7px; }}
    .thumb-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; margin-top: 12px; }}
    .thumb-card {{ display: grid; gap: 7px; color: #e8ebf2; text-decoration: none; background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 10px; min-width: 0; }}
    .thumb-card:hover {{ border-color: #80b7ff; }}
    .thumb-card.hidden {{ display: none; }}
    .thumb-frame {{ display: grid; place-items: center; height: 96px; border-radius: 4px; background-color: #2a2f39; background-image: linear-gradient(45deg, #39404c 25%, transparent 25%), linear-gradient(-45deg, #39404c 25%, transparent 25%), linear-gradient(45deg, transparent 75%, #39404c 75%), linear-gradient(-45deg, transparent 75%, #39404c 75%); background-size: 16px 16px; background-position: 0 0, 0 8px, 8px -8px, -8px 0; }}
    .thumb-frame img {{ max-width: 96%; max-height: 90px; image-rendering: pixelated; }}
    .thumb-name {{ overflow-wrap: anywhere; font-size: 12px; }}
    .thumb-meta {{ color: #aeb8cc; font-size: 12px; }}
    .clip-strip {{ display: flex; gap: 8px; overflow-x: auto; padding-bottom: 4px; }}
    .clip-frame {{ display: grid; gap: 4px; min-width: 72px; color: #e8ebf2; text-decoration: none; text-align: center; font-size: 12px; }}
    .clip-frame img {{ max-width: 72px; max-height: 72px; image-rendering: pixelated; background: #2a2f39; border-radius: 4px; padding: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #343a46; padding: 8px; text-align: left; font-size: 13px; }}
    th {{ color: #aeb8cc; }}
    ul {{ margin: 8px 0 0; padding-left: 20px; }}
  </style>
</head>
<body>
  <h1>Sprite Sheet Processing Report</h1>
  <div class="grid">
    <section class="card">
      <h2>Run Summary</h2>
      <p>total_sprites: {len(records)}</p>
      <p>sheets_processed: {sheets_processed}</p>
      <p>sheets_failed: {len(sheet_errors)}</p>
      <p>partial_sprites: {partial_count}</p>
      <p>needs_review: {needs_review_count}</p>
      <p>atlased_sprites: {atlased_count}</p>
      <p>atlases: {len(atlas_names)}</p>
      <p><a href="../project.spritecut.json">project.spritecut.json</a></p>
      <p><a href="settings.json">settings.json</a></p>
      <p><a href="visual_qa.html">visual_qa.html</a></p>
    </section>
    <section class="card"><h2>By Kind</h2><ul>{kind_items}</ul></section>
    <section class="card"><h2>By Category</h2><ul>{category_items}</ul></section>
    <section class="card"><h2>By Sheet</h2><ul>{sheet_items}</ul></section>
    <section class="card"><h2>Review Flags</h2><ul>{flag_items}</ul></section>
    <section class="card"><h2>Atlases</h2><ul>{atlas_items}</ul></section>
    <section class="card"><h2>Errors</h2><ul>{error_items}</ul></section>
  </div>
  <h2>Sprite Preview</h2>
  <section class="filters" aria-label="Review Filters">
    <strong>Review Filters</strong>
    <select id="statusFilter" onchange="filterSprites()">
      <option value="all">All statuses</option>
      <option value="needs_review">Needs review</option>
      <option value="approved">Approved</option>
    </select>
    <input id="flagFilter" type="search" placeholder="flag or category" oninput="filterSprites()">
  </section>
  <div class="thumb-grid">
    {''.join(thumb_cards)}
  </div>
  <h2>Animation Clips</h2>
  <div class="grid">
    {''.join(clip_cards) or '<section class="card"><p>No animation clips.</p></section>'}
  </div>
  <h2>Sample Records</h2>
  <table>
    <thead><tr><th>Name</th><th>Category</th><th>Kind</th><th>Size</th><th>Partial</th><th>Confidence</th><th>Flags</th><th>Pivot</th><th>Atlas</th></tr></thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
  <script>
    function filterSprites() {{
      const status = document.getElementById("statusFilter").value;
      const query = document.getElementById("flagFilter").value.trim().toLowerCase();
      for (const card of document.querySelectorAll(".thumb-card")) {{
        const statusOk = status === "all" || card.dataset.status === status;
        const haystack = `${{card.dataset.flags}} ${{card.dataset.category}} ${{card.textContent}}`.toLowerCase();
        const queryOk = !query || haystack.includes(query);
        card.classList.toggle("hidden", !(statusOk && queryOk));
      }}
    }}
  </script>
</body>
</html>
"""
    return report



def write_html_report(
    records: Sequence[Any],
    manifest_dir: Path,
    sheets_processed: int,
    sheet_errors: Sequence[Any],
    animation_clips: list[dict[str, object]] | None = None,
) -> None:
    report = render_main_report_html(records, manifest_dir, sheets_processed, sheet_errors, animation_clips)
    (manifest_dir / "report.html").write_text(report, encoding="utf-8")

def write_visual_regression_report(out_dir: Path, manifest_dir: Path) -> None:
    preview_dir = out_dir / "previews"
    artifacts: list[dict[str, object]] = []
    if preview_dir.exists():
        for path in sorted(preview_dir.rglob("*.png"), key=lambda item: item.as_posix().lower()):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts.append(
                {
                    "file": relative_link(manifest_dir, path),
                    "sha256": digest,
                    "bytes": path.stat().st_size,
                }
            )
    with (manifest_dir / "visual_regression.json").open("w", encoding="utf-8") as handle:
        json.dump({"preview_artifacts": artifacts}, handle, indent=2)


def _safe_open_sprite(path: str) -> Image.Image | None:
    try:
        with Image.open(path) as image:
            return image.convert("RGBA").copy()
    except Exception:
        return None


def _hue_shift_preview(image: Image.Image, degrees: float) -> Image.Image:
    rgba = image.convert("RGBA")
    data = np.array(rgba, dtype=np.uint8)
    alpha = data[:, :, 3]
    height, width = alpha.shape
    shift = (degrees % 360.0) / 360.0
    for y in range(height):
        for x in range(width):
            if alpha[y, x] == 0:
                continue
            r, g, b = data[y, x, :3] / 255.0
            h, s, v = colorsys.rgb_to_hsv(float(r), float(g), float(b))
            nr, ng, nb = colorsys.hsv_to_rgb((h + shift) % 1.0, s, v)
            data[y, x, 0] = int(round(nr * 255))
            data[y, x, 1] = int(round(ng * 255))
            data[y, x, 2] = int(round(nb * 255))
    return Image.fromarray(data, "RGBA")


def _parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        return (0, 0, 0)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _draw_label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    draw.text(xy, text, fill=(32, 34, 40), font=ImageFont.load_default())


def _write_palette_change_sample(record: Any, out_path: Path) -> bool:
    source = _safe_open_sprite(record.output_file)
    if source is None:
        return False
    variants = [
        ("original", source),
        ("hue +90", _hue_shift_preview(source, 90)),
        ("hue +180", _hue_shift_preview(source, 180)),
    ]
    max_thumb = 72
    label_height = 18
    swatch_height = 20
    cell_w = max_thumb + 18
    cell_h = max_thumb + label_height + swatch_height + 18
    sheet = Image.new("RGBA", (cell_w * len(variants), cell_h), (248, 248, 248, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (label, image) in enumerate(variants):
        thumb = image.copy()
        thumb.thumbnail((max_thumb, max_thumb), Image.Resampling.NEAREST)
        x = index * cell_w
        checker = _render_checker((max_thumb, max_thumb))
        sheet.alpha_composite(checker, (x + 9, 8))
        sheet.alpha_composite(thumb, (x + 9 + (max_thumb - thumb.width) // 2, 8 + (max_thumb - thumb.height) // 2))
        _draw_label(draw, (x + 8, max_thumb + 12), label)
        for color_index, color in enumerate(record.dominant_colors[:4]):
            sx = x + 8 + color_index * 16
            sy = max_thumb + label_height + 13
            draw.rectangle((sx, sy, sx + 12, sy + 12), fill=_parse_hex_color(color), outline=(48, 52, 60))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path)
    return True


def _erase_autotile_edges(tile: Image.Image, mask: int, edge_width: int) -> Image.Image:
    output = tile.convert("RGBA").copy()
    draw = ImageDraw.Draw(output)
    width, height = output.size
    edge_width = max(1, edge_width)
    transparent = (0, 0, 0, 0)
    if not mask & 1:
        draw.rectangle((0, 0, width - 1, edge_width - 1), fill=transparent)
    if not mask & 4:
        draw.rectangle((0, height - edge_width, width - 1, height - 1), fill=transparent)
    if not mask & 8:
        draw.rectangle((0, 0, edge_width - 1, height - 1), fill=transparent)
    if not mask & 2:
        draw.rectangle((width - edge_width, 0, width - 1, height - 1), fill=transparent)
    return output


def _write_autotile_variant_sample(record: Any, out_path: Path) -> bool:
    source = _safe_open_sprite(record.output_file)
    if source is None:
        return False
    tile = source.copy()
    tile.thumbnail((32, 32), Image.Resampling.NEAREST)
    if tile.width == 0 or tile.height == 0:
        return False
    edge_width = max(1, min(tile.width, tile.height) // 4)
    cell_w = tile.width + 6
    cell_h = tile.height + 16
    sheet = Image.new("RGBA", (cell_w * 4, cell_h * 4), (248, 248, 248, 255))
    draw = ImageDraw.Draw(sheet)
    for mask in range(16):
        col = mask % 4
        row = mask // 4
        x = col * cell_w
        y = row * cell_h
        checker = _render_checker(tile.size, cell=4)
        variant = _erase_autotile_edges(tile, mask, edge_width)
        sheet.alpha_composite(checker, (x + 3, y + 3))
        sheet.alpha_composite(variant, (x + 3, y + 3))
        _draw_label(draw, (x + 3, y + tile.height + 5), f"{mask:02d}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(out_path)
    return True


def render_visual_qa_html(
    before_after_cards: Sequence[str],
    flagged_rows: str,
    palette_cards: str,
    autotile_cards: str,
) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Visual QA Review</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #15171c; color: #e8ebf2; }}
    a {{ color: #80b7ff; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .card, .sample-card {{ background: #20242b; border: 1px solid #343a46; border-radius: 6px; padding: 14px; color: #e8ebf2; text-decoration: none; }}
    .pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .pair a, .sample-card {{ display: grid; gap: 8px; min-width: 0; }}
    img {{ max-width: 100%; image-rendering: pixelated; background: #2a2f39; border-radius: 4px; }}
    .samples {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }}
    small {{ color: #aeb8cc; overflow-wrap: anywhere; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; }}
    th, td {{ border-bottom: 1px solid #343a46; padding: 8px; text-align: left; font-size: 13px; }}
    th {{ color: #aeb8cc; }}
  </style>
</head>
<body>
  <h1>Visual QA Review</h1>
  <p><a href="report.html">Back to main report</a> | <a href="visual_qa.json">visual_qa.json</a></p>
  <h2>Before / After Crop Sheets</h2>
  <div class="grid">{''.join(before_after_cards) or '<section class="card"><p>No crop sheet previews found.</p></section>'}</div>
  <h2>Flagged Crop Issues</h2>
  <table>
    <thead><tr><th>Sprite</th><th>Category</th><th>Flags</th><th>Confidence</th><th>Source Sheet</th></tr></thead>
    <tbody>{flagged_rows or '<tr><td colspan="5">No flagged crop issues.</td></tr>'}</tbody>
  </table>
  <h2>Palette Change Samples</h2>
  <div class="samples">{palette_cards or '<section class="card"><p>No palette samples generated.</p></section>'}</div>
  <h2>Autotile Variant Samples</h2>
  <div class="samples">{autotile_cards or '<section class="card"><p>No autotile samples generated.</p></section>'}</div>
</body>
</html>
"""


def write_visual_qa_report(records: Sequence[Any], out_dir: Path, manifest_dir: Path) -> None:
    preview_dir = out_dir / "previews"
    qa_dir = preview_dir / "visual_qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    before_after_sheets: list[dict[str, str]] = []
    for sheet_name in sorted({record.source_sheet for record in records}):
        boxes = preview_dir / f"{sheet_name}_boxes.png"
        contact = preview_dir / f"{sheet_name}_contact.png"
        if boxes.exists() or contact.exists():
            before_after_sheets.append(
                {
                    "sheet": sheet_name,
                    "before": relative_link(manifest_dir, boxes) if boxes.exists() else "",
                    "after": relative_link(manifest_dir, contact) if contact.exists() else "",
                }
            )

    flagged_records = [record for record in records if record.review_status == "needs_review" or record.review_flags]
    flagged_crop_issues = [
        {
            "id": record.id,
            "category": record.category,
            "flags": record.review_flags,
            "confidence": record.confidence,
            "sprite": relative_link(manifest_dir, Path(record.output_file)),
            "source_sheet": record.source_sheet,
        }
        for record in flagged_records[:80]
    ]

    palette_change_samples: list[dict[str, str]] = []
    for record in records[:8]:
        sample_path = qa_dir / f"{_safe_name(record.id)}_palette_changes.png"
        if _write_palette_change_sample(record, sample_path):
            palette_change_samples.append(
                {
                    "id": record.id,
                    "sample": relative_link(manifest_dir, sample_path),
                    "dominant_colors": ", ".join(record.dominant_colors),
                }
            )

    autotile_variant_samples: list[dict[str, str]] = []
    autotile_candidates = [record for record in records if record.kind == "sprite"][:4]
    for record in autotile_candidates:
        sample_path = qa_dir / f"{_safe_name(record.id)}_autotile_16.png"
        if _write_autotile_variant_sample(record, sample_path):
            autotile_variant_samples.append(
                {
                    "id": record.id,
                    "sample": relative_link(manifest_dir, sample_path),
                    "mode": "cardinal_16",
                }
            )

    manifest = {
        "before_after_sheets": before_after_sheets,
        "flagged_crop_issues": flagged_crop_issues,
        "palette_change_samples": palette_change_samples,
        "autotile_variant_samples": autotile_variant_samples,
    }
    (manifest_dir / "visual_qa.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    before_after_cards = []
    for item in before_after_sheets:
        before = html.escape(item["before"])
        after = html.escape(item["after"])
        before_after_cards.append(
            "<section class=\"card before-after\">"
            f"<h3>{html.escape(item['sheet'])}</h3>"
            "<div class=\"pair\">"
            f"<a href=\"{before}\"><span>Before</span><img src=\"{before}\" loading=\"lazy\" alt=\"before boxes\"></a>"
            f"<a href=\"{after}\"><span>After</span><img src=\"{after}\" loading=\"lazy\" alt=\"after contact sheet\"></a>"
            "</div></section>"
        )

    flagged_rows = "".join(
        "<tr>"
        f"<td><a href=\"{html.escape(item['sprite'])}\">{html.escape(item['id'])}</a></td>"
        f"<td>{html.escape(item['category'])}</td>"
        f"<td>{html.escape(', '.join(item['flags']) or 'none')}</td>"
        f"<td>{html.escape(str(item['confidence']))}</td>"
        f"<td>{html.escape(item['source_sheet'])}</td>"
        "</tr>"
        for item in flagged_crop_issues
    )
    palette_cards = "".join(
        "<a class=\"sample-card\" href=\"{sample}\"><img src=\"{sample}\" loading=\"lazy\" alt=\"palette sample\"><span>{label}</span><small>{colors}</small></a>".format(
            sample=html.escape(item["sample"]),
            label=html.escape(item["id"]),
            colors=html.escape(item["dominant_colors"]),
        )
        for item in palette_change_samples
    )
    autotile_cards = "".join(
        "<a class=\"sample-card\" href=\"{sample}\"><img src=\"{sample}\" loading=\"lazy\" alt=\"autotile sample\"><span>{label}</span><small>{mode}</small></a>".format(
            sample=html.escape(item["sample"]),
            label=html.escape(item["id"]),
            mode=html.escape(item["mode"]),
        )
        for item in autotile_variant_samples
    )

    report = render_visual_qa_html(before_after_cards, flagged_rows, palette_cards, autotile_cards)
    (manifest_dir / "visual_qa.html").write_text(report, encoding="utf-8")


