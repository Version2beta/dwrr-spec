# Changelog

## 0.1.1

Working-tree consistency corrections (no version bump or corpus/expected-response
changes): operation-specific Go decoding ignores unused recognized fields;
arbitrary-precision payload/index/take handling and backlog-clamped take; adapter
supports published and current Go Take signatures without changing the v0.10.1
module pin. Checker retains all original checks and adds regression histories
and five protocol-error checks (41 total). Clarified existing nonnegative
cost/quantum validation domain and uncapped wire-integer wording; added language
mappings/status and explicit remaining Go qualifications. These repair/clarify
existing rules rather than introduce new scheduler semantics or shared errors.
Valid constructor counts beyond the Go adapter's native `int` representation now
terminate as resource exhaustion (stderr, exit 1, no response), not protocol
errors (exit 2). Documented this permitted representation failure separately
from malformed input; no shared integer cap or guaranteed allocation/OOM recovery.
Go-specific boundary/stream tests supplement the unchanged cross-language checker.

Scheduler behavior and the corpus are unchanged. The conformance protocol is stricter and fully specified:

- A request is checked as a whole before anything is done with it, and protocol checks come before scheduler checks. A malformed field is a protocol error even when the request also names an invalid queue.
- Blank lines are protocol errors.
- Costs and quanta must be canonical decimal strings: no sign, leading zeros, spaces or decimal point.
- Indexes, counts, `n` and item values must be JSON integers.
- Every field an operation needs is required; fields it doesn't use are ignored. Duplicate keys are unspecified.
- New `tools/check_driver.py` checks flushing, exit status at end of input, and every kind of protocol error.
- The Go driver and `tools/spec_model.py` follow these rules.

## 0.1.0

- First draft of the specification, the conformance protocol and the corpus: 1,839 cases and 44,728 steps recorded from `github.com/version2beta/dwrr` v0.10.1 and cross-checked against the executable specification.
