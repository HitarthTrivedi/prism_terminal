---
title: Slide deck
description: A deck, pitch or PowerPoint — one claim per slide, speaker notes under every slide, and a structure a deck tool can build directly.
stages: [presentation, content]
triggers: [ppt, pptx, powerpoint, power point, slide, slides, slide deck, deck, pitch deck, keynote, presentation, google slides]
transport: [browser, api]
budget: 2900
version: 1
---

## The job

A deck is read at a distance, in a room, while someone talks over it. It
is not a document with borders. Every slide that needs to be read in full
to be understood has already failed.

## Rules

1. **One idea per slide.** If a slide needs "and", it is two slides.
2. **The title is the claim, not the topic.** "Margins fell 4% on
   freight" — not "Margins". A reader who reads only the titles, in
   order, should get the whole argument.
3. **Six lines, twelve words.** At most six bullets on a slide, at most
   about twelve words each. Anything longer belongs in the speaker notes.
4. **Speaker notes under every slide.** Two to four sentences: what the
   presenter actually says, including the number behind the claim. This
   is where the detail cut from the slide goes.
5. **A number needs a shape.** Three or more related figures are a table
   or a chart, never a list of bullets. Say which chart and what is on
   each axis.
6. **Open with the ask, not the agenda.** An agenda slide is a slide
   spent on housekeeping. Slide one says why this meeting matters.
7. **Close with the decision.** The last slide is what you want the room
   to agree, in a sentence, with the next step and who owns it.
8. **No placeholder text ever.** No "Lorem ipsum", no `[Client Name]`, no
   "insert chart here", no "TBD". If a figure is unknown, write the
   figure you do have and say in the notes what is missing.

## Shape

Write every slide in this exact block, in order, numbered from 1:

```
SLIDE 3 — Margins fell 4% on freight
• Diesel up 22% since January
• Two carriers dropped the Surat lane
• Freight is now 11% of landed cost
NOTES: Freight went from 7% to 11% of landed cost in five months …
```

Twelve to eighteen slides for a pitch, six to ten for an internal update,
unless the request says otherwise. State the count at the top.

## Quality checklist

- Reading only the slide titles, in order, gives the whole argument.
- No slide exceeds six bullets or roughly twelve words a bullet.
- Every slide has a NOTES line with real content, not a restatement of
  the bullets.
- Every group of three or more numbers is a table or a named chart.
- The last slide states a decision and a next step with an owner.
- No placeholder, bracket-name or "TBD" anywhere in the deck.

## Non-goals

Do not design the deck — no colour palettes, no font choices, no slide
layouts, unless the request asked for art direction. A later step or a
deck tool does that and it is handed this structure. Do not write a
document and call it a deck: prose paragraphs on a slide are the single
most common failure here.
