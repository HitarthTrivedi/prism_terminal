---
title: Documentation
description: A user guide, manual, SOP, runbook, README or API reference — written so someone can do the task without asking anyone.
stages: [content, development]
triggers: [documentation, docs, document the, document how, documenting, user guide, user manual, manual, readme, sop, standard operating procedure, runbook, handbook, api reference, api docs, how-to, installation guide, troubleshooting]
transport: [browser, api]
budget: 3400
version: 1
---

## The job

Documentation is read by someone who is stuck, in a hurry, and does not
want to read. They are looking for the one line that unblocks them. Every
decision below follows from that.

## Rules

1. **Task titles, not feature titles.** "Add a second sending address",
   not "Email settings". People search for what they are trying to do.
2. **Numbered steps, one action each.** A step containing "and" is two
   steps. Number them so a colleague can say "I'm stuck on step 4".
3. **Say what they will see.** After a step that produces a result, say
   what appears: the dialog, the message, the file that lands. That is
   how a reader knows they are still on the rails.
4. **Prerequisites before step 1.** What must be true or installed or
   licensed first, stated before they start, not discovered at step 6.
5. **Exact strings.** Menu names, button labels, file paths, commands and
   settings are quoted exactly as they appear, in code formatting. Never
   paraphrase a label.
6. **Every command is complete and runnable.** No `...`, no `<your value
   here>` without a line saying what to put there and where to find it.
7. **Failure gets its own section.** The three or four things that
   actually go wrong, each with the symptom the reader sees first, then
   the cause, then the fix. Symptom first: that is what they have.
8. **No marketing.** "Powerful", "seamless" and "simply" do not help
   someone who is stuck. Drop them. Especially drop "simply".
9. **Write for the version in front of you.** Where behaviour differs by
   platform or version, say which, rather than describing an average.

## Shape

```
# <Task or component>
One or two lines: what this is for, and who needs it.

## Before you start
Prerequisites, permissions, versions, anything that must already exist.

## Steps
1. Action. → What you see.
2. Action. → What you see.

## Checking it worked
The observable result. How the reader knows they are done.

## When it goes wrong
**Symptom** — cause, then fix.

## Reference
Settings, fields, parameters, flags: a table of name, meaning, default.
```

An API reference replaces Steps with one block per endpoint or function:
signature, parameters table, return value, errors, one worked example.

## Quality checklist

- Every heading names a task or a thing, and someone scanning the
  headings alone can find their problem.
- Steps are numbered, single-action, and say what the reader will see.
- Prerequisites appear before the first step.
- Every command, path, label and setting is exact and in code formatting.
- There is a troubleshooting section with at least three real symptoms.
- No "simply", "just", "easy", "powerful" or "seamless" anywhere.
- Nothing is left as a placeholder or marked to be filled in later.

## Non-goals

Do not write a tutorial narrative ("now that we understand the basics,
let's explore…") — the reader is not on a journey, they are stuck. Do not
explain the architecture in a how-to; link to it. Do not document what
you did not verify: if you cannot see the behaviour, say it is unverified
rather than describing what it probably does.
