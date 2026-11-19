#!/usr/bin/env python3
"""Check a driver's protocol behavior that corpus replay can't see (PROTOCOL.md).

    python3 tools/check_driver.py --driver "./my-driver"

1. Interactive: sends one request at a time and waits for each response before
   sending the next, so a driver that doesn't flush after every response
   stalls and fails.
2. End of input: the driver exits with status 0.
3. Protocol errors (§3.1): for each kind, the driver must exit with status 2,
   write no response for the bad line, and keep the responses it already wrote.

Exits 0 when every check passes, 1 otherwise. Needs only Python 3.9 or newer,
on a system where pipes can be read from a background thread (all common ones).
"""
import argparse
import json
import os
import queue
import shlex
import subprocess
import sys
import threading

TIMEOUT = 10  # seconds to wait for any single response or exit

# Drivers run without PYTHONUNBUFFERED, which would hide a missing flush in a Python driver.
DRIVER_ENV = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}

NEW = '{"op":"new","count":2}'
OK_NULL = {"ok": None}

# Request, expected response. Sent one at a time, each answered before the next.
INTERACTIVE = [
    (NEW, OK_NULL),
    ('{"op":"set_quantum","queue":0,"quantum":"2"}', OK_NULL),
    ('{"op":"set_quantum","queue":1,"quantum":"3"}', OK_NULL),
    ('{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"2"},{"value":2,"cost":"2"}]}', OK_NULL),
    ('{"op":"enqueue","queue":1,"items":[{"value":3,"cost":"4"},{"value":4,"cost":"1"}]}', OK_NULL),
    ('{"op":"take","n":1,"ignored":"extra fields are ignored"}',
     {"ok": [{"queue": 0, "value": 1, "cost": "2"}]}),
    ('{"op":"enqueue","queue":0,"items":[{"value":5,"cost":"0"}]}', {"error": "zero_cost"}),
    ('{"op":"enqueue","queue":0,"items":[{"value":5,"cost":"18446744073709551615"}]}',
     {"error": "cost_too_large"}),
    ('{"op":"enqueue","queue":7,"items":[]}', {"error": "invalid_index"}),
    ('{"op":"take","n":-1}', {"error": "negative_take"}),
    ('  {"op":"add_queue"}  ', {"ok": 2}),
    ('{"op":"take","n":10}', {"ok": [{"queue": 0, "value": 2, "cost": "2"},
                                     {"queue": 1, "value": 3, "cost": "4"},
                                     {"queue": 1, "value": 4, "cost": "1"}]}),
    ('{"op":"remove_head","queue":0}', OK_NULL),
    ('{"op":"drain_queue","queue":1}', {"ok": []}),
    ('{"op":"remove_queue"}', OK_NULL),
    (NEW, OK_NULL),
    ('{"op":"take","n":1}', {"ok": []}),
]

