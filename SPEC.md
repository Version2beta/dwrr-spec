# dwrr specification

**Version:** 0.1.1 (draft). 0.1.1 tightens the conformance protocol; scheduler behavior is unchanged from 0.1.0.
**Status:** Describes the behavior of `github.com/version2beta/dwrr` v0.10.x. Every implementation of dwrr conforms to this document.

This specification defines a deficit weighted round robin (DWRR) scheduler over FIFO queues: its state, its operations, their results and errors, and the numeric limits every implementation shares. It's language-neutral. Each implementation chooses names and error mechanisms that are idiomatic in its language, and documents how they map to the names here.

The words **must**, **must not** and **may** are normative. Sections marked *informative* explain or illustrate, and add no requirements.

## 1. Conformance

An implementation conforms if, for every sequence of operations, it produces the same results and the same errors as the reference scheduler defined in §5. Internal state, data structures and performance are the implementation's own business. Only observable behavior must match: return values, errors, and the order of items returned.

Conformance is checked by the shared harness against the shared reference and conformance corpus, described in `PROTOCOL.md`.

## 2. Limits

| Name | Value |
|---|---|
| `MAX_COST` | 2⁶³ − 1 = 9,223,372,036,854,775,807 |
| `MAX_QUANTUM` | 2⁶³ − 1 = 9,223,372,036,854,775,807 |

Every implementation must accept every cost and quantum from 1 to these limits, and reject values outside that range with the errors in §6. The limits are the same in every language, even where the language's integers could hold more, so the conformance corpus means the same thing everywhere.

Implementations must compute credit exactly. Credit never exceeds `MAX_COST − 1 + MAX_QUANTUM` = 2⁶⁴ − 3 (§8), so an implementation can use unsigned 64-bit integers, wider integers, or arbitrary-precision integers. It must not round, saturate or wrap. Where a language's native numbers are exact only to a smaller range, for example IEEE 754 doubles beyond 2⁵³, the implementation must use an exact representation.

## 3. Concepts

- **Item:** a pair of a **value**, which is opaque to the scheduler and returned unchanged, and a **cost**, an integer from 1 to `MAX_COST`. An item's cost is fixed when the item is enqueued.
- **Queue:** a FIFO sequence of items. Queues are identified by **index**: 0 to *N* − 1, where *N* is the current number of queues. Each queue has:
  - a **quantum**, an integer from 1 to `MAX_QUANTUM`; it starts at 1;
  - a **credit**, a non-negative integer; it starts at 0.
- **Cursor:** the index of the queue the scheduler is visiting, or will visit next.
- **Active:** whether the queue at the cursor has already received its quantum for the current visit.
- **Visit:** the period from a queue receiving its quantum until the scheduler moves past it. During a visit the queue serves items from its front while its credit covers their cost.

## 4. State

A scheduler's state is:

- an ordered list of *N* queues, each with its items, quantum and credit;
- the cursor, an integer;
- the active flag, a boolean.

**Invariants.** After every operation:

1. A queue with no items has credit 0.
2. If *N* > 0, then 0 ≤ cursor < *N*. If *N* = 0, then cursor = 0.
3. If active is true, the queue at the cursor has at least one item.

"Advance" below means: set cursor to (cursor + 1) mod *N*.
"Close the visit" means: set active to false, then advance.

## 5. Operations

Each operation is atomic: it either completes, or it reports an error and leaves the state unchanged. Where an operation can fail in more than one way, it reports the first error in the order listed.

### 5.1 `new(count)`

Creates a scheduler with `count` empty queues (count ≥ 0), each with quantum 1 and credit 0. Cursor is 0 and active is false.

### 5.2 `enqueue(queue, items)`

Appends `items`, in order, to the end of queue `queue`.

Errors, in this order:
1. `invalid_index` if `queue` isn't between 0 and *N* − 1.
2. Checking the items in order, for the first item that's invalid: `zero_cost` if its cost is 0, or `cost_too_large` if its cost exceeds `MAX_COST`.

