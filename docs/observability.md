# Observability

Every service exposes structured logs and `/metrics`; Gateway and Sync also
expose `/health` and `/ready`. Gateway extracts W3C `traceparent` from HTTP and
injects it into gRPC metadata. Sync extracts it from Kafka headers before it
calls `IndexDocument`, preserving a document-change trace.

Key online metrics include `rag_requests_total`, request duration,
`rag_retrieval_duration_seconds` by `faiss`, `bm25`, `rrf`, LLM counters,
`grpc_requests_total`, `kafka_messages_total`, and `kafka_consumer_lag`.
RAGAS stays an offline evaluation workflow and is deliberately not presented as
real-time Prometheus telemetry.

Set `OTEL_ENABLED=false` or `OTEL_EXPORTER=console` for local development. Set
`OTEL_ENABLED=true`, `OTEL_EXPORTER=otlp`, and the collector endpoint in a
production manifest.
