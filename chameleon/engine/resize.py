"""Deterministic, responsive reflow for CHAMELEON design documents.

The layout model works with designer-declared groups as indivisible units,
keeps full-bleed imagery full-bleed, and infers content roles from element
properties rather than element ids. For large aspect-ratio changes it flows
those units into horizontal or vertical bands instead of stretching the
original coordinate system.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import re
from typing import Any


_ACTION_WORDS = {
    "buy", "claim", "click", "discover", "download", "explore", "get",
    "join", "learn", "order", "register", "reserve", "shop", "sign",
    "start", "subscribe", "try", "visit",
}
_LEGAL_WORDS = {
    "copyright", "disclaimer", "prohibited", "responsibly", "terms",
    "trademark", "where", "rights", "void",
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _dimension(canvas: Any, key: str, label: str) -> int:
    value = canvas.get(key) if isinstance(canvas, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label}.{key} must be a positive integer")
    return value


def _clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), max(low, high))


def _box(element: dict[str, Any]) -> tuple[float, float, float, float]:
    """Axis-aligned bounds including rotation about the element's center."""
    x = _number(element.get("x"))
    y = _number(element.get("y"))
    width = max(0.0, _number(element.get("width")))
    height = max(0.0, _number(element.get("height")))
    angle = math.radians(_number(element.get("rotation")))
    rotated_width = abs(width * math.cos(angle)) + abs(height * math.sin(angle))
    rotated_height = abs(width * math.sin(angle)) + abs(height * math.cos(angle))
    cx, cy = x + width / 2, y + height / 2
    return (
        cx - rotated_width / 2,
        cy - rotated_height / 2,
        cx + rotated_width / 2,
        cy + rotated_height / 2,
    )


def _make_node(indices: list[int], elements: list[dict[str, Any]]) -> dict[str, Any]:
    bounds = [_box(elements[index]) for index in indices]
    left = min(box[0] for box in bounds)
    top = min(box[1] for box in bounds)
    right = max(box[2] for box in bounds)
    bottom = max(box[3] for box in bounds)
    members = [elements[index] for index in indices]
    text = " ".join(
        str(element.get("content", ""))
        for element in members
        if element.get("type") == "text"
    )
    words = set(re.findall(r"[a-z]+", text.lower()))
    return {
        "indices": indices,
        "members": members,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0.0, right - left),
        "height": max(0.0, bottom - top),
        "cx": (left + right) / 2,
        "cy": (top + bottom) / 2,
        "area": max(0.0, right - left) * max(0.0, bottom - top),
        "text": text,
        "words": words,
        "grouped": len(indices) > 1 or any(
            member.get("group_id") is not None for member in members
        ),
        "role": "other",
    }


def _is_full_bleed(element: dict[str, Any], source_width: float, source_height: float) -> bool:
    if element.get("type") != "image":
        return False
    x0, y0, x1, y1 = _box(element)
    width, height = x1 - x0, y1 - y0
    covers_canvas = (
        width >= source_width * 0.82
        and height >= source_height * 0.82
        and x0 <= source_width * 0.12
        and y0 <= source_height * 0.12
        and x1 >= source_width * 0.88
        and y1 >= source_height * 0.88
    )
    return covers_canvas and (
        element.get("fit") == "cover"
        or width * height >= source_width * source_height * 0.72
    )


def _action_score(text: str) -> int:
    words = set(re.findall(r"[a-z]+", text.lower()))
    return len(words & _ACTION_WORDS)


