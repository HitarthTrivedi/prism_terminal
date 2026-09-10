"""A reference cinematic project assembled from reusable motion primitives.

The reference is an authored test, not a production template. Its purpose is
to prove a richer grammar than independent headline slides: a recurring field
of particles becomes a content stream, a product interface, a knowledge graph
and finally the brand mark. Each shot inherits the same world and advances one
visual idea.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from pathlib import Path

from .. import reel_edit


@dataclass(frozen=True)
class CinematicTheme:
    brand: str = "Conciz"
    tagline: str = "Long reads, distilled into decisions."
    background: str = "#05070d"
    surface: str = "#10151f"
    ink: str = "#f3f5f2"
    muted: str = "#a7afb9"
    accent: str = "#82d4bc"
    warm: str = "#e9a978"


def _font_face() -> str:
    root = Path(__file__).resolve().parents[3]
    fonts = root / "assets" / "fonts"
    faces = []
    for family, filename, weight in (
        ("Cine Display", "BarlowCondensed-SemiBold.ttf", 600),
        ("Cine Text", "Barlow-Regular.ttf", 400),
        ("Cine Text", "Barlow-Medium.ttf", 500),
    ):
        raw = base64.b64encode((fonts / filename).read_bytes()).decode("ascii")
        faces.append(
            f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"src:url(data:font/ttf;base64,{raw}) format('truetype')}}")
    return "".join(faces)


def _particles(count: int = 36, *, phase: str = "scatter-band") -> str:
    """One deterministic signal field reused across adjacent shots.

    Every phase has identical band and core coordinates.  That is the visual
    continuity contract: the last pose of one shot is the first pose of the
    next, even though the renderer still owns separate scene layers.
    """
    cells = []
    palette = ("var(--accent)", "var(--warm)", "#a9b6ff", "#eef2ef")
    graph = ((220, 430), (820, 390), (170, 940),
             (850, 930), (250, 1390), (800, 1420))
    for i in range(count):
        col, row = i % 9, i // 9
        band_x = 110 + col * 104 + ((row % 2) * 23)
        band_y = 720 + row * 29
        scatter_x = 70 + ((i * 83) % 940)
        scatter_y = 190 + ((i * 137) % 1480)
        angle = (i / count) * math.tau
        radius = 28 + (i % 5) * 15
        core_x = 540 + math.cos(angle) * radius
        core_y = 915 + math.sin(angle) * radius
        graph_x, graph_y = graph[(i // 6) % len(graph)]
        graph_x += ((i % 3) - 1) * 18
        graph_y += ((i % 2) * 2 - 1) * 14
        size = 10 + (i * 7) % 18
        colour = palette[i % len(palette)]
        depth = i % 5
        blur = (0, 0, 0.5, 1.2, 2.1)[depth]
        opacity = (0.9, 0.76, 0.62, 0.5, 0.38)[depth]
        cells.append(
            "<i class='particle' style='"
            f"--x:{band_x}px;--y:{band_y}px;--sx:{scatter_x}px;--sy:{scatter_y}px;"
            f"--cx:{core_x:.1f}px;--cy:{core_y:.1f}px;--gx:{graph_x}px;--gy:{graph_y}px;"
            f"--d:{(i % 8) * 46}ms;--s:{size}px;--c:{colour};--blur:{blur}px;"
            f"--alpha:{opacity};--depth:{0.84 + depth * .06}'></i>")
    safe_phase = "".join(c for c in phase if c.isalnum() or c == "-")
    return (f"<div class='particles particles-{safe_phase}' aria-hidden='true'>"
            + "".join(cells) + "</div>")


def _world() -> str:
    return (
        "<div class='world' aria-hidden='true'><div class='aura aura-a'></div>"
        "<div class='aura aura-b'></div><div class='light-strand'></div>"
        "<div class='bokeh bokeh-a'></div><div class='bokeh bokeh-b'></div>"
        "<div class='grain'></div></div>")


def _shot_one() -> str:
    return (_world() + _particles(phase="scatter-band") +
            "<div class='s1-copy'><p class='kicker'>The reading pile grows.</p>"
            "<h1>Signal is hiding<br>inside the noise.</h1></div>"
            "<p class='s1-note'>Articles · reports · meetings · research</p>")


def _shot_two() -> str:
    items = "".join(
        f"<div class='source-shell source-{i}'><article class='source'>"
        f"<span>{kind}</span><b>{title}</b><i></i><i></i><i></i>"
        "</article></div>"
        for i, (kind, title) in enumerate((
            ("PDF", "Market review"), ("WEB", "Product research"),
            ("NOTE", "Customer call")), 1))
    return (_world() + _particles(phase="band-core") +
            "<p class='chapter'>01 / bring the source</p>"
            f"<div class='sources'>{items}</div>"
            "<div class='intake-shell'><div class='intake'><span>Drop anything here</span>"
            "<b>Conciz reads the structure</b><div class='scan'></div></div></div>")


def _shot_three() -> str:
    paths = []
    nodes = []
    data = ((220, 430, "claim"), (820, 390, "context"), (170, 940, "number"),
            (850, 930, "quote"), (250, 1390, "risk"), (800, 1420, "action"))
    for i, (x, y, label) in enumerate(data):
        paths.append(f"<path style='--delay:{520 + i * 90}ms' d='M540 915 C540 700 {x} {y + 80} {x} {y}'/>")
        nodes.append(f"<div class='fact fact-{i}' style='left:{x-75}px;top:{y-36}px;"
                     f"--delay:{780+i*90}ms'>{label}</div>")
    return (_world() + _particles(phase="core-graph")
            + "<div class='handoff-light' aria-hidden='true'></div>"
            "<p class='chapter'>02 / find the structure</p>"
            "<svg class='connections' viewBox='0 0 1080 1920' aria-hidden='true'>"
            + "".join(paths) + "</svg><div class='hub'><span>C</span><i></i></div>"
            + "".join(nodes) +
            "<div class='s3-copy'><h1>Every useful idea,<br>connected.</h1>"
            "<p>Claims, context, numbers and actions stay traceable.</p></div>")


def _shot_four() -> str:
    return (_world() + "<div class='light-field' aria-hidden='true'></div>"
            "<p class='chapter dark'>03 / ask, don’t search</p>"
            "<div class='conversation'><div class='question-shell'><div class='question'>"
            "What changed in customer retention?</div></div>"
            "<div class='answer-shell'><div class='answer'><p>Retention improved after onboarding changed.</p>"
            "<div class='metric'><b>+11.8%</b><span>90-day retention</span></div>"
            "<footer><i></i> Sources linked to the answer</footer></div></div></div>"
            "<p class='s4-caption'>Ask the question. Get the answer—<br>with evidence attached.</p>")


def _shot_five() -> str:
    cards = "".join(
        f"<div class='memory-shell memory-{i}'><article class='memory'>"
        f"<span>{tag}</span><b>{title}</b><p>{copy}</p></article></div>"
        for i, (tag, title, copy) in enumerate((
            ("DECISION", "Simplify onboarding", "Three steps now explain the core action."),
            ("EVIDENCE", "Retention rose", "The clearest lift appeared after week two."),
            ("NEXT", "Test the new prompt", "Compare completion across both cohorts.")), 1))
    return (_world() + "<p class='chapter'>04 / keep what matters</p>"
            "<div class='orbit orbit-a'></div><div class='orbit orbit-b'></div>"
            "<div class='knowledge-shell'><div class='knowledge-core'>"
            "<span>Knowledge base</span><b>Always in context.</b></div></div>"
            f"<div class='memories'>{cards}</div>"
            "<p class='s5-caption'>A living system of decisions,<br>not another folder of summaries.</p>")


def _shot_six(theme: CinematicTheme) -> str:
    return (_world() + _particles(phase="final-orbit") +
            "<div class='final-orb-shell' aria-hidden='true'><div class='final-orb'>"
            "<i></i><i></i><i></i><em></em></div></div>"
            f"<div class='endmark'><h1>{theme.brand}</h1><p>{theme.tagline}</p>"
            "<span>Turn reading into momentum</span></div>")


def _css(theme: CinematicTheme) -> str:
    return _font_face() + f"""
