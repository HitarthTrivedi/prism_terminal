"""Faults a program can see in a bill of materials.

Written for captured text: a rendered parts table arrives as rows of cells
joined by spaces, with no pipes. The first version needed pipe rows and so
rejected every real parts list as "not a table" before checking anything.

This is the checker the doctrine exists for. A language model writing a
parts list produces rows that read perfectly and cannot be bought: no grade,
no recognised designation, a dimension off by a factor of ten — or, as in
the owner's own BOQ/BOM run, bearings quantified in inches because a layer
length off the drawing was listed as the quantity.

Adding an item to ENVELOPE: only a part whose defining size is
unmistakable, with the range taken from a standard's or a manufacturer's own
table, in mm. Err wide. A false fault costs a re-ask and teaches people to
ignore the checker; a missed one costs a purchase order.
"""
from __future__ import annotations

import re

from core import skills as SK

# (regex for the item, low mm, high mm, what a real one is like)
# Only parts whose defining size is unmistakable. The first list also held
# bolts, nuts, washers, cable glands, castors, hinges, terminal blocks,
# proximity sensors and selector switches. A fact-check against standards and
# manufacturer data on 2026-09-11 found six of those ranges wrong, and every
# one rejected a real, common part: a 600 mm foundation bolt (IS 5624), a
# 2 mm washer, a 64 mm cam switch, an M63 gland, a 250 mm castor wheel, a
# 2000 mm piano hinge.
ENVELOPE = (
    (r"\bmushroom\b", 22, 90,
     "a mushroom-head emergency stop is 40 or 60 mm across"),
    (r"\bpush\s?button\b", 16, 40,
     "a panel push button fits a 16, 22 or 30 mm hole"),
    # Pilot lights also come in 8 and 12 mm; one shared 16 mm floor rejected them.
    (r"\bpilot (?:lamp|light)\b|\bindicator (?:lamp|light)\b", 8, 40,
     "a pilot light is 8, 12, 16, 22 or 30 mm"),
)
SERIES = (
    (r"\bISMC\s?(\d{2,3})\b", 75, 400, "ISMC runs 75 to 400"),
    (r"\bISMB\s?(\d{2,3})\b", 100, 600, "ISMB runs 100 to 600"),
    (r"\bISA\s?(\d{2,3})\s?[x×]\s?(\d{2,3})", 20, 200, "ISA runs 20 to 200"),
    (r"\bISLC\s?(\d{2,3})\b", 75, 400, "ISLC runs 75 to 400"),
)
# Also "class 10.9", "Fe 500D", IS/IEC and IEC numbers, aluminium tempers
# like "6061-T6", and E350/E410 written without "IS 2062" -- all real grades
# the first pattern missed.
GRADE = re.compile(
    r"\bIS(?:/IEC)?\s?\d{3,5}\b|\bIEC\s?\d{4,5}\b|\bISO\s?\d+\b|"
    r"\bEN\s?\d+[A-Za-z]?\b|\bASTM\s?[A-Z]?\d+\b|\bDIN\s?\d+\b|"
    r"\bSS\s?\d{3}L?\b|\bAISI\s?\d{3}L?\b|\bE\s?(?:250|275|300|350|410|450)\b|"
    r"\bFe\s?\d{3}[A-Z]?\b|\b[1-8]\d{3}-T\d{1,2}\b|\bgrade\b|"
    r"\bclass\s?\d{1,2}\.\d\b|\bIP\s?\d{2}\b",
    re.IGNORECASE)
VAGUE_MATERIAL = re.compile(
    r"\b(?:mild steel|ms\b|stainless steel|carbon steel|high[- ]tensile|"
    r"aluminium|aluminum|plastic|rubber|metal)\b", re.IGNORECASE)
UNIT = re.compile(r"\b(?:nos?|no\.|pcs?|pieces?|sets?|kgs?|mtrs?|metres?|"
                  r"meters?|m|m2|m²|sqm|rmt|lot|ltrs?|litres?|pairs?|pkts?|"
                  r"packets?|rolls?|each|in|inch(?:es)?|ft|feet)\b",
                  re.IGNORECASE)
