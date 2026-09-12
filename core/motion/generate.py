"""
Prism Motion Graphics — scene-at-a-time generation
────────────────────────────────────────────────────
Turn one names the project, the camera's overall intent, and a storyboard
row per scene — not the scenes themselves. Every scene's actual nodes are
then asked for on their own turn, in the same conversation, and checked
before the next is asked for. This is the same shape as
core.reel_web.build_spec(), for the same two reasons: a model asked to
write a whole motion graphic in one reply spreads its budget thin across
every scene (measured on Studio: 278 chars/scene one-shot vs. 2,339
chars/scene one-turn-per-scene — see CHANGES.md "Round 6"), and a fault
raised while the model is still "on" that scene lands; raised later
against a reply it has moved past, it does not.
"""
from __future__ import annotations

import re
from typing import Any, Callable

from .. import reel_web as _web
from .schema import MotionValidationError

SCENE_EXPECT = '"nodes"'

_PALETTE_GUIDANCE = """Choose a PALETTE and a TYPE PAIRING for this specific brief — not from a
fixed industry lookup. "Financial" does not mean navy, "SaaS" does not mean
cyan-on-obsidian — those are reflexes, and every video that reaches for the
same reflex for the same kind of request looks like it came from a template
library, no matter how different the copy is.

Decide instead from what the brief is actually asking to FEEL like: is it
warm/editorial and trustworthy (cream or ivory background, a dark ink text
colour, one warm metal or earth accent, a serif display face), cool/precise
and technical (deep charcoal or ink background, one saturated accent,
condensed sans display face), bright/energetic and consumer-facing (a light
or mid-tone ground, a bold saturated accent, a heavy display weight), or
something else the brief itself suggests — pick the mood, then commit to a
small NAMED set for the whole piece:
  project.palette: { bg_a, bg_b, ink, accent, accent2 } — bg_a/bg_b are the
    two backgrounds scenes alternate between (see rule 7 below), ink is the
    text colour that reads on whichever background is light, accent is the
    one colour used sparingly and consistently as the piece's signature.
  project.type: { display_font, body_font } — a real two-font pairing (a
    display/serif or condensed face for headlines and numbers, a plain
    sans for body copy and labels) picked for the SAME mood as the
    palette, not the same font doing both jobs.

DO NOT use generic or safe designs. Make bold, specific, production-quality
decisions — and make a genuinely different decision than the last brief
that felt similar, the same way rule 4 below asks for genuinely different
easing choices scene to scene."""

_NODE_CATALOGUE = """NODE TYPES (put these in "nodes"):
  text             — content, position, font_size, font_weight, fill, mode (see TEXT MODES).
                      A long headline may use "\\n" for a manual line break —
                      each line is centred and stacked automatically.
  shape_rect       — position, width, height, radius, fill, is_glass (optional).
                      For hairlines, pills, badges and chat bubbles. It is the
                      WRONG primitive for a background or a card: a flat
                      rectangle wider and taller than half the frame is sent
                      back — a background is a light_field (or a gradient
                      fill), a card is a glass_panel.
  shape_arrow      — from, to, curved, color, stroke_width, draw_start, draw_duration
  domain_chart     — chart_type (bar|line|ring|area|sparkline|metric), data, accent_color
  domain_ui_mockup — position, width, height, title, elements, cursor_actions
  domain_diagram   — nodes (id/label/position/shape/color), edges (from/to/pulse)
  glass_panel      — position, width, height, radius, tint (a colour; a hex tint is
                      applied at the panel's transmission), blur (px, 0-40),
                      transmission 0-1 (how much of the scene shows through),
                      border_light 0-1 (edge highlight), inner_shadow 0-1,
                      specular 0-1 (a diagonal highlight), contrast_guard
                      "dark" | "light" | false (a scrim so the panel's text stays
                      readable over a bright light as well as a dark wash). Put
                      the panel's own text/images in its "children" (positions
                      relative to the panel's centre). ONE main panel per shot —
                      depth comes from depth_layer hierarchy, not repeated cards.
  light_field      — position, width, height, color, color2, intensity 0-1,
                      spread 0.2-2, drift (px). A soft drifting light behind the
                      subject (screen-blended). Use it as the background layer in
                      place of a flat wash; it may bleed past the frame.
  depth_layer      — depth (0.4 far … 1 = the subject plane … 1.6 near) and
                      "children". A group that moves with the camera by its depth:
                      further layers drift and zoom less, nearer ones more. Compose
                      a shot as far light_field → mid glass_panel → near accents,
                      each in its own depth_layer.
  particle_field   — count, size, palette, seed, flicker, and "phases": a list of
                      {"at", "layout", "duration", "stagger"}; the field holds the
                      first layout and travels to each next one at its "at" (scene-
                      local). Layouts: {"kind":"scatter","box":[x0,y0,x1,y1]},
                      {"kind":"band","y","rows","cell","x0","x1"}, {"kind":"column",
                      "x","spread","y0","y1"}, {"kind":"ring","center","radius"},
                      {"kind":"points","points":[[x,y],...],"jitter"}, {"kind":"hidden"}.
                      Many small tiles of light — a signal, data, a crowd of sources —
                      that gathers, streams and converges. Give it the continuity_key
                      when it IS the carried subject; declare it again in the next
                      scene starting from the layout this scene ended on.
  icon             — name (chat|phone|mail|whatsapp|book|dial|spark|check), size,
                      color, tile (true = on a dark glass tile), tile_color, radius.
  orb              — radius, core (colour), tint, rim, glow_color, glow_blur, highlight
                      0-1, icon (an icon name drawn at its centre), ring_radius +
                      ring_color (a faint great circle around it). A sphere — a dark
                      hub, a glowing product orb.
  spline_tree      — hub [x,y], leaves [[x,y],...] (relative to position), color,
                      stroke_width, glow_blur, bend 0-1, draw_start, draw_duration,
                      stagger, dots. Thin curved lines drawn on from one hub to many
                      leaves — channels converging, a knowledge graph.
  image            — position, width, height, radius (corner rounding), anchor;
                      "src" is `asset:<name>` for one of the client's own images
                      the scene prompt names (never write a real URL or invent a name) — a logo,
                      a product photo, a screenshot. Drawn clipped to a rounded
                      rect; SVG marks work the same way as photos.

  continuity_key  — optional stable name for the visual subject that survives
                    across scene boundaries (for example "signal", "product",
                    or "orb"). Node ids remain unique per scene; reuse this
                    key when the same subject returns so Prism can track its
                    handoff and Studio can select the whole visual thread.

"anchor" (on any node) is ALWAYS a two-number [x, y] fraction of the node's
own box, e.g. [0.5, 0.5] for its centre, [0, 0] for its top-left corner —
never a keyword string like "center" or "top-left".

TEXT MODES (set on any text node via "mode"):
  word_stagger   — words pop in sequentially with spring overshoot (default, versatile)
  masked_reveal  — text rises from behind horizontal stencil clip (editorial, slow)
  shimmer_sweep  — fade in then light-beam sweeps across the headline (premium feel)
  char_cascade   — characters fall in with staggered bounce (energetic, consumer)
  split_slide    — text halves slide in from opposite sides (dramatic, brand)
  blur_pop       — blurs to sharp with scale pop (tech, SaaS)
  counter_tick   — numeric value ticks up from 0 to target (data, financial)
  typewriter     — characters appear left-to-right with cursor (developer, code)

ANIMATION, on any node via "animation" (all times are LOCAL to this scene, starting at 0):
  "enter": {"time":, "duration":, "tweens": [
              {"channel": "opacity", "from": 0, "to": 1, "easing": "power2.out"},
              {"channel": "y", "from": 20, "to": 0, "easing": "power2.out", "delay": 0.05},
              ...
           ]}
  "exit":  same shape as "enter" — give at least one node per scene a real
           exit so the scene doesn't just settle and hold until the cut.
  Put as many tweens in one enter/exit as the moment needs — this is how a
  blur-focus reveal, a directional slide, a scale-pop and a plain fade are
  all really just different CHANNEL COMBINATIONS of the same mechanism, not
  different fixed "types" to pick from. "from"/"to" for x/y are relative
  OFFSETS from the node's own resting position (20 means 20px away from
  where it settles, not an absolute coordinate); scale/scaleX/scaleY/
  rotation/skewX/skewY/opacity work the same way; blur/clipInset/
  backgroundPositionX/strokeDashoffset are absolute values in their own
  units (blur in px, clipInset 0-100 as percent revealed, strokeDashoffset
  in the node's own path-length units — leave it to the runtime's own
  full-length value, tween TO 0 to fully draw a line/arrow/mark).
  TWEEN CHANNELS: opacity, x, y, scale, scaleX, scaleY, rotation, skewX,
    skewY, blur, clipInset, backgroundPositionX, strokeDashoffset.
  "secondary_motion": {"property": "<any channel above>", "freq":, "amount":,
                        "seed": "<anything stable>"} — a small deterministic
           wiggle on top of the main animation, running the WHOLE time this
           node is on screen (see the background layer's rule below).
  "follow": {"lag":, "damping":} — on a CHILD node, makes it trail the parent's
           recent motion instead of moving in rigid lockstep. (Not yet
           supported by the current runtime — avoid relying on it.)

SHOT, on a SCENE (next to "nodes") — what the camera does for this beat. The
shots of all scenes are compiled into ONE continuous camera curve for the
whole film; a shot only says where the camera ends up, so it always starts
wherever the previous shot left it (there is no per-scene camera reset):
  "shot": {"intent": "push", "target": "<node id>" or [x, y], "zoom": 1.2, "duration": 0.6}
  Optional "duration" (seconds the move takes; default most of the scene)
  and "delay" (seconds into the scene before it starts, holding the previous
  shot's end state — a scene that settles on its icons, then pans down to
  the hub). A node target puts that node at the frame's centre.
  ("duration" is optional: seconds the move takes; omit it and the move
  spans the scene, right for a drift, wrong when copy must land on a
  settled frame.)
  hold     — stay where the camera is.
  reveal   — settle out onto the target (an opening).
  push     — move in on the target (zoom ×1.15 unless "zoom" is given).
  pull     — ease back out.
  orbit    — a slow tilt around the target.
  parallax — a lateral drift, zoom unchanged (depth_layers separate).
  macro    — close on a detail (zoom 1.6 unless given).
  resolve  — return to the centre at 1.0 for the ending.

TRANSITIONS, on a SCENE (not a node) via "transition_in" — how this scene
cuts in from the one before it. Omit it and one is still picked for you
(never a silent hard cut), but naming one on purpose usually reads better:
  push        — both scenes travel together, new one pushing the old off. Neutral, use for an ordinary beat.
  push_up     — same as push, vertical instead of horizontal.
  squeeze     — the old scene compresses away, the new one opens out. Mechanical, precise — industrial/technical subjects.
  zoom        — the old scene rushes past and blurs, the new one rises from behind it. Reserve it — it reads as pushing deeper into the same thought.
  blur_swoosh — both scenes blur/skew past each other, directional. Editorial, motion-forward.
  light_leak  — a warm light wash bridges the cut. Editorial, warm, premium — good between two beats of the same argument rather than a hard scene change.
  morph       — a plain crossfade. Any cut where a node's "continuity_key" carries over from the previous scene becomes a morph automatically: both instances of that subject are tweened along one matched path between their two poses, so only the subject moves and everything else dissolves.

EASING VALUES (GSAP's own — the runtime hands these straight to the tween engine):
  power1.in/out/inOut, power2.in/out/inOut, power3.in/out/inOut, power4.in/out/inOut,
  back.in/out/inOut, elastic.in/out/inOut, bounce.in/out/inOut,
  circ.in/out/inOut, expo.in/out/inOut, sine.in/out/inOut, none

  Pick by what the thing is doing, not by habit — reusing one easing for
  everything that moves is the fastest way to look like a slide deck, no
  matter how many elements are on screen. `.out` curves for things
  ARRIVING, `.in` curves for things LEAVING, `sine.inOut`/`none` for
  motion still running when the scene hands over. Use at least two
  distinct easings in every scene."""