# Corrections beyond the recorded (signed-32-bit) corpus domain. Keep these in
# the interactive history so continuations also exercise adapter bookkeeping.
BIG = 2**80
INTERACTIVE += [
    ('{"op":"new","count":2,"n":"ignored","queue":{},"items":false,"quantum":[]}', OK_NULL),
    ('{"op":"set_quantum","queue":0,"quantum":"2","count":false,"n":{}}', OK_NULL),
    ('{"op":"enqueue","queue":0,"items":[{"value":%d,"cost":"1","n":false}]}' % BIG, OK_NULL),
    ('{"op":"enqueue","queue":1,"items":[{"value":%d,"cost":"1"}]}' % -BIG, OK_NULL),
    ('{"op":"remove_head","queue":%d}' % BIG, {"error": "invalid_index"}),
    ('{"op":"drain_queue","queue":%d}' % -BIG, {"error": "invalid_index"}),
    ('{"op":"enqueue","queue":%d,"items":[{"value":1,"cost":"0"}]}' % BIG,
     {"error": "invalid_index"}),
    ('{"op":"set_quantum","queue":%d,"quantum":"0"}' % BIG, {"error": "invalid_index"}),
    ('{"op":"take","n":%d}' % -BIG, {"error": "negative_take"}),
    ('{"op":"take","n":%d,"count":{},"items":"ignored"}' % BIG,
     {"ok": [{"queue": 0, "value": BIG, "cost": "1"},
             {"queue": 1, "value": -BIG, "cost": "1"}]}),
    ('{"op":"take","n":%d}' % BIG, {"ok": []}),
    ('{"op":"enqueue","queue":0,"items":[{"value":%d,"cost":"1"}]}' % BIG, OK_NULL),
    ('{"op":"remove_head","queue":0,"n":false}', {"ok": {"value": BIG, "cost": "1"}}),
    ('{"op":"enqueue","queue":1,"items":[{"value":%d,"cost":"1"}]}' % -BIG, OK_NULL),
    ('{"op":"drain_queue","queue":1,"quantum":false}', {"ok": [{"value": -BIG, "cost": "1"}]}),
    ('{"op":"enqueue","queue":1,"items":[{"value":1,"cost":"1"}]}', OK_NULL),
    ('{"op":"remove_queue","queue":false,"count":[]}', OK_NULL),
    ('{"op":"take","n":%d}' % BIG, {"ok": []}),
    ('{"op":"add_queue","n":false,"items":{}}', {"ok": 1}),
    ('{"op":"enqueue","queue":1,"items":[{"value":7,"cost":"1"}]}', OK_NULL),
    ('{"op":"new","count":0,"quantum":{}}', OK_NULL),
    ('{"op":"take","n":%d}' % BIG, {"ok": []}),
]

# Name, the bad line. Each is sent after NEW, followed by a valid request that
# must never be answered.
PROTOCOL_ERRORS = [
    ("blank line", ""),
    ("whitespace-only line", "   "),
    ("not JSON", "hello"),
    ("JSON array", "[1,2]"),
    ("JSON string", '"take"'),
    ("missing op", "{}"),
    ("unknown op", '{"op":"frobnicate"}'),
    ("new without count", '{"op":"new"}'),
    ("new with negative count", '{"op":"new","count":-1}'),
    ("new with fractional count", '{"op":"new","count":2.5}'),
    ("enqueue without items", '{"op":"enqueue","queue":0}'),
    ("enqueue without queue", '{"op":"enqueue","items":[]}'),
    ("enqueue items not a list", '{"op":"enqueue","queue":0,"items":{}}'),
    ("enqueue item not an object", '{"op":"enqueue","queue":0,"items":[5]}'),
    ("item without value", '{"op":"enqueue","queue":0,"items":[{"cost":"1"}]}'),
    ("item without cost", '{"op":"enqueue","queue":0,"items":[{"value":1}]}'),
    ("fractional value", '{"op":"enqueue","queue":0,"items":[{"value":1.5,"cost":"1"}]}'),
    ("cost as a number", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":5}]}'),
    ("cost with a leading zero", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"05"}]}'),
    ("cost with a sign", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"+5"}]}'),
    ("cost with a space", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":" 5"}]}'),
    ("cost with a decimal point", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"5.0"}]}'),
    ("empty cost", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":""}]}'),
    ("cost above 2^64-1", '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"18446744073709551616"}]}'),
    ("queue as a string", '{"op":"enqueue","queue":"0","items":[]}'),
    ("malformed cost on an invalid queue (protocol check comes first)",
     '{"op":"enqueue","queue":99,"items":[{"value":1,"cost":"x"}]}'),
    ("set_quantum without quantum", '{"op":"set_quantum","queue":0}'),
    ("quantum with leading zeros", '{"op":"set_quantum","queue":0,"quantum":"007"}'),
    ("malformed quantum on an invalid queue", '{"op":"set_quantum","queue":-5,"quantum":"-1"}'),
    ("take without n", '{"op":"take"}'),
    ("n as a string", '{"op":"take","n":"3"}'),
    ("n as a boolean", '{"op":"take","n":true}'),
    ("remove_head without queue", '{"op":"remove_head"}'),
    ("drain_queue with null queue", '{"op":"drain_queue","queue":null}'),
]
PROTOCOL_ERRORS += [
    ("malformed later cost after scheduler-invalid first item",
     '{"op":"enqueue","queue":0,"items":[{"value":1,"cost":"0"},{"value":2,"cost":"01"}]}'),
    ("malformed cost with huge invalid queue",
     '{"op":"enqueue","queue":%d,"items":[{"value":1,"cost":"01"}]}' % BIG),
    ("malformed quantum with huge invalid queue",
     '{"op":"set_quantum","queue":%d,"quantum":"01"}' % BIG),
    ("exponent n", '{"op":"take","n":1e0}'),
    ("boolean value", '{"op":"enqueue","queue":0,"items":[{"value":true,"cost":"1"}]}'),
]

