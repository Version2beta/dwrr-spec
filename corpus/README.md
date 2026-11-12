# Conformance corpus

Recorded cases for checking a dwrr implementation against `SPEC.md`. The format and how to replay it are in `PROTOCOL.md`.

| File | Cases | Steps |
|---|---|---|
| `examples.jsonl` | 2 | 15 |
| `edge-cases.jsonl` | 20 | 225 |
| `errors.jsonl` | 10 | 70 |
| `boundaries.jsonl` | 7 | 53 |
| `random-small.jsonl` | 1000 | 23659 |
| `random-large.jsonl` | 500 | 13933 |
| `random-skip.jsonl` | 300 | 6773 |
| **Total** | **1839** | **44728** |

## What each file covers

- `examples.jsonl`: the worked example in `SPEC.md` §10, and bandwidth shared by declared bytes.
- `edge-cases.jsonl`: one case per rule in §5: paused visits, items joining a visit, blocked heads, weight changes, head removal, draining, queue removal and the cursor, added queues, and credit reset.
- `errors.jsonl`: every error code, the order errors are reported in, atomic batches, and errors leaving the state unchanged.
- `boundaries.jsonl`: costs and quanta at the limits, credit reaching its maximum of 2⁶⁴ − 3, and long runs of idle rounds that an implementation must skip exactly.
- `random-small.jsonl`: random sequences of every operation, including invalid ones, with quanta 1–8 and costs 1–32.
- `random-large.jsonl`: random sequences with quanta of at least 2⁶² and costs up to and beyond `MAX_COST`.
- `random-skip.jsonl`: random sequences with small quanta and costs up to 5,000, so idle rounds are common.

## Provenance

- Responses were recorded from `github.com/version2beta/dwrr` v0.10.1 through `drivers/go`.
- Every response was checked against `tools/spec_model.py`, the executable form of `SPEC.md`, computing idle rounds directly. All but 4 cases were also checked against the model stepping through every round; those 4 are the huge-skip cases in `boundaries.jsonl`, which would take about 2⁶³ rounds step by step.
- A response is only recorded when all of these agree.
- Random seeds: `random-small` 20261112, `random-large` 20261113, `random-skip` 20261114.
- Generated 2026-11-12 by `tools/gen_corpus.py`. Regenerating with the same seeds and library version reproduces these files exactly.