SCENE_ROLES = ("HOOK", "REVEAL", "PROOF", "SIGNOFF")

_LAYER_DOCTRINE = """LAYERS — give every node a "layer" (not just a z_index guess):
  background — full-bleed wash, glow or gradient behind everything else.
               MUST carry "secondary_motion" running for the WHOLE scene
               (not just enter/exit) — a slow drift, pulse or rotation.
               A background that just sits there once it's in is exactly
               what makes a scene read as a held slide, not a shot.
  midground  — a supporting shape or glass panel that gives the scene
               depth. Move it slower than the foreground (a smaller
               secondary_motion amount, or a longer enter duration) so it
               reads as further back, not flat with everything else.
  foreground — the hero of the scene: the headline, the product/logo
               image. MUST either really "exit" or carry its own
               "secondary_motion" while it holds — appearing once and then
               going completely still until the cut is the one thing this
               layer is not allowed to do. A closing scene settling on a
               logo is fine; settling DEAD is not — give it a slow
               breathe/drift even then.
  accent     — small floating detail(s): a badge, a stat, a short label.
               Fast, energetic motion — this is what makes a frame feel
               busy/alive without competing with the foreground.
  finish     — an overlay (vignette, radial darken at the edges) that sits
               on top of everything. Static — it's a treatment, not a
               character.

Not every layer needs a node every scene, but background and foreground
are required — a scene with no background layer has no depth, and a
scene with no foreground has no subject."""

_CINEMATIC_GLASS_DOCTRINE = """CONTINUOUS CINEMATIC PROFILE — this is a motion film, not a stack of unrelated slides.
  · Choose one recognisable visual spine (a signal, ribbon, orb, product card,
    line or light field) and carry it through the whole piece. Give its hero
    node a stable "continuity_key" and reuse that key whenever the subject
    returns in another scene.
  · The outgoing final pose and incoming first pose must agree: position,
    scale, rotation, dominant colour and opacity should feel like the same
    object crossing the handoff. Do not reset the subject to the centre at
    every cut.
  · Keep the subject alive during the transition. Use a directional
    blur_swoosh, light_leak or push when appropriate; avoid a full-scene fade
    to empty followed by a cold rebuild.
  · Give every scene a "shot" (see SHOT above) and let the compiled camera
    curve carry the film: reveal → push/orbit/parallax → resolve. Never
    reset the camera to the same zoom and centre at every scene.
  · Glass is layered depth: ONE main glass_panel (the material primitive, not
    a plain rect) carrying the copy, a light_field behind it, small accents in
    front — each in its own depth_layer (far ≈ 0.55, subject 1.0, near ≈ 1.45).
    Restrained border light and specular beat many identical cards. Preserve
    generous negative space and a clear typographic hierarchy.
  · Keep headlines and logos inside the safe area: on a 9:16 frame nothing
    that must be read sits in the top 11% or the bottom 20%.
  · The reference grammar in one line: a particle_field of scattered tiles
    gathers into a band, streams into a column, converges on icons and a
    hub orb over a spline_tree; a light_field sweeps in for a conversation
    in bubbles; a knowledge tree with small glass cards; the Knowledge Base
    card over a glowing tree; a great arc; the glowing orb; the logo. Use
    those primitives for those jobs instead of rebuilding them from rects.
  · The final scene resolves the carried subject into the logo, answer or CTA;
    it should feel like a destination, not a new template."""


