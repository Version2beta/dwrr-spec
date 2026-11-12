# dwrr-spec

The specification, conformance protocol and conformance corpus for **dwrr**, a deficit weighted round robin scheduler over FIFO queues with per-item costs. Every implementation of dwrr, in any language, conforms to this repository.

- [`SPEC.md`](SPEC.md): what every implementation must do, including state, operations, errors and limits.
- [`PROTOCOL.md`](PROTOCOL.md): how the conformance tools drive an implementation, and the corpus format.
- [`corpus/`](corpus/): recorded cases, each a sequence of operations with the exact expected responses.
- [`tools/`](tools/):
  - `replay.py` replays the corpus against any driver;
  - `spec_model.py` is the specification as an executable model;
  - `gen_corpus.py` regenerates the corpus.
- [`drivers/go/`](drivers/go/): the driver for the Go implementation, `github.com/version2beta/dwrr`.

## Checking an implementation

Build the implementation's driver, then run:

```sh
python3 tools/replay.py --driver "<command that starts the driver>"
```

It prints `PASS` with the case count, or the first mismatch in each failing case: the request, the expected response, and what the driver returned. The tools need Python 3.9 or newer and nothing else.

## Implementations

| Language | Repository | Conforms to |
|---|---|---|
| Go | [version2beta/dwrr](https://github.com/version2beta/dwrr) | 0.1.0 |

## Status

Version 0.1.0 is a draft. A live harness, which generates new sequences, fuzzes them and shrinks failures, is planned and will use the same protocol.

## License

MIT. Copyright (c) 2026 M. Robert Martin.
