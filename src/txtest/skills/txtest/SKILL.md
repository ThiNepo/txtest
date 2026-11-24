---
name: txtest
description: Create, edit, and run .txtest checks for written content. Use when a project asks for text evaluation with txtest, including selecting conditional blocks for a reading.
---

# txtest

Run `txtest FILE --set NAME` from the project root containing `txtests/NAME/`.
The command reads one UTF-8 text file and runs every `.txtest` in that set in
filename order. It needs `OPENAI_API_KEY` in the environment or a `.env` file.

## Write a check

Use one concrete criterion per file in `txtests/<set>/<name>.txtest`. The short
`description` appears in the results table. Put the evaluation instructions
in `<system>` and the evidence in `<user>`. Both blocks support Jinja with
`text`, `filename`, and `path`.

```text
---
description: Refund instructions give readers a deadline and a contact channel.
type: predicate
min_probability: 0.5
---
<system>
Does the refund policy state both the deadline for requesting a refund and
where the reader should submit that request?
</system>
<user>
{{ text }}
</user>
```

Use `predicate` for a yes/no condition. `min_probability` defaults to `0.5`.
Use `score` for graded criteria. Supply exactly five ordered `levels` from
lowest to highest, each with a unique string `label` and a concrete
`description`. `min_score` defaults to `4` on the 1–5 scale. Include examples
when they clarify how to distinguish similar cases.

## Select a reading

Write standalone `[TYPE VALUE]` and `[endTYPE]` markers around conditional
content. Run with `--block TYPE:VALUE` to keep shared text and the selected
block bodies. For a C++ reading, use:

```bash
txtest lesson.md --set lessons --block language:cpp
```

Repeat `--block` to filter more types or retain multiple values for a type.
To evaluate languages independently, run one command per language. With no
`--block` options, the full input is evaluated.

## Interpret results

Exit code `0` means all checks passed, `1` means a check failed, and `2` means
an input, configuration, or API error occurred. Inspect the row descriptions
and reported values to identify what needs review. Treat predicate values as
estimated probabilities and score values as judgments against the rubric.