def _scene_role(idx: int) -> str:
    return SCENE_ROLES[idx] if 0 <= idx < len(SCENE_ROLES) else "SCENE"


_ROLE_BRIEF = {
    "HOOK": "The cold open. One bold claim or the brand/product name, "
            "nothing else competing for attention. Fast — this scene "
            "should feel like it's already moving when it appears.",
    "REVEAL": "The payoff. Whatever the hook promised, shown large — the "
              "product, the logo, the number. This is the scene the "
              "other three exist to set up and close out.",
    "PROOF": "One supporting detail that earns the claim — a benefit, a "
             "stat, a second angle. Calmer than the hook, still moving.",
    "SIGNOFF": "Logo lockup and/or a short tagline/CTA. The close — "
               "energy settles here, it does not spike.",
}


def _scene_handoff(scene: dict) -> dict | None:
    """What the LAST foreground node in a finished scene exits with — fed
    to the next scene's instructions so the cut continues a motion/colour
    instead of resetting cold. Returns None if there's nothing to hand
    off (no foreground node, or it never exits)."""
    best = None
    for node in scene.get("nodes", []) or []:
        if not isinstance(node, dict) or node.get("layer") != "foreground":
            continue
        anim = node.get("animation")
        exit_ = anim.get("exit") if isinstance(anim, dict) else None
        # A keyed subject is handed off even without an authored exit — the
        # continuity compiler writes its bridge — so the next scene learns
        # where to pick it up. An unkeyed foreground still needs an exit
        # to have anything worth continuing.
        if isinstance(exit_, dict) or node.get("continuity_key"):
            best = {
                "type": exit_.get("type", "fade_in") if isinstance(exit_, dict) else "morph",
                "fill": node.get("fill") or node.get("accent_color"),
                "continuity_key": node.get("continuity_key", ""),
                "node": str(node.get("id", "")),
                "position": list(node.get("position") or [0, 0]),
                "scale": list(node.get("scale") or [1, 1]),
            }
    return best


# The node type names alone, read off the catalogue, so the one-line list
# each scene prompt carries cannot drift from the catalogue turn one sent.
_NODE_TYPE_NAMES = tuple(re.findall(
    r"^  ([a-z_]+)\s+—", _NODE_CATALOGUE.split("\n\n", 1)[0], re.M))


def _scene_rules(skeleton: str | None) -> str:
    """The rules every scene is written to, numbered once for the whole
    conversation. _PALETTE_GUIDANCE points at rules 4 and 7 by number."""
    rules = (
        "SCENE RULES — every scene you write after this turn follows these:\n"
        "1. 3-7 nodes. Do not overcrowd.\n"
        "2. Vary the text mode — use at most 2 different modes.\n"
        '3. Give at least one node a real "exit", not only "enter".\n'
        "4. The most common way a scene ends up reading as a PowerPoint "
        "slide, however busy it is, is every element using the same "
        "easing curve. Treat that as the failure to design against.\n"
        "5. Never use generic emojis in text content.\n"
        "6. The brand's accent colour should recur, not repeat identically —\n"
        "   the same one or two colours framing every single scene the same\n"
        "   way (same white headline, same accent subtitle, same background)\n"
        "   reads as one template stamped four times, not four scenes of one\n"
        "   film. Let where and how the accent is used change: a highlighted\n"
        "   word instead of a whole line, a filled shape instead of an\n"
        "   outline, a background wash instead of just text — same brand,\n"
        "   different weight each time.\n"
        "7. Use the palette/type chosen in this turn BY NAME — a full-bleed "
        "background node filled with project.palette.bg_a or bg_b (alternate "
        "which one scene to scene rather than repeating the same one every "
        "time), text filled with project.palette.ink or accent, "
        'font_family "var(--motion-display-font)" for headlines/numbers and '
        '"var(--motion-body-font)" for body/labels — never invent a fresh '
        "hex or font mid-scene that ignores what this turn already chose.\n"
        "8. A scene may name a \"transition_in\" (see TRANSITIONS above) "
        "for how it cuts in from the one before it — pick one that fits "
        "the beat, or leave it unset and a real one is still chosen for "
        "you rather than a hard cut.\n"
        "8b. Only the artwork listed under ARTWORK YOU MAY USE exists. A "
        "screenshot, photo or device frame the list does not name must not "
        "be drawn as an empty placeholder — an empty glass_panel or an image "
        "with no src is sent back. Carry that beat's copy on a glass_panel "
        "with the text inside it instead.\n"
        "9. Before placing a text or image node, sketch its actual box — "
        "position ± roughly half its width/height — against every OTHER "
        "text/image node's box already placed in the same scene. Two photos, "
        "or a headline and a photo, sharing the same region reads as debris, "
        "not layout, no matter how good either looks alone. Give each one "
        "its own clear region of the 1080x1920 frame (stack vertically, "
        "or split left/right) rather than centering everything on the "
        "same point. A shape_rect used as an intentional backdrop directly "
        "behind one specific node (a badge behind its own label, a card "
        "behind its own photo) is the one exception — that pairing is "
        "supposed to share a position.\n"
    )
    if skeleton in ("brand_launch", "cinematic_glass"):
        rules += ('10. Give every node a "layer" (see LAYERS above) — '
                  "background and foreground are both required in every "
                  "scene.\n")
    if skeleton == "cinematic_glass":
        rules += (
            '11. Put a stable "continuity_key" on the hero/subject node; '
            "reuse the same key in later scenes when that subject returns.\n"
            "12. At least one camera or secondary motion must continue across "
            "the handoff; the incoming pose must visibly pick up the outgoing "
            "one.\n"
            "13. Build from the material primitives, not from rectangles: the "
            "background layer is a light_field (or a gradient-filled rect), the "
            "card that carries copy is a glass_panel, depth comes from "
            "depth_layer, gathered tiles are a particle_field, a lit sphere is "
            "an orb. A flat shape_rect covering more than half the frame is "
            "checked for and sent back.\n")
    return rules


def _rulebook(skeleton: str | None) -> str:
    """The catalogue, the doctrines this profile uses and the scene rules,
    stated once, in turn one.

    scene_instructions() used to carry all of this itself: the catalogue
    and doctrines in full with scene 1 (19,800 characters with a four-
    picture asset list) and the rules again on every later scene (6,600
    each), in a tab where a run on 10 Sep 2026 had already grown the page
    until the kernel killed Chrome for memory. Every scene turn lands in
    this same tab straight after turn one, so the model has read it by
    then. Stated before the storyboard is planned, it also shapes the plan:
    a row can only name a node the model has read about.
    """
    parts = [_NODE_CATALOGUE]
    if skeleton in ("brand_launch", "cinematic_glass"):
        parts.append(_LAYER_DOCTRINE)
    if skeleton == "cinematic_glass":
        parts.append(_CINEMATIC_GLASS_DOCTRINE)
    parts.append(_scene_rules(skeleton))
    return ("THE RULEBOOK FOR EVERY SCENE. You plan the storyboard with it, "
            "and each scene you are asked for after this turn is written to "
            "it. The scene prompts name these sections instead of repeating "
            "them, so hold on to them.\n\n" + "\n\n".join(parts))


