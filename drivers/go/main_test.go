package main

import (
	"bytes"
	"context"
	"errors"
	"math/big"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/version2beta/dwrr"
)

// Run the actual stream loop in a subprocess so fatal statuses and output are
// checked without changing the driver's process-level error handling.
func TestDriverProcess(t *testing.T) {
	if os.Getenv("DWRR_DRIVER_TEST_PROCESS") != "1" {
		return
	}
	main()
	os.Exit(0)
}

func TestNewCountRepresentation(t *testing.T) {
	maxIntPlusOne := new(big.Int).SetUint64(uint64(^uint(0) >> 1))
	maxIntPlusOne.Add(maxIntPlusOne, big.NewInt(1))
	huge := new(big.Int).Lsh(big.NewInt(1), 80)
	cases := []struct {
		name, request, diagnostic string
		status                    int
	}{
		{"2^80", `{"op":"new","count":` + huge.String() + `}`, "resource exhaustion: count exceeds native int representation", 1},
		{"maxInt+1", `{"op":"new","count":` + maxIntPlusOne.String() + `}`, "resource exhaustion: count exceeds native int representation", 1},
		{"negative", `{"op":"new","count":-1}`, "new needs a non-negative count", 2},
		{"huge negative", `{"op":"new","count":-` + huge.String() + `}`, "new needs a non-negative count", 2},
		{"missing", `{"op":"new"}`, "count must be a JSON integer", 2},
		{"null", `{"op":"new","count":null}`, "count must be a JSON integer", 2},
		{"string", `{"op":"new","count":"2"}`, "count must be a JSON integer", 2},
		{"object", `{"op":"new","count":{}}`, "count must be a JSON integer", 2},
		{"array", `{"op":"new","count":[]}`, "count must be a JSON integer", 2},
		{"boolean", `{"op":"new","count":true}`, "count must be a JSON integer", 2},
		{"fraction", `{"op":"new","count":2.5}`, "count must be a JSON integer", 2},
		{"integer fraction", `{"op":"new","count":2.0}`, "count must be a JSON integer", 2},
		{"exponent", `{"op":"new","count":2e0}`, "count must be a JSON integer", 2},
		{"malformed", `{"op":"new","count":01}`, "malformed request:", 2},
		{"zero", `{"op":"new","count":0}`, "", 0},
		{"negative zero", `{"op":"new","count":-0}`, "", 0},
		{"small with ignored fields", `{"op":"new","count":2,"n":false,"items":{}}`, "", 0},
	}
	for _, tc := range cases {
		for _, prior := range []bool{false, true} {
			name := tc.name + "/first"
			prefix, want := "", ""
			if prior {
				name = tc.name + "/after-response"
				prefix, want = "{\"op\":\"new\",\"count\":0}\n", "{\"ok\":null}\n"
			}
			t.Run(name, func(t *testing.T) {
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestDriverProcess$")
				cmd.Env = append(os.Environ(), "DWRR_DRIVER_TEST_PROCESS=1")
				cmd.Stdin = strings.NewReader(prefix + tc.request + "\n{\"op\":\"take\",\"n\":0}\n")
				var stdout, stderr bytes.Buffer
				cmd.Stdout, cmd.Stderr = &stdout, &stderr
				err := cmd.Run()
				if ctx.Err() != nil {
					t.Fatal(ctx.Err())
				}
				status := 0
				if err != nil {
					var exit *exec.ExitError
					if !errors.As(err, &exit) {
						t.Fatal(err)
					}
					status = exit.ExitCode()
				}
				if tc.status == 0 {
					want += "{\"ok\":null}\n{\"ok\":[]}\n"
				}
				if status != tc.status || stdout.String() != want {
					t.Fatalf("status %d, stdout %q, stderr %q; want status %d, stdout %q", status, stdout.String(), stderr.String(), tc.status, want)
				}
				if tc.diagnostic == "" {
					if stderr.Len() != 0 {
						t.Fatalf("unexpected diagnostic: %s", &stderr)
					}
				} else if !strings.Contains(stderr.String(), tc.diagnostic) {
					t.Fatalf("stderr %q lacks %q", stderr.String(), tc.diagnostic)
				}
			})
		}
	}
}

type publishedTake struct{ items []dwrr.Scheduled[*big.Int] }

func (s publishedTake) Take(int) []dwrr.Scheduled[*big.Int] { return s.items }

type currentTake struct {
	items []dwrr.Scheduled[*big.Int]
	err   error
}

func (s currentTake) Take(int) ([]dwrr.Scheduled[*big.Int], error) { return s.items, s.err }

func TestTakePublishedAndCurrentSignatures(t *testing.T) {
	items := []dwrr.Scheduled[*big.Int]{{Value: big.NewInt(42), Cost: 1}}
	for _, s := range []any{publishedTake{items}, currentTake{items, nil}} {
		got, err := take(s, 1)
		if err != nil || len(got) != 1 || got[0].Value.Cmp(items[0].Value) != 0 {
			t.Fatalf("take(%T): %v, %v", s, got, err)
		}
	}
	want := errors.New("take failed")
	if _, err := take(currentTake{nil, want}, 1); !errors.Is(err, want) {
		t.Fatalf("lost current API error: %v", err)
	}
}
