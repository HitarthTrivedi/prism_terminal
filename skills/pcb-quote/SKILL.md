---
title: PCB fabrication reply
description: A reply to a PCB enquiry written from measured Gerber data — the fab parameters that decide the price, the ones that need a decision, and nothing the files did not show.
features: [gerber.writeup, gerber.form]
stages: []
transport: [browser, api]
budget: 3400
version: 1
---

## The job

A fabricator has measured the customer's Gerber files. The reply tells
the customer what was found, what it means for making the board, and what
is still missing before a price can be firm. The measurements are given;
they were taken by a program and are not yours to adjust.

## Rules

1. **The measured figures are given inputs.** Board size, minimum track
   and spacing, smallest drill, hole count, layer count — quote them as
   measured. Never round them into a nicer number and never re-derive one.
2. **Say what each figure means for making the board.** A 0.15 mm track
   is standard at 1 oz copper. 0.09 mm is fine-line: many shops charge more
   for it and some run it as normal on multilayer boards, so say "confirm
   against our class table". Heavier copper needs wider track. The customer
   wants the consequence, not the number they already have.
3. **Name the parameters that are not in the files at all.** Board
   thickness and outline tolerance, copper weight, surface finish, solder
   mask and silkscreen colour, material grade and Tg, panel or single,
   IPC-6012 Class 2 or 3, impedance control, via treatment (tented, plugged
   or filled) and electrical test. A price without these is a guess, and every one of
   them is a decision the customer has to make.
4. **Flag anything at the edge of the process.** An annular ring under
   the house minimum, a drill below what the shop runs, a spacing that
   forces a tighter pattern class — as a question, not a refusal.
5. **Layer count drives the price most, then quantity and turn time.**
   A 24 to 48 hour turn can double or triple it. Ask for quantity and
   delivery, and say the price depends on them.
6. **Never state a price unless one was supplied to you.** Rates come
   from the fabricator's own sheet. The reply prepares the quotation; it
   does not invent it.
7. **Confidentiality holds.** The customer's design is theirs. Do not
   describe the circuit, the components or what the board appears to do.
8. **One page.** Measurements as a table, questions as a numbered list.

## Shape

```
WHAT WE MEASURED     Table: parameter, value, what it means for fabrication.
WHAT WE NEED         Numbered: the parameters not in the files, each a decision.
POINTS TO WATCH      Anything near a process limit, phrased as a question.
NEXT                 What happens when they answer, and by when.
```

## Quality checklist

- Every measured value is quoted exactly as measured.
- Every measured value is paired with what it means for making the board.
- Board thickness, copper weight, finish, mask, material, IPC class and
  test are all asked for.
- Quantity and delivery are asked for.
- No price appears unless a rate was supplied.
- Nothing describes the circuit's function or its components.

## Non-goals

Do not suggest design changes to the board — it is not your design and a
fabricator who redesigns a customer's PCB loses the customer. Do not
guess a missing parameter to make the reply look complete: a listed
question is worth more than a wrong assumption.
