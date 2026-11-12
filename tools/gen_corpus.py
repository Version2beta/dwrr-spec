#!/usr/bin/env python3
"""Generate the conformance corpus.

    python3 tools/gen_corpus.py --go-driver ./dwrr-driver

Builds every case's requests (hand-written edge cases plus seeded random
sequences), records the responses of the Go implementation through its
driver, and checks every response against tools/spec_model.py. It writes
nothing unless every response agrees:

- with the executable spec computing idle rounds directly (--fast), for every case;
- with the executable spec stepping through every round, for every case where
  that finishes quickly (all but the few huge-skip cases, marked below).

Output: corpus/*.jsonl and corpus/README.md.
"""
import argparse
import json
import random
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from spec_model import MAX_COST, MAX_QUANTUM, handle  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
U64_MAX = 2**64 - 1
SEEDS = {"random-small": 20261112, "random-large": 20261113, "random-skip": 20261114}


class Case:
    """Builds one case's requests. Item values are numbered 1, 2, 3, … within the case."""

    def __init__(self, name, description, count, naive=True):
        self.name, self.description, self.naive = name, description, naive
        self.requests = [{"op": "new", "count": count}]
        self.next_value = 1

    def enqueue(self, queue, *costs):
        items = []
        for cost in costs:
            items.append({"value": self.next_value, "cost": str(cost)})
            self.next_value += 1
        self.requests.append({"op": "enqueue", "queue": queue, "items": items})
        return self

    def quantum(self, queue, quantum):
        self.requests.append({"op": "set_quantum", "queue": queue, "quantum": str(quantum)})
        return self

    def take(self, n):
        self.requests.append({"op": "take", "n": n})
        return self

    def add(self):
        self.requests.append({"op": "add_queue"})
        return self

    def remove(self):
        self.requests.append({"op": "remove_queue"})
        return self

    def head(self, queue):
        self.requests.append({"op": "remove_head", "queue": queue})
        return self

    def drain(self, queue):
        self.requests.append({"op": "drain_queue", "queue": queue})
        return self


def examples():
    c = Case("example/spec-section-10", "The worked example in SPEC.md §10.", 2)
    c.quantum(0, 2).quantum(1, 3).enqueue(0, 2, 2).enqueue(1, 4, 1).take(10)
    yield c
    c = Case("example/bytes-by-weight", "Three queues sharing by declared bytes, one weighted double.", 3)
    c.quantum(0, 1500).quantum(1, 3000).quantum(2, 1500)
    sizes = [200, 1400, 900, 64, 1500, 700]
    for q in range(3):
        c.enqueue(q, *[sizes[(i + q) % len(sizes)] for i in range(40)])
    c.take(60).take(60)
    yield c


