"""
Orchestrator — you shouldn't need to edit this file. It:
  1. Reads every *.json task file from /app/input (source + target_canvas)
  2. Calls your resize() from resize.py
  3. Runs a quick self-check (structural only — NOT the official scoring;
     see RULES.md for what the judge actually checks)
  4. Writes <task>_output.json and <task>_output.png to /app/output

Mirrors the same input/ -> output/ convention as the earlier India-program
challenges: drop task files in, get one JSON + one PNG out per task, no
manual steps in between.
"""

import json
import math
import sys
import time
from pathlib import Path

from engine.resize import resize

# Relative to the current working directory, which is /app both inside the
# Docker image (WORKDIR /app) and when run locally from this repo's root -
# so this works identically in both "python -m engine.main" (no Docker) and
# the containerized entrypoint.
INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
ASSETS_DIR = Path("brand_kit/assets")

REQUIRED_COMMON = ["id", "type", "x", "y", "width", "height"]
REQUIRED_BY_TYPE = {
    "text": ["content", "font_family", "font_size", "color"],
    "image": ["asset_id"],
    "shape": ["shape_type", "fill_color"],
}


def self_check(source: dict, output: dict) -> list[str]:
    """Quick, non-authoritative sanity check so obvious mistakes are caught
    locally before you submit. This is NOT the official scorer — see
    RULES.md for what actually gates and grades your submission."""
    problems = []

    if "canvas" not in output or "elements" not in output:
        return ["output is missing top-level 'canvas' or 'elements'"]

    src_elements = source.get("elements", [])
    out_elements = output.get("elements", [])
    src_ids = [el.get("id") for el in src_elements]
    out_ids = [el.get("id") for el in out_elements]
    if len(src_ids) != len(out_ids):
        problems.append(
            f"element count changed from {len(src_ids)} to {len(out_ids)}"
        )
    src_id_set, out_id_set = set(src_ids), set(out_ids)
    if src_id_set != out_id_set:
        problems.append(
            f"element id mismatch — missing {sorted(src_id_set - out_id_set)}, "
            f"unexpected {sorted(out_id_set - src_id_set)}"
        )
    if len(out_ids) != len(out_id_set):
        problems.append("output contains duplicate element ids")

    cw, ch = output["canvas"].get("width"), output["canvas"].get("height")
    output_by_id = {el.get("id"): el for el in out_elements if isinstance(el, dict)}
    for el in out_elements:
        if not isinstance(el, dict):
            problems.append("output contains a non-object element")
            continue
        for field in REQUIRED_COMMON:
            if field not in el:
                problems.append(f"element '{el.get('id')}': missing '{field}'")
                continue
        for field in REQUIRED_BY_TYPE.get(el.get("type"), []):
            if field not in el:
                problems.append(f"element '{el.get('id')}' (type={el.get('type')}): missing '{field}'")
        if cw and ch and all(k in el for k in ("x", "y", "width", "height")):
            geometry = [el[k] for k in ("x", "y", "width", "height")]
            if not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in geometry
            ):
                problems.append(f"element '{el.get('id')}' has invalid geometry")
                continue
            x, y, width, height = geometry
            if width < 0 or height < 0:
                problems.append(f"element '{el.get('id')}' has negative size")
            if x < -0.5 or y < -0.5 or x + width > cw + 0.5 or y + height > ch + 0.5:
                problems.append(f"element '{el.get('id')}' is off-canvas ({cw}x{ch})")

    source_by_id = {
        element.get("id"): element
        for element in src_elements
        if isinstance(element, dict)
    }
    for element_id, original in source_by_id.items():
        resized = output_by_id.get(element_id)
        if resized is None:
            continue
        if original.get("type") == "text":
            for field in ("content", "font_family"):
                if resized.get(field) != original.get(field):
                    problems.append(f"element '{element_id}' changed {field}")
        if (
            original.get("type") == "image"
            and original.get("fit") != "cover"
            and _positive(original.get("width"))
            and _positive(original.get("height"))
            and _positive(resized.get("width"))
            and _positive(resized.get("height"))
        ):
            old_ratio = original["width"] / original["height"]
            new_ratio = resized["width"] / resized["height"]
            if abs(new_ratio / old_ratio - 1.0) > 0.051:
                problems.append(f"image '{element_id}' aspect ratio changed")

    return problems


