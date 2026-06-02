from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from tools.sprite_ide_api import run_ide_command


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATHS = [
    REPO_ROOT / "skills" / "codex" / "spritecut-pipeline" / "SKILL.md",
    REPO_ROOT / ".claude" / "skills" / "spritecut-pipeline" / "SKILL.md",
]
REFERENCE_NAMES = [
    "spritecut-commands.md",
    "spritecut-quality-checklist.md",
]
SAMPLE_PACK_FILES = [
    "sample_pack_manifest.json",
    "misaligned_sheet.png",
    "palette_swap_request.json",
    "autotile_request.json",
]


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(?P<body>.*?)\n---\n", text, flags=re.S)
    if match is None:
        raise AssertionError(f"Missing YAML frontmatter: {path}")
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    return values


def extract_json_blocks(markdown: str) -> list[dict[str, object]]:
    blocks = re.findall(r"```json\n(.*?)\n```", markdown, flags=re.S)
    return [json.loads(block) for block in blocks]


def write_fixture_sprite(path: Path) -> None:
    image = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    image.putpixel((7, 7), (0, 0, 0, 0))
    image.save(path)


def adapt_request_for_temp(command: dict[str, object], root: Path) -> dict[str, object]:
    adapted = copy.deepcopy(command)
    action = adapted.get("action")
    if not isinstance(action, str):
        return adapted

    source = root / "source.png"
    first = root / "first.png"
    second = root / "second.png"
    write_fixture_sprite(source)
    write_fixture_sprite(first)
    write_fixture_sprite(second)

    if "input" in adapted:
        adapted["input"] = str(source)
    if "inputs" in adapted:
        adapted["inputs"] = [str(first), str(second)]
    if "output" in adapted:
        adapted["output"] = str(root / f"{action.replace('.', '_')}.png")
        if action == "palette.extract":
            adapted["output"] = str(root / "palette_extract.json")
    if "output_dir" in adapted:
        adapted["output_dir"] = str(root / action.replace(".", "_"))
    if "package_dir" in adapted:
        adapted["package_dir"] = str(root / "edit_package")
    return adapted


