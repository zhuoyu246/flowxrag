package internal

import (
	"sync"
	"time"
)

// CircuitBreaker rejects calls after consecutive downstream failures and probes
// again after resetTimeout. It protects the Python/LLM service from a stampede.
type CircuitBreaker struct {
	mu           sync.Mutex
	failures     int
	threshold    int
	openedAt     time.Time
	resetTimeout time.Duration
}

func NewCircuitBreaker(threshold int, resetTimeout time.Duration) *CircuitBreaker {
	return &CircuitBreaker{threshold: threshold, resetTimeout: resetTimeout}
}

func (b *CircuitBreaker) Allow() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.openedAt.IsZero() {
		return true
	}
	if time.Since(b.openedAt) >= b.resetTimeout {
		b.openedAt = time.Time{}
		b.failures = 0
		return true
	}
	return false
}

func (b *CircuitBreaker) Success() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures = 0
	b.openedAt = time.Time{}
}

func (b *CircuitBreaker) Failure() {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.failures++
	if b.failures >= b.threshold {
		b.openedAt = time.Now()
	}
}
