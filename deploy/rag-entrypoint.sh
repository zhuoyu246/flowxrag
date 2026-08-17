#!/bin/sh
set -eu

python rag-service/server.py &
grpc_pid=$!
trap 'kill -TERM "$grpc_pid" 2>/dev/null; wait "$grpc_pid"' TERM INT

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1 &
api_pid=$!
wait "$api_pid"