def _classify_nodes(
    nodes: list[dict[str, Any]], source_width: float, source_height: float
) -> None:
    """Infer roles from geometry, text styling, and group composition."""
    text_nodes: list[dict[str, Any]] = []
    image_nodes: list[dict[str, Any]] = []

    for node in nodes:
        members = node["members"]
        types = {member.get("type") for member in members}
        text_members = [m for m in members if m.get("type") == "text"]
        image_members = [m for m in members if m.get("type") == "image"]
        shape_members = [m for m in members if m.get("type") == "shape"]

        if text_members:
            text_nodes.append(node)
        if image_members:
            image_nodes.append(node)

        if node["grouped"]:
            if _action_score(node["text"]):
                node["role"] = "cta"
            elif any(abs(_number(member.get("rotation"))) >= 5 for member in members):
                node["role"] = "ribbon"
            elif shape_members and text_members:
                node["role"] = "badge"
            else:
                node["role"] = "other"
        elif types == {"shape"}:
            node["role"] = "decoration"
        elif text_members:
            text = node["text"]
            if _action_score(text):
                node["role"] = "cta"
            elif node["words"] & _LEGAL_WORDS:
                node["role"] = "legal"
            else:
                node["role"] = "unassigned_text"

    # Prefer a small, wide image near the top as a logo; reserve the largest
    # remaining image for the hero. This is content-independent and does not
    # depend on asset names or ids.
    logo_candidates = []
    for node in image_nodes:
        if node["grouped"] or not node["width"] or not node["height"]:
            continue
        aspect = node["width"] / node["height"]
        width_fraction = node["width"] / max(source_width, 1.0)
        height_fraction = node["height"] / max(source_height, 1.0)
        if aspect >= 1.55 and width_fraction <= 0.68 and height_fraction <= 0.32:
            top_score = 1.0 - _clamp(node["cy"] / max(source_height, 1.0), 0.0, 1.0)
            logo_candidates.append((aspect * (1.0 - 0.35 * width_fraction) + top_score, node))
    if logo_candidates:
        max(logo_candidates, key=lambda item: item[0])[1]["role"] = "logo"

    remaining_images = [node for node in image_nodes if node["role"] == "other"]
    if remaining_images:
        # Small images low in the original composition are more likely to be
        # marks/watermarks than the principal product photograph.
        hero = max(
            remaining_images,
            key=lambda node: node["area"]
            * (1.0 + 0.2 * (node["height"] / max(source_height, 1.0))),
        )
        hero["role"] = "hero"
        for node in remaining_images:
            if node is hero:
                continue
            if node["area"] < source_width * source_height * 0.06 and node["cy"] > source_height * 0.55:
                node["role"] = "watermark"
            else:
                node["role"] = "other_image"

    # Estimate the display headline from typography and length. Explicit
    # action copy and legal copy are kept out of this competition.
    candidates = [
        node for node in text_nodes if node["role"] == "unassigned_text"
    ]
    if candidates:
        def headline_score(node: dict[str, Any]) -> float:
            member = next(m for m in node["members"] if m.get("type") == "text")
            size = max(1.0, _number(member.get("font_size"), 16.0))
            family = str(member.get("font_family", "")).lower()
            weight = str(member.get("font_weight", "")).lower()
            display_bonus = 1.12 if any(token in family for token in ("serif", "display")) else 1.0
            display_bonus *= 1.08 if weight == "bold" else 1.0
            length_penalty = math.sqrt(max(1.0, len(str(member.get("content", ""))) / 38.0))
            return size * display_bonus / length_penalty

        headline = max(candidates, key=headline_score)
        headline["role"] = "headline"
        remaining_text = [node for node in candidates if node is not headline]

        # Long secondary copy is body copy; tiny legal lines are identified by
        # wording first and relative typography second.
        for node in remaining_text:
            member = next(m for m in node["members"] if m.get("type") == "text")
            content = str(member.get("content", ""))
            if node["words"] & _LEGAL_WORDS:
                node["role"] = "legal"
            elif len(content) >= 36:
                node["role"] = "body"
            else:
                node["role"] = "other_text"

        small_candidates = [
            node for node in remaining_text
            if node["role"] == "other_text"
        ]
        if len(text_nodes) >= 3 and small_candidates:
            smallest = min(
                small_candidates,
                key=lambda node: _number(
                    next(m for m in node["members"] if m.get("type") == "text").get("font_size"),
                    16.0,
                ),
            )
            font_sizes = [
                _number(m.get("font_size"), 16.0)
                for node in candidates
                for m in node["members"]
                if m.get("type") == "text"
            ]
            median_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 16.0
            small_size = _number(
                next(m for m in smallest["members"] if m.get("type") == "text").get("font_size"),
                median_size,
            )
            if small_size <= median_size * 0.62:
                smallest["role"] = "legal"

    # Low-z-index, unusually large ungrouped shapes are background decoration.
    # Small non-grouped shapes remain in the flow as ordinary visual units.
    for node in nodes:
        if node["role"] != "decoration":
            continue
        member = node["members"][0]
        if (
            node["area"] < source_width * source_height * 0.055
            and _number(member.get("z_index"), 99) > 1
        ):
            node["role"] = "other"


