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
    two backgrounds scenes alternate between (see rule 8 below), ink is the
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
  shape_rect       — position, width, height, radius, fill, is_glass (optional)
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
                      below (never write a real URL or invent a name) — a logo,
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
  "shot": {"intent": "push", "target": "<node id>" or [x, y], "zoom": 1.2}
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
  distinct easings in this scene."""


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


def storyboard_instructions(request: str, brand: dict | None = None,
                            skeleton: str | None = None) -> str:
    """Turn one: the look, the camera's overall intent, and a storyboard
    row per scene. Mirrors core.reel_web.design_instructions()'s split.

    `brand`: colours already measured off the client's own artwork (see
    core.reel.sample_brand — the same pixel-level measurement Reel/Studio
    use, not re-implemented here). Unlike Reel's Pillow renderer, nothing
    here applies these automatically — Motion's palette is the model's own
    choice — so it's told to use them as ITS accent rather than inventing
    one, the same way Studio is told to.
    """
    brand_note = ""
    if brand:
        brand_note = (
            f"\n\nThe brand colours have already been measured from the "
            f"client's own artwork: accent {brand.get('accent')}, deep "
            f"{brand.get('deep')}. Use these as the accent colour running "
            "through the piece rather than inventing your own — this is "
            "their actual brand, not a suggestion.")
    return (
        "You are Prism's Senior Visual Director and Motion Designer, "
        "planning a short vertical motion graphic.\n\n"
        f"WHAT THE CLIENT ASKED FOR:\n{request}"
        + brand_note + "\n\n"
        + _PALETTE_GUIDANCE + "\n\n"
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
        "for the WHOLE graphic — rule 3 below still applies.")
    )


def _brand_launch_storyboard_close() -> str:
    roles = "\n".join(f'  {i + 1}. {r} — {_ROLE_BRIEF[r]}'
                       for i, r in enumerate(SCENE_ROLES))
    return (
        "EXACTLY 4 scenes, in this fixed order, 8-14 seconds total — do "
        "not add, drop, reorder or rename them:\n" + roles + "\n\n"
        '"job" for each row IS its role above, in your own words for this '
        "brand. `camera.tracks` is for the WHOLE graphic — rule 3 below "
        "still applies."
    )


def _cinematic_glass_storyboard_close() -> str:
    return (
        "5-8 scenes, 16-30 seconds total. Design one continuous visual "
        "transformation rather than a sequence of poster frames: name the "
        "visual spine in the motion field, keep it recognisable, and state "
        "how each scene's final pose hands into the next scene's first pose. "
        "Use scene changes to reveal, transform or focus the same idea; "
        "reserve the final scene for a resolved logo/answer/CTA. `camera.tracks` "
        "is for the WHOLE graphic and should also feel continuous."
    )


def scene_instructions(idx: int, total: int, row: dict, assets: str = "",
                       skeleton: str | None = None,
                       handoff: dict | None = None) -> str:
    """Ask for ONE scene's nodes. The rest of the conversation already
    knows the palette and camera from turn one; this only needs the row.

    `skeleton="brand_launch"` swaps the freeform node catalogue for the
    layer doctrine (background/midground/foreground/accent/finish) and
    pins this scene to its fixed HOOK/REVEAL/PROOF/SIGNOFF role.
    `skeleton="cinematic_glass"` uses the same layer contract but adds a
    persistent visual spine, continuity keys and explicit handoff guidance.
    `handoff` is what core.motion.generate._scene_handoff() read off the
    PREVIOUS scene — how it exited — so this one can continue that motion
    or colour instead of cutting cold; None for the first scene.
    """
    job = str(row.get("job", "")).strip() or "carry the argument forward"
    look = str(row.get("look", "")).strip()
    motion = str(row.get("motion", "")).strip()
    try:
        seconds = float(row.get("seconds") or 3.0)
    except (TypeError, ValueError):
        seconds = 3.0
    catalogue = _NODE_CATALOGUE
    rules = (
        "DESIGN RULES FOR THIS SCENE:\n"
        "1. 3-7 nodes. Do not overcrowd.\n"
        "2. Vary the text mode — use at most 2 different modes.\n"
        '3. Give at least one node a real "exit", not only "enter".\n'
        "4. The most common way a scene ends up reading as a PowerPoint "
        "slide, however busy it is, is every element using the same "
        "easing curve. Treat that as the failure to design against.\n"
        "5. Never use generic emojis in text content.\n\n"
        "6. The brand's accent colour should recur, not repeat identically —\n"
        "   the same one or two colours framing every single scene the same\n"
        "   way (same white headline, same accent subtitle, same background)\n"
        "   reads as one template stamped four times, not four scenes of one\n"
        "   film. Let where and how the accent is used change: a highlighted\n"
        "   word instead of a whole line, a filled shape instead of an\n"
        "   outline, a background wash instead of just text — same brand,\n"
        "   different weight each time.\n"
        "7. Use the palette/type chosen in turn one BY NAME — a full-bleed "
        "background node filled with project.palette.bg_a or bg_b (alternate "
        "which one scene to scene rather than repeating the same one every "
        "time), text filled with project.palette.ink or accent, "
        'font_family "var(--motion-display-font)" for headlines/numbers and '
        '"var(--motion-body-font)" for body/labels — never invent a fresh '
        "hex or font mid-scene that ignores what turn one already chose.\n"
        "8. This scene may name a \"transition_in\" (see TRANSITIONS above) "
        "for how it cuts in from the one before it — pick one that fits "
        "the beat, or leave it unset and a real one is still chosen for "
        "you rather than a hard cut.\n"
        "9. Before placing a text or image node, sketch its actual box — "
        "position ± roughly half its width/height — against every OTHER "
        "text/image node's box already placed this scene. Two photos, or "
        "a headline and a photo, sharing the same region reads as debris, "
        "not layout, no matter how good either looks alone. Give each one "
        "its own clear region of the 1080x1920 frame (stack vertically, "
        "or split left/right) rather than centering everything on the "
        "same point. A shape_rect used as an intentional backdrop directly "
        "behind one specific node (a badge behind its own label, a card "
        "behind its own photo) is the one exception — that pairing is "
        "supposed to share a position.\n\n"
    )
    role_header = ""
    if skeleton in ("brand_launch", "cinematic_glass"):
        role = _scene_role(idx)
        catalogue = _NODE_CATALOGUE + "\n\n" + _LAYER_DOCTRINE
        if skeleton == "cinematic_glass":
            catalogue += "\n\n" + _CINEMATIC_GLASS_DOCTRINE
            rules = rules + (
                '10. Put a stable "continuity_key" on the hero/subject node; '
                "reuse the same key in later scenes when that subject returns.\n"
                "11. At least one camera or secondary motion must continue across "
                "the handoff; the incoming pose must visibly pick up the outgoing one.\n"
            )
        rules = rules + (
            '7. Give every node a "layer" (see LAYERS above) — background '
            "and foreground are both required this scene.\n"
        )
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
    # The catalogue and doctrines are sent in full with scene 1 and only
    # named afterwards: every later turn lands in the same browser tab,
    # and a run on 10 Sep 2026 grew that page until the kernel killed
    # Chrome for memory. The rules block below stays on every turn.
    if idx > 0:
        catalogue = (
            "NODE TYPES, TEXT MODES, ANIMATION, SHOT, TRANSITIONS, EASINGS"
            + (", LAYERS and the CINEMATIC GLASS profile" if skeleton == "cinematic_glass"
               else ", LAYERS" if skeleton == "brand_launch" else "")
            + " are exactly as written in the scene 1 message above — reuse "
            "them; they are not repeated here.")
    return (
        f"SCENE {idx + 1} of {total}.\n\n"
        + role_header
        + f"ITS JOB: {job}\n"
        + (f"THE LOOK: {look}\n" if look else "")
        + (f"THE MOTION: {motion}\n" if motion else "")
        + f"\nDuration: {seconds:g} seconds. All this scene's animation "
        "times count from 0 at this scene's own start.\n\n"
        + catalogue + "\n\n"
        + rules
        + (f"ARTWORK YOU MAY USE:\n{assets}\n\n" if assets else "")
        + "Reply with ONLY this JSON object, in a ```json fenced code "
        "block, nothing before or after it:\n"
        '{\n  "shot": {"intent": "...", "target": "<node id>"},\n'
        '  "nodes": [ /* 3-7 node objects, as above */ ]\n}'
    )


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
            board = [{"job": "", "look": "", "motion": "",
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

    project, camera, board = parse_storyboard(first_reply)
    total = len(board)
    if not total:
        raise MotionValidationError(
            "The storyboard names no scenes — there is nothing to build.")

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
            if faults:
                say(f"scene {i + 1} has {len(faults)} problem(s) — "
                    "sending them back")
                fixed = parse_scene(ask(
                    f"Scene {i + 1} was checked and these are wrong:\n\n"
                    + "\n".join(f"{n}. {x}" for n, x in enumerate(faults[:8], 1))
                    + "\n\nSend the corrected scene: ONLY the JSON object, "
                      "same shape, in a ```json fenced block.",
                    SCENE_EXPECT) or "")
                if fixed:
                    fixed["id"] = scene["id"]
                    fixed["duration"] = scene["duration"]
                    try:
                        left = check({"project": project, "camera": camera,
                                       "scenes": [fixed]})
                    except Exception:
                        left = []
                    # Kept only if genuinely cleaner — same rule as reel_web:
                    # a "fix" trading four faults for five is not a fix.
                    if len(left) < len(faults):
                        scene = fixed
                        say(f"   fixed — {len(faults)} down to {len(left)}")
                    else:
                        say("   the correction was no better — keeping the "
                            "first")
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