def storyboard_instructions(request: str, brand: dict | None = None,
                            skeleton: str | None = None, script: str = "") -> str:
    """Turn one: the look, the camera's overall intent, a storyboard row
    per scene, and the rulebook every scene after it is written to (see
    _rulebook()). Mirrors core.reel_web.design_instructions()'s split.

    `brand`: colours already measured off the client's own artwork (see
    core.reel.sample_brand — the same pixel-level measurement Reel/Studio
    use, not re-implemented here). Unlike Reel's Pillow renderer, nothing
    here applies these automatically — Motion's palette is the model's own
    choice — so it's told to use them as ITS accent rather than inventing
    one, the same way Studio is told to.
    """
    if skeleton == SPINE_SKELETON:
        return copy_instructions(request, brand=brand, script=script)
    brand_note = ""
    if brand:
        brand_note = (
            f"\n\nThe brand colours have already been measured from the "
            f"client's own artwork: accent {brand.get('accent')}, deep "
            f"{brand.get('deep')}. Use these as the accent colour running "
            "through the piece rather than inventing your own — this is "
            "their actual brand, not a suggestion.")
    from . import spine as _spine
    spine_note = ""
    if skeleton == "cinematic_glass":
        n_rows = 7
        if script and script.strip():
            import re as _re
            found = len(_re.findall(r"(?im)^\s*scene\s*0?(\d+)\b", script))
            if found:
                n_rows = max(4, min(10, found))
        spine_note = "\n\n" + _spine.storyboard_text(n_rows)
    script_note = ""
    if script and script.strip():
        script_note = (
            "\n\nTHE SCRIPT — the copy stage already wrote what this piece "
            "says, beat by beat. It is the story; do not write another one:\n"
            + script.strip()[:6000]
            + "\n\nOne storyboard row per beat of that script, in its order. "
            'Each row\'s "caption" is that beat\'s on-screen line, VERBATIM — '
            "the scene will carry it as its main text and is checked "
            "against it. Rows without a caption are only allowed where the "
            "script itself has no words for that beat.")
    return (
        "You are Prism's Senior Visual Director and Motion Designer, "
        "planning a short vertical motion graphic.\n\n"
        f"WHAT THE CLIENT ASKED FOR:\n{request}"
        + brand_note + script_note + spine_note + "\n\n"
        + _PALETTE_GUIDANCE + "\n\n"
        + _rulebook(skeleton) + "\n\n"
        "This is turn one of a conversation. Right now, name the project "
        "settings, the camera's overall intent, and a STORYBOARD — one row "
        "per scene, words only, no nodes yet. Each scene's actual content "
        "is asked for on its own turn, right after this one, so it gets "
        "your full attention rather than a fraction of one reply split "
        "across everything.\n\n"
        "Reply with ONLY this JSON object, in a ```json fenced code block, "
        "nothing before or after it:\n"
        "{\n"
        '  "project": {"width": 1080, "height": 1920, "fps": 30, '
        '"duration": 8.0, "background": "#07091A",\n'
        '    "palette": {"bg_a": "...", "bg_b": "...", "ink": "...", '
        '"accent": "...", "accent2": "..."},\n'
        '    "type": {"display_font": "...", "body_font": "...", '
        '"google_fonts_url": "https://fonts.googleapis.com/css2?family=...&display=block"}\n'
        "  },\n"
        '  "camera": {"tracks": [\n'
        '    {"time": 0.0, "position": [540, 960], "zoom": 1.0},\n'
        '    {"time": 1.2, "position": [540, 900], "zoom": 1.35, '
        '"duration": 1.1, "easing": "power2.inOut"}\n'
        "  ]},\n"
        '  "storyboard": [\n'
        '    {"scene": 1, "seconds": 2.5,\n'
        '     "job": "what this scene is FOR in the argument",\n'
        '     "beat": "gather",\n'
        '     "caption": "the on-screen words for this beat (the script\'s line, verbatim)",\n'
        '     "subject": "what the carried subject IS and what STATE it is in here",\n'
        '     "look": "what is on screen and how it is composed — what is '
        'big, what is a supporting label, what kind of node carries it",\n'
        '     "motion": "what moves, in what order, from where — and what '
        'is still moving when the scene hands over"}\n'
        "  ]\n"
        "}\n\n"
        + (_cinematic_glass_storyboard_close() if skeleton == "cinematic_glass"
           else _brand_launch_storyboard_close() if skeleton == "brand_launch"
           else
        "3-6 scenes, 6-15 seconds total. ONE STORYBOARD ROW PER SCENE. Give "
        "each one a different job and a different composition — several "
        "scenes that are all a centred headline over the same background "
        "is the failure this stage exists to prevent. `camera.tracks` is "
        "for the WHOLE graphic; each scene's \"shot\" (see SHOT above) "
        "carries on from it.")
    )


def _brand_launch_storyboard_close() -> str:
    roles = "\n".join(f'  {i + 1}. {r} — {_ROLE_BRIEF[r]}'
                       for i, r in enumerate(SCENE_ROLES))
    return (
        "EXACTLY 4 scenes, in this fixed order, 8-14 seconds total — do "
        "not add, drop, reorder or rename them:\n" + roles + "\n\n"
        '"job" for each row IS its role above, in your own words for this '
        "brand. `camera.tracks` is for the WHOLE graphic; each scene's "
        "\"shot\" (see SHOT above) carries on from it."
    )


def _cinematic_glass_storyboard_close() -> str:
    return (
        "5-8 scenes, 16-30 seconds total. Design one continuous visual "
        "transformation rather than a sequence of poster frames: name the "
        "visual spine in the motion field, keep it recognisable, and state "
        "how each scene's final pose hands into the next scene's first pose. "
        "Use scene changes to reveal, transform or focus the same idea; "
        "reserve the final scene for a resolved logo/answer/CTA. `camera.tracks` "
        "is for the WHOLE graphic and should also feel continuous. In each "
        "row's `look`, name the material primitives that carry the scene "
        "(light_field, glass_panel, depth_layer, particle_field, orb, "
        "spline_tree, icon) — a scene described as rectangles and arrows "
        "will be built from rectangles and arrows."
    )


