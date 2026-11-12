# dwrr conformance protocol

**Version:** 0.1.0 (draft)

How a dwrr implementation is driven by the conformance tools. Each implementation provides a small **driver** program, and the tools send it operations and compare its results with the expected ones. This document defines the driver's input and output, and the format of the conformance corpus. The behavior being checked is defined in `SPEC.md`.

## 1. Driver

A driver is a program that wraps one implementation.

- It reads **requests** from standard input, one JSON object per line, UTF-8.
- For each request, it writes exactly one **response** to standard output: one JSON object on one line, followed by a newline.
- It flushes standard output after every response, because the tools may wait for each response before sending the next request.
- It writes nothing else to standard output. Diagnostics go to standard error.
- At end of input, it exits with status 0.
- On a malformed line, an unknown `op`, or any request before the first `new`, it writes a message to standard error and exits with status 2. These are protocol errors, not scheduler errors.

A driver holds one scheduler at a time. A `new` request replaces it.

A scheduler error, for example a zero cost, doesn't end the stream. The driver reports it in the response and continues with the next request.

## 2. Numbers

- `cost` and `quantum` are sent and returned as **decimal strings**, for example `"9223372036854775807"`, because many JSON parsers lose precision above 2⁵³.
- Queue indexes, `count`, `n` and item values are JSON numbers. In the corpus they stay between −2³¹ and 2³¹ − 1.
- Costs and quanta in the corpus stay between 0 and 2⁶⁴ − 1, so a driver for a language with 64-bit unsigned integers can pass them straight through. Values above `MAX_COST` or `MAX_QUANTUM` must be rejected with the errors in `SPEC.md` §6.

## 3. Requests and responses

Item values are integers, and the scheduler returns them unchanged.

| Request | Successful response |
|---|---|
| `{"op":"new","count":3}` | `{"ok":null}` |
| `{"op":"enqueue","queue":0,"items":[{"value":7,"cost":"12"}]}` | `{"ok":null}` |
| `{"op":"set_quantum","queue":0,"quantum":"5"}` | `{"ok":null}` |
| `{"op":"add_queue"}` | `{"ok":3}`: the new queue's index |
| `{"op":"remove_queue"}` | `{"ok":null}` |
| `{"op":"remove_head","queue":0}` | `{"ok":{"value":7,"cost":"12"}}`, or `{"ok":null}` when the queue is empty |
| `{"op":"drain_queue","queue":0}` | `{"ok":[{"value":7,"cost":"12"}]}`: the removed items in FIFO order, possibly `[]` |
| `{"op":"take","n":4}` | `{"ok":[{"queue":0,"value":7,"cost":"12"}]}`: items in service order, possibly `[]` |

A failed operation responds with its error code from `SPEC.md` §6:

```json
{"error":"invalid_index"}
```

The codes are `invalid_index`, `zero_cost`, `cost_too_large`, `zero_quantum`, `quantum_too_large` and `negative_take`.

The driver must produce these codes even where its implementation can't receive the invalid input through its typed interface, for example a negative queue index in a language that uses unsigned indexes. In that case the driver checks the input itself, in the order `SPEC.md` specifies, and responds with the code without calling the implementation.

## 4. Comparing responses

Responses are compared as parsed JSON: key order and whitespace don't matter, and values must be exactly equal. A cost of `"12"` and a cost of `12` are different.

## 5. Corpus

The corpus is a set of recorded cases in `corpus/`, one JSON Lines file per category. Each line is one case:

```json
{"name":"edge/set-quantum-keeps-credit","description":"…","steps":[
  {"request":{"op":"new","count":2},"response":{"ok":null}},
  {"request":{"op":"take","n":1},"response":{"ok":[]}}
]}
```

- Every case begins with a `new` request, so cases are independent of each other.
- Replaying a case means sending each step's request in order and comparing the driver's response with the step's recorded response. A case passes when every response matches.
- A step after a mismatch is still sent, but the first mismatch is what gets reported.

The recorded responses come from the Go implementation, and each one was cross-checked against `tools/spec_model.py`, an executable form of `SPEC.md`. A response is only recorded when the two agree. `corpus/README.md` records the generator, seeds and library version.

## 6. Tools

- `tools/replay.py --driver "<command>"` replays every corpus file against a driver and reports the first mismatch in each failing case. It needs only Python 3.9 or newer. An implementation's CI can run it without installing Go.
- `tools/spec_model.py --driver` runs the executable spec as a driver. Replaying the corpus against it is how the corpus itself is checked.
- The live harness, which generates and fuzzes new sequences and shrinks failures, is planned and will follow this same protocol.

## 7. Versioning

The protocol and the corpus are versioned with `SPEC.md`. An implementation states which specification version it conforms to. A change to recorded responses, other than adding cases, is a change to the specification.
