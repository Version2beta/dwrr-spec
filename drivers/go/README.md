# Go driver

Drives `github.com/version2beta/dwrr` for the conformance tools, following `PROTOCOL.md`. The first `go mod tidy` creates `go.sum`; commit it.

```sh
cd drivers/go
go mod tidy
go build -o dwrr-driver .
cd ../..
python3 tools/replay.py --driver drivers/go/dwrr-driver
```

The Go library panics on an invalid queue index and on a negative `take`. The driver checks for both itself, and responds with `invalid_index` or `negative_take` as the protocol requires.

To test a local copy of the library instead of the released version, add a replace directive before building:

```sh
go mod edit -replace github.com/version2beta/dwrr=../../../dwrr
```
