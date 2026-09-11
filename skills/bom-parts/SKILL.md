---
title: Bill of materials
description: A fabrication parts list written from a measured drawing — every line buyable, with a grade, a standard and a plausible size.
features: [bom.standards, bom.format]
stages: []
transport: [browser, api]
budget: 4000
version: 1
---

## The job

A BOM is handed to a purchase officer who will raise enquiries from it. A
line they cannot buy from is a phone call back to the draughtsman. The
test of every row: could someone send this line to a supplier, on its
own, and get a quotation back?

## Rules

1. **A line is a buyable item.** Description, grade or material standard,
   size or section designation, quantity, unit. A row missing any of
   these is not a BOM row.
2. **Name the standard, not the material family.** "IS 2062 E250 BR", not
   "mild steel" — and where toughness matters add "impact test required"
   or order B0 or C, because BR makes the test optional. "EN8 (080M40)",
   not "medium carbon steel". "Hex bolt M12 × 40, IS 1364 (Part 1), class
   8.8 to IS 1367 (Part 3)", not "high-tensile bolt". Structural
   friction-grip bolts are IS 3757 8.8S or 10.9S, with IS 6623 nuts and
   IS 6649 washers.
3. **Use the designation a supplier recognises.** ISMC 100, ISA
   50×50×6, ISMB 150, M12 × 40 — the trade's own shorthand, not a
   description of the shape. Pipe names its standard and wall class:
   "40 NB Medium, IS 1239 (Part 1)" up to 150 NB, IS 3589 above. An ASME
   schedule is a different wall and not interchangeable. A foundation bolt
   is "Foundation bolt M20 × 600, IS 5624"; a cable gland names its thread
   and clamping range, "M20, 6–12 mm".
4. **Sizes must be physically sensible.** Check every dimension against
   the thing it is: a mushroom-head emergency stop is about 40 mm across,
   not 250. An M6 bolt is not 400 mm long in a sheet-metal panel. A
   gearbox for a 1.5 kW drive is not 2 tonnes. A dimension that reads
   like a typo usually is one — say so rather than propagating it.
5. **Quantities are counted, never estimated silently.** Where a count
   came from the measurement, keep it. Where you inferred one, mark the
   row and say what you assumed.
6. **Group by how it is bought.** Structural sections, plates, fasteners,
   bought-out items, consumables. A purchase officer works one heading at
   a time.
7. **Weight where it is sold by weight.** Sections and plates: give kg
   from the IS 808 sectional weight, rounded to 1 kg, and say whether it is
   theoretical or weighbridge weight — rolled sections carry a ±2.5% mass
   tolerance. State the rate basis: per kg or per tonne.
8. **Bought-out items name a make or an equivalent.** "Siemens 3SU1 or
   equivalent" is buyable; "emergency stop button" is a research task.
9. **Never invent a part that was not in the drawing or the brief.** If
   the assembly plainly needs a fastener nobody dimensioned, add it under
   a clearly marked ASSUMED heading with the reason.

## Shape

One table, grouped, with these columns in this order:

```
| # | Description | Standard / grade | Size / designation | Qty | Unit | Weight (kg) | Remarks |
```

Then two short blocks:

```
ASSUMPTIONS   Every inferred quantity, size or grade, one line each.
TO CONFIRM    What the drawing does not say and someone must answer.
```

## Quality checklist

- Every row has a grade or standard and a recognised size designation.
- Every row has a quantity and a unit.
- No dimension is physically implausible for the item it describes.
- Bought-out items name a make or say "or equivalent".
- Inferred rows are marked and listed under ASSUMPTIONS.
- Anything the drawing does not settle is listed under TO CONFIRM rather
  than guessed into the table.

## Non-goals

Do not price anything — rates and totals are a separate step with the
customer's own rate library behind it. Do not redesign the part or
suggest a better construction; the drawing is the brief. Do not merge
rows of different grades to shorten the list.
