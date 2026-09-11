---
title: Bill of quantities
description: A tender-ready BOQ written from measured quantities — every item traceable to the measurement, derived figures declared, nothing silently invented.
features: [boq.standards, boq.interpret, boq.format]
stages: []
transport: [browser, api]
budget: 3800
version: 1
---

## The job

A BOQ is a contractual document. Someone will price it, someone else will
be held to those prices, and a third person will audit it two years later
when there is an argument. Every quantity must be traceable to something
that was measured, or declared as something that was not.

## Rules

1. **The measured CSV is the truth.** Quantities come from the
   measurement. You may group, describe and order them; you may not
   change a number. Where a figure disagrees with what you expect, say so
   in a note instead of correcting it.
2. **Derived figures are declared and shown.** If a count was worked out
   rather than measured — cameras at a spacing, cable along its route,
   fixings per metre — state the basis on the row:
   "derived: 1 per 3 m of route, 42 m → 14 nos". An undeclared derived
   figure is the single worst thing in this document.
3. **Every item has a unit and the unit matches the item.** m, m², m³,
   nos, kg, lot. A length priced as an area is the error that survives
   all the way to the invoice.
4. **Describe the item the way it is priced.** The description must carry
   everything that changes the rate: material, size, finish, fixing,
   height or depth band, and what the rate includes.
5. **Say what the rate includes and excludes.** Per item, or in a
   preamble that covers the section. Supply only, supply and fix,
   including scaffolding, excluding civil work.
6. **Follow the standard the project names.** If the drawing, the
   customer's own sample BOQ or the brief names a method of measurement
   or a schedule of rates, use its item numbering and its wording.
   Where the customer supplied a sample BOQ, match its structure exactly.
7. **Nothing absent from the drawing appears as a measured item.** It
   goes under PROVISIONAL with a note saying why it is there.
8. **Round the way the method rounds.** Where the brief names no method,
   use IS 1200: dimensions to 0.01 m and areas and volumes to 0.01 (Part 1);
   steelwork lengths to 0.001 m and mass to the nearest 1 kg (Part 8).
   Counts are whole. Never present a measurement to five decimals.
9. **Measure net, as fixed.** Wastage, cutting and laps belong in the rate,
   not the quantity. Under IS 1200 Part 8, bolts, nuts and washers in
   steelwork go by mass, not count. Cable is measured along its route with
   no allowance for slack, plus loops of about 3 m at each termination and
   joint, as CPWD measures it.

## Shape

```
PREAMBLE       What the rates include, exclude, and the basis of measurement.
SECTION A — <trade or area>
| Item | Description | Unit | Qty | Basis |
...
PROVISIONAL    Items not measurable from what was supplied, each with a reason.
ASSUMPTIONS    Every derivation, spacing rule and inference, one line each.
TO CONFIRM     What the drawing does not settle.
```

## Quality checklist

- Every quantity matches the measured figures, unchanged.
- Every derived figure names its basis on the row.
- Every row has a unit and the unit suits the item.
- Descriptions carry everything that affects the rate.
- Inclusions and exclusions are stated for every section.
- Where a sample BOQ was supplied, the numbering and wording follow it.
- Anything unmeasurable is under PROVISIONAL, never in the main table.

## Non-goals

Do not price the BOQ and do not total it — rates come from the customer's
own rate library in a later, arithmetic-only step, and a rate written by
a language model is the one thing this document must never contain. Do
not redesign or value-engineer; the drawing is the brief.
