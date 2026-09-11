---
title: PDF or Word document
description: A document that will be printed, sent as a PDF or opened in Word — brochure, datasheet, one-pager, proposal, product document or report. Built page by page, with the front page working on its own.
stages: [content, presentation, development]
triggers: [pdf, docx, word document, word doc, word file, document, brochure, datasheet, data sheet, one-pager, one pager, leaflet, flyer, whitepaper, white paper, proposal, catalogue, catalog, spec sheet, annual report, case study pdf]
transport: [browser, api]
budget: 3200
version: 1
---

## The job

A PDF is a fixed thing, and so is a Word document that is sent rather
than edited together. Nobody scrolls it looking for context, and nobody
can ask you a question about it. It is often printed, often forwarded
without its covering email, and often read out of order. It has to work
alone.

## Rules

1. **Page one stands alone.** Who this is from, what it is about, who it
   is for, and the date. A page that arrives forwarded, with no email
   around it, must still make sense.
2. **Write in pages, not in flow.** Say where each page breaks and what
   is on it. A document written as one river of text lands with a heading
   alone at the foot of a page and its table overleaf.
3. **A page has one job.** One product, one argument, one comparison. Two
   subjects on a page means neither gets read.
4. **Tables for anything compared.** Specifications, options, prices and
   timelines are tables with named columns and units in the header, never
   prose. Give every table a caption that says what it shows.
5. **Numbers carry units and currency.** Every figure: unit, currency,
   and the basis (per piece, per m², ex-works, inclusive of GST).
6. **Say what is not included.** For anything that quotes, scopes or
   promises: an explicit exclusions or assumptions block. This is the
   paragraph that prevents the argument later.
7. **Validity and version.** A price, a specification or a proposal
   carries a date and how long it stands. A document with no date is
   quoted back at you two years later.
8. **Contact and next step on the last page.** Who to reply to, how, and
   what happens next.
9. **No live-document habits.** No "click here", no "see the section
   above", no hover states. Refer to pages by number and headings by name.

## Shape

Mark every page explicitly:

```
PAGE 1 — Cover
  Title, one-line subtitle, client name, date, your company and contact.
PAGE 2 — What this is
  ...
TABLE (page 4): "Grade comparison — IS 2062 E250 vs E350"
  | Property | E250 | E350 | Unit |
```

Typical lengths: one-pager 1 page; datasheet 2; brochure 4 to 8;
proposal 6 to 12. State the page count at the top and keep to it.

## Quality checklist

- Page 1 names the sender, the subject, the recipient and the date.
- Every page is marked and has one subject.
- Every compared set of values is a table with units in the header.
- Every price or specification carries its basis, currency and validity.
- There is an exclusions or assumptions block wherever something is
  promised or priced.
- The last page says who to contact and what happens next.
- No screen-only language and no unresolved placeholder.

## Non-goals

Do not choose fonts, colours or layout grids unless art direction was
asked for — a later step or a design tool does that from this structure.
Do not invent a figure to fill a table: leave the cell marked "to be
confirmed" and list it in the assumptions block.
