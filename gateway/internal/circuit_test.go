package internal

import (
	"testing"
	"time"
)

func TestCircuitBreakerOpensAndResets(t *testing.T) {
	breaker := NewCircuitBreaker(2, time.Millisecond)
	breaker.Failure()
	if !breaker.Allow() {
		t.Fatal("circuit opened too early")
	}
	breaker.Failure()
	if breaker.Allow() {
		t.Fatal("circuit should reject after threshold")
	}
	time.Sleep(2 * time.Millisecond)
	if !breaker.Allow() {
		t.Fatal("circuit should allow a probe after reset")
	}
}