def _text_width_factor(character: str) -> float:
    if character.isspace():
        return 0.29
    if character in "ilI|!.,:;'`":
        return 0.30
    if character in "mwMW@%&":
        return 0.82
    if character.isupper():
        return 0.63
    if character.isdigit():
        return 0.56
    return 0.52


def _wrapped_line_count(text: str, font_size: float, width: float, letter_spacing: float) -> int:
    """Approximate renderer line wrapping without depending on external assets."""
    if width <= 0:
        return max(1, text.count("\n") + 1)
    line_count = 0
    for explicit_line in text.split("\n"):
        if not explicit_line:
            line_count += 1
            continue
        words = explicit_line.split()
        if not words:
            line_count += 1
            continue
        current = 0.0
        for word in words:
            word_width = sum(
                font_size * _text_width_factor(char) + letter_spacing
                for char in word
            )
            space_width = font_size * 0.29 + letter_spacing
            if current and current + space_width + word_width <= width:
                current += space_width + word_width
            elif current:
                line_count += max(1, math.ceil(word_width / max(width, 1.0)))
                current = word_width % max(width, 1.0)
            else:
                line_count += int(word_width >= width) * int(word_width // max(width, 1.0))
                current = word_width % max(width, 1.0) if word_width >= width else word_width
        line_count += 1
    return max(1, line_count)


def _fit_font_size(element: dict[str, Any], width: float, height: float) -> float:
    original = max(1.0, _number(element.get("font_size"), 16.0))
    line_height = max(0.7, _number(element.get("line_height"), 1.2))
    letter_spacing = _number(element.get("letter_spacing"))
    content = str(element.get("content", ""))

    def fits(size: float) -> bool:
        lines = _wrapped_line_count(content, size, max(width - 2.0, 1.0), letter_spacing)
        needed_height = lines * size * line_height * 1.08
        return needed_height <= max(height, 1.0)

    if fits(original):
        return original
    low, high = 1.0, original
    for _ in range(24):
        middle = (low + high) / 2
        if fits(middle):
            low = middle
        else:
            high = middle
    return round(max(1.0, low), 2)


def _set_box(
    element: dict[str, Any],
    x: float,
    y: float,
    width: float,
    height: float,
    canvas_width: float,
    canvas_height: float,
    *,
    fit_text: bool = True,
) -> None:
    width = max(0.0, min(width, canvas_width))
    height = max(0.0, min(height, canvas_height))
    x = _clamp(x, 0.0, canvas_width - width)
    y = _clamp(y, 0.0, canvas_height - height)
    element["x"] = round(x, 3)
    element["y"] = round(y, 3)
    element["width"] = round(width, 3)
    element["height"] = round(height, 3)
    if element.get("type") == "text" and fit_text:
        element["font_size"] = _fit_font_size(element, width, height)


def _place_node_in_slot(
    node: dict[str, Any],
    output: list[dict[str, Any]],
    slot: tuple[float, float, float, float],
    canvas_width: float,
    canvas_height: float,
) -> None:
    sx, sy, slot_width, slot_height = slot
    slot_width = max(0.0, slot_width)
    slot_height = max(0.0, slot_height)
    members = node["members"]

    # Text gets the full slot so it can wrap naturally; images keep their
    # original aspect ratio; groups use one shared transform to retain their
    # internal offsets, sizes, and layering.
    if len(members) == 1 and members[0].get("type") == "text":
        element = output[node["indices"][0]]
        _set_box(
            element, sx, sy, slot_width, slot_height,
            canvas_width, canvas_height,
        )
        return

    if len(members) == 1 and members[0].get("type") == "image":
        member = members[0]
        source_width = max(_number(member.get("width")), 1.0)
        source_height = max(_number(member.get("height")), 1.0)
        scale = min(slot_width / source_width, slot_height / source_height)
        width, height = source_width * scale, source_height * scale
        x = sx + (slot_width - width) / 2
        y = sy + (slot_height - height) / 2
        _set_box(
            output[node["indices"][0]], x, y, width, height,
            canvas_width, canvas_height,
        )
        return

    unit_width = max(node["width"], 1.0)
    unit_height = max(node["height"], 1.0)
    scale = min(slot_width / unit_width, slot_height / unit_height)
    cx, cy = sx + slot_width / 2, sy + slot_height / 2
    for index, member in zip(node["indices"], members):
        width = max(0.0, _number(member.get("width"))) * scale
        height = max(0.0, _number(member.get("height"))) * scale
        member_cx = _number(member.get("x")) + _number(member.get("width")) / 2
        member_cy = _number(member.get("y")) + _number(member.get("height")) / 2
        x = cx + (member_cx - node["cx"]) * scale - width / 2
        y = cy + (member_cy - node["cy"]) * scale - height / 2
        _set_box(
            output[index], x, y, width, height,
            canvas_width, canvas_height,
        )
        if output[index].get("type") == "text":
            output[index]["font_size"] = max(
                1.0, round(_number(member.get("font_size"), 16.0) * scale, 2)
            )


def _flow_weights(node: dict[str, Any], horizontal: bool) -> float:
    role = node["role"]
    if horizontal:
        weights = {
            "logo": 0.95, "hero": 0.58, "headline": 2.1, "body": 2.1,
            "ribbon": 0.9, "badge": 0.9, "cta": 1.15, "legal": 1.75,
            "watermark": 0.55, "other_image": 0.8, "other_text": 1.0,
            "other": 0.85, "decoration": 0.7,
        }
    else:
        weights = {
            "logo": 0.65, "hero": 1.45, "headline": 1.25, "body": 1.2,
            "ribbon": 0.55, "badge": 0.58, "cta": 0.7, "legal": 0.52,
            "watermark": 0.45, "other_image": 0.72, "other_text": 0.75,
            "other": 0.65, "decoration": 0.4,
        }
    return weights.get(role, 0.8)


def _sort_key(node: dict[str, Any], horizontal: bool) -> tuple[int, float]:
    if horizontal:
        priority = {
            "logo": 0, "hero": 1, "headline": 2, "body": 3, "ribbon": 4,
            "other_image": 5, "other_text": 6, "other": 7, "badge": 0,
            "cta": 3, "watermark": 4, "legal": 5,
        }
        coordinate = node["cx"]
    else:
        priority = {
            "logo": 0, "headline": 1, "hero": 2, "body": 3, "ribbon": 4,
            "other_image": 5, "other_text": 6, "other": 7, "badge": 8,
            "cta": 9, "watermark": 10, "legal": 11,
        }
        coordinate = node["cx"]
    return priority.get(node["role"], 7), coordinate


def _flow_nodes(
    nodes: list[dict[str, Any]],
    output: list[dict[str, Any]],
    canvas_width: float,
    canvas_height: float,
    *,
    horizontal: bool,
    bounds: tuple[float, float, float, float],
) -> None:
    """Lay out units as non-overlapping equal-axis cells with role weighting."""
    left, top, width, height = bounds
    if not nodes or width <= 0 or height <= 0:
        return
    gap = min(20.0, max(2.0, (width if horizontal else height) * 0.012))
    total_gap = gap * max(0, len(nodes) - 1)
    usable = max(1.0, (width if horizontal else height) - total_gap)
    weights = [_flow_weights(node, horizontal) for node in nodes]
    weight_sum = sum(weights) or float(len(nodes))
    offset = 0.0
    for node, weight in zip(nodes, weights):
        extent = usable * weight / weight_sum
        if horizontal:
            slot = (left + offset, top, extent, height)
        else:
            slot = (left, top + offset, width, extent)
        _place_node_in_slot(node, output, slot, canvas_width, canvas_height)
        offset += extent + gap


def _landscape_reflow(
    nodes: list[dict[str, Any]],
    output: list[dict[str, Any]],
    canvas_width: float,
    canvas_height: float,
) -> None:
    margin_x = max(2.0, canvas_width * 0.025)
    margin_y = max(2.0, canvas_height * 0.045)
    inner_width = max(1.0, canvas_width - 2 * margin_x)
    inner_height = max(1.0, canvas_height - 2 * margin_y)
    gap_y = max(2.0, inner_height * 0.055)
    top_height = inner_height * 0.66
    bottom_height = max(1.0, inner_height - top_height - gap_y)

    upper_roles = {"logo", "hero", "headline", "body", "ribbon", "other_image"}
    upper = [node for node in nodes if node["role"] in upper_roles]
    lower = [node for node in nodes if node["role"] not in upper_roles]

    # A design with only primary content should use the whole band rather than
    # leaving a visually empty footer row.
    if not lower and upper:
        _flow_nodes(
            sorted(upper, key=lambda node: _sort_key(node, True)),
            output, canvas_width, canvas_height, horizontal=True,
            bounds=(margin_x, margin_y, inner_width, inner_height),
        )
        return
    if not upper and lower:
        _flow_nodes(
            sorted(lower, key=lambda node: _sort_key(node, True)),
            output, canvas_width, canvas_height, horizontal=True,
            bounds=(margin_x, margin_y, inner_width, inner_height),
        )
        return

    _flow_nodes(
        sorted(upper, key=lambda node: _sort_key(node, True)),
        output, canvas_width, canvas_height, horizontal=True,
        bounds=(margin_x, margin_y, inner_width, top_height),
    )
    _flow_nodes(
        sorted(lower, key=lambda node: _sort_key(node, True)),
        output, canvas_width, canvas_height, horizontal=True,
        bounds=(
            margin_x, margin_y + top_height + gap_y,
            inner_width, bottom_height,
        ),
    )


def _portrait_reflow(
    nodes: list[dict[str, Any]],
    output: list[dict[str, Any]],
    canvas_width: float,
    canvas_height: float,
) -> None:
    margin_x = max(2.0, canvas_width * 0.055)
    margin_y = max(2.0, canvas_height * 0.035)
    _flow_nodes(
        sorted(nodes, key=lambda node: _sort_key(node, False)),
        output, canvas_width, canvas_height, horizontal=False,
        bounds=(
            margin_x, margin_y,
            max(1.0, canvas_width - 2 * margin_x),
            max(1.0, canvas_height - 2 * margin_y),
        ),
    )


def _relative_reflow(
    nodes: list[dict[str, Any]],
    output: list[dict[str, Any]],
    source_width: float,
    source_height: float,
    canvas_width: float,
    canvas_height: float,
) -> None:
    margin = max(1.0, min(canvas_width, canvas_height) * 0.015)
    available_width = max(1.0, canvas_width - 2 * margin)
    available_height = max(1.0, canvas_height - 2 * margin)
    scale = min(available_width / max(source_width, 1.0), available_height / max(source_height, 1.0))

    for node in nodes:
        center_x = margin + _clamp(node["cx"] / max(source_width, 1.0), 0.0, 1.0) * available_width
        center_y = margin + _clamp(node["cy"] / max(source_height, 1.0), 0.0, 1.0) * available_height
        # Elements that intentionally bleed past the source edge become
        # edge-anchored decorations, but their full output boxes remain valid.
        if node["role"] == "decoration":
            if node["left"] < 0:
                center_x = node["width"] * scale / 2
            elif node["right"] > source_width:
                center_x = canvas_width - node["width"] * scale / 2
            if node["top"] < 0:
                center_y = node["height"] * scale / 2
            elif node["bottom"] > source_height:
                center_y = canvas_height - node["height"] * scale / 2

        transformed_width = node["width"] * scale
        transformed_height = node["height"] * scale
        if transformed_width > canvas_width or transformed_height > canvas_height:
            scale_for_node = min(
                canvas_width / max(node["width"], 1.0),
                canvas_height / max(node["height"], 1.0),
            )
        else:
            scale_for_node = scale
        cx = _clamp(center_x, transformed_width / 2, canvas_width - transformed_width / 2)
        cy = _clamp(center_y, transformed_height / 2, canvas_height - transformed_height / 2)

        for index, member in zip(node["indices"], node["members"]):
            width = max(0.0, _number(member.get("width"))) * scale_for_node
            height = max(0.0, _number(member.get("height"))) * scale_for_node
            member_cx = _number(member.get("x")) + _number(member.get("width")) / 2
            member_cy = _number(member.get("y")) + _number(member.get("height")) / 2
            x = cx + (member_cx - node["cx"]) * scale_for_node - width / 2
            y = cy + (member_cy - node["cy"]) * scale_for_node - height / 2
            _set_box(
                output[index], x, y, width, height,
                canvas_width, canvas_height,
                fit_text=not node["grouped"],
            )
            if member.get("type") == "text" and node["grouped"]:
                output[index]["font_size"] = max(
                    1.0, round(_number(member.get("font_size"), 16.0) * scale_for_node, 2)
                )


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Return a reflowed copy of ``source`` for ``target_canvas``.

    Original ids, content, fonts, colors, assets, and element count are
    retained. Only geometry and text font sizes are adapted. Grouped elements
    share one transform, non-background images retain their aspect ratio, and
    all output bounds are clipped safely to the requested canvas.
    """
    if not isinstance(source, dict):
        raise ValueError("source must be a design object")
    source_canvas = source.get("canvas")
    source_width = _dimension(source_canvas, "width", "source.canvas")
    source_height = _dimension(source_canvas, "height", "source.canvas")
    target_width = _dimension(target_canvas, "width", "target_canvas")
    target_height = _dimension(target_canvas, "height", "target_canvas")

    original_elements = source.get("elements")
    if not isinstance(original_elements, list) or not original_elements:
        raise ValueError("source.elements must be a non-empty list")
    required_by_type = {
        "text": ("content", "font_family", "font_size", "color"),
        "image": ("asset_id",),
        "shape": ("shape_type", "fill_color"),
    }
    seen_ids: set[str] = set()
    for index, element in enumerate(original_elements):
        label = f"source.elements[{index}]"
        if not isinstance(element, dict):
            raise ValueError(f"{label} must be an object")
        if not isinstance(element.get("id"), str) or not element["id"]:
            raise ValueError(f"{label}.id must be a non-empty string")
        if element["id"] in seen_ids:
            raise ValueError(f"duplicate element id: {element['id']}")
        seen_ids.add(element["id"])
        element_type = element.get("type")
        if element_type not in required_by_type:
            raise ValueError(f"{label}.type must be text, image, or shape")
        required = ("x", "y", "width", "height") + required_by_type[element_type]
        missing = [key for key in required if key not in element]
        if missing:
            raise ValueError(f"{label} is missing required fields: {', '.join(missing)}")
        for key in ("x", "y", "width", "height"):
            value = element[key]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
            ):
                raise ValueError(f"{label}.{key} must be a finite number")
        if element["width"] < 0 or element["height"] < 0:
            raise ValueError(f"{label} width and height cannot be negative")
        if element_type == "text":
            if not isinstance(element["content"], str):
                raise ValueError(f"{label}.content must be a string")
            if not isinstance(element["font_family"], str):
                raise ValueError(f"{label}.font_family must be a string")
            if not _number(element["font_size"], 0.0) >= 1.0:
                raise ValueError(f"{label}.font_size must be at least 1")

    source_width = float(source_width)
    source_height = float(source_height)
    output = deepcopy(original_elements)
    full_bleed_indices: set[int] = set()
    for index, element in enumerate(original_elements):
        if _is_full_bleed(element, source_width, source_height):
            full_bleed_indices.add(index)
            _set_box(
                output[index], 0.0, 0.0, target_width, target_height,
                target_width, target_height, fit_text=False,
            )

    grouped_indices: dict[Any, list[int]] = defaultdict(list)
    for index, element in enumerate(original_elements):
        if index in full_bleed_indices:
            continue
        group_id = element.get("group_id")
        if group_id is not None:
            grouped_indices[group_id].append(index)

    consumed = set(full_bleed_indices)
    nodes: list[dict[str, Any]] = []
    for indices in grouped_indices.values():
        nodes.append(_make_node(indices, original_elements))
        consumed.update(indices)
    for index in range(len(original_elements)):
        if index not in consumed:
            nodes.append(_make_node([index], original_elements))

    _classify_nodes(nodes, source_width, source_height)

    content_nodes = [node for node in nodes if node["role"] != "decoration"]
    decoration_nodes = [node for node in nodes if node["role"] == "decoration"]
    source_ratio = source_width / source_height
    target_ratio = target_width / target_height

    if target_ratio >= 1.45 and (
        target_ratio >= source_ratio * 1.28
        or target_ratio >= 3.0
        or source_ratio < 0.82
    ):
        _landscape_reflow(
            content_nodes, output, float(target_width), float(target_height)
        )
        layout_scale = min(
            target_width / source_width,
            target_height / source_height,
        )
        for node in decoration_nodes:
            width = node["width"] * layout_scale
            height = node["height"] * layout_scale
            cx = _clamp(
                node["cx"] / source_width * target_width,
                width / 2, target_width - width / 2,
            )
            cy = _clamp(
                node["cy"] / source_height * target_height,
                height / 2, target_height - height / 2,
            )
            if node["left"] < 0:
                cx = width / 2
            elif node["right"] > source_width:
                cx = target_width - width / 2
            if node["top"] < 0:
                cy = height / 2
            elif node["bottom"] > source_height:
                cy = target_height - height / 2
            for index, member in zip(node["indices"], node["members"]):
                member_width = max(0.0, _number(member.get("width"))) * layout_scale
                member_height = max(0.0, _number(member.get("height"))) * layout_scale
                member_cx = _number(member.get("x")) + _number(member.get("width")) / 2
                member_cy = _number(member.get("y")) + _number(member.get("height")) / 2
                _set_box(
                    output[index],
                    cx + (member_cx - node["cx"]) * layout_scale - member_width / 2,
                    cy + (member_cy - node["cy"]) * layout_scale - member_height / 2,
                    member_width, member_height,
                    target_width, target_height,
                )
    elif target_ratio < 0.88 and target_ratio < source_ratio * 0.68:
        _portrait_reflow(
            content_nodes, output, float(target_width), float(target_height)
        )
        _relative_reflow(
            decoration_nodes, output,
            source_width, source_height, target_width, target_height,
        )
    else:
        _relative_reflow(
            nodes, output,
            source_width, source_height, target_width, target_height,
        )

    return {
        "canvas": {"width": target_width, "height": target_height},
        "elements": output,
    }
