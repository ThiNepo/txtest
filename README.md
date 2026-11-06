# txtest

Unit tests for written content.

`txtest` evaluates a text file against criteria you define with the OpenAI Decisions API. Each test produces a `PASS`, `FAIL`, or `ERROR`, with a short description and its value and threshold shown in the terminal.

## Installation

Requires Python 3.11 or later. Install from this repository:

```bash
git clone https://github.com/ThiNepo/txtest.git
cd txtest
python -m pip install .
```

Set `OPENAI_API_KEY` in your environment or create a `.env` file:

```text
OPENAI_API_KEY=your-api-key
```

`txtest` looks for `.env` in the current directory and its parents. An existing environment variable takes precedence.

## Quickstart

The repository includes a fictional library desk-reservation policy and two demonstration tests:

- [Cancellation steps](txtests/policies/01-cancellation-steps.txtest): checks whether the policy explains how to cancel a reservation.
- [Policy clarity](txtests/policies/02-policy-clarity.txtest): scores the policy against five rubric levels.

From the repository root, run:

```bash
txtest examples/reservation-policy.md --set policies
```

This evaluates [the complete policy](examples/reservation-policy.md) with every `.txtest` file in `txtests/policies/`, in filename order. Each test makes one request, sequentially, without automatic retries. A failed test or an API error does not stop the remaining tests. Results stay in the terminal.

For a demonstration of missing information, try [the incomplete policy](examples/reservation-policy-incomplete.md):

```bash
txtest examples/reservation-policy-incomplete.md --set policies
```

Its cancellation procedure is deliberately missing, so the cancellation test is intended to produce `FAIL`. Scores and probabilities are model judgments and may vary between runs; these examples do not prescribe fixed output values.

The module entry point works too:

```bash
python -m txtest examples/reservation-policy.md --set policies
```

## Writing tests

Keep each test in `txtests/<set>/<name>.txtest`. Sets are resolved from the current directory, and the input is one UTF-8 text file.

A test contains YAML frontmatter followed by Jinja templates in `<system>` and `<user>` blocks. For example:

```text
---
description: Explains how to cancel a reservation.
type: predicate
min_probability: 0.5
---
<system>
Does the policy give the reader a concrete procedure for cancelling a reservation?
</system>

<user>
{{ text }}
</user>
```

`description` is required and appears beside the result so the reader can understand what was checked. The `<system>` block becomes the question instructions; the rendered `<user>` block becomes the text evaluated by that question.

The templates have three variables:

| Variable | Value |
| --- | --- |
| `text` | The full contents of the input file. |
| `filename` | The input file's name. |
| `path` | The input path provided to the command. |

An undefined Jinja variable produces a test error before a request is made.

### Predicate tests

Use `type: predicate` for a yes/no condition. The result is the model's estimated probability that the condition is true, from `0` to `1`. The test passes when the probability is at least `min_probability`, which defaults to `0.5`. Probabilities and their thresholds appear as percentages in the terminal.

### Score tests

Use `type: score` for a rubric with exactly five levels, ordered from lowest to highest. Each entry in `levels` needs a unique string `label` and a nonempty `description`. See the complete [policy clarity test](txtests/policies/02-policy-clarity.txtest) for a concrete rubric.

The result uses a **1–5 scale**: the API's zero-based score is shifted by one. Fractional scores are preserved and compared with `min_score`, which defaults to `4`, without rounding first. A score equal to the minimum passes. Each test passes or fails independently.

`score` is the default type when `type` is omitted. Predicate tests use `min_probability`; score tests use `min_score` and `levels`.

The accepted frontmatter fields are `description`, `type`, `min_probability`, `min_score`, `levels`, and `model`. This implementation uses `gpt-6-luna` by default and accepts that same value if `model` is explicitly set.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | All tests passed. |
| `1` | At least one test failed, with no execution errors. |
| `2` | A configuration, input, API, or response error occurred. |

A model refusal is an error. An empty or missing test set is also an error.

## Development

Run the offline test suite with:

```bash
python -m unittest discover -s tests -v
```

## License

Apache-2.0. See [LICENSE](LICENSE).
