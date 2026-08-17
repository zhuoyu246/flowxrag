# Operational pitfalls

1. Never commit an offset before the document is indexed. The implementation
   commits only after a successful gRPC call or a successful DLQ publication.
2. A Redis document lock needs a TTL and token-checked release. Deleting a lock
   blindly can remove another consumer's lease after expiry.
3. ConfigMaps contain addresses and tuning only. Database passwords, DeepSeek,
   Tavily, and JWT keys belong in a Secret or local `.env`.
4. Native HPA uses CPU and memory here. Kafka lag needs Kafka exporter,
   Prometheus, and Prometheus Adapter before it can become an HPA signal.
5. HTTP, gRPC, and Kafka require W3C context propagation; otherwise a trace
   breaks at the service boundary.
6. Do not put API keys in a Dockerfile. Also distinguish readiness from
   liveness: a non-ready pod must not receive traffic.
