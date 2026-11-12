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
	"os"
	"regexp"
	"strconv"

	"github.com/version2beta/dwrr"
)

type item struct {
	Value int64  `json:"value"`
	Cost  string `json:"cost"`
}

// wireItem is an enqueued item as received, so missing fields can be detected.
type wireItem struct {
	Value *int64  `json:"value"`
	Cost  *string `json:"cost"`
}

type scheduled struct {
	Queue uint   `json:"queue"`
	Value int64  `json:"value"`
	Cost  string `json:"cost"`
}

type request struct {
	Op      string      `json:"op"`
	Count   *int        `json:"count"`
	Queue   *int64      `json:"queue"`
	Quantum *string     `json:"quantum"`
	Items   *[]wireItem `json:"items"`
	N       *int        `json:"n"`
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

func number(s *string, field string) uint64 {
	if s == nil {
		protocolError("missing %s", field)
	}
	v, err := strconv.ParseUint(*s, 10, 64)
	if !canonicalDecimal.MatchString(*s) || err != nil {
		protocolError("%s must be a canonical decimal string between 0 and 2^64-1", field)
	}
	return v
}

// need checks that a field the operation uses is present.
func need(present bool, op, field string) {
	if !present {
		protocolError("%s needs %s", op, field)
	}
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

	var s *dwrr.DWRR[int64]
	queues := 0
	for in.Scan() {
		var r request
		line := bytes.TrimSpace(in.Bytes())
		if len(line) == 0 || line[0] != '{' {
			protocolError("request must be a JSON object")
		}
		if err := json.Unmarshal(line, &r); err != nil {
			protocolError("malformed request: %v", err)
		}
		switch r.Op {
		case "new", "enqueue", "set_quantum", "add_queue", "remove_queue", "remove_head", "drain_queue", "take":
		default:
			protocolError("unknown op %q", r.Op)
		}
		if s == nil && r.Op != "new" {
			protocolError("%q before the first new", r.Op)
		}
		// index checks the queue against the current scheduler. Every protocol
		// check for the request must already have passed.
		index := func() (uint, bool) {
			if *r.Queue < 0 || *r.Queue >= int64(queues) {
				fail("invalid_index")
				return 0, false
			}
			return uint(*r.Queue), true
		}
		switch r.Op {
		case "new":
			if r.Count == nil || *r.Count < 0 {
				protocolError("new needs a non-negative count")
			}
			s, queues = dwrr.NewDWRR[int64](uint(*r.Count)), *r.Count
			ok(nil)
		case "enqueue":
			need(r.Queue != nil, r.Op, "queue")
			need(r.Items != nil, r.Op, "items")
			items := make([]dwrr.Item[int64], 0, len(*r.Items))
			for _, it := range *r.Items {
				need(it.Value != nil, r.Op, "a value for every item")
				items = append(items, dwrr.Item[int64]{Value: *it.Value, Cost: number(it.Cost, "cost")})
			}
			q, valid := index()
			if !valid {
				continue
			}
			if err := s.Enqueue(q, items); err != nil {
				failErr(err)
			} else {
				ok(nil)
			}
		case "set_quantum":
			need(r.Queue != nil, r.Op, "queue")
			quantum := number(r.Quantum, "quantum")
			q, valid := index()
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
			queues++
		case "remove_queue":
			s.RemoveQueue()
			if queues > 0 {
				queues--
			}
			ok(nil)
		case "remove_head":
			need(r.Queue != nil, r.Op, "queue")
			q, valid := index()
			if !valid {
				continue
			}
			if it, found := s.RemoveHead(q); found {
				ok(item{it.Value, strconv.FormatUint(it.Cost, 10)})
			} else {
				ok(nil)
			}
		case "drain_queue":
			need(r.Queue != nil, r.Op, "queue")
			q, valid := index()
			if !valid {
				continue
			}
			items := []item{}
			for _, it := range s.DrainQueue(q) {
				items = append(items, item{it.Value, strconv.FormatUint(it.Cost, 10)})
			}
			ok(items)
		case "take":
			if r.N == nil {
				protocolError("take needs n")
			}
			if *r.N < 0 {
				fail("negative_take") // The Go library panics here.
				continue
			}
			results := []scheduled{}
			for _, it := range s.Take(*r.N) {
				results = append(results, scheduled{it.Queue, it.Value, strconv.FormatUint(it.Cost, 10)})
			}
			ok(results)
		}
	}
	if err := in.Err(); err != nil {
		protocolError("reading input: %v", err)
	}
}
