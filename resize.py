"""
Project CHAMELEON — Automatic Design Reflow Engine
Implementation in engine/resize.py
"""

import math
from typing import Any, Dict, List, Optional, Tuple


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
    except Exception as e:
        # Fallback to safe proportional scale if unexpected error occurs
        return _safe_fallback_resize(source, target_canvas)


class ReflowEngine:
    def __init__(self, source: dict[str, Any], target_canvas: dict[str, Any]):
        self.src_w = float(source["canvas"]["width"])
        self.src_h = float(source["canvas"]["height"])
        self.tgt_w = float(target_canvas["width"])
        self.tgt_h = float(target_canvas["height"])
        
        self.src_ar = self.src_w / self.src_h if self.src_h > 0 else 1.0
        self.tgt_ar = self.tgt_w / self.tgt_h if self.tgt_h > 0 else 1.0
        
        self.scale_x = self.tgt_w / self.src_w if self.src_w > 0 else 1.0
        self.scale_y = self.tgt_h / self.src_h if self.src_h > 0 else 1.0

        # Deep copy elements to avoid mutating source input
        self.elements = [dict(el) for el in source["elements"]]
        self.el_map = {el["id"]: el for el in self.elements}

        # Analyze roles and groups
        self.groups: Dict[str, List[dict]] = {}
        for el in self.elements:
            gid = el.get("group_id")
            if gid:
                self.groups.setdefault(gid, []).append(el)

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

        # 3. Synchronize Group Elements (e.g. text labels inside button/badge shapes)
        self._sync_all_groups()

        # 4. Resolve Collisions and Clamp within Canvas Bounds
        self._resolve_collisions_and_clamp()

        # 5. Build schema-valid output dictionary
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
            el.get("font_size", 0) for el in self.elements if el["type"] == "text"
        ]
        max_font_size = max(text_font_sizes) if text_font_sizes else 0

        for el in self.elements:
            eid = el["id"]
            etype = el["type"]
            x, y = el["x"], el["y"]
            w, h = el["width"], el["height"]
            opacity = el.get("opacity", 1.0)
            z_index = el.get("z_index", 0)
            gid = el.get("group_id")

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
                gid_lower = gid.lower()
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
                asset_id = str(el.get("asset_id", "")).lower()
                is_top = (y + h / 2) < (0.35 * self.src_h)
                if "logo" in eid.lower() or "logo" in asset_id or (is_top and w / (h or 1) > 2.0):
                    roles["logo"].append(eid)
                else:
                    roles["hero_image"].append(eid)

            elif etype == "text":
                content = str(el.get("content", "")).lower()
                fs = el.get("font_size", 0)

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

        for eid in self.roles["decorative"]:
            el = self.el_map[eid]
            # Scale decor relative to target canvas proportions
            rel_cx = (el["x"] + el["width"] / 2.0) / self.src_w
            rel_cy = (el["y"] + el["height"] / 2.0) / self.src_h
            
            s = min(self.scale_x, self.scale_y)
            new_w = el["width"] * s
            new_h = el["height"] * s
            
            el["width"] = round(new_w, 2)
            el["height"] = round(new_h, 2)
            el["x"] = round((rel_cx * self.tgt_w) - (new_w / 2.0), 2)
            el["y"] = round((rel_cy * self.tgt_h) - (new_h / 2.0), 2)

    def _reflow_vertical_stack(self):
        """Reflow layout for Portrait and Square target canvases (AR <= 1.3)."""
        curr_y = self.tgt_h * 0.04
        content_w = self.tgt_w * 0.88
        center_x = self.tgt_w / 2.0

        # Logo
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            ar = el["width"] / (el["height"] or 1.0)
            target_w = min(self.tgt_w * 0.45, el["width"] * self.scale_x)
            target_h = target_w / (ar or 1.0)
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(center_x - target_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.03)

        # Hero Image
        for eid in self.roles["hero_image"]:
            el = self.el_map[eid]
            ar = el["width"] / (el["height"] or 1.0)
            max_h = self.tgt_h * 0.38
            max_w = content_w
            target_h = min(max_h, max_w / (ar or 1.0))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(center_x - target_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.03)

        # Headline
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(center_x - content_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(content_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.25)
            curr_y += el["height"] + (self.tgt_h * 0.02)

        # Subhead
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(center_x - content_w / 2.0, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(content_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.18)
            curr_y += el["height"] + (self.tgt_h * 0.02)

        # Badges
        badge_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["badge"] if self.el_map[eid].get("group_id")})
        if badge_groups:
            self._layout_badge_row(badge_groups, curr_y, center_x)
            curr_y += self.tgt_h * 0.07

        # CTA
        cta_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["cta"] if self.el_map[eid].get("group_id")})
        for gid in cta_groups:
            self._layout_cta_group(gid, curr_y, center_x)
            curr_y += self.tgt_h * 0.09

        # Legal
        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.92, 2)
            el["x"] = round(center_x - el["width"] / 2.0, 2)
            el["y"] = round(self.tgt_h - el["height"] - (self.tgt_h * 0.02), 2)
            self._fit_text_element(el, min_font_size=9, max_font_size=13)

        # Ribbons
        ribbon_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["ribbon"] if self.el_map[eid].get("group_id")})
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
            ar = el["width"] / (el["height"] or 1.0)
            target_h = min(self.tgt_h * 0.80, left_w / (ar or 1.0))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round((left_w - target_w) / 2.0 + (self.tgt_w * 0.03), 2)
            el["y"] = round((self.tgt_h - target_h) / 2.0, 2)

        curr_y = self.tgt_h * 0.06

        # Logo on right top
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            ar = el["width"] / (el["height"] or 1.0)
            target_w = min(right_w * 0.5, el["width"] * self.scale_x)
            target_h = target_w / (ar or 1.0)
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(right_x + (right_w - target_w) / 2.0, 2)
            el["y"] = round(curr_y, 2)
            curr_y += target_h + (self.tgt_h * 0.04)

        # Headline
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(right_x, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(right_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.32)
            curr_y += el["height"] + (self.tgt_h * 0.03)

        # Subhead
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(right_x, 2)
            el["y"] = round(curr_y, 2)
            el["width"] = round(right_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.22)
            curr_y += el["height"] + (self.tgt_h * 0.03)

        # Badges
        badge_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["badge"] if self.el_map[eid].get("group_id")})
        if badge_groups:
            self._layout_badge_row(badge_groups, curr_y, right_x + right_w / 2.0)
            curr_y += self.tgt_h * 0.08

        # CTA
        cta_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["cta"] if self.el_map[eid].get("group_id")})
        for gid in cta_groups:
            self._layout_cta_group(gid, curr_y, right_x + right_w / 2.0)
            curr_y += self.tgt_h * 0.10

        # Legal
        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.90, 2)
            el["x"] = round((self.tgt_w - el["width"]) / 2.0, 2)
            el["y"] = round(self.tgt_h - el["height"] - (self.tgt_h * 0.02), 2)
            self._fit_text_element(el, min_font_size=8, max_font_size=12)

        # Ribbons
        ribbon_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["ribbon"] if self.el_map[eid].get("group_id")})
        for gid in ribbon_groups:
            self._layout_ribbon_group(gid)

    def _reflow_extreme_leaderboard(self):
        """Reflow layout for Extreme Landscape / Leaderboard (AR > 2.8, e.g. 728x90)."""
        curr_x = self.tgt_w * 0.02
        center_y = self.tgt_h / 2.0

        # 1. Logo Zone (Far Left)
        for eid in self.roles["logo"]:
            el = self.el_map[eid]
            ar = el["width"] / (el["height"] or 1.0)
            target_h = min(self.tgt_h * 0.65, max(24.0, el["height"] * self.scale_y * 1.5))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(curr_x, 2)
            el["y"] = round(center_y - target_h / 2.0, 2)
            curr_x += target_w + (self.tgt_w * 0.02)

        # 2. Hero Image Zone
        for eid in self.roles["hero_image"]:
            el = self.el_map[eid]
            ar = el["width"] / (el["height"] or 1.0)
            target_h = min(self.tgt_h * 0.75, max(30.0, el["height"] * self.scale_y * 1.5))
            target_w = target_h * ar
            el["width"] = round(target_w, 2)
            el["height"] = round(target_h, 2)
            el["x"] = round(curr_x, 2)
            el["y"] = round(center_y - target_h / 2.0, 2)
            curr_x += target_w + (self.tgt_w * 0.02)

        # 3. Right Zone for CTA (Far Right)
        cta_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["cta"] if self.el_map[eid].get("group_id")})
        cta_reserved_w = min(180.0, self.tgt_w * 0.25) if cta_groups else 0.0
        text_zone_right = self.tgt_w - cta_reserved_w - (self.tgt_w * 0.02)
        text_zone_w = max(self.tgt_w * 0.30, text_zone_right - curr_x)

        # 4. Headline in Text Zone
        for eid in self.roles["headline"]:
            el = self.el_map[eid]
            el["x"] = round(curr_x, 2)
            el["width"] = round(text_zone_w, 2)
            self._fit_text_element(el, max_height=self.tgt_h * 0.55, min_font_size=10, max_font_size=15)
            el["y"] = round(center_y - el["height"] / 2.0, 2)

        # 5. Position CTA Button on Far Right
        for gid in cta_groups:
            cta_x = self.tgt_w - cta_reserved_w - (self.tgt_w * 0.02)
            self._layout_cta_group(gid, center_y, cta_x + cta_reserved_w / 2.0, is_vertical_center=True, target_w=cta_reserved_w)

        # 6. Compact Badges
        badge_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["badge"] if self.el_map[eid].get("group_id")})
        if badge_groups:
            self._layout_badge_row(badge_groups, 4.0, self.tgt_w * 0.5, max_badge_w=90.0)

        # 7. Subhead & Legal in Banner
        for eid in self.roles["subhead"]:
            el = self.el_map[eid]
            el["x"] = round(curr_x, 2)
            el["width"] = round(text_zone_w, 2)
            self._fit_text_element(el, min_font_size=8, max_font_size=11)
            el["y"] = round(self.tgt_h - el["height"] - 2, 2)

        for eid in self.roles["legal"]:
            el = self.el_map[eid]
            el["width"] = round(self.tgt_w * 0.40, 2)
            el["x"] = round(self.tgt_w - el["width"] - 5, 2)
            el["y"] = round(self.tgt_h - 12, 2)
            self._fit_text_element(el, min_font_size=7, max_font_size=9)

        # Ribbons
        ribbon_groups = list({self.el_map[eid].get("group_id") for eid in self.roles["ribbon"] if self.el_map[eid].get("group_id")})
        for gid in ribbon_groups:
            self._layout_ribbon_group(gid)

    def _fit_text_element(self, el: dict, max_height: Optional[float] = None, min_font_size: float = 8.0, max_font_size: float = 72.0):
        """Dynamically compute font_size and height for text fitting."""
        content = el.get("content", "")
        if not content:
            return

        box_w = max(10.0, float(el["width"]))
        src_fs = float(el.get("font_size", 20.0))

        # Target font size estimation
        scale = min(self.scale_x, self.scale_y)
        target_fs = max(min_font_size, min(max_font_size, src_fs * scale))

        # Calculate line wrapping
        char_w = target_fs * 0.52
        chars_per_line = max(1, int(box_w / char_w))
        
        lines = math.ceil(len(content) / chars_per_line)
        max_lines = el.get("max_lines")
        if max_lines:
            lines = min(lines, max_lines)

        line_height_multiplier = el.get("line_height", 1.2)
        needed_h = lines * target_fs * line_height_multiplier

        if max_height and needed_h > max_height:
            # Scale down font size to fit max_height
            ratio = max_height / (needed_h or 1.0)
            target_fs = max(min_font_size, target_fs * math.sqrt(ratio))
            chars_per_line = max(1, int(box_w / (target_fs * 0.52)))
            lines = math.ceil(len(content) / chars_per_line)
            if max_lines:
                lines = min(lines, max_lines)
            needed_h = lines * target_fs * line_height_multiplier

        el["font_size"] = round(target_fs, 1)
        el["height"] = round(needed_h, 1)

    def _layout_cta_group(self, gid: str, pos_y: float, center_x: float, is_vertical_center: bool = False, target_w: Optional[float] = None):
        """Layout CTA button group (shape + text label)."""
        group_els = self.groups.get(gid, [])
        if not group_els:
            return

        shape_el = next((e for e in group_els if e["type"] == "shape"), group_els[0])
        text_el = next((e for e in group_els if e["type"] == "text"), None)

        actual_target_w = target_w or min(self.tgt_w * 0.45, shape_el["width"] * self.scale_x)
        actual_target_h = max(32.0, min(self.tgt_h * 0.45, shape_el["height"] * self.scale_y))

        shape_x = center_x - actual_target_w / 2.0
        shape_y = pos_y - actual_target_h / 2.0 if is_vertical_center else pos_y

        shape_el["width"] = round(actual_target_w, 2)
        shape_el["height"] = round(actual_target_h, 2)
        shape_el["x"] = round(shape_x, 2)
        shape_el["y"] = round(shape_y, 2)
        if "corner_radius" in shape_el:
            shape_el["corner_radius"] = round(min(actual_target_h / 2.0, actual_target_h * 0.45), 1)

        if text_el:
            text_el["width"] = round(actual_target_w * 0.9, 2)
            self._fit_text_element(text_el, max_height=actual_target_h * 0.8, min_font_size=10, max_font_size=24)
            text_el["x"] = round(center_x - text_el["width"] / 2.0, 2)
            text_el["y"] = round(shape_y + (actual_target_h - text_el["height"]) / 2.0, 2)
            text_el["text_align"] = "center"

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
            shape_el = next((e for e in group_els if e["type"] == "shape"), None)
            text_el = next((e for e in group_els if e["type"] == "text"), None)

            if shape_el:
                shape_el["x"] = round(bx, 2)
                shape_el["y"] = round(pos_y, 2)
                shape_el["width"] = round(badge_w, 2)
                shape_el["height"] = round(badge_h, 2)
                if "corner_radius" in shape_el:
                    shape_el["corner_radius"] = round(min(badge_h / 2.0, badge_h * 0.45), 1)

            if text_el:
                text_el["width"] = round(badge_w * 0.9, 2)
                self._fit_text_element(text_el, max_height=badge_h * 0.8, min_font_size=8, max_font_size=16)
                text_el["x"] = round(bx + (badge_w - text_el["width"]) / 2.0, 2)
                text_el["y"] = round(pos_y + (badge_h - text_el["height"]) / 2.0, 2)
                text_el["text_align"] = "center"

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
            if el["type"] == "text":
                self._fit_text_element(el, min_font_size=9, max_font_size=18)

    def _sync_all_groups(self):
        """Ensure all text labels in groups stay centered inside group shapes."""
        for gid, group_els in self.groups.items():
            shape_el = next((e for e in group_els if e["type"] == "shape"), None)
            text_el = next((e for e in group_els if e["type"] == "text"), None)
            if shape_el and text_el:
                # Synchronize rotation
                if "rotation" in shape_el:
                    text_el["rotation"] = shape_el["rotation"]

    def _resolve_collisions_and_clamp(self):
        """Clamp non-decorative elements to canvas bounds and prevent off-canvas rendering."""
        for el in self.elements:
            eid = el["id"]
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
    scale_x = target_canvas["width"] / source["canvas"]["width"]
    scale_y = target_canvas["height"] / source["canvas"]["height"]

    out_elements = []
    for el in source["elements"]:
        el_copy = dict(el)
        el_copy["x"] = max(0.0, min(el_copy["x"] * scale_x, float(target_canvas["width"]) - 1.0))
        el_copy["y"] = max(0.0, min(el_copy["y"] * scale_y, float(target_canvas["height"]) - 1.0))
        el_copy["width"] = max(1.0, min(el_copy["width"] * scale_x, float(target_canvas["width"])))
        el_copy["height"] = max(1.0, min(el_copy["height"] * scale_y, float(target_canvas["height"])))
        if el_copy["type"] == "text":
            el_copy["font_size"] = max(8.0, el_copy["font_size"] * min(scale_x, scale_y))
        out_elements.append(el_copy)

    return {
        "canvas": {"width": target_canvas["width"], "height": target_canvas["height"]},
        "elements": out_elements,
    }
