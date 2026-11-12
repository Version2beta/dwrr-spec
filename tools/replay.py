#!/usr/bin/env python3
"""Replay the conformance corpus against a driver (PROTOCOL.md).

    python3 tools/replay.py --driver "./my-driver"
    python3 tools/replay.py --driver "mix run driver.exs" corpus/edge-cases.jsonl

Sends every case's requests to one driver process, compares each response
with the recorded one, and reports the first mismatch in each failing case.
Exits 0 when every case passes, 1 when any case fails, and 2 when the driver
itself fails. Needs only Python 3.9 or newer.
"""
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def load(paths):
    cases = []
    for path in paths:
        with open(path) as f:
            for number, line in enumerate(f, 1):
                if line.strip():
                    case = json.loads(line)
                    case["_source"] = f"{path.name}:{number}"
                    cases.append(case)
    return cases


def main():
    parser = argparse.ArgumentParser(description="Replay the dwrr conformance corpus against a driver.")
    parser.add_argument("--driver", required=True, help="command that starts the driver")
    parser.add_argument("files", nargs="*", type=Path, help="corpus files (default: corpus/*.jsonl)")
    parser.add_argument("--show", type=int, default=5, help="failing cases to show in detail (default 5)")
    args = parser.parse_args()

    files = args.files or sorted(CORPUS.glob("*.jsonl"))
    if not files:
        sys.exit(f"no corpus files found in {CORPUS}")
    cases = load(files)
    requests = [step["request"] for case in cases for step in case["steps"]]
    stdin = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in requests)

    process = subprocess.run(shlex.split(args.driver), input=stdin, capture_output=True, text=True)
    lines = process.stdout.splitlines()
    if process.returncode != 0 or len(lines) != len(requests):
        print(f"driver failed: exit status {process.returncode}, "
              f"{len(lines)} responses for {len(requests)} requests", file=sys.stderr)
        print(process.stderr[-4000:], file=sys.stderr)
        sys.exit(2)

    position, failures = 0, []
    for case in cases:
        first = None
        for index, step in enumerate(case["steps"]):
            try:
                got = json.loads(lines[position])
            except json.JSONDecodeError:
                got = {"unparseable": lines[position]}
            position += 1
            if first is None and got != step["response"]:
                first = (index, step, got)
        if first:
            failures.append((case, first))

    steps = len(requests)
    if not failures:
        print(f"PASS: {len(cases)} cases, {steps} steps, {len(files)} files")
        return
    print(f"FAIL: {len(failures)} of {len(cases)} cases ({steps} steps, {len(files)} files)")
    for case, (index, step, got) in failures[:args.show]:
        print(f"\n{case['name']}  ({case['_source']}, step {index + 1})")
        if case.get("description"):
            print(f"  {case['description']}")
        print(f"  request:  {json.dumps(step['request'])}")
        print(f"  expected: {json.dumps(step['response'])}")
        print(f"  got:      {json.dumps(got)}")
    if len(failures) > args.show:
        print(f"\n…and {len(failures) - args.show} more failing cases")
    sys.exit(1)


if __name__ == "__main__":
    main()