def scene_instructions(idx: int, total: int, row: dict, assets: str = "",
                       skeleton: str | None = None,
                       handoff: dict | None = None) -> str:
    """Ask for ONE scene's nodes. The rest of the conversation already
    knows the palette, the camera and the rulebook from turn one (see
    _rulebook()); this only needs the row.

    `skeleton="brand_launch"` pins this scene to its fixed HOOK/REVEAL/
    PROOF/SIGNOFF role. `skeleton="cinematic_glass"` adds explicit handoff
    guidance for the persistent visual spine. The layer doctrine, the
    cinematic profile and the continuity-key rules those profiles are held
    to were stated in storyboard_instructions() and are only named here.
    `handoff` is what core.motion.generate._scene_handoff() read off the
    PREVIOUS scene — how it exited — so this one can continue that motion
    or colour instead of cutting cold; None for the first scene.
    """
    job = str(row.get("job", "")).strip() or "carry the argument forward"
    caption = str(row.get("caption", "")).strip()
    subject = str(row.get("subject", "")).strip()
    beat_name = str(row.get("beat", "")).strip()
    look = str(row.get("look", "")).strip()
    motion = str(row.get("motion", "")).strip()
    try:
        seconds = float(row.get("seconds") or 3.0)
    except (TypeError, ValueError):
        seconds = 3.0
    role_header = ""
    if skeleton in ("brand_launch", "cinematic_glass"):
        role = _scene_role(idx)
        role_header = ("PROFILE: CINEMATIC GLASS — one continuous visual spine.\n\n"
                       if skeleton == "cinematic_glass"
                       else f"ROLE: {role} — {_ROLE_BRIEF[role]}\n\n")
        if handoff:
            role_header += (
                f'CONTINUING FROM THE LAST SCENE: it exited with a '
                f'"{handoff["type"]}"'
                + (f' in {handoff["fill"]}' if handoff.get("fill") else "")
                + (f' on continuity_key "{handoff["continuity_key"]}"'
                   if handoff.get("continuity_key") else "")
                + ". Open THIS scene picking that motion or colour up — "
                "reverse the exit direction, or carry the colour into "
                "this scene's foreground — rather than starting cold.\n"
                + ((f'That subject settled at position {handoff.get("position")} '
                    f'and scale {handoff.get("scale")}. Give this scene\'s node '
                    f'with continuity_key "{handoff["continuity_key"]}" a '
                    "settled position and scale within reach of that — the "
                    "cut will morph between the two poses; a pose across the "
                    "frame or many times larger cannot be bridged and will "
                    "be sent back.\n")
                   if handoff.get("continuity_key") else "")
                + "\n"
            )
    # The catalogue, the doctrines and the scene rules used to travel with
    # this prompt — in full with scene 1, the rules again on every turn —
    # and are stated once now, in turn one (see _rulebook() for the run that
    # made that matter). This names them and keeps what belongs to this
    # scene alone: its row, its role or profile, the handoff from the scene
    # before, the node names, its artwork, and the shape of the reply.
    named = ("NODE TYPES, TEXT MODES, ANIMATION, SHOT, TRANSITIONS, EASING "
             "VALUES"
             + (", LAYERS, the CINEMATIC GLASS profile (its safe area "
                "included)" if skeleton == "cinematic_glass"
                else ", LAYERS" if skeleton == "brand_launch" else "")
             + " and the SCENE RULES")
    assets = assets or ""
    names = _web._asset_names(assets)
    if not assets.strip():
        artwork = ""
    elif idx == 0:
        # Turn one is written before the artwork exists and takes no asset
        # list, so scene 1 is the first place the model reads it: in full
        # once, by name after that.
        artwork = f"ARTWORK YOU MAY USE:\n{assets}\n\n"
    elif names:
        artwork = ("ARTWORK YOU MAY USE (described in scene 1's message): "
                   + ", ".join(f"asset:{n}" for n in names)
                   + ". No other name exists.\n\n")
    else:
        artwork = ("THERE ARE NO IMAGES (see scene 1's message): write no "
                   "image node.\n\n")
    return (
        f"SCENE {idx + 1} of {total}.\n\n"
        + role_header
        + f"ITS JOB: {job}\n"
        + (f'ITS CAPTION: "{caption}" — this scene\'s main text node carries '
           "exactly these words (a manual line break is fine); a scene "
           "whose text says something else is sent back.\n" if caption else "")
        + (f"ITS SUBJECT: {subject}\n" if subject else "")
        + (("\n" + __import__("core.motion.spine", fromlist=["recipe_text"]).recipe_text(beat_name) + "\n")
           if beat_name and skeleton == "cinematic_glass" else "")
        + (f"THE LOOK: {look}\n" if look else "")
        + (f"THE MOTION: {motion}\n" if motion else "")
        + f"\nDuration: {seconds:g} seconds. All this scene's animation "
        "times count from 0 at this scene's own start.\n\n"
        + "Node types: " + ", ".join(_NODE_TYPE_NAMES) + ".\n"
        + named + " are as the storyboard turn above set them out and still "
        "apply; they are not repeated here.\n\n"
        + artwork
        + "Reply with ONLY this JSON object, in a ```json fenced code "
        "block, nothing before or after it:\n"
        '{\n  "shot": {"intent": "...", "target": "<node id>"},\n'
        '  "nodes": [ /* 3-7 node objects, as NODE TYPES describes */ ]\n}\n'
        '"transition_in" may sit next to "nodes" to name how this scene cuts '
        "in (one of the TRANSITIONS)."
    )


STORYBOARD_EXPECT = ("storyboard", "project")


def _words(text: str) -> list[str]:
    import re
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def caption_faults(scene: dict, row: dict) -> list[str]:
    """The one story check a program can make: when the storyboard row
    has a caption (the script's line for this beat), some text node in
    the scene must carry those words. Compared on lowercased word runs,
    so a manual line break or a stray comma does not fail it; a scene
    that says something else — or nothing — does."""
    caption = str(row.get("caption", "")).strip() if isinstance(row, dict) else ""
    if not caption:
        return []
    want = _words(caption)
    if not want:
        return []
    texts: list[str] = []

    def visit(node):
        if isinstance(node, dict):
            if node.get("type") == "text":
                texts.append(str(node.get("content") or ""))
            for child in node.get("children") or []:
                visit(child)

    for node in scene.get("nodes") or []:
        visit(node)
    joined = " ".join(_words(" ".join(texts)))
    if " ".join(want) in joined:
        return []
    hit = max((sum(1 for w in want if w in _words(t)) / len(want) for t in texts), default=0.0)
    return [f'the scene\'s caption is "{caption}" but ' +
            ("no text node carries it" if hit < 0.5 else
             "its text only partly matches it") +
            ' — put the caption, verbatim, in the scene\'s main "text" node '
            "(a manual line break is fine)"]


REPAIR_ROUNDS = 2

# What each fault family needs changed — added on the second round, when a
# bare list of faults came back with the same scene.
_REPAIR_MOVES = (
    ("sits completely still", 'give the foreground node an "exit" block (time near the '
                              'end, a real x/y/opacity change) or a "secondary_motion" '
                              "wiggle — do not only re-send its enter"),
    ("overlap by", "move one of the two nodes to its own region of the frame — "
                   "stack them vertically or split left/right, and shrink the larger"),
    ("names no \"shot\"", 'add "shot": {"intent": ..., "target": ...} next to "nodes"'),
    ("caption is", 'put the caption, word for word, in the scene\'s main "text" node'),
    ("runs off the edge", "pull the node inside the frame and check its anchor"),
    ("platform's own UI", "move it below the top band, above the bottom band"),
    ("no \"secondary_motion\"", 'add "secondary_motion" to the background node'),
    ("flat shape_rect", "replace it with a light_field (background) or a glass_panel (card)"),
    ("empty glass_panel", "put the copy inside it as children, or remove it"),
    ("no \"content\"", 'put the words in "content"'),
    ("beat \"", "build the primitives and phases the beat's recipe lists — the recipe is the scene"),
    ("no \"src\"", 'use "src": "asset:<name>" from the list, or remove the image'),
)