If any item is invalid, nothing is appended. An empty `items` list is valid and changes nothing.

Items appended to the queue currently being visited join that visit; they don't cause another quantum to be granted.

### 5.3 `set_quantum(queue, quantum)`

Sets the queue's quantum. The queue's credit and the active flag are unchanged. The new quantum is used the next time the queue receives one (§5.8). Setting a queue's current quantum changes nothing.

Errors, in this order:
1. `invalid_index`
2. `zero_quantum` if `quantum` is 0.
3. `quantum_too_large` if `quantum` exceeds `MAX_QUANTUM`.

### 5.4 `add_queue()`

Appends an empty queue with quantum 1 and credit 0, and returns its index (*N* before the call). The cursor and active flag are unchanged.

### 5.5 `remove_queue()`

Removes the last queue, index *N* − 1, with all its items. If *N* is 0, it does nothing.

Otherwise, with *last* = *N* − 1:
1. If active is true and cursor = *last*, set active to false and cursor to 0.
2. Remove the queue. The new count is *last*.
3. If *last* = 0, set cursor to 0. Otherwise, if cursor ≥ *last*, set cursor to cursor mod *last*.

Removed items aren't returned.

### 5.6 `remove_head(queue)`

Removes and returns the item at the front of the queue without scheduling it. If the queue is empty, it returns *none* and changes nothing.

If removing the item leaves the queue empty:
1. set the queue's credit to 0;
2. if active is true and cursor = `queue`, close the visit.

Otherwise the queue's credit and any visit in progress are unchanged.

Errors: `invalid_index`.

### 5.7 `drain_queue(queue)`

Removes and returns all the queue's items, in FIFO order; the list is empty if the queue was empty. Then:
1. set the queue's credit to 0;
2. if active is true and cursor = `queue`, close the visit.

Errors: `invalid_index`.

### 5.8 `take(n)`

Returns up to `n` items in service order. Each result is a triple: the source queue's index, the item's value, and the item's cost.

Errors: `negative_take` if `n` < 0.

If `n` = 0, it returns an empty list and changes nothing. Otherwise it repeats these steps until it has `n` items or every queue is empty:

```
while len(out) < n and some queue has items:
    q = cursor
    if not active:
        if queue q is empty:
            credit[q] = 0
            advance
            continue
        credit[q] = credit[q] + quantum[q]          # grant the quantum
        active = true
    if queue q is empty:                            # unreachable by invariant 3; kept for safety
        credit[q] = 0
        close the visit
        continue
    head = first item of queue q
    if credit[q] < head.cost:                       # the queue can't afford its next item
        close the visit
        continue
    credit[q] = credit[q] - head.cost
    remove head from queue q
    append (q, head.value, head.cost) to out
    if queue q is empty:
        credit[q] = 0
        close the visit
```

Consequences worth stating (informative):

- **The limit is a retrieval limit, not a fairness cap.** If `take` returns because it has `n` items, a visit in progress stays active with its remaining credit. The next `take` continues that visit without granting another quantum.
- **`take` returns fewer than `n` items only when every queue is empty.**
- **Idle rounds.** When no queue can afford its next item, the loop above keeps granting quanta round after round until one can. Implementations may compute the outcome of those rounds directly instead of stepping through them, provided every observable result is identical. The Go implementation does this.
- **With *N* = 0, `take` returns an empty list.**

## 6. Errors

Each implementation maps these codes to its language's error mechanism, and documents the mapping. A code may be raised as an exception, returned as an error value, or treated as a programming error (a panic) where that's idiomatic, as Go does for `invalid_index` and `negative_take`.

