"""
Prism Motion Graphics — authored fixtures
──────────────────────────────────────────
Hand-written specs that exercise the material and camera primitives with
known-good values. They are the reference the runtime is validated
against BEFORE the model is shown a primitive in the catalogue: if an
authored fixture does not render as intended, no prompt wording will.

Used by tests/test_motion_materials.py and examples/motion_materials.py.
Stdlib only.
"""
from __future__ import annotations

from typing import Any, Dict


def materials_fixture(width: int = 1080, height: int = 1920, fps: int = 30,
                      brand: str = "Prism",
                      tagline: str = "Long reads, distilled.") -> Dict[str, Any]:
    """Three shots on one continuity thread.

    far  light_field   (depth 0.55)  — the light behind everything
    mid  glass_panel   (depth 1.0)   — the carried subject, key "panel"
    near accent pill   (depth 1.45)  — a floating detail that leads the camera

    Shots: reveal → push → resolve, so the compiled camera curve settles,
    moves in on the panel and returns to centre for the ending.
    """
    w, h = float(width), float(height)
    cx, cy = w / 2, h / 2
    s = w / 1080.0  # scale every authored size with the frame

    def panel(node_id: str, pos, size, headline: str, sub: str, key: str = "panel"):
        pw, ph = size
        return {
            "id": node_id, "type": "glass_panel", "position": list(pos),
            "width": pw, "height": ph, "radius": 36 * s,
            "tint": "#1B2140", "transmission": 0.62, "blur": 22,
            "border_light": 0.7, "inner_shadow": 0.45, "specular": 0.55,
            "contrast_guard": "dark", "layer": "midground",
            "continuity_key": key,
            "children": [
                {"id": f"{node_id}_h", "type": "text", "content": headline,
                 "position": [0, -ph * 0.16], "font_size": 64 * s, "font_weight": 800,
                 "fill": "#F5F7FF", "mode": "masked_reveal", "reveal_start": 0.25},
                {"id": f"{node_id}_s", "type": "text", "content": sub,
                 "position": [0, ph * 0.18], "font_size": 30 * s, "font_weight": 500,
                 "fill": "rgba(245,247,255,0.78)", "mode": "standard",
                 "animation": {"enter": {"time": 0.3, "duration": 0.5, "tweens": [
                     {"channel": "opacity", "from": 0, "to": 1},
                     {"channel": "y", "from": 18, "to": 0, "easing": "power2.out"}]}}},
            ],
        }

    def light(node_id: str, pos, color, color2):
        return {
            "id": node_id, "type": "light_field", "position": list(pos),
            "width": w * 1.1, "height": w * 1.1, "color": color, "color2": color2,
            "intensity": 0.7, "spread": 1.0, "drift": 50 * s, "layer": "background",
            "animation": {"secondary_motion": {"property": "x", "freq": 0.08,
                                               "amount": 30 * s, "seed": node_id}},
        }

    def pill(node_id: str, pos, label: str):
        return {
            "id": node_id, "type": "shape_rect", "position": list(pos),
            "width": 240 * s, "height": 64 * s, "radius": 32 * s,
            "fill": "rgba(255,255,255,0.10)", "stroke": "rgba(255,255,255,0.35)",
            "stroke_width": 1, "layer": "accent",
            "children": [{"id": f"{node_id}_t", "type": "text", "content": label,
                          "position": [0, 0], "font_size": 24 * s, "font_weight": 600,
                          "fill": "#FFFFFF", "mode": "standard"}],
            "animation": {"enter": {"time": 0.8, "duration": 0.6, "tweens": [
                {"channel": "opacity", "from": 0, "to": 1},
                {"channel": "scale", "from": -0.2, "to": 0, "easing": "back.out(1.6)"}]},
                "secondary_motion": {"property": "y", "freq": 0.25, "amount": 8 * s,
                                     "seed": node_id}},
        }

    def scene(idx: int, seconds: float, shot: Dict[str, Any], far, mid, near):
        return {
            "id": f"scene_{idx}", "duration": seconds, "shot": shot,
            "nodes": [
                {"id": f"far_{idx}", "type": "depth_layer", "depth": 0.55,
                 "position": [0, 0], "children": [far]},
                {"id": f"mid_{idx}", "type": "depth_layer", "depth": 1.0,
                 "position": [0, 0], "children": [mid]},
                {"id": f"near_{idx}", "type": "depth_layer", "depth": 1.45,
                 "position": [0, 0], "children": [near]},
            ],
        }

    pw, ph = 820 * s, 520 * s
    return {
        "project": {
            "width": width, "height": height, "fps": fps, "duration": 7.5,
            "background": "#070A16",
            "palette": {"bg_a": "#070A16", "bg_b": "#131A33", "ink": "#F5F7FF",
                        "accent": "#7C9CFF", "accent2": "#FF6B8B"},
        },
        "visual": {"background": "#070A16", "vignette_strength": 0.5,
                   "grain_opacity": 0.04, "grid": {"enabled": False},
                   "spotlight": {"position": [0.5, 0.35],
                                 "color": "rgba(60,80,160,0.16)"}},
        "_motion_profile": "cinematic_glass",
        "scenes": [
            scene(0, 2.5, {"intent": "reveal", "target": "panel_0"},
                  light("light_0", [cx - 120 * s, cy - 260 * s],
                        "rgba(124,156,255,0.55)", "rgba(255,107,139,0.35)"),
                  panel("panel_0", [cx, cy - 80 * s], (pw, ph),
                        "Every source,\none signal", "Reading the brief"),
                  pill("pill_0", [cx + 250 * s, cy - 400 * s], "NEW")),
            scene(1, 2.5, {"intent": "push", "target": "panel_1", "zoom": 1.18},
                  light("light_1", [cx + 140 * s, cy - 120 * s],
                        "rgba(124,156,255,0.55)", "rgba(255,107,139,0.35)"),
                  panel("panel_1", [cx - 40 * s, cy + 40 * s], (pw, ph),
                        "Structured\nevidence", "Claims, context, numbers"),
                  pill("pill_1", [cx - 280 * s, cy - 320 * s], "TRACEABLE")),
            scene(2, 2.5, {"intent": "resolve"},
                  light("light_2", [cx, cy],
                        "rgba(124,156,255,0.5)", "rgba(255,107,139,0.4)"),
                  panel("panel_2", [cx, cy], (pw * 0.92, ph * 0.92),
                        brand, tagline),
                  pill("pill_2", [cx, cy + 420 * s], "TRY IT")),
        ],
    }


def inspo_fixture(width: int = 1080, height: int = 1920, fps: int = 60,
                  brand: str = "IIEleven Agents",
                  tagline: str = "Pre-built, configurable AI Agents with a human touch",
                  cta: str = "Talk to the team") -> Dict[str, Any]:
    """The reference film (inspo.mp4), recreated beat for beat in the Motion
    pipeline — core.motion.compose.compose() with the reference's own copy.
    Eleven scenes on one continuity thread ("signal"):

    scattered tiles → a band with labelled cards → tiles stream into a
    column while chat / phone / mail icons converge on a hub → a dark
    sphere hangs over a tree of thin lines among bokeh → a blue light sweeps
    in and a conversation plays in bubbles → a knowledge tree with cards →
    the Knowledge Base card over a glowing graph → a great arc and 24/7 →
    the glowing orb → the logo, tagline and call to action.

    Coordinates are authored in 1080x1920 and scaled to the frame.
    """
    from .compose import REFERENCE_COPY, compose
    copy = dict(REFERENCE_COPY)
    copy.update({"brand": brand, "tagline": tagline, "cta": cta})
    return compose(copy, width=width, height=height, fps=fps)