def _positive(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def validate_task(task: object) -> tuple[dict, dict]:
    """Validate the task's structural/schema-critical fields before layout."""
    if not isinstance(task, dict):
        raise ValueError("task root must be a JSON object")
    source, target_canvas = task.get("source"), task.get("target_canvas")
    if not isinstance(source, dict) or not isinstance(target_canvas, dict):
        raise ValueError("task must contain object fields 'source' and 'target_canvas'")

    canvas = source.get("canvas")
    if not isinstance(canvas, dict):
        raise ValueError("source.canvas must be an object")
    for label, value in (
        ("source.canvas.width", canvas.get("width")),
        ("source.canvas.height", canvas.get("height")),
        ("target_canvas.width", target_canvas.get("width")),
        ("target_canvas.height", target_canvas.get("height")),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{label} must be a positive integer")

    elements = source.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("source.elements must be a non-empty array")

    seen_ids: set[str] = set()
    for index, element in enumerate(elements):
        label = f"source.elements[{index}]"
        if not isinstance(element, dict):
            raise ValueError(f"{label} must be an object")
        element_id = element.get("id")
        if not isinstance(element_id, str) or not element_id:
            raise ValueError(f"{label}.id must be a non-empty string")
        if element_id in seen_ids:
            raise ValueError(f"duplicate element id: {element_id}")
        seen_ids.add(element_id)

        element_type = element.get("type")
        if element_type not in REQUIRED_BY_TYPE:
            raise ValueError(f"{label}.type must be text, image, or shape")
        required = REQUIRED_COMMON + REQUIRED_BY_TYPE[element_type]
        missing = [field for field in required if field not in element]
        if missing:
            raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")

        for field in ("x", "y", "width", "height"):
            value = element.get(field)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{label}.{field} must be a finite number")
        if element["width"] < 0 or element["height"] < 0:
            raise ValueError(f"{label} width and height cannot be negative")
        if element_type == "text":
            if not isinstance(element.get("content"), str):
                raise ValueError(f"{label}.content must be a string")
            if not isinstance(element.get("font_family"), str):
                raise ValueError(f"{label}.font_family must be a string")
            if not _positive(element.get("font_size")):
                raise ValueError(f"{label}.font_size must be a positive number")

    return source, target_canvas


def render_to_png(design: dict, assets_dir: Path, png_path: Path) -> None:
    """Render through the official local adapter; never emit a placeholder."""
    from renderer.converter.convert import render_design_to_png  # type: ignore

    render_design_to_png(design, assets_dir, str(png_path))
    if not png_path.is_file() or png_path.stat().st_size < 8:
        raise RuntimeError("renderer did not produce a PNG")
    with png_path.open("rb") as rendered:
        if rendered.read(8) != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("renderer output is not a valid PNG")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    task_files = sorted(INPUT_DIR.glob("*.json"))
    if not task_files:
        print(f"No task files found in {INPUT_DIR}", file=sys.stderr)
        return 1

    exit_code = 0
    for task_path in task_files:
        stem = task_path.stem
        json_temp = OUTPUT_DIR / f".{stem}_output.json.tmp"
        png_temp = OUTPUT_DIR / f".{stem}_render.tmp.png"
        json_path = OUTPUT_DIR / f"{stem}_output.json"
        png_path = OUTPUT_DIR / f"{stem}_output.png"

        try:
            task = json.loads(task_path.read_text(encoding="utf-8"))
            source, target_canvas = validate_task(task)
            started = time.perf_counter()
            output = resize(source, target_canvas)
            elapsed = time.perf_counter() - started

            problems = self_check(source, output)
            if problems:
                raise ValueError("output checks failed: " + "; ".join(problems))

            json_temp.write_text(
                json.dumps(output, indent=2, allow_nan=False),
                encoding="utf-8",
            )
            render_to_png(output, ASSETS_DIR, png_temp)
            json_temp.replace(json_path)
            png_temp.replace(png_path)
            print(
                f"[{task_path.name}] OK in {elapsed:.2f}s "
                f"-> {json_path.name}, {png_path.name}"
            )
        except Exception as exc:
            exit_code = 1
            print(f"[{task_path.name}] ERROR: {exc}", file=sys.stderr)
        finally:
            json_temp.unlink(missing_ok=True)
            png_temp.unlink(missing_ok=True)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