AFTER = '{"op":"take","n":1}'


def interactive(command):
    """Send requests one at a time; each must be answered before the next is sent."""
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, bufsize=1, env=DRIVER_ENV)
    lines = queue.Queue()

    def read():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)  # end of output

    threading.Thread(target=read, daemon=True).start()
    try:
        for number, (request, expected) in enumerate(INTERACTIVE, 1):
            process.stdin.write(request + "\n")
            process.stdin.flush()
            try:
                line = lines.get(timeout=TIMEOUT)
            except queue.Empty:
                return f"request {number} got no response within {TIMEOUT}s (is stdout flushed after each response?): {request}"
            if line is None:
                return f"driver closed stdout before answering request {number}: {request}"
            try:
                got = json.loads(line)
            except json.JSONDecodeError:
                return f"request {number}: response isn't JSON: {line!r}"
            if got != expected:
                return f"request {number}: {request}\n    expected {json.dumps(expected)}\n    got      {json.dumps(got)}"
        process.stdin.close()
        try:
            status = process.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            return "driver didn't exit at end of input"
        if status != 0:
            return f"driver exited with status {status} at end of input, expected 0"
        try:
            if lines.get(timeout=TIMEOUT) is not None:
                return "driver wrote an extra line before exiting"
        except queue.Empty:
            return "driver's stdout stayed open after it exited"
        return None
    finally:
        if process.poll() is None:
            process.kill()


def protocol_error(command, bad_line, before_new=False):
    stdin = ("" if before_new else NEW + "\n") + bad_line + "\n" + AFTER + "\n"
    try:
        p = subprocess.run(command, input=stdin, capture_output=True, text=True, timeout=TIMEOUT,
                           env=DRIVER_ENV)
    except subprocess.TimeoutExpired:
        return f"driver didn't exit within {TIMEOUT}s"
    expected_lines = [] if before_new else [OK_NULL]
    got_lines = []
    for line in p.stdout.splitlines():
        try:
            got_lines.append(json.loads(line))
        except json.JSONDecodeError:
            got_lines.append(line)
    problems = []
    if p.returncode != 2:
        problems.append(f"exit status {p.returncode}, expected 2")
    if got_lines != expected_lines:
        problems.append(f"stdout {got_lines}, expected {expected_lines}")
    return "; ".join(problems) or None


def main():
    parser = argparse.ArgumentParser(description="Check a dwrr driver's protocol behavior.")
    parser.add_argument("--driver", required=True, help="command that starts the driver")
    args = parser.parse_args()
    command = shlex.split(args.driver)

    results = [("interactive requests, flushing and exit status 0 at end of input", interactive(command)),
               ("protocol error: request before the first new",
                protocol_error(command, '{"op":"take","n":1}', before_new=True))]
    for name, line in PROTOCOL_ERRORS:
        results.append((f"protocol error: {name}", protocol_error(command, line)))

    failures = [(name, problem) for name, problem in results if problem]
    for name, problem in results:
        print(f"{'FAIL' if problem else 'ok  '}  {name}")
        if problem:
            print(f"      {problem}")
    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(results) - len(failures)} of {len(results)} checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