QTY_CELL = re.compile(r"^\s*[\d,]+(?:\.\d+)?\s*$")
EQUIV = re.compile(r"\bor equivalent\b|\bor equal\b|\bmake\s*[:-]|"
                   r"\b(?:siemens|schneider|abb|l&t|larsen|phoenix|omron|"
                   r"rittal|bosch|skf|fag|nbr|festo|smc|wago|legrand|havells|"
                   r"bonfiglioli|nord|sew|eaton)\b", re.IGNORECASE)
BOUGHT_OUT = re.compile(
    r"\bmotor\b|\bgearbox\b|\bgear motor\b|\bbearing\b|\bcylinder\b|\bvalve\b|"
    r"\bsensor\b|\bswitch\b|\bcontactor\b|\bplc\b|\bvfd\b|"
    # Not a bare "drive": a drive SHAFT is fabricated, and "Drive Shaft" was
    # asked for a make on the owner's own parts list.
    r"\b(?:ac|servo|variable frequency) drives?\b|\brelay\b|"
    r"\bpump\b|\bfan\b|\bencoder\b|\bcoupling\b|\bchain\b|\bsprocket\b",
    re.IGNORECASE)
# Things bought by count. Given a length as their quantity, they are a layer
# length read off the drawing, not a number anyone can order.
COUNTABLE = re.compile(
    r"\bbearings?\b|\bbolts?\b|\bnuts?\b|\bwashers?\b|\bscrews?\b|\bmotors?\b|"
    r"\bgear ?box(?:es)?\b|\bsensors?\b|\bswitch(?:es)?\b|\bvalves?\b|\bpumps?\b|"
    r"\bcouplings?\b|\bcast[oe]rs?\b|\bhinges?\b|\bglands?\b|\bbuttons?\b|"
    r"\bpulleys?\b|\bsprockets?\b|\brollers?\b|\bidlers?\b|\bplummer blocks?\b",
    re.IGNORECASE)
COUNT_UNIT = re.compile(r"\b(?:nos?|no\.|pcs?|pieces?|sets?|each|pairs?|units?)\b",
                        re.IGNORECASE)
LENGTH_QTY = re.compile(
    r"\b(?:in|inch(?:es)?|ft|feet|mtrs?|rmt|mm|m)\s+([\d,]+(?:\.\d+)?)"
    r"|([\d,]+(?:\.\d+)?)\s*(?:in|inch(?:es)?|ft|feet|mtrs?|rmt)\b",
    re.IGNORECASE)
ASSUMPTIONS = re.compile(r"\bassumption|\bassumed\b|\bTO CONFIRM\b|\binferred\b|"
                         r"\bto be confirmed\b|\bbasis\b", re.IGNORECASE)
# The unit may not run on into "-16" or a letter: on the owner's own parts
# list "46 M-16 Nut" read as a 46-metre nut, item number and thread size
# taken for a dimension.
DIM = re.compile(r"(\d+(?:\.\d+)?)\s*(mm|cm|m|inch|\"|kg|tonnes?|ton)(?![-\w])",
                 re.IGNORECASE)
TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4, "\"": 25.4}

MAX_REPORTED = 5


def _label(row: str) -> str:
    if " | " in row:
        cells = row.split(" | ")
        return (cells[1] if len(cells) > 1 else cells[0])[:44]
    return re.sub(r"^\d{1,3}[.)]?\s+", "", row)[:44]


def _body(row: str) -> str:
    """The row without its item number, which is not a dimension."""
    if " | " in row:
        return " | ".join(row.split(" | ")[1:])
    return re.sub(r"^\d{1,3}[.)]?\s+", "", row)


def _mm(value: float, unit: str) -> float:
    return value * TO_MM.get(unit.lower(), 1.0)