class AgentSkillPackTests(unittest.TestCase):
    def test_codex_and_claude_skill_files_have_trigger_frontmatter(self) -> None:
        for path in SKILL_PATHS:
            with self.subTest(path=path):
                self.assertTrue(path.exists())
                data = frontmatter(path)
                self.assertEqual(data["name"], "spritecut-pipeline")
                self.assertIn("sprite sheets", data["description"])
                self.assertIn("misaligned", data["description"])
                self.assertIn("palette", data["description"])
                self.assertIn("autotile", data["description"])
                self.assertIn("IDE", data["description"])
                self.assertIn("Unity", data["description"])

    def test_codex_and_claude_skill_packs_stay_in_sync(self) -> None:
        codex_skill = SKILL_PATHS[0].read_text(encoding="utf-8")
        claude_skill = SKILL_PATHS[1].read_text(encoding="utf-8")
        self.assertEqual(codex_skill, claude_skill)
        for reference_name in REFERENCE_NAMES:
            codex_reference = (SKILL_PATHS[0].parent / "references" / reference_name).read_text(encoding="utf-8")
            claude_reference = (SKILL_PATHS[1].parent / "references" / reference_name).read_text(encoding="utf-8")
            self.assertEqual(codex_reference, claude_reference)
        for sample_name in SAMPLE_PACK_FILES:
            codex_sample = SKILL_PATHS[0].parent / "assets" / "sample-pack" / sample_name
            claude_sample = SKILL_PATHS[1].parent / "assets" / "sample-pack" / sample_name
            self.assertTrue(codex_sample.exists(), codex_sample)
            self.assertTrue(claude_sample.exists(), claude_sample)
            self.assertEqual(codex_sample.read_bytes(), claude_sample.read_bytes())

    def test_skill_bodies_cover_core_workflows_and_safety_rules(self) -> None:
        required = [
            "python tools\\sprite_sheet_tool_ui.py",
            "python tools\\cut_tileset_sprites.py",
            "python tools\\sprite_ide_api.py --request",
            "Review + Apply",
            "Aseprite",
            "references/spritecut-quality-checklist.md",
            "--auto-detect-all",
            "project.spritecut.json",
            "python -m unittest discover",
        ]
        for path in SKILL_PATHS:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                for needle in required:
                    self.assertIn(needle, text)

    def test_skill_reference_files_document_json_actions(self) -> None:
        for skill_path in SKILL_PATHS:
            reference = skill_path.parent / "references" / "spritecut-commands.md"
            with self.subTest(reference=reference):
                self.assertTrue(reference.exists())
                text = reference.read_text(encoding="utf-8")
                for action in [
                    "sprite.edit",
                    "sprite.batch_edit",
                    "palette.extract",
                    "palette.swap",
                    "palette.hue_shift",
                    "palette.variants",
                    "autotile.generate",
                ]:
                    self.assertIn(action, text)
                self.assertIn("max_colors", text)
                self.assertIn("ok\": false", text)
                self.assertIn("stdin", text.lower())

    def test_command_reference_json_examples_parse_and_match_ide_api(self) -> None:
        reference = SKILL_PATHS[0].parent / "references" / "spritecut-commands.md"
        examples = extract_json_blocks(reference.read_text(encoding="utf-8"))
        actions = [example.get("action") for example in examples if isinstance(example.get("action"), str)]
        self.assertEqual(
            actions,
            [
                "palette.extract",
                "palette.swap",
                "palette.hue_shift",
                "palette.variants",
                "sprite.edit",
                "sprite.batch_edit",
                "autotile.generate",
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for example in examples:
                if not isinstance(example.get("action"), str):
                    continue
                with self.subTest(action=example["action"]):
                    result = run_ide_command(adapt_request_for_temp(example, root))
                    self.assertEqual(result["ok"], True)
                    self.assertEqual(result["action"], example["action"])

    def test_quality_checklist_covers_review_safety_and_handoff(self) -> None:
        required = [
            "Do not overwrite source art",
            "manifest\\report.html",
            "low-confidence",
            "needs_review",
            "palette.extract",
            "autotile.generate",
            "applied_project\\import_plans",
            "python tools\\sprite_ide_api.py --help",
        ]
        for skill_path in SKILL_PATHS:
            checklist = skill_path.parent / "references" / "spritecut-quality-checklist.md"
            with self.subTest(checklist=checklist):
                self.assertTrue(checklist.exists())
                text = checklist.read_text(encoding="utf-8")
                for needle in required:
                    self.assertIn(needle, text)

    def test_openai_interface_metadata_is_specific_and_invocable(self) -> None:
        for skill_path in SKILL_PATHS:
            metadata = skill_path.parent / "agents" / "openai.yaml"
            with self.subTest(metadata=metadata):
                self.assertTrue(metadata.exists())
                text = metadata.read_text(encoding="utf-8")
                self.assertIn('display_name: "SpriteCut Pipeline"', text)
                self.assertIn("$spritecut-pipeline", text)
                self.assertIn("misaligned sprite sheets", text)

    def test_sync_tool_reports_current_skill_packs_in_sync(self) -> None:
        from tools.sync_spritecut_skills import compare_skill_packs

        changes = compare_skill_packs(
            SKILL_PATHS[0].parent,
            SKILL_PATHS[1].parent,
            relative_roots=("SKILL.md", "references", "agents", "assets"),
        )
        self.assertEqual(changes, [])

    def test_sync_tool_can_copy_canonical_pack_to_mirror(self) -> None:
        from tools.sync_spritecut_skills import compare_skill_packs, sync_skill_pack

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            mirror = root / "mirror"
            (canonical / "references").mkdir(parents=True)
            (canonical / "assets" / "sample-pack").mkdir(parents=True)
            (mirror / "references").mkdir(parents=True)
            (canonical / "SKILL.md").write_text("canonical skill\n", encoding="utf-8")
            (canonical / "references" / "guide.md").write_text("guide\n", encoding="utf-8")
            (canonical / "assets" / "sample-pack" / "request.json").write_text('{"action":"palette.extract"}\n', encoding="utf-8")
            (mirror / "SKILL.md").write_text("old skill\n", encoding="utf-8")
            (mirror / "references" / "stale.md").write_text("stale\n", encoding="utf-8")

            planned = compare_skill_packs(canonical, mirror, relative_roots=("SKILL.md", "references", "assets"))
            self.assertGreaterEqual(len(planned), 2)
            sync_skill_pack(canonical, mirror, relative_roots=("SKILL.md", "references", "assets"), apply=True)

            self.assertEqual(compare_skill_packs(canonical, mirror, relative_roots=("SKILL.md", "references", "assets")), [])
            self.assertFalse((mirror / "references" / "stale.md").exists())


if __name__ == "__main__":
    unittest.main()