:root{{--bg:{theme.background};--surface:{theme.surface};--ink:{theme.ink};
--muted:{theme.muted};--accent:{theme.accent};--warm:{theme.warm};
--ease:cubic-bezier(.16,1,.3,1);--firm:cubic-bezier(.22,1,.36,1)}}
.scene{{font-family:'Cine Text',sans-serif;background:var(--bg);color:var(--ink)}}
.world{{position:absolute;inset:-180px;overflow:hidden;background:
radial-gradient(ellipse at 55% 42%,#132120 0%,#090d14 33%,#05070d 66%,#030409 100%);z-index:0;
animation:camera 5200ms cubic-bezier(.37,0,.63,1) both}}
.aura{{position:absolute;border-radius:50%;filter:blur(88px);opacity:.18;will-change:transform}}
.aura-a{{width:760px;height:760px;left:500px;top:180px;background:var(--accent);
animation:floatA 5400ms cubic-bezier(.37,0,.63,1) both}}
.aura-b{{width:620px;height:620px;left:-60px;top:1110px;background:#6779d0;
animation:floatB 5400ms cubic-bezier(.37,0,.63,1) both}}
.light-strand{{position:absolute;left:160px;top:-180px;width:2px;height:2450px;
background:linear-gradient(transparent,rgba(255,255,255,.12) 32%,rgba(130,212,188,.32) 54%,transparent 78%);
box-shadow:0 0 34px rgba(130,212,188,.22);transform:rotate(21deg);opacity:.48}}
.bokeh{{position:absolute;border-radius:50%;filter:blur(18px);will-change:transform}}
.bokeh-a{{width:180px;height:180px;right:60px;top:1010px;background:rgba(130,212,188,.14);
animation:bokehA 5100ms cubic-bezier(.37,0,.63,1) both}}
.bokeh-b{{width:260px;height:260px;left:-80px;top:470px;background:rgba(132,146,230,.12);
filter:blur(30px);animation:bokehB 5100ms cubic-bezier(.37,0,.63,1) both}}
.grain{{position:absolute;inset:0;opacity:.055;background-image:
radial-gradient(rgba(255,255,255,.72) .55px,transparent .75px);background-size:6px 6px}}
.chapter{{position:absolute;left:92px;top:118px;z-index:70;margin:0;
font:500 32px/1 'Cine Text';letter-spacing:2px;color:var(--accent)}}
.chapter.dark{{color:#1c2a32}}
.particles{{position:absolute;inset:0;z-index:18;pointer-events:none}}
.particle{{position:absolute;left:0;top:0;width:var(--s);height:var(--s);
background:linear-gradient(135deg,rgba(255,255,255,.72),var(--c) 48%,color-mix(in srgb,var(--c),#000 24%));
border-radius:4px;filter:blur(var(--blur));opacity:var(--alpha);
box-shadow:0 0 12px var(--c),0 0 34px color-mix(in srgb,var(--c),transparent 42%);
will-change:transform,opacity}}
.particles-scatter-band .particle{{animation:scatterToBand 3800ms var(--firm) var(--d) both}}
.particles-band-core .particle{{animation:bandToCore 4400ms var(--firm) both}}
.particles-core-graph .particle{{animation:coreToGraph 2200ms var(--firm) both}}
.particles-final-orbit .particle{{animation:finalOrbit 1500ms var(--ease) both}}
.s1-copy{{position:absolute;left:92px;top:380px;width:850px;z-index:50}}
.kicker{{margin:0 0 35px;font:500 38px 'Cine Text';color:var(--accent);
animation:rise 650ms var(--firm) 260ms both}}
.s1-copy h1{{margin:0;font:600 132px/.94 'Cine Display';letter-spacing:-2px;
text-wrap:balance;animation:rise 900ms var(--ease) 390ms both}}
.s1-note{{position:absolute;left:92px;bottom:155px;z-index:50;margin:0;
font:400 34px 'Cine Text';color:var(--muted);animation:rise 700ms var(--firm) 820ms both}}
.sources{{position:absolute;left:82px;top:270px;width:916px;height:390px;z-index:30;pointer-events:none}}
.source-shell{{position:absolute;width:310px;height:330px;padding:6px;border-radius:31px;
background:linear-gradient(145deg,rgba(255,255,255,.2),rgba(130,212,188,.08) 46%,rgba(255,255,255,.025));
box-shadow:0 44px 100px rgba(0,8,16,.44),0 0 70px rgba(130,212,188,.06),
inset 0 1px rgba(255,255,255,.22);animation:sourceIn 900ms var(--ease) both;pointer-events:auto}}
.source{{position:relative;width:100%;height:100%;padding:34px;border-radius:25px;
background:linear-gradient(145deg,rgba(20,29,40,.84),rgba(7,11,18,.73));
backdrop-filter:blur(28px) saturate(1.35);box-shadow:inset 0 1px rgba(255,255,255,.11),
inset 0 -1px rgba(130,212,188,.08)}}
.source-1{{left:0;top:32px;--rot:-5deg;animation-delay:420ms}}
.source-2{{left:298px;top:0;--rot:1deg;animation-delay:560ms}}
.source-3{{left:596px;top:42px;--rot:6deg;animation-delay:700ms}}
.source span,.memory span{{display:block;font:500 32px 'Cine Text';letter-spacing:2px;color:var(--accent)}}
.source b{{display:block;margin-top:32px;font:500 38px/1.08 'Cine Text'}}
.source i{{display:block;width:100%;height:7px;margin-top:23px;border-radius:5px;background:#45505f}}
.source i+ i{{width:76%;margin-top:14px}}.source i+ i+ i{{width:50%}}
.intake-shell{{position:absolute;left:126px;top:1034px;width:828px;height:482px;padding:7px;
z-index:40;border-radius:49px;background:linear-gradient(145deg,rgba(255,255,255,.2),
rgba(130,212,188,.12) 48%,rgba(255,255,255,.025));box-shadow:0 80px 200px rgba(0,7,15,.5),
0 0 90px rgba(130,212,188,.08),inset 0 1px rgba(255,255,255,.25);
animation:intakeIn 950ms var(--ease) 920ms both}}
.intake{{position:relative;width:100%;height:100%;padding:63px;border-radius:42px;
background:linear-gradient(155deg,rgba(20,29,40,.88),rgba(6,10,17,.76));
backdrop-filter:blur(34px) saturate(1.45);box-shadow:inset 0 1px rgba(255,255,255,.12),
inset 0 -1px rgba(130,212,188,.08)}}
.intake span{{font:400 36px 'Cine Text';color:var(--muted)}}
.intake b{{display:block;width:620px;margin-top:38px;font:600 84px/.96 'Cine Display'}}
.scan{{position:absolute;left:70px;right:70px;bottom:65px;height:3px;overflow:visible;
background:rgba(255,255,255,.12)}}
.scan:after{{content:'';display:block;width:32%;height:3px;background:var(--accent);
box-shadow:0 0 20px var(--accent);animation:scan 1800ms var(--firm) 750ms both}}
.connections{{position:absolute;inset:0;z-index:15}}
.connections path{{fill:none;stroke:rgba(130,212,188,.52);stroke-width:2;
stroke-dasharray:1400;animation:draw 1250ms var(--firm) var(--delay) both}}
.handoff-light{{position:absolute;left:440px;top:815px;width:200px;height:200px;z-index:65;
border-radius:50%;background:radial-gradient(circle,#f0f4ef 0%,#b7d5da 42%,rgba(164,196,205,.78) 62%,transparent 72%);
box-shadow:0 0 120px rgba(184,220,220,.6);pointer-events:none;
animation:openLight 4400ms cubic-bezier(.76,0,.24,1) both}}
.hub{{position:absolute;left:428px;top:803px;width:224px;height:224px;z-index:45;
display:grid;place-items:center;border-radius:50%;background:
radial-gradient(circle at 35% 26%,#f2fffa 0%,#c8f9e8 8%,var(--accent) 24%,#286356 58%,#0a1716 78%);
box-shadow:inset -20px -26px 46px rgba(0,0,0,.26),inset 12px 14px 34px rgba(255,255,255,.22),
0 0 0 18px rgba(130,212,188,.04),0 0 125px rgba(130,212,188,.38);
animation:hubIn 850ms var(--ease) 520ms both}}
.hub span{{position:relative;z-index:2;font:600 110px 'Cine Display';color:#07110f}}
.hub i{{position:absolute;inset:-52px;border:1px solid rgba(130,212,188,.24);border-radius:50%;
pointer-events:none;animation:halo 5000ms cubic-bezier(.37,0,.63,1) both}}
.fact{{position:absolute;z-index:40;min-width:150px;padding:20px 25px;text-align:center;
border-radius:17px;background:linear-gradient(145deg,rgba(28,37,49,.82),rgba(8,12,20,.75));
backdrop-filter:blur(18px) saturate(1.3);box-shadow:inset 0 1px rgba(255,255,255,.18),
inset 0 0 0 1px rgba(130,212,188,.11),0 24px 55px rgba(0,5,11,.38);
font:500 32px/1 'Cine Text';color:var(--ink);animation:factIn 650ms var(--ease) var(--delay) both}}
.s3-copy{{position:absolute;left:92px;right:92px;bottom:125px;z-index:55}}
.s3-copy h1{{margin:0;font:600 106px/.95 'Cine Display';letter-spacing:-1px}}
.s3-copy p{{margin:24px 0 0;width:730px;font:400 38px/1.2 'Cine Text';color:var(--muted)}}
.light-field{{position:absolute;inset:-100px;z-index:2;background:
radial-gradient(circle at 12% 82%,rgba(233,169,120,.85),transparent 31%),
radial-gradient(circle at 88% 16%,rgba(111,188,220,.88),transparent 35%),
linear-gradient(150deg,#d7d5d1 0%,#a9c0ce 48%,#b7a9ba 100%);
filter:saturate(.82);animation:lightScene 4500ms cubic-bezier(.37,0,.63,1) both}}
.conversation{{position:absolute;left:72px;top:390px;width:936px;z-index:40;transform-origin:50% 48%;
animation:conversationFlow 4500ms cubic-bezier(.76,0,.24,1) both}}
.question-shell{{width:804px;margin-left:132px;padding:6px;border-radius:42px 42px 14px 42px;
background:linear-gradient(145deg,rgba(255,255,255,.52),rgba(25,40,51,.28) 35%,rgba(255,255,255,.08));
box-shadow:0 42px 110px rgba(13,25,34,.28),inset 0 1px rgba(255,255,255,.72);
animation:bubbleIn 720ms var(--ease) 150ms both}}
.question{{width:100%;padding:42px 48px;border-radius:36px 36px 9px 36px;
background:linear-gradient(145deg,rgba(20,26,33,.95),rgba(8,13,19,.86));color:#f5f5f2;
font:500 48px/1.14 'Cine Text';box-shadow:inset 0 1px rgba(255,255,255,.12)}}
.answer-shell{{width:874px;margin-top:36px;padding:7px;border-radius:43px 43px 43px 15px;
background:linear-gradient(145deg,rgba(255,255,255,.82),rgba(255,255,255,.28) 54%,rgba(77,114,127,.15));
box-shadow:0 48px 125px rgba(13,25,34,.28),inset 0 1px rgba(255,255,255,.85);
animation:bubbleIn 850ms var(--ease) 650ms both}}
.answer{{width:100%;padding:48px;border-radius:36px 36px 36px 9px;
background:linear-gradient(155deg,rgba(250,251,248,.86),rgba(230,239,238,.68));color:#172026;
backdrop-filter:blur(32px) saturate(1.18);box-shadow:inset 0 1px rgba(255,255,255,.9),
inset 0 -1px rgba(37,83,73,.12)}}
.answer>p{{margin:0;width:720px;font:500 50px/1.13 'Cine Text'}}
.metric{{display:flex;align-items:end;gap:30px;margin-top:54px;padding-top:44px;border-top:1px solid #a5adb0}}
.metric b{{font:600 112px/.8 'Cine Display';color:#1d6656}}
.metric span{{width:220px;font:500 33px/1.05 'Cine Text';color:#546168}}
.answer footer{{margin-top:52px;font:500 32px 'Cine Text';color:#546168}}
.answer footer i{{display:inline-block;width:12px;height:12px;margin-right:13px;border-radius:50%;background:#288c75}}
.s4-caption{{position:absolute;left:92px;bottom:150px;z-index:45;margin:0;color:#142027;
font:500 48px/1.1 'Cine Text';animation:rise 720ms var(--firm) 1300ms both}}
.orbit{{position:absolute;box-shadow:inset 0 0 0 1px rgba(130,212,188,.2);border-radius:50%;z-index:12;
animation:halo 5200ms cubic-bezier(.37,0,.63,1) both}}
.orbit-a{{width:1160px;height:1160px;left:-340px;top:360px}}
.orbit-b{{width:820px;height:820px;left:540px;top:180px;animation-direction:reverse}}
.knowledge-shell{{position:absolute;left:253px;top:643px;width:574px;height:284px;padding:7px;z-index:40;
border-radius:37px;background:linear-gradient(145deg,rgba(255,255,255,.22),rgba(130,212,188,.11),
rgba(255,255,255,.025));box-shadow:0 60px 155px rgba(0,5,11,.48),0 0 90px rgba(130,212,188,.08),
inset 0 1px rgba(255,255,255,.24);transform-origin:center;
animation:knowledgeFlow 4500ms cubic-bezier(.76,0,.24,1) both}}
.knowledge-core{{position:relative;width:100%;height:100%;padding:51px 57px;border-radius:30px;
background:linear-gradient(145deg,rgba(19,29,39,.84),rgba(7,12,18,.73));
backdrop-filter:blur(32px) saturate(1.4);box-shadow:inset 0 1px rgba(255,255,255,.12)}}
.knowledge-core span{{font:500 32px 'Cine Text';color:var(--accent)}}
.knowledge-core b{{display:block;margin-top:28px;font:600 67px/.96 'Cine Display'}}
.memories{{position:absolute;inset:0;z-index:35}}
.memory-shell{{position:absolute;width:402px;min-height:247px;padding:6px;border-radius:31px;
background:linear-gradient(145deg,rgba(255,255,255,.18),rgba(130,212,188,.06),rgba(255,255,255,.02));
box-shadow:0 42px 105px rgba(0,5,11,.42),inset 0 1px rgba(255,255,255,.2);
animation:memoryFlow 4500ms cubic-bezier(.76,0,.24,1) both}}
.memory{{position:relative;width:100%;min-height:235px;padding:34px;border-radius:25px;
background:linear-gradient(145deg,rgba(20,28,38,.82),rgba(7,11,18,.72));
backdrop-filter:blur(26px) saturate(1.35);box-shadow:inset 0 1px rgba(255,255,255,.1)}}
.memory-1{{left:65px;top:310px;--tx:274px;--ty:282px}}
.memory-2{{right:48px;top:1000px;--tx:-291px;--ty:-408px}}
.memory-3{{left:86px;top:1265px;--tx:253px;--ty:-673px}}
.memory b{{display:block;margin-top:17px;font:500 39px 'Cine Text'}}
.memory p{{margin:13px 0 0;font:400 32px/1.18 'Cine Text';color:var(--muted)}}
.s5-caption{{position:absolute;left:92px;bottom:110px;z-index:55;margin:0;font:500 45px/1.1 'Cine Text';
animation:captionFlow 4500ms var(--firm) both}}
.final-orb-shell{{position:absolute;left:196px;top:371px;width:688px;height:688px;padding:5px;z-index:30;
border-radius:50%;background:conic-gradient(from 215deg,rgba(255,255,255,.08),rgba(206,255,240,.72),
rgba(130,212,188,.08),rgba(255,255,255,.02),rgba(206,255,240,.72),rgba(255,255,255,.08));
box-shadow:0 0 200px rgba(130,212,188,.22),inset 0 1px rgba(255,255,255,.7);
animation:orbReveal 1300ms var(--ease) both}}
.final-orb{{position:relative;width:100%;height:100%;border-radius:50%;overflow:visible;
background:radial-gradient(circle at 34% 26%,#f4fffb 0%,#d8fff2 7%,var(--accent) 20%,#387f70 43%,#122a26 66%,#06100f 78%);
box-shadow:inset -70px -85px 120px rgba(0,0,0,.4),inset 25px 28px 65px rgba(255,255,255,.18)}}
.final-orb i{{position:absolute;inset:-80px;border:1px solid rgba(130,212,188,.16);border-radius:50%;
animation:halo 4800ms cubic-bezier(.37,0,.63,1) both}}
.final-orb i:nth-child(2){{inset:-145px;opacity:.55;animation-direction:reverse}}
.final-orb i:nth-child(3){{inset:210px;background:#edf8f3;border:0;box-shadow:0 0 48px #fff}}
.final-orb em{{position:absolute;left:112px;top:76px;width:235px;height:100px;border-radius:50%;
background:rgba(255,255,255,.32);filter:blur(24px);transform:rotate(-22deg)}}
.endmark{{position:absolute;left:92px;right:92px;bottom:155px;z-index:60;text-align:center}}
.endmark h1{{margin:0;font:600 188px/.82 'Cine Display';letter-spacing:-2px;animation:rise 850ms var(--ease) 500ms both}}
.endmark p{{margin:38px auto 0;font:400 43px/1.18 'Cine Text';color:var(--muted);animation:rise 650ms var(--firm) 700ms both}}
.endmark span{{display:inline-block;margin-top:54px;padding:22px 36px;border-radius:16px;
background:linear-gradient(145deg,rgba(130,212,188,.12),rgba(255,255,255,.025));
box-shadow:inset 0 1px rgba(255,255,255,.16),inset 0 0 0 1px rgba(130,212,188,.19),
0 24px 70px rgba(0,0,0,.28);backdrop-filter:blur(20px);font:500 32px 'Cine Text';
color:var(--accent);animation:rise 650ms var(--firm) 900ms both}}
.cut-flow.leaving{{opacity:calc(1 - var(--ease) * .38);transform:scale(calc(1 + var(--ease) * .028));
filter:blur(calc(var(--ease) * 1.6px))}}
.cut-flow.entering{{opacity:var(--ease);transform:scale(calc(.985 + var(--ease) * .015));filter:none}}
@keyframes camera{{from{{transform:scale(1.08) translate3d(-12px,18px,0)}}to{{transform:scale(1) translate3d(8px,-7px,0)}}}}
@keyframes floatA{{from{{transform:translate3d(80px,-50px,0) scale(.85)}}to{{transform:translate3d(-40px,70px,0) scale(1.08)}}}}
@keyframes floatB{{from{{transform:translate3d(-50px,90px,0)}}to{{transform:translate3d(70px,-30px,0)}}}}
@keyframes bokehA{{from{{opacity:.25;transform:translate3d(70px,-40px,0) scale(.8)}}to{{opacity:.7;transform:translate3d(-55px,75px,0) scale(1.2)}}}}
@keyframes bokehB{{from{{opacity:.45;transform:translate3d(-40px,80px,0) scale(1.15)}}to{{opacity:.16;transform:translate3d(80px,-50px,0) scale(.82)}}}}
@keyframes scatterToBand{{0%{{opacity:0;transform:translate3d(var(--sx),var(--sy),0) scale(calc(var(--depth) * .3))}}
18%{{opacity:var(--alpha);transform:translate3d(var(--sx),var(--sy),0) scale(var(--depth))}}
58%{{opacity:var(--alpha);transform:translate3d(var(--sx),var(--sy),0) scale(var(--depth))}}
100%{{opacity:var(--alpha);transform:translate3d(var(--x),var(--y),0) scale(var(--depth))}}}}
@keyframes bandToCore{{0%,61%{{opacity:var(--alpha);transform:translate3d(var(--x),var(--y),0) scale(var(--depth))}}
100%{{opacity:calc(var(--alpha) * .92);transform:translate3d(var(--cx),var(--cy),0) scale(calc(var(--depth) * .48))}}}}
@keyframes coreToGraph{{0%,12%{{opacity:calc(var(--alpha) * .92);transform:translate3d(var(--cx),var(--cy),0) scale(calc(var(--depth) * .48))}}
72%{{opacity:var(--alpha);transform:translate3d(var(--gx),var(--gy),0) scale(calc(var(--depth) * .62))}}
100%{{opacity:.08;transform:translate3d(var(--gx),var(--gy),0) scale(.25)}}}}
@keyframes finalOrbit{{0%{{opacity:.12;transform:translate3d(var(--cx),calc(var(--cy) - 200px),0) scale(.2)}}
100%{{opacity:var(--alpha);transform:translate3d(var(--x),calc(var(--y) - 25px),0) scale(var(--depth))}}}}
@keyframes rise{{from{{opacity:0;transform:translate3d(0,42px,0)}}to{{opacity:1;transform:translate3d(0,0,0)}}}}
@keyframes sourceIn{{from{{opacity:0;transform:translate3d(0,130px,0) rotate(calc(var(--rot) * 1.8)) scale(.84)}}to{{opacity:1;transform:rotate(var(--rot)) scale(1)}}}}
@keyframes intakeIn{{from{{opacity:0;transform:translate3d(0,150px,0) scale(.92)}}to{{opacity:1;transform:translate3d(0,0,0) scale(1)}}}}
@keyframes scan{{from{{transform:translateX(0) scaleX(.12)}}to{{transform:translateX(215%) scaleX(1)}}}}
@keyframes draw{{from{{stroke-dashoffset:1400}}to{{stroke-dashoffset:0}}}}
@keyframes hubIn{{from{{opacity:0;transform:scale(.6)}}to{{opacity:1;transform:scale(1)}}}}
@keyframes halo{{from{{transform:rotate(-9deg) scale(.96)}}to{{transform:rotate(11deg) scale(1.05)}}}}
@keyframes factIn{{from{{opacity:0;transform:scale(.68)}}to{{opacity:1;transform:scale(1)}}}}
@keyframes openLight{{0%,64%{{opacity:0;transform:scale(.2)}}78%{{opacity:.72}}100%{{opacity:1;transform:scale(11)}}}}
@keyframes lightScene{{0%{{opacity:1;transform:scale(1.18) translate3d(-35px,20px,0)}}
66%{{opacity:1;transform:scale(1.04) translate3d(18px,-12px,0)}}
100%{{opacity:0;transform:scale(.84) translate3d(25px,-18px,0)}}}}
@keyframes conversationFlow{{0%,67%{{opacity:1;transform:translate3d(0,0,0) scale(1)}}
100%{{opacity:.34;transform:translate3d(0,62px,0) scale(.62)}}}}
@keyframes bubbleIn{{from{{opacity:0;transform:translate3d(0,100px,0) scale(.88)}}to{{opacity:1;transform:translate3d(0,0,0) scale(1)}}}}
@keyframes knowledgeFlow{{0%{{opacity:.32;transform:translate3d(0,-4px,0) scale(.62)}}
18%,70%{{opacity:1;transform:translate3d(0,0,0) scale(1)}}
100%{{opacity:.48;transform:translate3d(0,-70px,0) scale(.2);border-radius:50%}}}}
@keyframes memoryFlow{{0%{{opacity:0;transform:translate3d(0,70px,0) scale(.84)}}
18%,70%{{opacity:1;transform:translate3d(0,0,0) scale(1)}}
100%{{opacity:0;transform:translate3d(var(--tx),var(--ty),0) scale(.12)}}}}
@keyframes captionFlow{{0%,12%{{opacity:0;transform:translateY(35px)}}28%,72%{{opacity:1;transform:none}}
100%{{opacity:0;transform:translateY(-18px)}}}}
@keyframes orbReveal{{from{{opacity:0;transform:scale(.18)}}to{{opacity:1;transform:scale(1)}}}}
"""


def build_demo_spec(theme: CinematicTheme | None = None, *, fps: int = 60) -> dict:
    """Return the complete self-contained test project.

    It has no external artwork or web-font dependency, which keeps review
    focused on composition and motion rather than asset availability.
    """
    theme = theme or CinematicTheme()
    shots = (
        (3.8, _shot_one(), "flow", "pressure"),
        (4.4, _shot_two(), "flow", "ingest"),
        (4.4, _shot_three(), "flow", "structure"),
        (4.5, _shot_four(), "flow", "conversation"),
        (4.5, _shot_five(), "flow", "memory"),
        (4.2, _shot_six(theme), "flow", "brand"),
    )
    spec = {
        "fps": int(fps),
        "design": {
            "name": "Cinematic lab — information becomes intelligence",
            "direction": (
                "One continuous visual world. Scattered information gathers into a stream, "
                "becomes structured evidence, answers a real question, joins a living knowledge "
                "system and resolves into the brand. Depth, light and camera motion carry the "
                "film; typography explains only what the visual cannot."),
            "css": _css(theme),
            "cut_ms": 1050,
        },
        "brand": {"name": theme.brand, "accent": theme.accent},
        "scenes": [
            {"seconds": seconds, "cut": cut, "type": role, "html": html, "css": ""}
            for seconds, html, cut, role in shots
        ],
        "_cinematic_lab": {"version": 3, "profile": "continuous-glass",
                           "audio": "procedural-reference"},
    }
    reel_edit.ensure_stable_ids(spec)
    return spec
