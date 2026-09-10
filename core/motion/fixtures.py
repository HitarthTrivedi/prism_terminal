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
    pipeline. Eleven scenes on one continuity thread ("signal"):

    scattered tiles → a band with labelled cards → tiles stream into a
    column while chat / phone / mail icons converge on a hub → a dark
    sphere hangs over a tree of thin lines among bokeh → a blue light sweeps
    in and a conversation plays in bubbles → a knowledge tree with cards →
    the Knowledge Base card over a glowing graph → a great arc and 24/7 →
    the glowing orb → the logo, tagline and call to action.

    Coordinates are authored in 1080x1920 and scaled to the frame.
    """
    s = width / 1080.0

    def P(x, y):
        return [round(x * s, 1), round(y * s, 1)]

    def S(v):
        return round(v * s, 2)

    def text(node_id, content, x, y, size, weight=600, fill="#F5F7FF", mode="standard",
             enter=None, exit_=None, **extra):
        node = {"id": node_id, "type": "text", "content": content, "position": P(x, y),
                "font_size": S(size), "font_weight": weight, "fill": fill, "mode": mode,
                "layer": "foreground"}
        node.update(extra)
        anim = {}
        if enter:
            anim["enter"] = enter
        if exit_:
            anim["exit"] = exit_
        if anim:
            node["animation"] = anim
        return node

    def fade_in(at, dur=0.5, dy=18, easing="power2.out"):
        tweens = [{"channel": "opacity", "from": 0, "to": 1}]
        if dy:
            tweens.append({"channel": "y", "from": S(dy), "to": 0, "easing": easing})
        return {"time": at, "duration": dur, "tweens": tweens}

    def fade_out(at, dur=0.4, dy=-12):
        tweens = [{"channel": "opacity", "from": 1, "to": 0}]
        if dy:
            tweens.append({"channel": "y", "from": 0, "to": S(dy), "easing": "power2.in"})
        return {"time": at, "duration": dur, "tweens": tweens}

    def slide_in(at, dur=0.8, dx=700):
        return {"time": at, "duration": dur, "tweens": [
            {"channel": "opacity", "from": 0, "to": 1, "easing": "power2.out"},
            {"channel": "x", "from": S(dx), "to": 0, "easing": "power3.out"},
            {"channel": "blur", "from": 10, "to": 0, "easing": "power2.out"}]}

    def slide_out(at, dur=0.6, dx=-420):
        return {"time": at, "duration": dur, "tweens": [
            {"channel": "opacity", "from": 1, "to": 0, "easing": "power2.in"},
            {"channel": "x", "from": 0, "to": S(dx), "easing": "power3.in"},
            {"channel": "blur", "from": 0, "to": 12}]}

    def glass_card(node_id, x, y, w, h, lines, size=22, title=None, enter_at=0.3,
                   exit_at=None, key=None, blur=0.0, radius=18, tint="#0d1119",
                   transmission=0.42):
        children = []
        if title:
            children.append(text(f"{node_id}_t", title, 0, -h * 0.28, size + 8, 700))
        children.append(text(f"{node_id}_b", lines, 0, (h * 0.12 if title else 0), size, 400,
                             fill="rgba(245,247,255,0.86)", line_height=1.3))
        node = {"id": node_id, "type": "glass_panel", "position": P(x, y), "width": S(w),
                "height": S(h), "radius": S(radius), "tint": tint, "transmission": transmission,
                "blur": 16, "border_light": 0.5, "inner_shadow": 0.3, "specular": 0.25,
                "contrast_guard": "dark", "layer": "midground", "children": children,
                "animation": {"enter": fade_in(enter_at, 0.6, 26)}}
        if exit_at is not None:
            node["animation"]["exit"] = fade_out(exit_at)
        if key:
            node["continuity_key"] = key
        if blur:
            node["animation"]["enter"]["tweens"].append({"channel": "blur", "from": blur, "to": blur})
        return node

    def light(node_id, x, y, size, color, color2=None, intensity=0.6, drift=40, layer="background",
              enter=None, exit_=None, key=None, spread=1.0):
        node = {"id": node_id, "type": "light_field", "position": P(x, y), "width": S(size),
                "height": S(size), "color": color, "color2": color2 or color,
                "intensity": intensity, "spread": spread, "drift": S(drift), "layer": layer,
                "animation": {"secondary_motion": {"property": "y", "freq": 0.07,
                                                   "amount": S(24), "seed": node_id}}}
        if enter:
            node["animation"]["enter"] = enter
        if exit_:
            node["animation"]["exit"] = exit_
        if key:
            node["continuity_key"] = key
        return node

    def field(node_id, phases, count=230, size=21, key="signal", flicker=0.25):
        scaled = []
        for ph in phases:
            lay = dict(ph["layout"])
            for k in ("x0", "x1", "y", "x", "y0", "y1", "cell", "spread", "radius", "jitter"):
                if k in lay:
                    lay[k] = S(lay[k])
            if "box" in lay:
                lay["box"] = [S(v) for v in lay["box"]]
            if "center" in lay:
                lay["center"] = P(*lay["center"])
            if "points" in lay:
                lay["points"] = [P(*p) for p in lay["points"]]
            scaled.append({**ph, "layout": lay})
        return {"id": node_id, "type": "particle_field", "position": [0, 0], "count": count,
                "size": S(size), "seed": "inspo-signal", "phases": scaled, "flicker": flicker,
                "layer": "midground", "continuity_key": key,
                "palette": ["#4f8cff", "#ff5fa8", "#b58cff", "#eef3ff", "#2a3f9a", "#7b3f8f",
                            "#8fb3ff", "#ff8fc6", "#1f2a5c", "#3ddad0"]}

    def icon(node_id, name, x, y, size, enter_at, exit_at=None, tile=True, color="#FFFFFF"):
        node = {"id": node_id, "type": "icon", "name": name, "position": P(x, y), "size": S(size),
                "tile": tile, "color": color, "layer": "foreground",
                "animation": {"enter": {"time": enter_at, "duration": 0.55, "tweens": [
                    {"channel": "opacity", "from": 0, "to": 1},
                    {"channel": "scale", "from": -0.3, "to": 0, "easing": "back.out(1.7)"}]},
                    "secondary_motion": {"property": "y", "freq": 0.22, "amount": S(6), "seed": node_id}}}
        if exit_at is not None:
            node["animation"]["exit"] = fade_out(exit_at, 0.35)
        return node

    def scene(idx, seconds, shot, nodes, easing=None):
        out = {"id": f"scene_{idx}", "duration": seconds, "shot": shot, "nodes": nodes}
        if easing:
            out["handoff_easing"] = easing
        return out

    scatter = {"kind": "scatter", "box": [20, 40, 1060, 760], "cluster": 6, "cell": 25}
    band = {"kind": "band", "y": 830, "rows": 5, "cell": 25, "x0": 10, "x1": 1070}
    column = {"kind": "column", "x": 400, "spread": 70, "y0": -100, "y1": 1500}
    hub_points = {"kind": "points", "points": [[540, 1500], [520, 1380], [560, 1420]], "jitter": 30}
    hidden = {"kind": "hidden"}

    scenes = [
        # 1 · scattered signal
        scene(0, 2.6, {"intent": "hold"}, [
            field("field_0", [{"at": 0.0, "layout": hidden},
                              {"at": 0.05, "layout": scatter, "duration": 0.5, "stagger": 0.7},
                              {"at": 0.9, "layout": band, "duration": 1.3, "stagger": 0.9}]),
        ]),
        # 2 · the band, and what it is for
        scene(1, 3.0, {"intent": "parallax"}, [
            field("field_1", [{"at": 0.0, "layout": band},
                              {"at": 2.2, "layout": column, "duration": 0.9, "stagger": 0.4}]),
            glass_card("card_cs", 220, 1020, 250, 76, "Customer Support", 20, enter_at=0.4, exit_at=2.3,
                       tint="#4a2f8a", transmission=0.35),
            glass_card("card_hr", 537, 1030, 300, 76, "Hotel Receptionist", 20, enter_at=0.55, exit_at=2.3,
                       tint="#8a2f6a", transmission=0.35),
            glass_card("card_as", 860, 1040, 280, 76, "Appointment Setter", 20, enter_at=0.7, exit_at=2.3,
                       tint="#1f6f6a", transmission=0.35),
        ]),
        # 3 · the stream, the channels, the tree
        scene(2, 2.8, {"intent": "push", "target": "phone", "zoom": 1.08}, [
            field("field_2", [{"at": 0.0, "layout": column},
                              {"at": 1.5, "layout": hub_points, "duration": 0.8, "stagger": 0.3},
                              {"at": 2.3, "layout": hidden, "duration": 0.4, "stagger": 0.1}]),
            icon("chat_a", "chat", 295, 458, 96, 0.35, exit_at=2.35),
            icon("chat_b", "chat", 531, 329, 74, 0.5, exit_at=2.35),
            icon("phone", "phone", 517, 557, 268, 0.15, exit_at=2.4),
            icon("mail", "mail", 798, 458, 112, 0.6, exit_at=2.35),
            icon("whatsapp", "whatsapp", 309, 880, 96, 1.0, exit_at=2.35),
            {"id": "tree_in", "type": "spline_tree", "position": [0, 0], "hub": P(540, 1500),
             "leaves": [P(295, 500), P(531, 370), P(517, 690), P(798, 510), P(309, 930)],
             "color": "rgba(255,255,255,0.5)", "stroke_width": S(1.6), "bend": 0.55,
             "draw_start": 1.2, "draw_duration": 0.8, "stagger": 0.08, "layer": "midground",
             "animation": {"exit": fade_out(2.35, 0.3, 0)}},
        ]),
        # 4 · the hub sphere, the tree, the bokeh
        scene(3, 3.5, {"intent": "push", "target": "hub_orb", "zoom": 1.1}, [
            light("bokeh_orange", 498, 1268, 260, "rgba(255,160,70,1)", intensity=1.0, drift=26,
                  enter=fade_in(0.4, 0.8, 0), spread=0.5),
            light("bokeh_purple", 300, 1090, 340, "rgba(160,100,255,0.9)", intensity=0.8, drift=34,
                  enter=fade_in(0.7, 0.9, 0), spread=0.55),
            light("bokeh_blue", 800, 900, 260, "rgba(100,160,255,1)", intensity=0.9, drift=30,
                  enter=fade_in(0.9, 0.9, 0), spread=0.5),
            light("bokeh_gold", 1000, 1150, 180, "rgba(255,210,120,1)", intensity=0.9, drift=20,
                  enter=fade_in(1.4, 0.8, 0), spread=0.45),
            text("logo_top", brand, 540, 120, 44, 700, enter=fade_in(0.2, 0.6, 10)),
            {"id": "hang_line", "type": "shape_rect", "position": P(492, 232), "width": S(2),
             "height": S(470), "fill": "rgba(255,255,255,0.35)", "anchor": [0.5, 0], "layer": "midground",
             "animation": {"enter": {"time": 0.0, "duration": 0.7, "tweens": [
                 {"channel": "clipInset", "from": 0, "to": 100, "easing": "power2.out"}]}}},
            {"id": "hub_orb", "type": "orb", "position": P(492, 467), "radius": S(112),
             "core": "#0b0e15", "tint": "rgba(255,255,255,0.16)", "rim": "rgba(255,255,255,0.28)",
             "layer": "foreground", "continuity_key": "signal",
             "animation": {"secondary_motion": {"property": "y", "freq": 0.12, "amount": S(8), "seed": "hub"}}},
            {"id": "tree_hub", "type": "spline_tree", "position": [0, 0], "hub": P(492, 579),
             "leaves": [P(877, 438), P(250, 1000), P(700, 1240), P(420, 1400)],
             "color": "rgba(255,255,255,0.32)", "stroke_width": S(1.4), "bend": 0.5,
             "draw_start": 0.5, "draw_duration": 1.0, "stagger": 0.12, "layer": "midground"},
            glass_card("card_inbound", 877, 438, 270, 96, "Qualifies inbound leads from\nbudget and timing", 17,
                       title="Inbound", enter_at=1.2, blur=1.5),
            icon("wire", "spark", 104, 438, 130, 0.9, tile=False, color="rgba(170,120,255,0.75)"),
        ]),
        # 5 · light sweeps in; the conversation
        scene(4, 4.8, {"intent": "parallax", "target": P(600, 900)}, [
            {"id": "sky", "type": "shape_circle", "position": P(700, 1000), "radius": S(1500),
             "layer": "background",
             "fill": "radial-gradient(circle at 62% 30%, #f7faff 0%, #d6e7ff 20%, #86b4ff 48%, #2f66e6 78%, #1d47b8 100%)",
             "animation": {"enter": {"time": 0.0, "duration": 0.65, "tweens": [
                 {"channel": "x", "from": S(2400), "to": 0, "easing": "power3.out"},
                 {"channel": "scale", "from": -0.3, "to": 0, "easing": "power3.out"}]},
                 "secondary_motion": {"property": "x", "freq": 0.06, "amount": S(30), "seed": "sky"}}},
            light("sky_glow", 900, 300, 1600, "rgba(255,255,255,0.9)", "rgba(190,220,255,0.8)",
                  intensity=0.7, drift=50, layer="midground",
                  enter=fade_in(0.2, 0.8, 0)),
            {"id": "bubble_1", "type": "shape_rect", "position": P(470, 790), "width": S(1180),
             "height": S(210), "radius": S(72), "fill": "#FFFFFF", "layer": "foreground",
             "shadow_color": "rgba(20,40,90,0.28)", "shadow_blur": S(44), "shadow_offset_y": S(20),
             "children": [text("bubble_1_t", "Ok Holly, we’ve processed your\nreturn, your store credit is rea…",
                               60, 0, 62, 500, fill="#101216", line_height=1.22)],
             "animation": {"enter": slide_in(0.35, 0.9, 760), "exit": slide_out(3.7, 0.6, -520)}},
            {"id": "bubble_2", "type": "shape_rect", "position": P(860, 930), "width": S(700),
             "height": S(120), "radius": S(60), "fill": "#2563FF", "layer": "foreground",
             "continuity_key": "signal",
             "shadow_color": "rgba(20,40,90,0.28)", "shadow_blur": S(36), "shadow_offset_y": S(16),
             "children": [text("bubble_2_t", "Does it ever expire?", 0, 0, 56, 500, fill="#FFFFFF")],
             "animation": {"enter": slide_in(1.25, 0.9, 700), "exit": slide_out(3.75, 0.55, -460)}},
            {"id": "bubble_3", "type": "shape_rect", "position": P(300, 1085), "width": S(900),
             "height": S(130), "radius": S(64), "fill": "#FFFFFF", "layer": "foreground",
             "shadow_color": "rgba(20,40,90,0.28)", "shadow_blur": S(36), "shadow_offset_y": S(16),
             "children": [text("bubble_3_t", "…it never expires at all!", 40, 0, 56, 500, fill="#101216")],
             "animation": {"enter": slide_in(2.1, 0.9, 760), "exit": slide_out(3.8, 0.5, -420)}},
        ], easing="power3.inOut"),
        # 6 · the knowledge tree and its cards
        scene(5, 2.3, {"intent": "push", "target": "card_desk", "zoom": 1.1}, [
            {"id": "sky_2", "type": "shape_rect", "position": P(540, 960), "width": S(1400),
             "height": S(2200), "radius": 0, "layer": "background",
             "fill": "linear-gradient(215deg, #dcebff 0%, #8fb8ff 35%, #3a6fe8 70%, #16307f 100%)",
             "animation": {"secondary_motion": {"property": "x", "freq": 0.05, "amount": S(24), "seed": "sky2"}}},
            light("sky_2_glow", 300, 500, 1300, "rgba(255,255,255,0.8)", "rgba(200,225,255,0.7)",
                  intensity=0.55, drift=40, layer="midground"),
            {"id": "tree_cards", "type": "spline_tree", "position": [0, 0], "hub": P(540, 260),
             "leaves": [P(680, 453), P(560, 838), P(565, 734), P(300, 600)],
             "color": "rgba(255,255,255,0.55)", "stroke_width": S(1.6), "bend": 0.5,
             "draw_start": 0.1, "draw_duration": 0.9, "stagger": 0.1, "layer": "midground"},
            glass_card("card_web", 680, 453, 380, 130, "…web forms and ads, assess\nroutes to the right sales rep…", 19,
                       enter_at=0.5, blur=2.5),
            text("label_desk", "Front Desk Receptionist", 560, 838, 22, 600, enter=fade_in(0.8, 0.5, 8)),
            glass_card("card_desk", 565, 734, 520, 150, "…desk receptionist to handle department\ninquiries", 19,
                       enter_at=0.7, key="signal"),
            glass_card("card_ads", 300, 600, 300, 110, "Handles web forms\nand ads", 18, enter_at=0.9, blur=3.0),
        ]),
        # 7 · the Knowledge Base
        scene(6, 3.7, {"intent": "hold"}, [
            light("kb_glow", 545, 1150, 900, "rgba(70,120,255,0.6)", intensity=0.5, drift=20,
                  enter=fade_in(0.6, 1.0, 0)),
            {"id": "kb_card", "type": "glass_panel", "position": P(545, 838), "width": S(590),
             "height": S(225), "radius": S(26), "tint": "#0b0f17", "transmission": 0.4, "blur": 18,
             "border_light": 0.55, "inner_shadow": 0.35, "specular": 0.3, "contrast_guard": "dark",
             "layer": "midground", "continuity_key": "signal",
             "children": [
                 {"id": "kb_icon", "type": "icon", "name": "book", "position": P(-230, -48), "size": S(44),
                  "tile": False, "color": "#F5F7FF"},
                 text("kb_title", "Knowledge Base", -30, -48, 32, 700),
                 text("kb_desc", "Connects your agent to internal docs so\nanswers stay accurate and up to date.",
                      0, 42, 21, 400, fill="rgba(245,247,255,0.78)", line_height=1.35)],
             "animation": {"enter": fade_in(0.25, 0.7, 20)}},
            {"id": "tree_kb", "type": "spline_tree", "position": [0, 0], "hub": P(545, 950),
             "leaves": [P(250, 1250), P(540, 1360), P(840, 1250), P(400, 1460), P(700, 1470)],
             "color": "rgba(140,200,255,0.95)", "stroke_width": S(1.8), "bend": 0.45,
             "glow_blur": S(10), "draw_start": 0.9, "draw_duration": 1.0, "stagger": 0.1, "layer": "midground"},
            icon("kb_leaf_a", "dial", 250, 1250, 60, 1.7, tile=False, color="rgba(160,210,255,0.9)"),
            icon("kb_leaf_b", "book", 540, 1360, 60, 1.8, tile=False, color="rgba(160,210,255,0.9)"),
            icon("kb_leaf_c", "check", 840, 1250, 60, 1.9, tile=False, color="rgba(160,210,255,0.9)"),
            text("label_sales", "Product Sales", 250, 1292, 18, 500, fill="rgba(200,215,255,0.8)",
                 enter=fade_in(1.9, 0.4, 6)),
            text("label_comp", "Compliance", 840, 1292, 18, 500, fill="rgba(200,215,255,0.8)",
                 enter=fade_in(2.0, 0.4, 6)),
        ]),
        # 8 · the great arc, always on
        scene(7, 1.8, {"intent": "pull"}, [
            {"id": "arc", "type": "shape_circle", "position": P(1250, 300), "radius": S(900),
             "fill": "none", "stroke": "rgba(255,255,255,0.4)", "stroke_width": S(2), "layer": "midground",
             "continuity_key": "signal",
             "animation": {"enter": {"time": 0.0, "duration": 1.2, "tweens": [
                 {"channel": "opacity", "from": 0, "to": 1, "easing": "power2.out"},
                 {"channel": "scale", "from": -0.08, "to": 0, "easing": "power2.out"}]},
                 "secondary_motion": {"property": "rotation", "freq": 0.05, "amount": 2, "seed": "arc"}}},
            text("always", "24/7", 332, 135, 34, 500, enter=fade_in(0.5, 0.5, 6)),
        ]),
        # 9 · the orb
        scene(8, 2.1, {"intent": "macro", "target": "orb", "zoom": 1.2}, [
            {"id": "orb_ring", "type": "shape_circle", "position": P(700, 500), "radius": S(560),
             "fill": "none", "stroke": "rgba(255,255,255,0.14)", "stroke_width": S(1.5), "layer": "background",
             "animation": {"secondary_motion": {"property": "rotation", "freq": 0.06, "amount": 3, "seed": "ring"}}},
            {"id": "orb", "type": "orb", "position": P(498, 616), "radius": S(170), "core": "#1b7a6a",
             "tint": "rgba(140,255,190,0.6)", "rim": "rgba(200,255,220,0.45)", "glow_color": "#37c98a",
             "glow_blur": S(70), "highlight": 0.7, "icon": "dial", "layer": "foreground",
             "continuity_key": "signal",
             "animation": {"secondary_motion": {"property": "y", "freq": 0.15, "amount": S(6), "seed": "orb"}}},
            {"id": "orb_blue", "type": "orb", "position": P(498, 616), "radius": S(170), "core": "#1d4fd8",
             "tint": "rgba(160,200,255,0.65)", "rim": "rgba(200,225,255,0.45)", "glow_color": "#4a8cff",
             "glow_blur": S(70), "highlight": 0.7, "icon": "dial", "layer": "foreground",
             "animation": {"enter": {"time": 1.0, "duration": 0.7, "tweens": [
                 {"channel": "opacity", "from": 0, "to": 1, "easing": "sine.inOut"}]},
                 "secondary_motion": {"property": "y", "freq": 0.15, "amount": S(6), "seed": "orb"}}},
        ]),
        # 10 · the mark, the name, the ask
        scene(9, 2.55, {"intent": "resolve"}, [
            text("mark", "II", 540, 760, 112, 800, enter=fade_in(0.0, 0.3, 0), exit_=fade_out(0.65, 0.25, 0),
                 continuity_key="signal", letter_spacing=S(-4)),
            text("logo", brand.split(" ")[0], 548, 740, 104, 800, anchor=[1, 0.5],
                 enter={"time": 0.72, "duration": 0.6, "tweens": [
                     {"channel": "opacity", "from": 0, "to": 1, "easing": "power2.out"},
                     {"channel": "scale", "from": -0.08, "to": 0, "easing": "power3.out"}]},
                 letter_spacing=S(-3)),
            text("logo_light", " ".join(brand.split(" ")[1:]) or "", 566, 740, 104, 300, anchor=[0, 0.5],
                 enter={"time": 0.76, "duration": 0.6, "tweens": [
                     {"channel": "opacity", "from": 0, "to": 1, "easing": "power2.out"},
                     {"channel": "scale", "from": -0.08, "to": 0, "easing": "power3.out"}]},
                 letter_spacing=S(-2)),
            text("tagline", tagline, 540, 903, 33, 400, fill="rgba(245,247,255,0.9)",
                 enter=fade_in(1.05, 0.5, 10)),
            {"id": "cta", "type": "shape_rect", "position": P(540, 1051), "width": S(330), "height": S(72),
             "radius": S(36), "fill": "#FFFFFF", "layer": "accent",
             "children": [text("cta_t", cta, 0, 0, 25, 600, fill="#0b0d12")],
             "animation": {"enter": {"time": 1.3, "duration": 0.5, "tweens": [
                 {"channel": "opacity", "from": 0, "to": 1},
                 {"channel": "scale", "from": -0.15, "to": 0, "easing": "back.out(1.6)"}]}}},
        ]),
    ]
    total = round(sum(sc["duration"] for sc in scenes), 3)
    return {
        "project": {"width": width, "height": height, "fps": fps, "duration": total,
                    "background": "#050507",
                    "palette": {"bg_a": "#050507", "bg_b": "#0b0f17", "ink": "#F5F7FF",
                                "accent": "#5b7cff", "accent2": "#ff6bb5"}},
        "visual": {"background": "#050507", "vignette_strength": 0.18, "grain_opacity": 0.03,
                   "grid": {"enabled": False}, "particles": {"count": 0},
                   "spotlight": {"position": [0.5, 0.4], "color": "rgba(40,60,120,0.10)",
                                 "secondary": "rgba(10,12,24,0.2)"}},
        "_motion_profile": "cinematic_glass",
        "scenes": scenes,
    }
