# Local development

1. Copy `.env.example` to `.env` and fill only local secrets.
2. Keep `VECTOR_STORE=faiss`.
3. Run `docker compose -f deploy/docker-compose-dev.yml up --build`.

The development stack runs PostgreSQL, Redis, Kafka, the three business
services, and Streamlit. It deliberately omits Jenkins, Gitea, Harbor,
Prometheus, Grafana, Jaeger, and Canal to keep laptop usage reasonable.

Kafka events use this payload and `document_id` as the Kafka key:

```json
{"document_id":"doc-42","operation":"UPDATE","timestamp":1735689600,"source":"manual.pdf","file_path":"/app/data/uploads/manual.pdf"}
```

The `file_path` must be visible to both Sync and RAG services through the same
volume. External Canal is optional because the current metadata database is
PostgreSQL, not MySQL.
