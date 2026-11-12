#!/usr/bin/env python3
"""An executable form of SPEC.md.

The scheduler below follows the specification's text step by step: §5 for the
operations, §6 for errors. It uses Python's unlimited integers, so it never
needs to argue about overflow.

    python3 tools/spec_model.py --driver          # act as a conformance driver (PROTOCOL.md)
    python3 tools/spec_model.py --driver --fast   # same, computing idle rounds directly

`take` normally steps through every round, exactly as SPEC.md §5.8 is written.
When every waiting queue needs many more rounds to afford its next item, that
is slow, so --fast computes those idle rounds directly. SPEC.md §5.8 permits
this as long as every result is identical. The corpus generator checks --fast
against the step-by-step mode wherever both can run.
"""
import json
import re
import sys

MAX_COST = MAX_QUANTUM = 2**63 - 1


class SchedulerError(Exception):
    """A scheduler error from SPEC.md §6. Its message is the error code."""


class Scheduler:
    def __init__(self, count, fast=False):
        self.items = [[] for _ in range(count)]   # each item is (value, cost)
        self.quantum = [1] * count
        self.credit = [0] * count
        self.cursor = 0
        self.active = False
        self.fast = fast

    # Helpers named in SPEC.md §4.
    def _n(self):
        return len(self.items)

    def _advance(self):
        self.cursor = (self.cursor + 1) % self._n()

    def _close_visit(self):
        self.active = False
        self._advance()

    def _check_index(self, queue):
        if not (0 <= queue < self._n()):
            raise SchedulerError("invalid_index")

    # §5.2
    def enqueue(self, queue, items):
        self._check_index(queue)
        for _, cost in items:
            if cost == 0:
                raise SchedulerError("zero_cost")
            if cost > MAX_COST:
                raise SchedulerError("cost_too_large")
        self.items[queue].extend(items)

    # §5.3
    def set_quantum(self, queue, quantum):
        self._check_index(queue)
        if quantum == 0:
            raise SchedulerError("zero_quantum")
        if quantum > MAX_QUANTUM:
            raise SchedulerError("quantum_too_large")
        self.quantum[queue] = quantum

    # §5.4
    def add_queue(self):
        self.items.append([])
        self.quantum.append(1)
        self.credit.append(0)
        return self._n() - 1

    # §5.5
    def remove_queue(self):
        if self._n() == 0:
            return
        last = self._n() - 1
        if self.active and self.cursor == last:
            self.active = False
            self.cursor = 0
        self.items.pop()
        self.quantum.pop()
        self.credit.pop()
        if last == 0:
            self.cursor = 0
        elif self.cursor >= last:
            self.cursor %= last

    # §5.6
    def remove_head(self, queue):
        self._check_index(queue)
        if not self.items[queue]:
            return None
        item = self.items[queue].pop(0)
        if not self.items[queue]:
            self.credit[queue] = 0
            if self.active and self.cursor == queue:
                self._close_visit()
        return item

    # §5.7
    def drain_queue(self, queue):
        self._check_index(queue)
        removed, self.items[queue] = self.items[queue], []
        self.credit[queue] = 0
        if self.active and self.cursor == queue:
            self._close_visit()
        return removed

    # §5.8
    def take(self, n):
        if n < 0:
            raise SchedulerError("negative_take")
        out = []
        if n == 0:
            return out
        while len(out) < n and any(self.items):
            q = self.cursor
            if not self.active:
                if not self.items[q]:
                    self.credit[q] = 0
                    self._advance()
                    continue
                if self.fast:
                    self._skip_idle_rounds()
                self.credit[q] += self.quantum[q]
                self.active = True
            if not self.items[q]:
                self.credit[q] = 0
                self._close_visit()
                continue
            value, cost = self.items[q][0]
            if self.credit[q] < cost:
                self._close_visit()
                continue
            self.credit[q] -= cost
            self.items[q].pop(0)
            out.append((q, value, cost))
            if not self.items[q]:
                self.credit[q] = 0
                self._close_visit()
        return out

    def _skip_idle_rounds(self):
        """Grant whole rounds in which no waiting queue could afford its next item.

        At this point no visit is active. A waiting queue i needs
        g_i = ceil((cost_i - credit_i) / quantum_i) more grants before it can
        afford its next item (0 if it already can). If every waiting queue
        needs at least m >= 2, the next m - 1 complete rounds serve nothing:
        each waiting queue simply receives m - 1 quanta, and the cursor ends
        where it started. Empty queues have no credit and are unaffected.
        """
        needed = []
        for i, queue in enumerate(self.items):
            if queue:
                gap = queue[0][1] - self.credit[i]
                needed.append(0 if gap <= 0 else -(-gap // self.quantum[i]))
        rounds = min(needed) - 1
        if rounds >= 1:
            for i, queue in enumerate(self.items):
                if queue:
                    self.credit[i] += rounds * self.quantum[i]

    def check_invariants(self):
        """SPEC.md §4 invariants and the §8 credit bound."""
        for i in range(self._n()):
            assert self.items[i] or self.credit[i] == 0, f"empty queue {i} has credit"
            assert 0 <= self.credit[i] <= 2**64 - 3, f"queue {i} credit out of range"
        if self._n() == 0:
            assert self.cursor == 0, "cursor must be 0 with no queues"
        else:
            assert 0 <= self.cursor < self._n(), "cursor out of range"
        assert not self.active or self.items[self.cursor], "active visit on an empty queue"


CANONICAL_DECIMAL = re.compile(r"(0|[1-9][0-9]*)")
U64_MAX = 2**64 - 1


class ProtocolError(ValueError):
    """A request PROTOCOL.md §3.1 doesn't allow. The driver exits with status 2."""


def _integer(request, field):
    value = request.get(field)
    if type(value) is not int:   # rejects bool, float, str and missing
        raise ProtocolError(f"{field} must be an integer")
    return value


def _decimal(value, field):
    if type(value) is not str or not CANONICAL_DECIMAL.fullmatch(value) or int(value) > U64_MAX:
        raise ProtocolError(f"{field} must be a canonical decimal string between 0 and 2^64-1")
    return int(value)


def parse(request):
    """Check a whole request (PROTOCOL.md §3.1) and return (op, arguments)."""
    if type(request) is not dict:
        raise ProtocolError("request must be a JSON object")
    op = request.get("op")
    if op == "new":
        count = _integer(request, "count")
        if count < 0:
            raise ProtocolError("count must be zero or more")
        return op, (count,)
    if op == "enqueue":
        queue = _integer(request, "queue")
        items = request.get("items")
        if type(items) is not list or any(type(it) is not dict for it in items):
            raise ProtocolError("items must be a list of objects")
        return op, (queue, [(_integer(it, "value"), _decimal(it.get("cost"), "cost")) for it in items])
    if op == "set_quantum":
        return op, (_integer(request, "queue"), _decimal(request.get("quantum"), "quantum"))
    if op in ("remove_head", "drain_queue"):
        return op, (_integer(request, "queue"),)
    if op == "take":
        return op, (_integer(request, "n"),)
    if op in ("add_queue", "remove_queue"):
        return op, ()
    raise ProtocolError(f"unknown op {op!r}")


def handle(scheduler, request, fast):
    """Apply one PROTOCOL.md request. Returns (scheduler, response).

    Raises ProtocolError for anything PROTOCOL.md §3.1 doesn't allow; protocol
    checks happen before any scheduler check.
    """
    op, args = parse(request)
    if op == "new":
        return Scheduler(args[0], fast), {"ok": None}
    if scheduler is None:
        raise ProtocolError(f"{op!r} before the first new")
    s = scheduler
    try:
        if op == "enqueue":
            s.enqueue(*args)
            result = None
        elif op == "set_quantum":
            s.set_quantum(*args)
            result = None
        elif op == "add_queue":
            result = s.add_queue()
        elif op == "remove_queue":
            s.remove_queue()
            result = None
        elif op == "remove_head":
            item = s.remove_head(*args)
            result = None if item is None else {"value": item[0], "cost": str(item[1])}
        elif op == "drain_queue":
            result = [{"value": v, "cost": str(c)} for v, c in s.drain_queue(*args)]
        else:  # take
            result = [{"queue": q, "value": v, "cost": str(c)} for q, v, c in s.take(*args)]
        response = {"ok": result}
    except SchedulerError as e:
        response = {"error": str(e)}
    s.check_invariants()
    return s, response


def driver(fast):
    scheduler = None
    for line in sys.stdin:
        try:
            request = json.loads(line)   # a blank line fails here, as PROTOCOL.md requires
            scheduler, response = handle(scheduler, request, fast)
        except (json.JSONDecodeError, ProtocolError) as e:
            print(f"spec_model: protocol error: {e}", file=sys.stderr)
            sys.exit(2)
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    if "--driver" not in sys.argv:
        print(__doc__)
        sys.exit(0)
    driver(fast="--fast" in sys.argv)
