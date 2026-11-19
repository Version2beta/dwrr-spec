# dwrr-spec

The specification, conformance protocol and conformance corpus for **dwrr**, a deficit weighted round robin scheduler over FIFO queues with per-item costs. Implementations target the language-neutral contract in this repository; checked status and qualifications are listed below.

- [`SPEC.md`](SPEC.md): what every implementation must do, including state, operations, errors and limits.
- [`PROTOCOL.md`](PROTOCOL.md): how the conformance tools drive an implementation, and the corpus format.
- [`corpus/`](corpus/): recorded cases, each a sequence of operations with the exact expected responses.
- [`tools/`](tools/):
  - `replay.py` replays the corpus against any driver;
  - `check_driver.py` checks what replay can't: flushing, exit status, and every kind of protocol error;
  - `spec_model.py` is the specification as an executable model;
  - `gen_corpus.py` regenerates the corpus.
- [`drivers/go/`](drivers/go/): the driver for the Go implementation, `github.com/version2beta/dwrr`.

## Checking an implementation

Build the implementation's driver, then run both checks:

```sh
python3 tools/replay.py --driver "<command that starts the driver>"
python3 tools/check_driver.py --driver "<command that starts the driver>"
```

`replay.py` prints `PASS` with the case count, or the first mismatch in each failing case: the request, the expected response, and what the driver returned. `check_driver.py` lists each protocol check and whether it passed. The tools need Python 3.9 or newer and nothing else.

## Implementations

| Language | Repository | Target / checked status |
|---|---|---|
| Go | [version2beta/dwrr](https://github.com/version2beta/dwrr) | Draft 0.1.1 fixed core; freshly built adapter with published v0.10.1 and current unreleased local source passes 1,839 cases / 44,728 steps and 41 protocol checks; qualifications below |
| Elixir | [version2beta/dwrr-elixir](https://github.com/version2beta/dwrr-elixir) | Draft 0.1.1 fixed core + optional local Server; current-source driver passes the same corpus and 41 checks; unpublished 0.1.0 |
| Python | Local `dwrr-python` design documents | Proposed draft 0.1.1 target only; D1–D5 unapproved, no library/driver/tests or executable parity claim |

These are bounded local checks, not an all-sequences proof or minimum-runtime/CI
certification. Go's adapter reports constructor counts beyond native `int` as
resource exhaustion (stderr, exit 1, no response), not a protocol error. Actual
allocation/OOM recovery is not guaranteed. Its 64 MiB scanner ceiling also remains;
neither is a shared protocol bound. Current
unreleased Go also has a generation-exhaustion lifetime restriction even on the
fixed path. See [`drivers/go/README.md`](drivers/go/README.md) and SPEC §11. No
such caps are imposed on Elixir or the proposed Python contract.

## Status

Version 0.1.1 is a draft. See [`CHANGELOG.md`](CHANGELOG.md). A live harness, which generates new sequences, fuzzes them and shrinks failures, is planned and will use the same protocol.

## License

MIT. Copyright (c) 2026 M. Robert Martin.
