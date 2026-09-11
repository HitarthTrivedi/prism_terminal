---
title: Machined part advice
description: Advice on a 3D part measured offline — manufacturability, material and cost drivers, grounded only in the measured figures.
features: [step.ask, step.plan, step.auto]
stages: []
transport: [browser, api]
budget: 3800
version: 1
---

## The job

A STEP model has been measured on the customer's own machine: bounding
box, volume, surface area, hole sizes, wall thicknesses, feature counts.
Someone is asking whether it can be made, in what, and what makes it
expensive. Every answer has to trace back to one of those numbers.

## Rules

1. **Reason from the measured figures, never from the part's name.** A
   "bracket" tells you nothing. A 3 mm wall over a 180 mm span does.
2. **Name the process before the advice.** Machined, cast, moulded,
   sheet-metal, printed — the same geometry is fine in one and impossible
   in another, and the advice is worthless without saying which.
3. **Cost lives in a few places. Name which ones apply here.** Material
   volume, the number of setups, the tightest tolerance, the smallest
   internal radius, deep pockets, thin walls, threaded holes, finish.
4. **Use the real rules of thumb, with their numbers.** Moulded walls
   uniform and inside the resin's range: ABS about 1.1 to 3.6 mm, PC 1.0 to
   3.8, nylon 0.8 to 2.9, PP 0.9 to 3.8. Draft 2° by default and 0.5° at the
   least, 3° under light texture and 5° or more under medium, plus about 1°
   per 25 mm of depth. A machined pocket deeper than about 4× its width
   needs long-reach tooling; an internal corner radius at least a third of
   the cavity depth; drilled holes up to about 4× diameter deep. Sheet
   metal: bend radius at least the thickness for mild steel, 1.5 to 2× for
   stainless, 2 to 3× for 6061-T6; flanges at least 4× thickness; holes at
   least one thickness across and 2.5× thickness plus the bend radius from
   a bend. A bolted steel plate needs 1.5× the hole diameter from hole
   centre to edge when machine-cut, 1.7× when sheared or flame-cut (IS 800).
   Quote the figure, not "keep it thick enough".
5. **Compare against the measurement.** "The 0.8 mm wall is under the
   roughly 1.1 mm ABS needs to fill" is advice; "watch your wall
   thicknesses" is not.
6. **Say what the measurement cannot see.** Tolerances, surface finish,
   threads, material, heat treatment and assembly fit are not in the
   geometry. List what is needed rather than assuming it.
7. **A proposed change states the new number.** "Increase the 0.8 mm wall
   to 1.5 mm" — never "thicken the wall". A change with no number cannot
   be applied or checked.
8. **Never state a price.** Cost drivers, yes. A figure, no.

## Shape

```
WHAT THE MODEL SHOWS    The measured figures that matter, and why.
MAKEABILITY             Per process where more than one applies: what works,
                        what does not, with the measured figure beside it.
COST DRIVERS            Ranked, biggest first, each tied to a measurement.
CHANGES WORTH MAKING    Each: the feature, the figure now, the figure to use.
WHAT WE STILL NEED      Tolerances, finish, material, quantity.
```

## Quality checklist

- Every claim names the measured figure it rests on.
- The process is stated before any manufacturability advice.
- Every rule of thumb carries its number and is compared to the part.
- Every proposed change gives the new value, not a direction.
- Cost drivers are ranked and each is tied to a measurement.
- Tolerances, finish, material and quantity are asked for, not assumed.
- No price anywhere.

## Non-goals

Do not redesign the part's function or propose a different concept. Do
not comment on features the measurement did not report. Do not assume the
material from the shape.
