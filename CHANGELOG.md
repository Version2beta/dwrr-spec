# Changelog

## 0.1.1

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