def repair_prompt(idx: int, faults: list[str], round_no: int) -> str:
    """The message a faulty scene is sent back with. Round one lists the
    faults; round two adds the concrete change each one needs, and says
    the last correction did not fix them."""
    head = (f"Scene {idx + 1} was checked and these are wrong:\n\n" if round_no == 0 else
            f"Scene {idx + 1} still has these problems after your correction — the "
            "last reply came back with the same faults, so change the nodes "
            "named here directly:\n\n")
    lines = []
    for n, fault in enumerate(faults[:8], 1):
        line = f"{n}. {fault}"
        if round_no > 0:
            for key, move in _REPAIR_MOVES:
                if key in fault:
                    line += f"\n   → {move}"
                    break
        lines.append(line)
    return (head + "\n".join(lines)
            + "\n\nSend the corrected scene: ONLY the JSON object, same shape, "
              "in a ```json fenced block."
            + (" Keep every node that was not named." if round_no > 0 else ""))


def beat_check(scene: dict, row: dict, skeleton: str | None) -> list[str]:
    """The scene against its storyboard row's beat (core.motion.spine)."""
    if skeleton != "cinematic_glass" or not isinstance(row, dict):
        return []
    from . import spine as _spine
    return _spine.beat_faults(scene, str(row.get("beat", "")).strip())


def shot_faults(scene: dict, skeleton: str | None, has_camera: bool = False) -> list[str]:
    """Under the cinematic profile every scene names a shot; a scene
    without one holds the previous camera state, which is how the second
    Alphakore run (10 Sep 2026) held one push for its last five scenes.
    A storyboard that authored its own `camera.tracks` is exempt — the
    resolver plays that curve when no scene names a shot, and asking for
    shots on top of it cost the third run two wasted repair rounds a scene."""
    if skeleton != "cinematic_glass" or scene.get("shot") or has_camera:
        return []
    return ['the scene names no "shot" — add one (see SHOT: hold, reveal, push, '
            'pull, orbit, parallax, macro, resolve) so the camera keeps moving '
            "through the film"]


def parse_storyboard(text: str) -> tuple[dict, dict, list[dict]]:
    """Turn one's reply: (project, camera, storyboard rows).

    A reply that answers whole scenes anyway is not an error — its scene
    list is a perfectly good storyboard if none was written, the same
    accommodation core.reel_web.parse_design() makes.
    """
    project: dict = {}
    camera: dict = {}
    board: list[dict] = []
    for got in _web._json_objects(text):
        p = got.get("project")
        if isinstance(p, dict) and not project:
            project = p
        c = got.get("camera")
        if isinstance(c, dict) and not camera:
            camera = c
        rows = got.get("storyboard")
        if isinstance(rows, list) and not board:
            board = [r for r in rows if isinstance(r, dict)]
        if not board and isinstance(got.get("scenes"), list):
            # Kept as a last resort — but flagged, so build_spec() asks for
            # the real storyboard once before building on rows with no job,
            # no caption and no subject (the Alphakore run built seven
            # unconnected scenes on exactly such rows).
            board = [{"job": "", "look": "", "motion": "", "_from_scenes": True,
                      "seconds": s.get("duration")}
                     for s in got["scenes"] if isinstance(s, dict)]
        if project and board:
            break
    if not project:
        raise MotionValidationError(
            "The storyboard stage returned no project settings.")
    return project, camera, board


def parse_scene(text: str) -> dict | None:
    """One scene's reply: {"nodes": [...]} plus, when the reply carried
    them, the scene-level "shot" and "transition_in" (schema.py validates
    both; anything else on the scene is the loop's to set). None if
    unusable."""
    for got in _web._json_objects(text):
        if isinstance(got.get("scenes"), list) and got["scenes"]:
            inner = got["scenes"][0]
            if isinstance(inner, dict) and isinstance(inner.get("nodes"), list):
                got = inner
        nodes = got.get("nodes")
        if isinstance(nodes, list) and nodes:
            scene = {"nodes": [n for n in nodes if isinstance(n, dict)]}
            for key in ("shot", "transition_in"):
                if got.get(key) is not None:
                    scene[key] = got[key]
            return scene
    return None


def _scene_count(text: str) -> int:
    """How many scenes-with-nodes a reply actually contained — same
    over-eager-reply detector as core.reel_web._scene_count()."""
    n = 0
    for got in _web._json_objects(text):
        rows = got.get("scenes")
        if isinstance(rows, list):
            n += sum(1 for s in rows
                      if isinstance(s, dict) and isinstance(s.get("nodes"), list))
    return n or (1 if parse_scene(text) else 0)


def fallback_scene(row: dict) -> dict:
    """A plain, code-authored scene for when this one's reply can't be
    recovered — mirrors core.reel_web.fallback_scene(): a graphic with one
    dull scene ships, one with a hole in it does not."""
    words = str(row.get("job", "")).strip() or "…"
    return {
        "nodes": [{
            "type": "text", "content": words, "position": [540, 960],
            "font_size": 64, "font_weight": 700, "fill": "#F8FAFC",
            "mode": "word_stagger",
            "animation": {"enter": {"type": "fade_in", "duration": 0.6,
                                     "easing": "easeOutCubic"}},
        }],
    }


def _pose_lines(scene: dict, label: str) -> list[str]:
    """One line per keyed node in `scene`, for a repair prompt."""
    out = []
    for node in scene.get("nodes", []) or []:
        if isinstance(node, dict) and node.get("continuity_key"):
            out.append(
                f'{label} carries continuity_key "{node["continuity_key"]}" on '
                f'node "{node.get("id", "")}" at position '
                f'{list(node.get("position") or [0, 0])}, scale '
                f'{list(node.get("scale") or [1, 1])}.')
    return out


