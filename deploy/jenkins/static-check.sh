#!/usr/bin/env sh
set -eu

for service in gateway sync-service; do
  (
    cd "$service"
    go mod tidy
    go vet ./...
  )
done
