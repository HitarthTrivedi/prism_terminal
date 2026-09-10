# Prism cinematic lab

An isolated motion-film experiment built on Studio's deterministic Chromium
capture. It is deliberately not registered with the GUI, router or licensed
server.

The lab owns three concerns:

- `project.py` — reusable motion primitives and the authored six-shot test;
- `render.py` — reviewed stills, MP4 capture and a temporary procedural score;
- `examples/cinematic_lab.py` — the only command-line entry point.

The reference follows one transformation instead of assembling unrelated
slides. Adjacent shots share exact particle/core coordinates, and each cut
starts from the previous shot's final visual state:

```text
scattered sources → intake → structure → answer → memory → brand
```

Run from `prism_gui`, always choosing a fresh output folder:

```bash
python examples/cinematic_lab.py --out ../cinematic-review-02 \
  --brand Conciz --tagline "Long reads, distilled into decisions."
```

The lab defaults to 60 FPS. Add `--previews-only` while iterating on surfaces
and layout; it runs preflight, renders six settled frames, and captures the
17% / 50% / 83% state of every scene handoff without paying for a full video
encode.

Full lab renders request a higher-fidelity master path (98-quality browser
captures and H.264 CRF 16). The shared Studio renderer keeps its existing
defaults unless a caller explicitly asks for these settings.

`--no-audio` keeps the MP4 silent. The default score is an intentionally
temporary timing reference made locally by FFmpeg, not production music.

## Promotion gate

Do not wire this into normal reel generation until it can:

1. accept an explicit visual story/shot graph rather than hard-coded copy;
2. map approved image and product assets to purposeful roles;
3. preview start, settled and exit frames for every shot;
4. expose camera, depth, light and audio beats as editable Studio tracks;
5. preserve the current browser and golden-frame test guarantees.

The current module is a direction prototype. It proves the visual grammar and
separation boundary; it does not claim that arbitrary AI output will match the
authored sample.