def _repair_continuity(scenes: list[dict], project: dict, camera: dict,
                       ask: Callable[..., str], say, check=None) -> None:
    """Whole-piece check the per-scene `check` cannot do: every handoff
    is planned by core.motion.continuity and each scene that breaks the
    contract is sent back ONCE with the exact fault and the neighbouring
    poses it must meet. A returned scene is kept only if the piece as a
    whole has fewer continuity issues afterwards and the scene itself is
    no worse on the per-scene check — same "a fix must actually be a fix"
    rule build_spec() applies per scene.

    In place on `scenes`. Never raises: the resolver compiles whatever is
    left and render.py refuses only what still cannot be bridged.
    """
    from . import continuity as _continuity

    def probe(rows: list[dict]) -> list[dict]:
        rep = _continuity.report({"project": project, "camera": camera,
                                  "scenes": rows,
                                  "_motion_profile": "cinematic_glass"})
        return ([dict(e, severity="error") for e in rep["errors"]]
                + [dict(w, severity="warning") for w in rep["warnings"]])

    issues = probe(scenes)
    if not issues:
        return
    # Only what would stop the render goes back to the model. Warnings
    # (a scene without a keyed node, an opening subject the ending does
    # not resolve) are logged and left: each extra turn in the same tab is
    # minutes of the writer's time on an already long page, and a run
    # measured on 10 Sep 2026 lost its browser session after the seventh
    # such turn. At most three scenes are sent back, worst first.
    errors = [it for it in issues if it.get("severity", "error") == "error"]
    for it in issues:
        if it not in errors:
            say(f"continuity note: {it['message']}")
    if not errors:
        return
    by_scene: dict[int, list[str]] = {}
    for it in errors:
        by_scene.setdefault(int(it["scene_index"]), []).append(it["message"])
    say(f"continuity: {len(errors)} problem(s) across "
        f"{len(by_scene)} scene(s) — sending them back")
    order = sorted(by_scene, key=lambda i: -len(by_scene[i]))[:3]
    for idx in sorted(order):
        if idx < 0 or idx >= len(scenes):
            continue
        msgs = by_scene[idx]
        context = []
        if idx > 0:
            context += _pose_lines(scenes[idx - 1], f"The scene before (scene {idx})")
        if idx + 1 < len(scenes):
            context += _pose_lines(scenes[idx + 1], f"The scene after (scene {idx + 2})")
        fixed = parse_scene(ask(
            f"Scene {idx + 1} was checked against its neighbours and breaks "
            "the continuity contract:\n\n"
            + "\n".join(f"{n}. {x}" for n, x in enumerate(msgs[:6], 1))
            + ("\n\n" + "\n".join(context) if context else "")
            + f"\n\nSend the corrected scene {idx + 1}: ONLY the JSON object, "
              "same shape, in a ```json fenced block. Keep everything that "
              "was not mentioned.",
            SCENE_EXPECT) or "")
        if not fixed:
            # No JSON back usually means the tab is struggling; do not
            # spend more turns on it.
            say(f"   scene {idx + 1} never came back — keeping the first "
                "and stopping the continuity pass")
            break
        fixed["id"] = scenes[idx]["id"]
        fixed["duration"] = scenes[idx]["duration"]
        trial = list(scenes)
        trial[idx] = fixed
        after = probe(trial)
        worse_alone = False
        if check:
            try:
                before_n = len(check({"project": project, "camera": camera,
                                      "scenes": [scenes[idx]]}))
                after_n = len(check({"project": project, "camera": camera,
                                     "scenes": [fixed]}))
                worse_alone = after_n > before_n
            except Exception:
                worse_alone = False
        after_errors = [it for it in after if it.get("severity", "error") == "error"]
        if len(after_errors) < len(errors) and not worse_alone:
            scenes[idx] = fixed
            say(f"   scene {idx + 1} fixed — {len(errors)} down to {len(after_errors)}")
            errors = after_errors
        else:
            say(f"   scene {idx + 1}'s correction was no better — keeping the first")


SPINE_SKELETON = "spine"
COPY_EXPECT = '"copy"'


def copy_instructions(request: str, brand: dict | None = None, script: str = "") -> str:
    """Turn one of the composed path: the model writes the WORDS for the
    reference's grammar — every slot the composer has, with its width —
    and the palette. No storyboard, no scenes: the structure is
    core.motion.compose's, and three generated reels (10-11 Sep 2026)
    showed a model does not build the transformation however it is asked."""
    from . import compose as _compose
    brand_note = ""
    if brand:
        brand_note = (
            f"\n\nThe brand colours were measured from the client's own artwork: "
            f"accent {brand.get('accent')}, deep {brand.get('deep')}. Use the accent "
            'as "accent" in the palette below.')
    script_note = ""
    if script and script.strip():
        script_note = (
            "\n\nTHE SCRIPT — the copy stage already wrote what this piece says. "
            "Take the words from it; do not write another story:\n"
            + script.strip()[:6000])
    return (
        "You are Prism's copywriter for a short vertical motion graphic. The "
        "film's structure is already designed and built — a signal of tiles "
        "gathers, streams into a hub, a bright sky sweeps in with a chat "
        "exchange, cards on a tree, a knowledge card, a ring with a fact, an "
        "orb, then the brand mark, tagline and call to action. Your job is "
        "ONLY the words that go into its slots, fitted to the widths given.\n\n"
        f"WHAT THE CLIENT ASKED FOR:\n{request}" + brand_note + script_note
        + "\n\nReply with ONLY this JSON object, in a ```json fenced code block, "
        "nothing before or after it:\n"
        "{\n"
        '  "project": {"palette": {"accent": "#hex — the brand accent", "accent2": "#hex — a second accent"}},\n'
        '  "copy": ' + _compose.copy_slots_text().replace("\n", "\n  ") + "\n"
        "}\n\n"
        "RULES: every slot filled, in the brand's own voice, taken from the "
        "script where the script has the line; character limits are hard "
        "(what does not fit is cut); plain text only — no markdown, no "
        "emoji; the three bubbles read as one real exchange with a customer "
        "(reply, question, answer); \"fact\" is a number or two words; the "
        '"captions" are optional one-liners for beats without their own words.'
    )


def parse_copy(text: str) -> tuple[dict, dict]:
    """The copy turn's reply: (project, copy). Either may be empty."""
    project: dict = {}
    copy: dict = {}
    for got in _web._json_objects(text):
        p = got.get("project")
        if isinstance(p, dict) and not project:
            project = p
        c = got.get("copy")
        if isinstance(c, dict) and not copy:
            copy = c
        elif not copy and isinstance(got.get("brand"), str):
            copy = got                                  # the slots at the top level
        if project and copy:
            break
    return project, copy


def _logo_from(assets_table: dict | None) -> dict | None:
    """The client's own mark from the asset table, for the resolve beat —
    a "logo" kind first, else the first transparent artwork."""
    if not assets_table:
        return None
    ranked = sorted(assets_table.items(),
                    key=lambda kv: (0 if kv[1].get("kind") == "logo" else 1,
                                    0 if kv[1].get("alpha") else 1))
    name, a = ranked[0]
    return {"src": f"asset:{name}", "w": a.get("w"), "h": a.get("h")}


def build_composed(first_reply: str, ask: Callable[..., str], assets_table: dict | None = None,
                   check=None, log=None, on_scene=None) -> dict:
    """The composed path: parse the copy (asking once more if none came),
    compose the reference's grammar around it, report what the inspector
    sees, and return the spec. Never asks for a scene."""
    from . import compose as _compose

    def say(msg):
        if log:
            log(msg)

    project, copy = parse_copy(first_reply)
    if not copy:
        say("turn one carried no copy — asking for the slots again")
        again = ask(
            'Send ONLY the JSON object with "project" (its "palette") and "copy" — '
            "every slot listed, fitted to its width — in a ```json fenced block.",
            COPY_EXPECT) or ""
        project2, copy = parse_copy(again)
        project = project or project2
    if not copy:
        raise MotionValidationError("The copy turn returned no words to compose with.")
    if on_scene:
        try:
            on_scene(0, 1)
        except Exception:                        # noqa: BLE001
            pass
    palette = project.get("palette") if isinstance(project.get("palette"), dict) else {}
    try:
        fps = int(float(project.get("fps") or 30))
    except (TypeError, ValueError):
        fps = 30
    spec = _compose.compose(copy, width=1080, height=1920, fps=max(12, min(60, fps)),
                            logo=_logo_from(assets_table), palette=palette)
    spec["_copy"] = copy
    if assets_table:
        spec["_assets"] = assets_table
    if check:
        try:
            faults = check(spec)
        except Exception as e:                   # noqa: BLE001
            faults = [f"couldn't inspect the composed piece ({e})"]
        if faults:
            say(f"composed {len(spec['scenes'])} scenes; the inspector notes "
                f"{len(faults)} thing(s): " + "; ".join(str(f) for f in faults[:4]))
        else:
            say(f"composed {len(spec['scenes'])} scenes — nothing to send back")
    return spec