def edge_cases():
    E = "edge/"
    yield Case(E + "empty-scheduler", "Operations on a scheduler with no queues.", 0) \
        .take(1).take(0).remove().add().take(1).remove().remove().take(3)
    yield Case(E + "take-zero-keeps-paused-visit",
               "take(0) changes nothing, and a paused visit resumes without another quantum.", 2) \
        .quantum(0, 3).enqueue(0, 1, 1, 1, 1).enqueue(1, 1).take(1).take(0).take(1).take(1).take(5)
    yield Case(E + "take-limit-is-not-a-fairness-cap",
               "Taking one item at a time gives the same order as one large take.", 3) \
        .quantum(0, 2).quantum(1, 5).quantum(2, 3) \
        .enqueue(0, 1, 2, 1, 1).enqueue(1, 3, 3, 1).enqueue(2, 2, 2, 2) \
        .take(1).take(1).take(1).take(1).take(1).take(1).take(1).take(1).take(1).take(1).take(1)
    yield Case(E + "enqueue-joins-active-visit",
               "Items added to the queue being visited join that visit without another quantum.", 2) \
        .quantum(0, 4).enqueue(0, 1, 1).enqueue(1, 1).take(1).enqueue(0, 2).take(3).take(2)
    yield Case(E + "blocked-head-carries-credit",
               "A head costing more than one quantum waits, carrying credit, while others are served.", 2) \
        .quantum(0, 3).quantum(1, 3).enqueue(0, 5, 1).enqueue(1, 1, 1, 1, 1, 1, 1).take(20)
    yield Case(E + "blocked-head-blocks-later-items",
               "An unaffordable head ends the visit even if later items are cheap.", 2) \
        .quantum(0, 2).enqueue(0, 3, 1, 1).enqueue(1, 1, 1, 1).take(4).take(10)
    c = Case(E + "set-quantum-keeps-credit",
             "Changing a queue's weight every round keeps its credit, so its large head is eventually served.", 2)
    c.enqueue(0, 10).enqueue(1, *([1] * 40))
    for i in range(30):
        c.quantum(0, 3 + i % 2).take(1)
    yield c
    yield Case(E + "set-quantum-during-paused-visit",
               "A new quantum applies at the next grant, not when a paused visit resumes.", 2) \
        .quantum(0, 3).enqueue(0, 1, 1, 1, 1, 1).enqueue(1, 1, 1).take(1).quantum(0, 1).take(2).take(10)
    yield Case(E + "set-quantum-same-value", "Setting the current quantum changes nothing.", 2) \
        .quantum(0, 2).enqueue(0, 1, 1, 1).enqueue(1, 1).take(1).quantum(0, 2).take(10)
    yield Case(E + "remove-head-keeps-visit",
               "Removing a head that leaves items behind keeps credit and the visit.", 2) \
        .quantum(0, 5).enqueue(0, 1, 1, 1, 1).enqueue(1, 1).take(1).head(0).take(2).take(5)
    yield Case(E + "remove-head-empties-active-queue",
               "Removing the last item of the queue being visited resets its credit and closes the visit.", 3) \
        .quantum(0, 5).enqueue(0, 1, 1).enqueue(1, 1).enqueue(2, 1).take(1).head(0).take(5).head(0)
    yield Case(E + "remove-head-exposes-cheaper-head",
               "Credit saved for an expensive head is spent on the cheaper item behind it once the head is removed.", 2) \
        .quantum(0, 4).enqueue(0, 10, 1, 1, 1).enqueue(1, 1).take(1).head(0).take(10)
    yield Case(E + "drain-active-queue",
               "Draining the queue being visited returns its items, resets its credit and closes the visit.", 3) \
        .quantum(0, 5).enqueue(0, 1, 1, 1).enqueue(1, 1).enqueue(2, 1).take(1).drain(0).take(5).drain(0)
    yield Case(E + "drain-inactive-queue", "Draining a queue that isn't being visited.", 2) \
        .quantum(1, 2).enqueue(0, 1, 1).enqueue(1, 3, 1).take(1).drain(1).take(5)
    yield Case(E + "remove-active-last-queue",
               "Removing the last queue while it's being visited sends the cursor to 0.", 3) \
        .quantum(2, 5).enqueue(0, 1).enqueue(1, 1).enqueue(2, 1, 1, 1).take(3).remove().take(5)
    yield Case(E + "remove-queue-wraps-cursor",
               "Removing queues past the cursor keeps the cursor in range.", 4) \
        .enqueue(0, 1).enqueue(1, 1).enqueue(2, 1).enqueue(3, 1, 1).take(3).remove().remove().take(5)
    yield Case(E + "remove-all-then-add", "Removing every queue, then adding new ones.", 2) \
        .enqueue(0, 1).enqueue(1, 1).take(1).remove().remove().take(1).add().add().enqueue(1, 2).enqueue(0, 1).take(3)
    yield Case(E + "add-queue-during-visit",
               "Adding a queue doesn't affect a visit in progress; the new queue joins the next round.", 2) \
        .quantum(0, 3).enqueue(0, 1, 1, 1, 1).enqueue(1, 1).take(1).add().enqueue(2, 1, 1).take(10)
    yield Case(E + "empty-queue-loses-credit", "A queue that empties loses its credit.", 2) \
        .quantum(0, 10).enqueue(0, 1).enqueue(1, 1).take(2).enqueue(0, 5, 5).enqueue(1, 1).take(10)
    yield Case(E + "sustained-backlog-shares", "Two backlogged queues with quanta 1 and 3 and unit costs.", 2) \
        .quantum(1, 3).enqueue(0, *([1] * 30)).enqueue(1, *([1] * 90)).take(40).take(40)


