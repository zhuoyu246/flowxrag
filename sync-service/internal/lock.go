package internal

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"

	"github.com/redis/go-redis/v9"
)

const releaseLockScript = `if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end`

type documentLock struct {
	client *redis.Client
	key    string
	token  string
}

func (s *Service) acquireDocumentLock(ctx context.Context, documentID string) (*documentLock, error) {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return nil, err
	}
	lock := &documentLock{client: s.redis, key: "rag:document:lock:" + documentID, token: hex.EncodeToString(bytes)}
	ok, err := s.redis.SetNX(ctx, lock.key, lock.token, s.cfg.LockTTL).Result()
	if err != nil {
		return nil, fmt.Errorf("redis lock: %w", err)
	}
	if !ok {
		return nil, fmt.Errorf("document %s is already being processed", documentID)
	}
	return lock, nil
}

func (lock *documentLock) Release(ctx context.Context) error {
	return lock.client.Eval(ctx, releaseLockScript, []string{lock.key}, lock.token).Err()
}
