// Command dwrr-driver drives github.com/version2beta/dwrr for the conformance
// tools. It reads one JSON request per line on stdin and writes one JSON
// response per line on stdout, as described in PROTOCOL.md.
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"os"
	"regexp"
	"strconv"

	"github.com/version2beta/dwrr"
)

type item struct {
	Value *big.Int `json:"value"`
	Cost  string   `json:"cost"`
}

type scheduled struct {
	Queue uint     `json:"queue"`
	Value *big.Int `json:"value"`
	Cost  string   `json:"cost"`
}

// Decode only fields used by the selected operation. Unused fields, including
// recognized fields of the wrong type, have no protocol meaning.
type request map[string]json.RawMessage

var jsonInteger = regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`)

func integer(r request, field string) *big.Int {
	raw := bytes.TrimSpace(r[field])
	if !jsonInteger.Match(raw) {
		protocolError("%s must be a JSON integer", field)
	}
	n, _ := new(big.Int).SetString(string(raw), 10)
	return n
}

// take supports both the published v0.10.1 API and the unreleased error-returning
// API, without changing the module pin. Only fixed integer quanta enter here.
func take(s any, n int) ([]dwrr.Scheduled[*big.Int], error) {
	switch s := s.(type) {
	case interface {
		Take(int) ([]dwrr.Scheduled[*big.Int], error)
	}:
		return s.Take(n)
	case interface {
		Take(int) []dwrr.Scheduled[*big.Int]
	}:
		return s.Take(n), nil
	default:
		panic("unsupported dwrr Take signature")
	}
}

var canonicalDecimal = regexp.MustCompile(`^(0|[1-9][0-9]*)$`)

var codes = []struct {
	err  error
	code string
}{
	{dwrr.ErrZeroCost, "zero_cost"},
	{dwrr.ErrCostTooLarge, "cost_too_large"},
	{dwrr.ErrZeroQuantum, "zero_quantum"},
	{dwrr.ErrQuantumTooLarge, "quantum_too_large"},
}

func protocolError(format string, args ...any) {
	fmt.Fprintf(os.Stderr, "dwrr-driver: "+format+"\n", args...)
	os.Exit(2)
}

func number(r request, field string) uint64 {
	var text string
	if err := json.Unmarshal(r[field], &text); err != nil || !canonicalDecimal.MatchString(text) {
		protocolError("%s must be a canonical decimal string between 0 and 2^64-1", field)
	}
	v, err := strconv.ParseUint(text, 10, 64)
	if err != nil {
		protocolError("%s must be a canonical decimal string between 0 and 2^64-1", field)
	}
	return v
}

func main() {
	in := bufio.NewScanner(os.Stdin)
	in.Buffer(make([]byte, 1<<20), 1<<26)
	out := bufio.NewWriter(os.Stdout)
	respond := func(v any) {
		b, err := json.Marshal(v)
		if err != nil {
			protocolError("encoding response: %v", err)
		}
		out.Write(b)
		out.WriteByte('\n')
		out.Flush()
	}
	ok := func(v any) { respond(map[string]any{"ok": v}) }
	fail := func(code string) { respond(map[string]string{"error": code}) }
	failErr := func(err error) {
		for _, c := range codes {
			if errors.Is(err, c.err) {
				fail(c.code)
				return
			}
		}
		protocolError("unexpected error: %v", err)
	}

	var s *dwrr.DWRR[*big.Int]
	var lengths []int
	total := 0
	for in.Scan() {
		var r request
		line := bytes.TrimSpace(in.Bytes())
		if len(line) == 0 || line[0] != '{' {
			protocolError("request must be a JSON object")
		}
		if err := json.Unmarshal(line, &r); err != nil {
			protocolError("malformed request: %v", err)
		}
		var op string
		if err := json.Unmarshal(r["op"], &op); err != nil {
			protocolError("op must be a string")
		}
		switch op {
		case "new", "enqueue", "set_quantum", "add_queue", "remove_queue", "remove_head", "drain_queue", "take":
		default:
			protocolError("unknown op %q", op)
		}
		if s == nil && op != "new" {
			protocolError("%q before the first new", op)
		}
		// index checks the queue against the current scheduler. Every protocol
		// check for the request must already have passed.
		index := func(q *big.Int) (uint, bool) {
			if q.Sign() < 0 || q.Cmp(big.NewInt(int64(len(lengths)))) >= 0 {
				fail("invalid_index")
				return 0, false
			}
			return uint(q.Uint64()), true
		}
		switch op {
		case "new":
			count := integer(r, "count")
			if count.Sign() < 0 {
				protocolError("new needs a non-negative count")
			}
			// Both the library storage and backlog bookkeeping require native int
			// lengths. This is resource exhaustion, not a wire integer bound.
			maxInt := new(big.Int).SetUint64(uint64(^uint(0) >> 1))
			if count.Cmp(maxInt) > 0 {
				fmt.Fprintln(os.Stderr, "dwrr-driver: resource exhaustion: count exceeds native int representation")
				os.Exit(1)
			}
			n := int(count.Int64())
			s = dwrr.NewDWRR[*big.Int](uint(n))
			lengths, total = make([]int, n), 0
			ok(nil)
		case "enqueue":
			queue := integer(r, "queue")
			var batch []request
			if err := json.Unmarshal(r["items"], &batch); err != nil || batch == nil {
				protocolError("enqueue needs an items list")
			}
			items := make([]dwrr.Item[*big.Int], 0, len(batch))
			for _, it := range batch {
				items = append(items, dwrr.Item[*big.Int]{Value: integer(it, "value"), Cost: number(it, "cost")})
			}
			q, valid := index(queue)
			if !valid {
				continue
			}
			if err := s.Enqueue(q, items); err != nil {
				failErr(err)
			} else {
				lengths[q] += len(items)
				total += len(items)
				ok(nil)
			}
		case "set_quantum":
			queue := integer(r, "queue")
			quantum := number(r, "quantum")
			q, valid := index(queue)
			if !valid {
				continue
			}
			if err := s.SetQuantum(q, quantum); err != nil {
				failErr(err)
			} else {
				ok(nil)
			}
		case "add_queue":
			ok(s.AddQueue())
			lengths = append(lengths, 0)
		case "remove_queue":
			s.RemoveQueue()
			if len(lengths) > 0 {
				total -= lengths[len(lengths)-1]
				lengths = lengths[:len(lengths)-1]
			}
			ok(nil)
		case "remove_head":
			queue := integer(r, "queue")
			q, valid := index(queue)
			if !valid {
				continue
			}
			if it, found := s.RemoveHead(q); found {
				lengths[q]--
				total--
				ok(item{it.Value, strconv.FormatUint(it.Cost, 10)})
			} else {
				ok(nil)
			}
		case "drain_queue":
			queue := integer(r, "queue")
			q, valid := index(queue)
			if !valid {
				continue
			}
			total -= lengths[q]
			lengths[q] = 0
			items := []item{}
			for _, it := range s.DrainQueue(q) {
				items = append(items, item{it.Value, strconv.FormatUint(it.Cost, 10)})
			}
			ok(items)
		case "take":
			limit := integer(r, "n")
			if limit.Sign() < 0 {
				fail("negative_take")
				continue
			}
			// More than the actual backlog is observationally the same as the backlog:
			// take stops only at its limit or all-empty. Never narrow an unbounded n.
			n := total
			if limit.Cmp(big.NewInt(int64(total))) < 0 {
				n = int(limit.Int64())
			}
			selected, err := take(s, n)
			if err != nil {
				failErr(err)
				continue
			}
			results := []scheduled{}
			for _, it := range selected {
				lengths[it.Queue]--
				total--
				results = append(results, scheduled{it.Queue, it.Value, strconv.FormatUint(it.Cost, 10)})
			}
			ok(results)
		}
	}
	if err := in.Err(); err != nil {
		protocolError("reading input: %v", err)
	}
}
