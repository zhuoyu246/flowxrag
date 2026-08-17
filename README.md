# RAGFlowX

> 面向企业知识库场景的 CRAG（Corrective RAG）问答系统：保留本地 FAISS 检索能力，并完成 Go 网关、gRPC、Kafka CDC、可观测性与容器化部署升级。

## 项目亮点

- **纠错式检索问答**：以 LangGraph 编排问题路由、混合检索、结果纠偏、联网兜底与回答生成。
- **混合检索**：FAISS 向量检索、BM25 关键词检索与 RRF 融合排序；支持可选 Rerank。
- **微服务通信**：Gin 网关与 Python RAG 服务通过 Protobuf/gRPC 通信，保留原有 FastAPI 接口兼容前端。
- **增量索引**：MySQL 文档元数据变更由 Canal 解析 binlog，投递 Kafka 后异步刷新 FAISS 索引。
- **可靠消费**：Sync Service 采用 Redis 文档锁、手动提交 Offset、指数重试与 DLQ，避免重复消费和消息丢失。
- **工程化治理**：JWT、Redis 滑动窗口限流、熔断、OpenTelemetry、Prometheus、Grafana、Jaeger、Docker Compose、Kubernetes 与 Jenkins。

## 架构概览

可编辑架构图：[ragflowx-architecture.drawio](docs/images/ragflowx-architecture.drawio)。

```text
Streamlit UI → Go Gateway (Gin) → gRPC → Python RAG Service → FAISS
                    │                         │
                 Redis                  FastAPI / LangGraph

MySQL → Canal → Kafka → Go Sync Service → gRPC IndexDocument → FAISS
```

| 组件 | 职责 |
| --- | --- |
| `gateway/` | Gin API 网关；JWT、Redis 限流、熔断、Trace 透传、gRPC 调用与旧接口代理。 |
| `rag-service/` | Python gRPC 适配层；复用原 FastAPI、LangGraph、FAISS、BM25、RRF 核心逻辑。 |
| `sync-service/` | Kafka 消费者；解析 Canal JSON、Redis 分布式锁、重试/DLQ 与索引 RPC。 |
| `backend/` | 原有 FastAPI 业务、文档管理、CRAG 图编排、会话与鉴权能力。 |
| `deploy/` | Docker Compose、Canal/MySQL 配置、Kubernetes、Jenkins 与监控配置。 |

## 技术栈

| 分类 | 技术 |
| --- | --- |
| RAG | Python、FastAPI、LangGraph、FAISS、BM25、RRF、OpenAI-compatible LLM、Tavily |
| 微服务 | Go、Gin、Protobuf、gRPC、Kafka、Redis、MySQL、PostgreSQL |
| 可观测性 | OpenTelemetry、Prometheus、Grafana、Jaeger |
| 工程化 | Docker、Docker Compose、Kubernetes、Jenkins、GitHub Actions |

## 快速开始

### 1. 配置环境变量

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，仅填写自己申请的模型、Embedding、搜索服务等密钥。**`.env` 不会且不应被提交。**

最小配置示例：

```env
OPENAI_API_KEY=""
OPENAI_API_BASE="https://api.deepseek.com"
OPENAI_MODEL="deepseek-chat"
EMBEDDING_API_KEY=""
TAVILY_API_KEY=""
```

### 2. 一键启动完整开发环境

确保 Docker Desktop 已启动后执行：

```powershell
docker compose -f deploy/docker-compose-dev.yml up -d --build
docker compose -f deploy/docker-compose-dev.yml ps
```

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| 前端 | `http://localhost:8501` | Streamlit 知识库问答界面 |
| API 网关 | `http://localhost:8080` | 对外 HTTP 入口 |
| RAG FastAPI | `http://localhost:8000/docs` | 原有接口与 OpenAPI 文档 |
| RAG gRPC | `localhost:50051` | Chat / Search / IndexDocument RPC |

健康检查：

```powershell
Invoke-WebRequest http://localhost:8080/ready
Invoke-WebRequest http://localhost:8000/health
```

### 3. 本地运行原始应用（可选）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
```

另开终端启动前端：

```powershell
streamlit run frontend/app.py --server.port 8501
```

## 文档与索引链路

1. 用户上传 PDF，FastAPI 保存文件并写入文档元数据。
2. RAG 服务执行 PDF 解析、分块与 FAISS/BM25 索引。
3. 启用 CDC 时，文档元数据写入 MySQL `rag_cdc.document_records`。
4. Canal 订阅 ROW 格式 binlog，将 flat JSON 事件投递到 Kafka `rag-document-change`。
5. Go Sync Service 消费事件，使用 `rag:document:lock:{documentID}` Redis Token Lock 串行化同一文档。
6. 消费成功后才提交 Kafka Offset；多次失败会写入 `rag-document-dlq`。
7. Sync Service 经 gRPC 调用 `IndexDocument`，以幂等方式更新或删除 FAISS 索引。

本地查看 CDC 状态：

```powershell
docker compose -f deploy/docker-compose-dev.yml logs --tail=100 canal sync-service
docker compose -f deploy/docker-compose-dev.yml exec mysql mysql -urag_cdc -prag-cdc-local-only rag_cdc -e "SELECT id, source, status, updated_at FROM document_records;"
```

## 核心接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | RAG 服务健康状态与索引统计 |
| `GET` | `/documents` | 知识库统计 |
| `POST` | `/documents/upload` | 同步上传 PDF 并入库 |
| `POST` | `/api/v1/documents/upload/async` | 异步上传 PDF |
| `DELETE` | `/documents/source?source={name}` | 删除指定文档及其索引 |
| `POST` | `/documents/reindex` | 根据本地上传目录重建索引 |
| `POST` | `/chat` | 非流式问答 |
| `POST` | `/chat/stream` | SSE 流式问答 |
| `POST` | `/search` | 通过网关调用 gRPC 检索 |

## 可观测性与部署

- 指标：Gateway、RAG、Sync Service 均暴露 Prometheus 指标；Sync Service 包含 Kafka 消费结果、处理耗时和消费者滞后指标。
- 链路：HTTP、Kafka 与 gRPC 通过 W3C Trace Context 透传；设置 `OTEL_ENABLED=true` 后可导出至 OTLP Collector。
- 容器：开发环境使用 `deploy/docker-compose-dev.yml`；生产部署示例位于 `deploy/k8s/`。
- CI/CD：Jenkins 流水线定义位于 `deploy/jenkins/Jenkinsfile`。

更多说明：

- [系统架构](docs/architecture.md)
- [本地开发与 CDC 验证](docs/local_dev.md)
- [可观测性](docs/observability.md)
- [CI/CD](docs/cicd.md)
- [常见问题](docs/pitfall.md)

## 验证

```powershell
pytest -q
go test ./...
go vet ./...
docker compose -f deploy/docker-compose-dev.yml config
```

## 安全提交清单

提交前请确认以下命令没有输出真实密钥或本地数据：

```powershell
git ls-files .env data/uploads data/indexes
git status --short --ignored
```

仓库已忽略 `.env`、私钥、上传文件、FAISS 索引、评估结果、日志与虚拟环境。只提交 `.env.example` 中的空占位符，**禁止提交任何 API Key、Token、密码或生产连接串。**

## License

This project is intended for learning, technical demonstration, and internal knowledge-base prototyping.
