"""
Project CHAMELEON — Automatic Design Reflow Engine
Implementation in engine/resize.py
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """
    Intelligent Design Reflow Engine for Project CHAMELEON.

    Args:
        source: Dict containing "canvas" (width, height) and "elements" list.
        target_canvas: Dict containing "width" and "height".

    Returns:
        Dict with "canvas" and reflowed "elements" list preserving all element IDs,
        counts, text contents, font families, and image proportions while adapting
        layout, typography, and positioning to the target canvas size.
    """
    try:
        engine = ReflowEngine(source, target_canvas)
        return engine.reflow()
    except Exception:
        # Fallback to safe proportional scale if unexpected error occurs
        return _safe_fallback_resize(source, target_canvas)


def _get_prop(el: dict, *keys, default=None):
    """Utility to retrieve property trying multiple key aliases (snake_case and camelCase)."""
    for k in keys:
        if k in el and el[k] is not None:
            return el[k]
    return default


def _set_prop(el: dict, keys: Tuple[str, ...], value: Any):
    """Utility to update property using the existing key alias if present."""
    for k in keys:
        if k in el:
            el[k] = value
            return
    el[keys[0]] = value


class ReflowEngine:
    def __init__(self, source: dict[str, Any], target_canvas: dict[str, Any]):
        src_canvas = source.get("canvas", {})
        self.src_w = float(src_canvas.get("width", 1080))
        self.src_h = float(src_canvas.get("height", 1080))
        
        self.tgt_w = float(target_canvas.get("width", 1080))
        self.tgt_h = float(target_canvas.get("height", 1080))
        
        self.src_ar = self.src_w / self.src_h if self.src_h > 0 else 1.0
        self.tgt_ar = self.tgt_w / self.tgt_h if self.tgt_h > 0 else 1.0
        
        self.scale_x = self.tgt_w / self.src_w if self.src_w > 0 else 1.0
        self.scale_y = self.tgt_h / self.src_h if self.src_h > 0 else 1.0

        # Deep copy elements to avoid mutating source input
        self.elements = [dict(el) for el in source.get("elements", [])]
        self.el_map = {el.get("id"): el for el in self.elements if el.get("id") is not None}

        # Track reflowed IDs
        self.reflowed_ids: Set[str] = set()

        # Analyze roles and groups (support group_id and group)
        self.groups: Dict[str, List[dict]] = {}
        for el in self.elements:
            gid = _get_prop(el, "group_id", "group")
            if gid:
                self.groups.setdefault(str(gid), []).append(el)

        self.roles = self._classify_elements()

    def reflow(self) -> dict[str, Any]:
        """Main execution flow for deterministic reflow."""
        # 1. Handle Backgrounds & Decorative Elements
        self._reflow_backgrounds_and_decorations()

        # 2. Select Reflow Strategy based on Target Aspect Ratio
        if self.tgt_ar <= 1.3:
            self._reflow_vertical_stack()
        elif self.tgt_ar <= 2.8:
            self._reflow_split_landscape()
        else:
            self._reflow_extreme_leaderboard()

        # 3. Reflow remaining unhandled elements (roles["other"])
        self._reflow_other_elements()

        # 4. Synchronize Group Elements (e.g. text labels inside button/badge shapes)
        self._sync_all_groups()

        # 5. Resolve Collisions and Clamp within Canvas Bounds (Bounded Iterations)
        self._resolve_collisions_and_clamp()

        # 6. Build schema-valid output dictionary
        return {
            "canvas": {"width": int(self.tgt_w), "height": int(self.tgt_h)},
            "elements": self.elements,
        }

    def _classify_elements(self) -> Dict[str, List[str]]:
        """Identify semantic roles of elements based on geometry and properties."""
        roles: Dict[str, List[str]] = {
            "background": [],
            "decorative": [],
            "logo": [],
            "hero_image": [],
            "headline": [],
            "subhead": [],
            "cta": [],
            "badge": [],
            "ribbon": [],
            "legal": [],
            "other": [],
        }

        # Find maximum font size among text elements for headline classification
        text_font_sizes = [
            float(_get_prop(el, "font_size", "fontSize", default=0))
            for el in self.elements if el.get("type") == "text"
        ]
        max_font_size = max(text_font_sizes) if text_font_sizes else 0.0

        for el in self.elements:
            eid = el.get("id")
            if not eid:
                continue
            etype = el.get("type")
            x, y = float(el.get("x", 0.0)), float(el.get("y", 0.0))
            w, h = float(el.get("width", 0.0)), float(el.get("height", 0.0))
            opacity = float(el.get("opacity", 1.0))
            z_index = int(_get_prop(el, "z_index", "zIndex", default=0))
            gid = _get_prop(el, "group_id", "group")

            # Background detection
            is_full_canvas = (
                abs(x) < 5 and abs(y) < 5 and
                w >= 0.85 * self.src_w and h >= 0.85 * self.src_h
            )
            if z_index == 0 or (is_full_canvas and etype in ("image", "shape")):
                if el.get("fit") == "cover" or is_full_canvas:
                    roles["background"].append(eid)
                    continue

            # Decorative accent detection (low opacity or off-canvas placement in source)
            is_off_canvas_src = (
                x < -10 or y < -10 or
                x + w > self.src_w + 10 or y + h > self.src_h + 10
            )
            if opacity <= 0.35 or is_off_canvas_src:
                roles["decorative"].append(eid)
                continue

            # Group role classification
            if gid:
                gid_lower = str(gid).lower()
                if "cta" in gid_lower or "button" in gid_lower:
                    roles["cta"].append(eid)
                elif "badge" in gid_lower:
                    roles["badge"].append(eid)
                elif "ribbon" in gid_lower or el.get("rotation", 0) != 0:
                    roles["ribbon"].append(eid)
                else:
                    roles["other"].append(eid)
                continue

            # Standalone element classification
            if etype == "image":
                asset_ref = str(_get_prop(el, "asset_id", "src", default="")).lower()
                is_top = (y + h / 2.0) < (0.35 * self.src_h)
                if "logo" in str(eid).lower() or "logo" in asset_ref or (is_top and w / (h or 1.0) > 2.0):
                    roles["logo"].append(eid)
                else:
                    roles["hero_image"].append(eid)

            elif etype == "text":
                content = str(_get_prop(el, "content", "text", default="")).lower()
                fs = float(_get_prop(el, "font_size", "fontSize", default=0.0))

                # Legal text check
                if fs <= 14 or y > 0.85 * self.src_h or any(kw in content for kw in ["responsibly", "terms", "rights", "void", "copyright", "©"]):
                    roles["legal"].append(eid)
                # Headline check
                elif fs >= 0.8 * max_font_size and max_font_size > 0:
                    roles["headline"].append(eid)
                # Subhead check
                elif fs >= 0.4 * max_font_size:
                    roles["subhead"].append(eid)
                else:
                    roles["other"].append(eid)
            else:
                roles["other"].append(eid)

        return roles

    def _reflow_backgrounds_and_decorations(self):
        """Fit background layers to target canvas and scale decorative accents."""
        for eid in self.roles["background"]:
            el = self.el_map[eid]
            el["x"] = 0.0
            el["y"] = 0.0
            el["width"] = self.tgt_w
            el["height"] = self.tgt_h
            self.reflowed_ids.add(eid)

        for eid in self.roles["decorative"]:
            el = self.el_map[eid]
            x, y = float(el.get("x", 0.0)), float(el.get("y", 0.0))
            w, h = float(el.get("width", 0.0)), float(el.get("height", 0.0))
            
            # Scale decor relative to target canvas proportions
            rel_cx = (x + w / 2.0) / (self.src_w or 1.0)
            rel_cy = (y + h / 2.0) / (self.src_h or 1.0)
            
            s = min(self.scale_x, self.scale_y)
            new_w = w * s
            new_h = h * s
            
            el["width"] = round(new_w, 2)
            el["height"] = round(new_h, 2)
            el["x"] = round((rel_cx * self.tgt_w) - (new_w / 2.0), 2)
            el["y"] = round((rel_cy * self.tgt_h) - (new_h / 2.0), 2)
            self.reflowed_ids.add(eid)

    def _reflow_vertical_stack(self):
        """Reflow layout for Portrait and Square target canvases (AR <= 1.3)."""
        curr_y = self.tgt_h * 0.04
        content_w = self.tgt_w * 0.88
        center_x = self.tgt_w / 2.0

        # Logo
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            target_w = min(self.tgt_w * 0.45, w * self.scale_x)
            target_h = target_w / (ar if ar > 0 else 1.0)
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(center_x - target_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.03)
            self.reflowed_ids.add(eid)

        # Hero Image
        for eid in self.roles["hero_image"]:
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            max_h = self.tgt_h * 0.38
            max_w = content_w
            target_h = min(max_h, max_w / (ar if ar > 0 else 1.0))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(center_x - target_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.03)
            self.reflowed_ids.add(eid)

        # Headline
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(center_x - content_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(content_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.25)
            curr_y += float(el.get("height", 0.0)) + (self.tgt_h * 0.02)
            self.reflowed_ids.add(eid)

        # Subhead
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(center_x - content_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(content_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.18)
            curr_y += float(el.get("height", 0.0)) + (self.tgt_h * 0.02)
            self.reflowed_ids.add(eid)

        # Badges
        badge_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["badge"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        if badge_groups:
            self._layout_badge_row(badge_groups, curr_y, center_x)
            curr_y += self.tgt_h * 0.07

        # CTA
        cta_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["cta"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        for gid in cta_groups:
            self._layout_cta_group(gid, curr_y, center_x)
            curr_y += self.tgt_h * 0.09

        # Legal
        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.92, 2)
            el["x"] = round(center_x - float(el["width"]) / 2.0, 2)
            self._fit_text_element(el, min_font_size=9, max_font_size=13)
            el["y"] = round(self.tgt_h - float(el.get("height", 10.0)) - (self.tgt_h * 0.02), 2)
            self.reflowed_ids.add(eid)

        # Ribbons
        ribbon_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["ribbon"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        for gid in ribbon_groups:
            self._layout_ribbon_group(gid)

    def _reflow_split_landscape(self):
        """Reflow layout for Medium Landscape target canvases (1.3 < AR <= 2.8)."""
        left_w = self.tgt_w * 0.42
        right_x = self.tgt_w * 0.46
        right_w = self.tgt_w * 0.50

        # Hero image in left column
        if self.roles["hero_image"]:
            eid = self.roles["hero_image"][0]
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            target_h = min(self.tgt_h * 0.80, left_w / (ar if ar > 0 else 1.0))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round((left_w - target_w) / 2.0 + (self.tgt_w * 0.03), 2)
            el["y"] = round((self.tgt_h - target_h) / 2.0, 2)
            self.reflowed_ids.add(eid)

        curr_y = self.tgt_h * 0.06

        # Logo on right top
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            target_w = min(right_w * 0.5, w * self.scale_x)
            target_h = target_w / (ar if ar > 0 else 1.0)
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(right_x + (right_w - target_w) / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.04)
            self.reflowed_ids.add(eid)

        # Headline
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(right_x, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(right_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.32)
            curr_y += float(el.get("height", 0.0)) + (self.tgt_h * 0.03)
            self.reflowed_ids.add(eid)

        # Subhead
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(right_x, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(right_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.22)
            curr_y += float(el.get("height", 0.0)) + (self.tgt_h * 0.03)
            self.reflowed_ids.add(eid)

        # Badges
        badge_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["badge"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        if badge_groups:
            self._layout_badge_row(badge_groups, curr_y, right_x + right_w / 2.0)
            curr_y += self.tgt_h * 0.08

        # CTA
        cta_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["cta"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        for gid in cta_groups:
            self._layout_cta_group(gid, curr_y, right_x + right_w / 2.0)
            curr_y += self.tgt_h * 0.10

        # Legal
        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.90, 2)
            el["x"] = round((self.tgt_w - float(el["width"])) / 2.0, 2)
            self._fit_text_element(el, min_font_size=8, max_font_size=12)
            el["y"] = round(self.tgt_h - float(el.get("height", 10.0)) - (self.tgt_h * 0.02), 2)
            self.reflowed_ids.add(eid)

        # Ribbons
        ribbon_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["ribbon"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        for gid in ribbon_groups:
            self._layout_ribbon_group(gid)

    def _reflow_extreme_leaderboard(self):
        """Reflow layout for Extreme Landscape / Leaderboard (AR > 2.8, e.g. 728x90)."""
        curr_x = self.tgt_w * 0.02
        center_y = self.tgt_h / 2.0

        # 1. Logo Zone (Far Left)
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            target_h = min(self.tgt_h * 0.65, max(24.0, h * self.scale_y * 1.5))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(curr_x, 2)
            el["y"] = round(center_y - target_h / 2.0, 2)
            curr_x += target_w + (self.tgt_w * 0.02)
            self.reflowed_ids.add(eid)

        # 2. Hero Image Zone
        for eid in self.roles["hero_image"]:
            el = self.el_map[eid]
            w, h = float(el.get("width", 1.0)), float(el.get("height", 1.0))
            ar = w / (h if h > 0 else 1.0)
            target_h = min(self.tgt_h * 0.75, max(30.0, h * self.scale_y * 1.5))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(curr_x, 2)
            el["y"] = round(center_y - target_h / 2.0, 2)
            curr_x += target_w + (self.tgt_w * 0.02)
            self.reflowed_ids.add(eid)

        # 3. Right Zone for CTA (Far Right)
        cta_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["cta"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        cta_reserved_w = min(180.0, self.tgt_w * 0.25) if cta_groups else 0.0
        text_zone_right = self.tgt_w - cta_reserved_w - (self.tgt_w * 0.02)
        text_zone_w = max(self.tgt_w * 0.30, text_zone_right - curr_x)

        # 4. Headline in Text Zone
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(curr_x, 2)
            el["width"] = round(text_zone_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.55, min_font_size=10, max_font_size=15)
            el["y"] = round(center_y - float(el.get("height", 0.0)) / 2.0, 2)
            self.reflowed_ids.add(eid)

        # 5. Position CTA Button on Far Right
        for gid in cta_groups:
            cta_x = self.tgt_w - cta_reserved_w - (self.tgt_w * 0.02)
            self._layout_cta_group(gid, center_y, cta_x + cta_reserved_w / 2.0, is_vertical_center=True, target_w=cta_reserved_w)

        # 6. Compact Badges
        badge_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["badge"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        if badge_groups:
            self._layout_badge_row(badge_groups, 4.0, self.tgt_w * 0.5, max_badge_w=90.0)

        # 7. Subhead & Legal in Banner
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(curr_x, 2)
            el["width"] = round(text_zone_w, 2)
            self._fit_text_element(el, min_font_size=8, max_font_size=11)
            el["y"] = round(self.tgt_h - float(el.get("height", 0.0)) - 2, 2)
            self.reflowed_ids.add(eid)

        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.40, 2)
            el["x"] = round(self.tgt_w - float(el["width"]) - 5, 2)
            self._fit_text_element(el, min_font_size=7, max_font_size=9)
            el["y"] = round(self.tgt_h - 12, 2)
            self.reflowed_ids.add(eid)

        # Ribbons
        ribbon_groups = list(dict.fromkeys(
            str(_get_prop(self.el_map[eid], "group_id", "group"))
            for eid in self.roles["ribbon"] if _get_prop(self.el_map[eid], "group_id", "group")
        ))
        for gid in ribbon_groups:
            self._layout_ribbon_group(gid)

    def _reflow_other_elements(self):
        """Reflow remaining unhandled elements proportionally."""
        for el in self.elements:
            eid = el.get("id")
            if not eid or eid in self.reflowed_ids:
                continue

            x, y = float(el.get("x", 0.0)), float(el.get("y", 0.0))
            w, h = float(el.get("width", 10.0)), float(el.get("height", 10.0))

            el["x"] = round(x * self.scale_x, 2)
            el["y"] = round(y * self.scale_y, 2)
            el["width"] = round(max(1.0, w * self.scale_x), 2)
            el["height"] = round(max(1.0, h * self.scale_y), 2)

            if el.get("type") == "text":
                self._fit_text_element(el)

            self.reflowed_ids.add(eid)

    def _fit_text_element(self, el: dict, max_height: Optional[float] = None, min_font_size: float = 8.0, max_font_size: float = 72.0):
        """Dynamically compute font_size and height for text fitting (supporting both font_size & fontSize)."""
        content = str(_get_prop(el, "content", "text", default=""))
        if not content:
            return

        box_w = max(10.0, float(el.get("width", 100.0)))
        src_fs = float(_get_prop(el, "font_size", "fontSize", default=20.0))

        # Target font size estimation
        scale = min(self.scale_x, self.scale_y)
        target_fs = max(min_font_size, min(max_font_size, src_fs * scale))

        # Handle explicit line breaks in content
        raw_lines = content.split("\n")

        # Calculate line wrapping
        char_w = target_fs * 0.52
        chars_per_line = max(1, int(box_w / (char_w or 1.0)))
        
        lines = sum(max(1, math.ceil(len(line) / chars_per_line)) for line in raw_lines)
        max_lines = _get_prop(el, "max_lines", "maxLines")
        if max_lines:
            lines = min(lines, int(max_lines))

        line_height_multiplier = float(_get_prop(el, "line_height", "lineHeight", default=1.2))
        needed_h = lines * target_fs * line_height_multiplier

        if max_height and needed_h > max_height:
            # Scale down font size to fit max_height
            ratio = max_height / (needed_h or 1.0)
            target_fs = max(min_font_size, target_fs * math.sqrt(ratio))
            chars_per_line = max(1, int(box_w / (target_fs * 0.52)))
            lines = sum(max(1, math.ceil(len(line) / chars_per_line)) for line in raw_lines)
            if max_lines:
                lines = min(lines, int(max_lines))
            needed_h = lines * target_fs * line_height_multiplier

        _set_prop(el, ("font_size", "fontSize"), round(target_fs, 1))
        el["height"] = round(needed_h, 1)

    def _layout_cta_group(self, gid: str, pos_y: float, center_x: float, is_vertical_center: bool = False, target_w: Optional[float] = None):
        """Layout CTA button group (shape + text label)."""
        group_els = self.groups.get(gid, [])
        if not group_els:
            return

        shape_el = next((e for e in group_els if e.get("type") == "shape"), group_els[0])
        text_el = next((e for e in group_els if e.get("type") == "text"), None)

        shape_src_w = float(shape_el.get("width", 100.0))
        shape_src_h = float(shape_el.get("height", 40.0))

        actual_target_w = target_w or min(self.tgt_w * 0.45, shape_src_w * self.scale_x)
        actual_target_h = max(32.0, min(self.tgt_h * 0.45, shape_src_h * self.scale_y))

        shape_x = center_x - actual_target_w / 2.0
        shape_y = pos_y - actual_target_h / 2.0 if is_vertical_center else pos_y

        shape_el["width"] = round(actual_target_w, 2)
        shape_el["height"] = round(actual_target_h, 2)
        shape_el["x"] = round(shape_x, 2)
        shape_el["y"] = round(shape_y, 2)
        
        cr_key = "corner_radius" if "corner_radius" in shape_el else ("cornerRadius" if "cornerRadius" in shape_el else "corner_radius")
        shape_el[cr_key] = round(min(actual_target_h / 2.0, actual_target_h * 0.45), 1)

        self.reflowed_ids.add(shape_el.get("id"))

        if text_el:
            text_el["width"] = round(actual_target_w * 0.9, 2)
            self._fit_text_element(text_el, max_height=actual_target_h * 0.8, min_font_size=10, max_font_size=24)
            text_el["x"] = round(center_x - float(text_el["width"]) / 2.0, 2)
            text_el["y"] = round(shape_y + (actual_target_h - float(text_el.get("height", 0.0))) / 2.0, 2)
            _set_prop(text_el, ("text_align", "textAlign"), "center")
            self.reflowed_ids.add(text_el.get("id"))

    def _layout_badge_row(self, badge_gids: List[str], pos_y: float, center_x: float, max_badge_w: Optional[float] = None):
        """Layout multiple badges in a clean horizontal row."""
        num_badges = len(badge_gids)
        if num_badges == 0:
            return

        badge_w = max_badge_w or min(self.tgt_w * 0.28, 220.0 * self.scale_x)
        badge_h = max(24.0, min(self.tgt_h * 0.3, 48.0 * self.scale_y))
        gap = 12.0

        total_w = (num_badges * badge_w) + ((num_badges - 1) * gap)
        start_x = center_x - total_w / 2.0

        for idx, gid in enumerate(badge_gids):
            bx = start_x + idx * (badge_w + gap)
            group_els = self.groups.get(gid, [])
            shape_el = next((e for e in group_els if e.get("type") == "shape"), None)
            text_el = next((e for e in group_els if e.get("type") == "text"), None)

            if shape_el:
                shape_el["x"] = round(bx, 2)
                shape_el["y"] = round(pos_y, 2)
                shape_el["width"] = round(badge_w, 2)
                shape_el["height"] = round(badge_h, 2)
                cr_key = "corner_radius" if "corner_radius" in shape_el else ("cornerRadius" if "cornerRadius" in shape_el else "corner_radius")
                shape_el[cr_key] = round(min(badge_h / 2.0, badge_h * 0.45), 1)
                self.reflowed_ids.add(shape_el.get("id"))

            if text_el:
                text_el["width"] = round(badge_w * 0.9, 2)
                self._fit_text_element(text_el, max_height=badge_h * 0.8, min_font_size=8, max_font_size=16)
                text_el["x"] = round(bx + (badge_w - float(text_el["width"])) / 2.0, 2)
                text_el["y"] = round(pos_y + (badge_h - float(text_el.get("height", 0.0))) / 2.0, 2)
                _set_prop(text_el, ("text_align", "textAlign"), "center")
                self.reflowed_ids.add(text_el.get("id"))

    def _layout_ribbon_group(self, gid: str):
        """Position rotated ribbons in top-right area."""
        group_els = self.groups.get(gid, [])
        if not group_els:
            return

        rw = min(160.0, self.tgt_w * 0.25)
        rh = min(40.0, self.tgt_h * 0.25)
        rx = self.tgt_w - rw - (self.tgt_w * 0.03)
        ry = self.tgt_h * 0.03

        for el in group_els:
            el["width"] = round(rw, 2)
            el["height"] = round(rh, 2)
            el["x"] = round(rx, 2)
            el["y"] = round(ry, 2)
            if el.get("type") == "text":
                self._fit_text_element(el, min_font_size=9, max_font_size=18)
            self.reflowed_ids.add(el.get("id"))

    def _sync_all_groups(self):
        """Ensure all text labels in groups stay centered inside group shapes."""
        for gid, group_els in self.groups.items():
            shape_el = next((e for e in group_els if e.get("type") == "shape"), None)
            text_el = next((e for e in group_els if e.get("type") == "text"), None)
            if shape_el and text_el:
                # Synchronize rotation
                if "rotation" in shape_el:
                    text_el["rotation"] = shape_el["rotation"]

    def _resolve_collisions_and_clamp(self):
        """Clamp non-decorative elements to canvas bounds and resolve overlaps with bounded iterations."""
        # 1. Collision Resolution (Bounded Iterations = 10 max)
        content_eids = [
            el.get("id") for el in self.elements
            if el.get("id") not in self.roles["background"] and el.get("id") not in self.roles["decorative"]
        ]
        
        for _iteration in range(10):
            has_collision = False
            for i in range(len(content_eids)):
                el1 = self.el_map[content_eids[i]]
                g1 = _get_prop(el1, "group_id", "group")
                for j in range(i + 1, len(content_eids)):
                    el2 = self.el_map[content_eids[j]]
                    g2 = _get_prop(el2, "group_id", "group")

                    # Skip overlap checks for elements in the same group or decorative
                    if g1 and g2 and g1 == g2:
                        continue

                    x1, y1 = float(el1.get("x", 0)), float(el1.get("y", 0))
                    w1, h1 = float(el1.get("width", 0)), float(el1.get("height", 0))

                    x2, y2 = float(el2.get("x", 0)), float(el2.get("y", 0))
                    w2, h2 = float(el2.get("width", 0)), float(el2.get("height", 0))

                    # Check bounding box overlap
                    if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                        # Unwanted collision detected — adjust lower element downwards slightly
                        if y1 <= y2:
                            overlap_y = (y1 + h1) - y2
                            if overlap_y > 2.0:
                                el2["y"] = round(y2 + overlap_y + 4.0, 2)
                                has_collision = True
                        else:
                            overlap_y = (y2 + h2) - y1
                            if overlap_y > 2.0:
                                el1["y"] = round(y1 + overlap_y + 4.0, 2)
                                has_collision = True
            if not has_collision:
                break

        # 2. Canvas Bounds Clamping
        for el in self.elements:
            eid = el.get("id")
            if eid in self.roles["background"] or eid in self.roles["decorative"]:
                continue

            w = max(1.0, float(el.get("width", 10.0)))
            h = max(1.0, float(el.get("height", 10.0)))
            x = float(el.get("x", 0.0))
            y = float(el.get("y", 0.0))

            # Clamp x and y to fit inside target canvas
            clamped_x = max(0.0, min(x, self.tgt_w - w))
            clamped_y = max(0.0, min(y, self.tgt_h - h))

            el["x"] = round(clamped_x, 2)
            el["y"] = round(clamped_y, 2)
            el["width"] = round(min(w, self.tgt_w), 2)
            el["height"] = round(min(h, self.tgt_h), 2)


def _safe_fallback_resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    """Safe baseline uniform scaling fallback if any error occurs."""
    src_canvas = source.get("canvas", {})
    src_w = float(src_canvas.get("width", 1080))
    src_h = float(src_canvas.get("height", 1080))

    tgt_w = float(target_canvas.get("width", 1080))
    tgt_h = float(target_canvas.get("height", 1080))

    scale_x = tgt_w / (src_w or 1.0)
    scale_y = tgt_h / (src_h or 1.0)

    out_elements = []
    for el in source.get("elements", []):
        el_copy = dict(el)
        w = float(el_copy.get("width", 10.0))
        h = float(el_copy.get("height", 10.0))
        x = float(el_copy.get("x", 0.0))
        y = float(el_copy.get("y", 0.0))

        el_copy["x"] = max(0.0, min(x * scale_x, tgt_w - 1.0))
        el_copy["y"] = max(0.0, min(y * scale_y, tgt_h - 1.0))
        el_copy["width"] = max(1.0, min(w * scale_x, tgt_w))
        el_copy["height"] = max(1.0, min(h * scale_y, tgt_h))

        fs_val = _get_prop(el_copy, "font_size", "fontSize")
        if fs_val is not None:
            _set_prop(el_copy, ("font_size", "fontSize"), max(8.0, float(fs_val) * min(scale_x, scale_y)))

        out_elements.append(el_copy)

    return {
        "canvas": {"width": int(tgt_w), "height": int(tgt_h)},
        "elements": out_elements,
    }