def error_cases():
    E = "errors/"
    yield Case(E + "enqueue-invalid-index", "Queue indexes below 0 and at N are invalid.", 2) \
        .enqueue(-1, 1).enqueue(2, 1).enqueue(0, 1).take(5)
    yield Case(E + "enqueue-index-before-cost", "An invalid index is reported before an invalid cost.", 1) \
        .enqueue(5, 0).enqueue(-1, MAX_COST + 1).take(1)
    yield Case(E + "enqueue-batch-is-atomic",
               "A batch with one invalid item appends nothing, and the first invalid item decides the error.", 1) \
        .enqueue(0, 1, 0).enqueue(0, MAX_COST + 1, 0).enqueue(0, 0, MAX_COST + 1).enqueue(0, 1, U64_MAX).take(5)
    yield Case(E + "enqueue-empty-batch", "An empty batch is valid and changes nothing.", 1) \
        .enqueue(0).take(1).enqueue(0, 1).enqueue(0).take(1)
    yield Case(E + "cost-limits", "MAX_COST is accepted; anything larger is rejected.", 1) \
        .quantum(0, MAX_QUANTUM).enqueue(0, MAX_COST).enqueue(0, MAX_COST + 1).enqueue(0, U64_MAX).take(5)
    yield Case(E + "set-quantum-errors",
               "Index first, then zero, then too large; MAX_QUANTUM is accepted.", 1) \
        .quantum(1, 0).quantum(-1, MAX_QUANTUM + 1).quantum(0, 0).quantum(0, MAX_QUANTUM + 1) \
        .quantum(0, U64_MAX).quantum(0, MAX_QUANTUM).enqueue(0, MAX_COST, 1).take(5)
    yield Case(E + "rejected-quantum-keeps-old-quantum", "A rejected quantum leaves the previous one in place.", 2) \
        .quantum(0, 4).quantum(0, 0).quantum(0, MAX_QUANTUM + 1) \
        .enqueue(0, 1, 1, 1, 1, 1).enqueue(1, 1, 1).take(10)
    yield Case(E + "remove-head-and-drain-invalid-index", "remove_head and drain_queue check the index.", 1) \
        .head(1).head(-1).drain(1).drain(-1).enqueue(0, 1).head(0).head(0).drain(0)
    yield Case(E + "negative-take", "A negative take is an error and changes nothing.", 1) \
        .enqueue(0, 1, 1).take(-1).take(-100).take(5)
    yield Case(E + "errors-change-nothing", "Every kind of error leaves the state unchanged.", 2) \
        .quantum(0, 3).enqueue(0, 1, 1, 1, 1).enqueue(1, 1, 1).take(1) \
        .enqueue(9, 1).enqueue(0, 0).quantum(0, 0).quantum(9, 1).head(9).drain(9).take(-1).take(10)


def boundary_cases():
    B = "boundary/"
    yield Case(B + "max-cost-max-quantum", "Items costing MAX_COST with quantum MAX_QUANTUM.", 2) \
        .quantum(0, MAX_QUANTUM).quantum(1, MAX_QUANTUM) \
        .enqueue(0, MAX_COST, MAX_COST, 1).enqueue(1, 1, MAX_COST).take(10)
    yield Case(B + "peak-credit-after-reweight",
               "Credit reaches MAX_COST - 1 + MAX_QUANTUM = 2^64 - 3, and results stay exact.", 2) \
        .quantum(0, MAX_COST - 1).enqueue(0, MAX_COST, 1, 1, MAX_COST).enqueue(1, 1).take(1) \
        .quantum(0, MAX_QUANTUM).head(0).take(1).take(5)
    yield Case(B + "near-max-quanta", "Quanta just below the limit accumulate exactly.", 3) \
        .quantum(0, MAX_QUANTUM - 1).quantum(1, MAX_QUANTUM - 2).quantum(2, MAX_QUANTUM) \
        .enqueue(0, MAX_COST, MAX_COST - 1).enqueue(1, MAX_COST, 2).enqueue(2, MAX_COST, MAX_COST).take(10)
    yield Case(B + "huge-skip-quantum-one",
               "Costs near MAX_COST with quantum 1: the idle rounds must be skipped exactly.", 3, naive=False) \
        .enqueue(0, MAX_COST).enqueue(1, MAX_COST - 1).enqueue(2, MAX_COST - 2).take(3)
    yield Case(B + "huge-skip-mixed-quanta",
               "Large costs with small, different quanta: the queue needing fewest rounds is served first.", 3,
               naive=False) \
        .quantum(0, 3).quantum(1, 7).quantum(2, 5).enqueue(0, 2**62).enqueue(1, 2**62 + 1).enqueue(2, 2**61) \
        .take(1).take(1).take(1)
    yield Case(B + "huge-skip-ties",
               "Queues that become eligible in the same round are served in cursor order.", 3, naive=False) \
        .quantum(0, 2).quantum(1, 2).quantum(2, 2).enqueue(0, 2**40).enqueue(1, 2**40).enqueue(2, 2**40 - 1).take(3)
    yield Case(B + "huge-skip-after-paused-visit",
               "Skipping idle rounds after a paused visit, with credit already held.", 2, naive=False) \
        .quantum(0, 2).enqueue(0, 1, 1, 2**50).enqueue(1, 2**50 - 3).take(1).take(1).take(2)