| Code | Raised by | Condition |
|---|---|---|
| `invalid_index` | `enqueue`, `set_quantum`, `remove_head`, `drain_queue` | The queue index is negative or ≥ *N*. |
| `zero_cost` | `enqueue` | An item's cost is 0. |
| `cost_too_large` | `enqueue` | An item's cost exceeds `MAX_COST`. |
| `zero_quantum` | `set_quantum` | The quantum is 0. |
| `quantum_too_large` | `set_quantum` | The quantum exceeds `MAX_QUANTUM`. |
| `negative_take` | `take` | `n` < 0. |

An operation that reports an error must leave the state unchanged.

Where a language's types can't express an invalid value, for example a negative index held in an unsigned integer, that error can't occur through the typed interface. The implementation's conformance driver must still report it when given one.

## 7. Concurrency

This specification defines a single scheduler's behavior as a sequence of operations. It doesn't require any particular concurrency model.

An implementation that allows operations from several threads, processes or tasks must make each operation atomic with respect to the others, so that every execution is equivalent to some sequence of operations. An implementation may instead be a pure data structure and leave coordination to the caller, as long as it documents that.

Values are opaque. Whether an implementation copies them, and how concurrent changes to a value behave, is outside this specification.

## 8. Why credit is bounded (informative)

1. **Outside a visit, a queue's credit is at most `MAX_COST − 1`.**
   - A visit closes with credit remaining only when the credit is below the next item's cost, which is at most `MAX_COST`.
   - Emptying a queue resets its credit to 0.
   - `remove_head` and `set_quantum` never increase credit.
2. **A visit begins by adding one quantum,** at most `MAX_QUANTUM`. Credit therefore never exceeds `MAX_COST − 1 + MAX_QUANTUM = 2⁶⁴ − 3`.
3. **Computing idle rounds directly** (§5.8) needs no larger numbers. Skipping the largest number of whole rounds that leaves every waiting queue still unable to afford its next item adds at most `cost − 1 − credit` to any queue.

The maximum is reached when a queue holds `MAX_COST − 1` of credit from an earlier visit, its quantum is set to `MAX_QUANTUM`, and `remove_head` exposes a cheaper item before its next visit.

## 9. Fairness (informative)

While every queue stays backlogged, each queue's total served cost after *k* of its visits is within one maximum item cost of *k* × its quantum. Over time, backlogged queues therefore receive service in proportion to their quanta. A queue without waiting work receives nothing and holds no credit, so its share goes to the queues that have work. Fairness is measured in the costs callers declare, not in time or any other resource.

## 10. Example (informative)

```
new(2)
set_quantum(0, 2)
set_quantum(1, 3)
enqueue(0, [("a", 2), ("b", 2)])
enqueue(1, [("x", 4), ("y", 1)])
take(10)  →  [(0, "a", 2), (0, "b", 2), (1, "x", 4), (1, "y", 1)]
```

Queue 0 receives 2 credit and serves `a`, which empties its credit. It can't afford `b`, so its visit closes. Queue 1 receives 3 credit but can't afford `x`, which costs 4, so it carries 3 forward. Queue 0 then serves `b`, which empties the queue. Queue 1 now has 6 credit, serves `x` and `y`, and empties.

## 11. Mapping to implementations

| Operation | Go (`github.com/version2beta/dwrr`) |
|---|---|
| `new(count)` | `NewDWRR[T](count)` |
| `enqueue` | `Enqueue(queue, []Item[T])` returns `ErrZeroCost` or `ErrCostTooLarge` |
| `set_quantum` | `SetQuantum(queue, quantum)` returns `ErrZeroQuantum` or `ErrQuantumTooLarge` |
| `add_queue` | `AddQueue()` |
| `remove_queue` | `RemoveQueue()` |
| `remove_head` | `RemoveHead(queue)` returns `(Item[T], bool)` |
| `drain_queue` | `DrainQueue(queue)` |
| `take` | `Take(n)` |
| `invalid_index`, `negative_take` | panic |

Each new implementation adds a column here.
