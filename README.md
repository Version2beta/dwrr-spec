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

## Why a shared repository?

Go, Python and Elixir expose different ownership, concurrency and error APIs.
The fixed-quantum contract, recorded responses and driver protocol give them a
common behavioral target: identical service order, error precedence and exact
numeric limits for the same operations. Language-local extensions are not shared
requirements: Go's callable quanta, Elixir's optional Server and Python's mutable,
locked facade remain documented in their own repositories.

This repository is a development/conformance resource, not a runtime dependency
of those libraries. Implementations pin revisions or vendor snapshots so past
checks are reproducible; such pins do not automatically follow current source.
Elixir's main CI retains historical `8a0e3cf9ae860ba207213590c00feeb822bdd8f2`;
Python vendors `243dd125470365df2c52a6ce72de3ee8ecfce3fe`. Those snapshots remain
unchanged even when current implementation descriptions here are refreshed.

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
| Go | [version2beta/dwrr](https://github.com/version2beta/dwrr) | Draft 0.1.1 fixed core; recorded local adapter checks with published v0.10.1 and unreleased Go source pass 1,839 cases / 44,728 steps and 41 protocol checks; qualifications below |
| Elixir | [version2beta/dwrr-elixir](https://github.com/version2beta/dwrr-elixir) | Draft 0.1.1 fixed core + optional local Server; recorded local current-source driver checks pass the same corpus and 41 checks; 0.1.0 unpublished per local release records |
| Python | [version2beta/dwrr-python](https://github.com/version2beta/dwrr-python) | Implemented draft 0.1.1 fixed core; mutable internally locked `Scheduler`; local vendored-corpus replay passes 1,839 cases / 44,728 steps and 41 protocol checks; version 0.1.0 remains unuploaded per local release records |

These are bounded local checks, not an all-sequences proof or minimum-runtime/CI
certification. Go's adapter reports constructor counts beyond native `int` as
resource exhaustion (stderr, exit 1, no response), not a protocol error. Actual
allocation/OOM recovery is not guaranteed. Its 64 MiB scanner ceiling also remains;
neither is a shared protocol bound. Current
unreleased Go also has a generation-exhaustion lifetime restriction even on the
fixed path. See [`drivers/go/README.md`](drivers/go/README.md) and SPEC §11. No
such caps are imposed on Elixir or the Python contract. Python API/domain
mapping and retained verification records are in its
[SPEC.md](https://github.com/version2beta/dwrr-python/blob/main/SPEC.md) and
[TESTING.md](https://github.com/version2beta/dwrr-python/blob/main/TESTING.md).
Its local results use frozen vendored tools, not an automatic current-spec check;
no hosted CI, release approval or publication result is inferred here.

## CI

Push/PR checks are configured for corpus/tool identities and real pinned Go
adapter replay/protocol checks. See [ci/README.md](ci/README.md) for runtime
targets, provenance and limitations. Configuration is not a hosted-pass claim.

## Status

Version 0.1.1 is a draft. See [`CHANGELOG.md`](CHANGELOG.md). A live harness, which generates new sequences, fuzzes them and shrinks failures, is planned and will use the same protocol.

## License

MIT. Copyright (c) 2026 M. Robert Martin.