def build_spec(first_reply: str, ask: Callable[..., str], assets: str = "",
               assets_table: dict | None = None,
               check=None, log=None, should_stop=None, on_scene=None,
               skeleton: str | None = None) -> dict:
    """Run the rest of the design conversation and return the finished spec.

    `ask(prompt, expect) -> str` sends a follow-up in the tab turn one is
    already sitting in. `check(spec) -> list[str]` reports concrete faults
    for a one-scene spec. Both are injected rather than imported, so this
    can be exercised without a browser — see core.reel_web.build_spec()'s
    docstring, which this mirrors exactly. `on_scene(index, total)` fires
    before each scene is asked for, for the same reason: this loop takes
    minutes, and nothing here raises once turn one has parsed.

    `assets` is the text description (core.assets.manifest()'s output)
    telling the model what `asset:<name>` it may put in an "image" node's
    "src". `assets_table` is the real {name: {"path": ...}} table behind
    those names — stashed on the returned spec as `_assets` (same
    convention core.reel_web uses) so resolve_motion_spec() can swap each
    `asset:name` for the real file before anything tries to render it.

    `skeleton="brand_launch"` or `skeleton="cinematic_glass"` must match what storyboard_instructions() was
    called with for `first_reply` — it switches each scene's prompt to the
    layer doctrine and threads each finished scene's exit into the next
    scene's prompt as a handoff so consecutive cuts continue a motion instead
    of resetting. The cinematic profile also records `_motion_profile` on the
    assembled spec.
    """
    def say(msg):
        if log:
            log(msg)

    if skeleton == SPINE_SKELETON:
        return build_composed(first_reply, ask, assets_table=assets_table, check=check,
                              log=log, on_scene=on_scene)

    project, camera, board = parse_storyboard(first_reply)
    if board and all(r.get("_from_scenes") for r in board):
        # Turn one answered whole scenes instead of a storyboard. Those
        # scenes carry no job, caption or subject — building on them is
        # how a piece ends up with no connecting story. Ask once for the
        # storyboard itself; fall back to the scene list only if that
        # fails too.
        say("turn one answered scenes, not a storyboard — asking for the "
            "storyboard itself")
        again = ask(
            "That reply built the scenes. Before any scene is built, send "
            "the STORYBOARD only: the same JSON object with \"project\", "
            "\"camera\" and a \"storyboard\" list — one row per scene "
            "with \"seconds\", \"job\", \"caption\", \"subject\", "
            "\"look\" and \"motion\" — and NO \"scenes\" key. The "
            "scenes are asked for one at a time after this.",
            STORYBOARD_EXPECT) or ""
        try:
            project2, camera2, board2 = parse_storyboard(again)
        except MotionValidationError:
            project2, camera2, board2 = project, camera, []
        if board2 and not all(r.get("_from_scenes") for r in board2):
            project, camera, board = project2 or project, camera2 or camera, board2
        else:
            say("   no storyboard came back — building on the scene list")
    total = len(board)
    if not total:
        raise MotionValidationError(
            "The storyboard names no scenes — there is nothing to build.")
    if skeleton == "cinematic_glass":
        from . import spine as _spine
        names = _spine.beats_for(total)
        for i, row in enumerate(board):
            if not _spine.beat(str(row.get("beat", "")).strip()):
                row["beat"] = names[i]

    say(f"storyboard: {total} scene(s) — writing them one at a time")
    scenes: list[dict] = []
    overflow_notice = ""
    handoff: dict | None = None
    for i in range(total):
        if should_stop and should_stop():
            say("stopped — keeping the scenes written so far")
            break
        if on_scene:
            try:
                on_scene(i, total)
            except Exception:                        # noqa: BLE001
                pass          # a progress listener must never fail the run
        prompt = overflow_notice + scene_instructions(
            i, total, board[i], assets, skeleton=skeleton, handoff=handoff)
        overflow_notice = ""
        raw = ask(prompt, SCENE_EXPECT) or ""
        scene = parse_scene(raw)
        if scene is None:
            scene = parse_scene(ask(
                f"Send scene {i + 1} again as JSON only — first character "
                "'{', last '}', key \"nodes\", wrapped in a ```json fenced "
                "block. Nothing before or after.",
                SCENE_EXPECT) or "")
        elif _scene_count(raw) > 1:
            n = _scene_count(raw)
            say(f"scene {i + 1} came back with {n} scenes in it — only the "
                "first was kept; telling it to slow down before the next ask")
            overflow_notice = (
                f"Before the next scene: that last reply answered {n} "
                f"scenes at once. Only scene {i + 1} was kept — the rest "
                "were discarded, not saved for later, so nothing from them "
                "will appear in the motion graphic. From here on, answer "
                "EXACTLY ONE scene per reply, the one actually asked "
                "for.\n\n")
        if scene is None:
            say(f"scene {i + 1} never came back as JSON — using a plain one")
            scene = fallback_scene(board[i])

        try:
            seconds = float(board[i].get("seconds") or 3.0)
        except (TypeError, ValueError):
            seconds = 3.0
        scene["id"] = f"scene_{i}"
        scene["duration"] = seconds

        if check:
            try:
                faults = check({"project": project, "camera": camera,
                                 "scenes": [scene]})
            except Exception as e:
                say(f"couldn't check scene {i + 1} ({e})")
                faults = []
            faults = (caption_faults(scene, board[i]) + beat_check(scene, board[i], skeleton)
                      + shot_faults(scene, skeleton, bool((camera or {}).get("tracks"))) + faults)
            if faults:
                say(f"scene {i + 1} has {len(faults)} problem(s) — "
                    "sending them back")
            # Up to two rounds. The second names the change each fault
            # needs (the second Alphakore run's "held slide" faults came
            # back unchanged after a single, unguided round). A correction
            # is kept only if genuinely cleaner — same rule as reel_web: a
            # "fix" trading four faults for five is not a fix.
            for round_no in range(REPAIR_ROUNDS):
                if not faults:
                    break
                fixed = parse_scene(ask(
                    repair_prompt(i, faults, round_no), SCENE_EXPECT) or "")
                if not fixed:
                    break
                fixed["id"] = scene["id"]
                fixed["duration"] = scene["duration"]
                try:
                    left = check({"project": project, "camera": camera,
                                   "scenes": [fixed]})
                except Exception:
                    left = []
                left = (caption_faults(fixed, board[i]) + beat_check(fixed, board[i], skeleton)
                        + shot_faults(fixed, skeleton, bool((camera or {}).get("tracks"))) + left)
                if len(left) < len(faults):
                    scene = fixed
                    say(f"   fixed — {len(faults)} down to {len(left)}")
                    faults = left
                else:
                    say("   the correction was no better — keeping the first"
                        + (" and saying what to change" if round_no + 1 < REPAIR_ROUNDS else ""))
        scenes.append(scene)
        if skeleton in ("brand_launch", "cinematic_glass"):
            handoff = _scene_handoff(scene) or handoff
        say(f"scene {i + 1}/{total} written — "
            f"{len(scene.get('nodes', []))} node(s)")

    if not scenes:
        raise MotionValidationError("No scenes were written.")
    if skeleton == "cinematic_glass" and len(scenes) > 1:
        _repair_continuity(scenes, project, camera, ask, say, check)
    spec: dict[str, Any] = {"project": project, "scenes": scenes}
    if camera:
        spec["camera"] = camera
    if assets_table:
        spec["_assets"] = assets_table
    if skeleton:
        spec["_motion_profile"] = skeleton
    return spec
