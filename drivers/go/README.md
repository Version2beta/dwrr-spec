# Go driver

Drives the fixed-integer-quantum core of `github.com/version2beta/dwrr`, following
`PROTOCOL.md`. `go.mod` still pins published **v0.10.1**. The adapter supports both
that release's one-result `Take` and the current unreleased error-returning
`Take` through a narrow interface switch. No callable quanta enter this driver;
unexpected library errors are fatal diagnostics, not new shared error codes.

Build offline in an isolated workspace (from `drivers/go`); this requires the
pinned dependency already present in the normal Go module cache:

```sh
export GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off
spec_root=$(cd ../.. && pwd)
work=$(mktemp -d)
cp go.mod go.sum main.go main_test.go "$work/"
(cd "$work" && go test -race ./... && go vet ./... && go build -o dwrr-driver .)
python3 "$spec_root/tools/replay.py" --driver "$work/dwrr-driver"
python3 "$spec_root/tools/check_driver.py" --driver "$work/dwrr-driver"
go version -m "$work/dwrr-driver"
```

To test a local checkout, use a **separate** temporary workspace and an absolute
path. Do not edit this repository's module pin/lock or label this a release build:

```sh
library=/absolute/path/to/dwrr
local_work=$(mktemp -d)
cp go.mod go.sum main.go main_test.go "$local_work/"
(cd "$local_work" &&
  go mod edit -replace "github.com/version2beta/dwrr=$library" &&
  go test -race ./... && go vet ./... && go build -o dwrr-driver .)
python3 "$spec_root/tools/replay.py" --driver "$local_work/dwrr-driver"
python3 "$spec_root/tools/check_driver.py" --driver "$local_work/dwrr-driver"
go version -m "$local_work/dwrr-driver"
```

Record the library HEAD, dirty diff/source hashes and toolchain alongside results:
a local replacement identifies a path, not immutable source bytes. Minimum-Go
compatibility requires separate validation; a current-toolchain pass is not that.

## Parsing and qualifications

Only operation-required fields are decoded, but the **whole required request**
(including every enqueue item) is parsed before scheduler validation. The driver
maps invalid indexes and negative take limits itself, avoiding Go core panics.
Payloads, indexes and take limits use arbitrary-precision integers. Positive take
limits are reduced to the actual tracked backlog before calling Go: the reference
stops at all-empty anyway, so this preserves results, visit state and cursor.
Backlog counts change only after successful operations and reset on `new`.

Constructor `count` uses the same strict arbitrary-precision JSON-integer parser.
Missing/wrong-type, fractional/exponent and negative counts remain protocol errors
(stderr, exit 2). A valid nonnegative count above native `int` maximum is detected
**before narrowing or allocation** and terminates with a resource-exhaustion
diagnostic on stderr, exit **1**, no response for that line and no later request
processing; prior responses stand. This is the representation resource failure
permitted by PROTOCOL §1, not a new scheduler error or shared integer cap. There
is no arbitrary queue cap and no attempt to recover from actual allocation limits
or fatal OOM for representable counts. Go-specific tests cover the representation
boundary without allocating enormous in-range counts; the shared checker does
not require languages with wider representations to fail the same count.

**Not full-protocol equivalence:** the pre-existing 64 MiB scanner ceiling remains
an adapter restriction, not a shared wire limit, and is not exercised by the corpus
or checker. Neither Python nor Elixir inherits these Go resource restrictions. The current
Go core additionally panics before mutation at generation exhaustion (2^64−1
state changes), including fixed-only scheduling; that lifetime restriction is not
part of the shared all-sequences contract. Corpus/checker passes are bounded
evidence, not a proof of unrestricted conformance.
