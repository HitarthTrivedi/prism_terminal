# Prism skills

A skill is one folder that says what a good result looks like for one job,
and, where a program can tell, checks the result against that. It is the
same idea as a Claude Code skill: a short description the planner always
sees, a body loaded only when the job matches, and a deterministic check
that runs on the output.

```
skills/<key>/
    SKILL.md        frontmatter + the doctrine
    checks.py       optional  faults(text, context) -> list[str]
    examples/       optional  golden outputs the body points at
    references/     optional  long material for people; never typed
```

`core/skills.py` is the loader. Nothing else in the engine knows the format.

## The frontmatter

```
---
title: Slide deck
description: A deck or pitch presentation — one claim per slide, speaker notes, a shape a deck tool can build.
stages: [presentation, content]
features: []
triggers: [ppt, pptx, powerpoint, slides, slide deck, pitch deck, keynote]
transport: [browser, api]
budget: 2600
version: 1
---
```

| field | meaning |
|---|---|
| `title` | shown to the tool as the block heading |
| `description` | one sentence the router reads to decide whether the skill fits; write it as a trigger, not a summary |
| `stages` | pipeline stages the router may attach it to (`research leads brains content visual media audio development presentation summary`) |
| `features` | add-on jobs that append it themselves via `skills.addendum("<feature>")`, e.g. `boq.format`, `inquiry.negotiation`, `leads.reach` |
| `triggers` | words or phrases in the person's own request that attach the skill when the router did not. Only ONE skill is attached this way, the one mentioned earliest, so triggers should be the words someone uses for *this* deliverable and nothing broader |
| `transport` | `browser` (typed into ChatGPT, Claude, Canva …), `api` (a direct Groq call), or both |
| `budget` | characters typed over browser transport; the body is cut at a paragraph boundary past this |
| `version` | bump when the doctrine changes in a way a customer override should be re-read against |

A skill may be routed (has `stages`), feature-bound (has `features`), or both.

## The body

Write it for the tool that will read it, in this order, because the body is
cut from the bottom over browser transport:

1. **Job** — one paragraph: what this deliverable is and who reads it.
2. **Rules** — numbered, concrete, checkable. "Titles are claims, not
   topics" is a rule; "make it engaging" is not.
3. **Shape** — the exact structure of the output: sections, headings,
   tables, word counts, the JSON keys if it is machine-read.
4. **Quality checklist** — 5 to 8 yes/no lines the tool can tick before
   sending. `checks.py`, when present, enforces the ones a program can.
5. **Non-goals** — what this step must not do (scope that belongs to
   another stage, formats that break the parser).
6. **Example** — a short golden excerpt, or a pointer into `examples/`.

Keep the layout of a text answer under `## Shape`, what the step must not do
under `## Non-goals`, and worked samples under `## Example`. Those three are
left out when the stage runs on a maker (Canva, Gamma, v0, a video tool)
or on the presentation stage, whichever tool runs it,
because there they would tell the tool to write the thing out instead of
building it. Nothing at all is typed into a stage that must reply in JSON.

Keep it under about 120 lines. Doctrine that is already in the code's own
prompt is not repeated here: a feature skill adds the expert layer the
code lacks, it does not restate the code.

## checks.py

```python
def faults(text: str, context: dict) -> list[str]:
    """Return one plain sentence per problem; [] when the text passes."""
```

`text` is the stage's captured answer. `context` carries `stage`, `query`
and `prompt` — what the tool was shown for the task, without the skill's own
text, so a number check can tell a figure it was given from one it made up.
A checker never runs on a maker or on a stage that must reply in JSON, and
never on a reply whose chat shows a built file: a file card ("Document·DOCX …
Download"), or only Claude's sandbox log ("Read 11 files, ran 11 commands").

### What a checker reads

Not markdown. Prism captures the chat page as it is displayed, so a checker
sees:

- a heading as a short bare line, with no `#`
- a list item as a plain line, with its bullet or number gone
- a table row as its cells joined by single spaces, with no pipes
- bold as plain text
- a Perplexity or ChatGPT citation as a bare site name on the line under the
  claim: `nhb.gov`, `+1`

A checker written for markdown misfires on almost every real answer. Use the
helpers in `core/skills.py`, which read both shapes: `text_lines`, `headings`,
`has_section`, `section_lines`, `item_rows`, `table_like_lines`,
`placeholders` and `is_source_chip`.

Every checker needs samples in `tests/skill_samples/`:

- `source/<skill>-good.md` and `source/<skill>-bad.md`, written as a chat
  model would write them
- `captured/<skill>-good.txt` and `-bad.txt`, produced from those by
  `devtools/capture_skill_samples.py`, which renders them in real Chrome and
  saves Selenium's text exactly as the engine reads it
- where one exists, a real reply from a run in `real/`, with client names
  removed

The good samples must pass clean and the bad ones must be caught, in both
shapes. Faults are sent back
to the tool once, in the same chat, and the second answer is kept only if
it has fewer faults. A check that raises is reported and skipped; it can
never cost a run. Only the shipped `checks.py` is ever loaded.

## Overriding a shipped skill

```
~/.prism/skills/<key>/SKILL.md    replaces the body (frontmatter optional)
~/.prism/skills/<key>/notes.md    appended as "FIELD NOTES"
~/.prism/skills/<new-key>/        a skill of your own
```

## Writing triggers

Triggers decide what happens when the planner picks nothing, and the
fallback attaches exactly one skill: the one whose trigger appears earliest
in the request, then the one with the most matches. So:

- Use the words a customer actually types, including the wrong ones
  (`ppt`, `power point`, `one pager`).
- Do not claim a general word another skill needs. `report` belongs to
  nobody; `annual report` belongs to the document skill.
- Whole words only — `deck` does not match "redeckorate".
- At the same position the longer phrase wins, so `document the` beats
  `document` in "document the api".
- A skill with no triggers is fine. It then only ever runs when the planner
  names it, which is the right choice for doctrine that needs judgement.

## Seeing what applies

`/skills` in the terminal lists every skill, where it applies and whether
it is checked or overridden. A planned run prints the skills attached to
each stage before it starts.