def faults(text: str, context: dict) -> list:
    text = text or ""
    rows = SK.item_rows(text)
    if not rows:
        return ["No item rows were found. Give one numbered row per buyable "
                "item: description, standard or grade, size, quantity and "
                "unit."]

    out = []
    no_grade, vague, no_unit, no_qty, no_make, silly, by_length = ([] for _ in range(7))
    for i, row in enumerate(rows, 1):
        label = f"{i} ({_label(row)})"
        # A bought-in item named by its make is specified by that make; the
        # grade rule is for material the shop buys to a standard.
        if not GRADE.search(row) and not EQUIV.search(row):
            no_grade.append(label)
            v = VAGUE_MATERIAL.search(row)
            if v:
                vague.append(f"{i} ('{v.group(0).strip()}')")
        if not UNIT.search(row):
            no_unit.append(label)
        if " | " in row and not any(QTY_CELL.match(c) for c in row.split(" | ")):
            no_qty.append(label)
        if BOUGHT_OUT.search(row) and not EQUIV.search(row):
            no_make.append(label)
        if COUNTABLE.search(row) and not COUNT_UNIT.search(row):
            for m in LENGTH_QTY.finditer(row):
                figure = (m.group(1) or m.group(2) or "").replace(",", "")
                try:
                    if float(figure) >= 50:
                        by_length.append(f"{label}: {m.group(0).strip()}")
                        break
                except ValueError:
                    continue

        for pattern, lo, hi, what in ENVELOPE:
            if not re.search(pattern, row, re.IGNORECASE):
                continue
            dims = [(v, u) for v, u in DIM.findall(_body(row))
                    if u.lower() not in ("kg", "ton", "tonne", "tonnes")]
            # Only when the row carries ONE dimension. With a panel depth, a
            # cable range or a sensing distance beside it there is no telling
            # which figure is the part's size, and guessing is exactly how the
            # first version rejected real parts.
            if len(dims) == 1:
                value, u = dims[0]
                mm = _mm(float(value), u)
                if mm and not (lo <= mm <= hi):
                    silly.append(f"row {i} ({_label(row)}): {value} {u} — {what}")
            break
        for pattern, lo, hi, what in SERIES:
            m = re.search(pattern, row, re.IGNORECASE)
            if m:
                if not (lo <= float(m.group(1)) <= hi):
                    silly.append(f"row {i} ({_label(row)}): {m.group(0)} — {what}")
                break

    if by_length:
        out.append("Counted items are given a length as their quantity: "
                   + "; ".join(by_length[:MAX_REPORTED])
                   + ". A bearing or a bolt is counted in nos. A length read "
                     "off a drawing layer is not a count — say so in a note "
                     "instead of listing it as the quantity.")
    if silly:
        out.append("Dimension(s) that are not physically plausible — "
                   + "; ".join(silly[:MAX_REPORTED])
                   + ". Check against the drawing; a size that reads like a "
                     "typo usually is one.")
    if no_grade:
        out.append(f"{len(no_grade)} row(s) name no standard or grade: "
                   + ", ".join(no_grade[:MAX_REPORTED])
                   + ". A purchase officer cannot buy from a description "
                     "alone — give IS/EN/ASTM/AISI or a class.")
    if vague:
        out.append("Material named as a family rather than a grade: "
                   + ", ".join(vague[:MAX_REPORTED])
                   + ". 'Mild steel' is not buyable; 'IS 2062 E250' is.")
    if no_unit:
        out.append(f"{len(no_unit)} row(s) have no unit: "
                   + ", ".join(no_unit[:MAX_REPORTED]) + ".")
    if no_qty:
        out.append(f"{len(no_qty)} row(s) have no quantity: "
                   + ", ".join(no_qty[:MAX_REPORTED]) + ".")
    if no_make:
        out.append("Bought-out item(s) with no make named: "
                   + ", ".join(no_make[:MAX_REPORTED])
                   + ". Name a make and add 'or equivalent'.")
    if not ASSUMPTIONS.search(text):
        out.append("There is no ASSUMPTIONS or TO CONFIRM block. Every "
                   "inferred quantity and everything the drawing does not "
                   "settle belongs in one, not silently in the table.")
    return out
