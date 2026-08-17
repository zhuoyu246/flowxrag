# Architecture

The original Python FastAPI application remains the RAG authority. Its
LangGraph workflow calls the existing FAISS + BM25 + RRF retriever; neither the
Gateway nor the Sync Service contains RAG business logic.

```text
Streamlit -> Go Gateway -> gRPC -> Python RAG (LangGraph -> FAISS + BM25 + RRF)
                         \-> legacy HTTP proxy -> FastAPI document/auth/SSE APIs

Canal/MySQL or producer -> Kafka -> Go Sync -> Redis document lock -> gRPC IndexDocument -> FAISS

Gateway / Sync / RAG -> OpenTelemetry Collector -> Jaeger
                                         \-----> Prometheus -> Grafana
```

`VECTOR_STORE=faiss` is mandatory. The index is a local file, so the supplied
RAG Deployment remains single-replica with a PVC. Scaling it safely requires a
separate shared-index design, not an environment-variable switch to Milvus.

Kafka keys must use `document_id`, preserving per-document ordering. The Sync
Service parses `INSERT`, `UPDATE`, and `DELETE`; it commits an offset only after
the FAISS operation succeeds, or after the failed message is persisted to the
DLQ.