def random_cases(name, seed, count, mode):
    """Random sequences of every operation, including errors.

    small: quanta 1-8, costs 1-32.
    large: quanta >= 2^62 (so the step-by-step model stays fast), costs up to and past MAX_COST.
    skip:  quanta 1-3, costs up to 5,000, so idle rounds are common and long.
    """
    rng = random.Random(seed)
    for number in range(count):
        n = rng.randint(0, 5)
        c = Case(f"{name}/{number:04d}", "", n)
        queues = n

        def big_quanta(lo, hi):
            if mode == "large":
                for q in range(lo, hi):
                    c.quantum(q, MAX_QUANTUM - rng.randrange(2**62))

        def quantum():
            r = rng.random()
            if r < 0.05:
                return 0
            if r < 0.10:
                return MAX_QUANTUM + rng.randint(1, 2**63)
            if mode == "large":
                return MAX_QUANTUM - rng.randrange(2**62)
            return rng.randint(1, 3 if mode == "skip" else 8)

        def cost():
            r = rng.random()
            if r < 0.04:
                return 0
            if r < 0.08:
                return MAX_COST + rng.randint(1, 2**63)
            if mode == "large":
                return rng.choice([rng.randint(1, 4), MAX_COST - rng.randint(0, 3), rng.randint(1, MAX_COST)])
            if mode == "skip":
                return rng.choice([rng.randint(1, 4), rng.randint(100, 5000)])
            return rng.randint(1, 32)

        def index():
            if rng.random() < 0.1 or queues == 0:
                return rng.randint(-1, queues)
            return rng.randrange(queues)

        big_quanta(0, n)
        for _ in range(rng.randint(5, 40)):
            k = rng.random()
            if k < 0.30:
                c.enqueue(index(), *[cost() for _ in range(rng.randint(0, 4))])
            elif k < 0.55:
                c.take(-1 if rng.random() < 0.03 else rng.randint(0, 6))
            elif k < 0.67:
                c.quantum(index(), quantum())
            elif k < 0.77:
                c.head(index())
            elif k < 0.83:
                c.drain(index())
            elif k < 0.92:
                c.add()
                queues += 1
                big_quanta(queues - 1, queues)
            else:
                c.remove()
                queues = max(0, queues - 1)
        yield c


def go_responses(driver, cases):
    stdin = "".join(json.dumps(r, separators=(",", ":")) + "\n" for c in cases for r in c.requests)
    p = subprocess.run([driver], input=stdin, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"Go driver failed:\n{p.stderr[-4000:]}")
    lines = p.stdout.splitlines()
    out, i = [], 0
    for c in cases:
        out.append([json.loads(line) for line in lines[i:i + len(c.requests)]])
        i += len(c.requests)
    if i != len(lines):
        sys.exit(f"Go driver returned {len(lines)} responses for {i} requests")
    return out


def model_responses(case, fast):
    scheduler, out = None, []
    for request in case.requests:
        scheduler, response = handle(scheduler, request, fast)
        out.append(response)
    return out


