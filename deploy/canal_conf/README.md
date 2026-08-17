# MySQL → Canal → Kafka CDC

`docker compose -f deploy/docker-compose-dev.yml up -d` starts a MySQL 8
source database and Canal Server alongside the original PostgreSQL application
database. The FastAPI document routes maintain `rag_cdc.document_records`; its
ROW-format binlog is filtered by Canal and published as flat JSON to
`rag-document-change`.

The Go `sync-service` accepts both this Canal payload and the project's compact
fallback event. It takes a Redis token lock, calls `IndexDocument` over gRPC,
and the Python RAG service idempotently refreshes the FAISS index. A failed
message is retried, then written to `rag-document-dlq`; Kafka offset is committed
only after success, an ignored Canal control event, or durable DLQ publication.

For a quick local verification after the stack is healthy:

```powershell
docker compose -f deploy/docker-compose-dev.yml exec mysql mysql -urag_cdc -prag-cdc-local-only rag_cdc -e "SELECT id, source, status, updated_at FROM document_records;"
docker compose -f deploy/docker-compose-dev.yml logs --tail=100 canal sync-service
```

The bundled user/password values are deliberately local-development only. Set
strong secrets and enable TLS/SASL, restricted MySQL replication grants, Canal
HA, and a retained Kafka topic before production use.
