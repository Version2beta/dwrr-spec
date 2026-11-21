# CI scope and provenance

Push/PR CI has read-only permissions, bounded 15-minute jobs and Python 3.9
(the tools' advertised minimum) / 3.14. The runner is pinned to Ubuntu 24.04:
Ubuntu 26.04 (`ubuntu-latest` in the first hosted run) has no setup-python
3.9 x64 build, so that run failed during provisioning, before conformance. Python 3.9 is an EOL legacy
compatibility target, not a recommended production runtime or security-support
claim. Go 1.22.2 similarly checks the adapter's declared compatibility floor,
not current Go security support. `identity.json` records the pre-CI source revision
and SHA-256 identities of the actual spec, protocol, seven corpus files, tools
and explicit Go adapter source/doc/module/test assets (never generated binaries). Updates require deliberate review; CI never regenerates
expected responses or silently updates identities. The structural gate asserts
1,839 cases / 44,728 steps and exact inventory membership.

The behavioral gate builds the real Go adapter with Go 1.22.2 and the existing
`go.mod` v0.10.1 pin / `go.sum`, verifies downloaded public modules, tests with
the race detector, vets, replays every case and runs the 41-check protocol suite.
It does not run the executable specification against itself as conformance
proof. No sibling checkout or private cache is required. Hosted setup may fetch
these declared public dependencies; offline local runs require their existing
module cache. Python tools themselves are standard-library-only.

This tests the published fixed-core implementation, not current unreleased Go,
Python or Elixir. Elixir's historical CI snapshot and Python's vendored snapshot
remain separate provenance, not claims to test this revision. Identity and finite
replay checks are not all-sequences proof. New workflows have not been run hosted
as part of this local setup; no release, push or minimum-runtime pass is implied.

The identity record's `source_revision` names the pre-CI baseline. Its SPEC hash
now includes the reviewed informative Python mapping/status refresh; scheduler
rules, PROTOCOL and corpus bytes are unchanged. Vendored historical snapshots
in implementation repositories are deliberately not rewritten.