def main():
    parser = argparse.ArgumentParser(description="Generate the dwrr conformance corpus.")
    parser.add_argument("--go-driver", required=True, help="path to the built Go driver")
    parser.add_argument("--go-version", default="v0.10.1", help="dwrr version the driver was built with")
    args = parser.parse_args()

    files = {
        "examples": list(examples()),
        "edge-cases": list(edge_cases()),
        "errors": list(error_cases()),
        "boundaries": list(boundary_cases()),
        "random-small": list(random_cases("random-small", SEEDS["random-small"], 1000, "small")),
        "random-large": list(random_cases("random-large", SEEDS["random-large"], 500, "large")),
        "random-skip": list(random_cases("random-skip", SEEDS["random-skip"], 300, "skip")),
    }

    totals = {}
    for name, cases in files.items():
        recorded = go_responses(args.go_driver, cases)
        for case, responses in zip(cases, recorded):
            checks = [("spec model, idle rounds computed", model_responses(case, fast=True))]
            if case.naive:
                checks.append(("spec model, step by step", model_responses(case, fast=False)))
            for label, expected in checks:
                for i, (got, want) in enumerate(zip(responses, expected)):
                    if got != want:
                        sys.exit(f"DISAGREEMENT in {case.name}, step {i + 1}: {case.requests[i]}\n"
                                 f"  Go:  {got}\n  {label}: {want}")
        path = ROOT / "corpus" / f"{name}.jsonl"
        path.parent.mkdir(exist_ok=True)
        with open(path, "w") as f:
            for case, responses in zip(cases, recorded):
                record = {"name": case.name}
                if case.description:
                    record["description"] = case.description
                record["steps"] = [{"request": rq, "response": rs} for rq, rs in zip(case.requests, responses)]
                f.write(json.dumps(record, separators=(",", ":")) + "\n")
        steps = sum(len(c.requests) for c in cases)
        totals[name] = (len(cases), steps, sum(1 for c in cases if not c.naive))
        print(f"{path.relative_to(ROOT)}: {len(cases)} cases, {steps} steps")

    write_readme(totals, args.go_version)


def write_readme(totals, go_version):
    rows = "\n".join(f"| `{name}.jsonl` | {cases} | {steps} |" for name, (cases, steps, _) in totals.items())
    all_cases = sum(v[0] for v in totals.values())
    all_steps = sum(v[1] for v in totals.values())
    skip_only = sum(v[2] for v in totals.values())
    text = f"""# Conformance corpus

Recorded cases for checking a dwrr implementation against `SPEC.md`. The format and how to replay it are in `PROTOCOL.md`.

| File | Cases | Steps |
|---|---|---|
{rows}
| **Total** | **{all_cases}** | **{all_steps}** |

## What each file covers

- `examples.jsonl`: the worked example in `SPEC.md` §10, and bandwidth shared by declared bytes.
- `edge-cases.jsonl`: one case per rule in §5: paused visits, items joining a visit, blocked heads, weight changes, head removal, draining, queue removal and the cursor, added queues, and credit reset.
- `errors.jsonl`: every error code, the order errors are reported in, atomic batches, and errors leaving the state unchanged.
- `boundaries.jsonl`: costs and quanta at the limits, credit reaching its maximum of 2⁶⁴ − 3, and long runs of idle rounds that an implementation must skip exactly.
- `random-small.jsonl`: random sequences of every operation, including invalid ones, with quanta 1–8 and costs 1–32.
- `random-large.jsonl`: random sequences with quanta of at least 2⁶² and costs up to and beyond `MAX_COST`.
- `random-skip.jsonl`: random sequences with small quanta and costs up to 5,000, so idle rounds are common.

## Provenance

- Responses were recorded from `github.com/version2beta/dwrr` {go_version} through `drivers/go`.
- Every response was checked against `tools/spec_model.py`, the executable form of `SPEC.md`, computing idle rounds directly. All but {skip_only} cases were also checked against the model stepping through every round; those {skip_only} are the huge-skip cases in `boundaries.jsonl`, which would take about 2⁶³ rounds step by step.
- A response is only recorded when all of these agree.
- Random seeds: {", ".join(f"`{k}` {v}" for k, v in SEEDS.items())}.
- Generated {date.today().isoformat()} by `tools/gen_corpus.py`. Regenerating with the same seeds and library version reproduces these files exactly.
"""
    (ROOT / "corpus" / "README.md").write_text(text)
    print("corpus/README.md written")


if __name__ == "__main__":
    main()
