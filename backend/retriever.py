from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import threading
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List

import faiss
import numpy as np
import requests
from pypdf import PdfReader


# RAG local storage. On the server, set CRAG_DATA_DIR to the data disk, for example:
# CRAG_DATA_DIR=/root/autodl-tmp/crag_expert_system
DATA_DIR = Path(os.getenv("CRAG_DATA_DIR", os.getenv("DATA_DIR", "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
INDEX_DIR = DATA_DIR / "indexes"
MODEL_CACHE_DIR = DATA_DIR / "models"

CHUNKS_PATH = INDEX_DIR / "chunks.json"
INDEX_PATH = INDEX_DIR / "faiss.index"
HASHING_DIM = int(os.getenv("HASHING_EMBED_DIM", "768"))
CHUNKING_STRATEGY = "parent_child_recursive"
DEFAULT_PARENT_CHUNK_SIZE = int(os.getenv("PARENT_CHUNK_SIZE", "2200"))
DEFAULT_PARENT_CHUNK_OVERLAP = int(os.getenv("PARENT_CHUNK_OVERLAP", "260"))
DEFAULT_CHILD_CHUNK_SIZE = int(os.getenv("CHILD_CHUNK_SIZE", "520"))
DEFAULT_CHILD_CHUNK_OVERLAP = int(os.getenv("CHILD_CHUNK_OVERLAP", "90"))
DEFAULT_BM25_K1 = float(os.getenv("BM25_K1", "1.5"))
DEFAULT_BM25_B = float(os.getenv("BM25_B", "0.75"))
DEFAULT_RRF_K = int(os.getenv("HYBRID_RRF_K", "60"))
DEFAULT_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "1.0"))
DEFAULT_BM25_WEIGHT = float(os.getenv("HYBRID_BM25_WEIGHT", "1.0"))
DEFAULT_OVERVIEW_BOOST = os.getenv("OVERVIEW_QUERY_BOOST", "true").strip().strip('"').strip("'").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
RECURSIVE_SEPARATORS = [
    "\n\n",
    "\n",
    "。 ",
    "。",
    "！",
    "？",
    ". ",
    "; ",
    "；",
    "，",
    ", ",
    " ",
]


@dataclass
class Chunk:
    id: str
    content: str
    source: str
    page: int
    chunk_index: int
    parent_id: str = ""
    parent_content: str = ""
    parent_index: int = 0
    child_index: int = 0
    chunking_strategy: str = "parent_child_recursive"


@dataclass
class SearchResult:
    content: str
    source: str
    page: int
    score: float
    retrieval_score: float | None = None


def ensure_data_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class EmbeddingBackend:
    """Embedding backend used by local RAG retrieval.

    Production path:
      Any OpenAI-compatible embedding API that exposes /v1/embeddings.

    Development fallback:
      sentence-transformers or hashing vectorizer.

    DeepSeek is still the remote LLM for grading/generation. It receives text
    evidence, not vectors.
    """

    def __init__(self) -> None:
        self.provider = "hashing"
        self.device = "cpu"
        self.dimension = HASHING_DIM
        self._model = None
        self._api_enabled = False
        self._last_error = ""
        self.api_base = ""
        self.model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        self._session = requests.Session()
        self._session.trust_env = False

        provider = os.getenv("EMBEDDING_PROVIDER", "sentence-transformers").lower()
        if provider in {"api", "openai", "openai-compatible", "vllm"}:
            if self._try_configure_api():
                return
            if os.getenv("EMBEDDING_STRICT", "false").lower() == "true":
                raise RuntimeError(f"Embedding API is not available: {self._last_error}")

        if provider in {"sentence-transformers", "sentence_transformers", "api", "openai", "openai-compatible", "vllm"}:
            self._try_load_sentence_transformer()

    def _try_configure_api(self) -> bool:
        self.api_base = os.getenv("EMBEDDING_API_BASE", "http://127.0.0.1:8010/v1").rstrip("/")
        self.model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.dimension = int(os.getenv("EMBEDDING_DIMENSION", "1024"))
        try:
            vectors = self._embed_api_batch(
                ["embedding health check"],
                timeout=float(os.getenv("EMBEDDING_STARTUP_TIMEOUT", "3")),
            )
            self.dimension = int(vectors.shape[1])
            self.device = "remote-api"
            self.provider = f"api:{self.model_name}"
            self._api_enabled = True
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def _try_load_sentence_transformer(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            model_name = os.getenv(
                "EMBEDDING_MODEL",
                "BAAI/bge-small-zh-v1.5",
            )
            device = resolve_embedding_device()
            self._model = SentenceTransformer(
                model_name,
                cache_folder=str(MODEL_CACHE_DIR),
                device=device,
            )
            self.device = device
            self.provider = f"sentence-transformers:{model_name}"
            self.dimension = int(self._model.get_sentence_embedding_dimension())
        except Exception:
            self._model = None

    def embed(self, texts: List[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")

        if self._api_enabled:
            return self._embed_api(texts)

        if self._model is not None:
            batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
            vectors = self._model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            return np.asarray(vectors, dtype="float32")

        vectors = np.vstack([self._hashing_embed(text) for text in texts]).astype("float32")
        faiss.normalize_L2(vectors)
        return vectors

    def _embed_api(self, texts: List[str]) -> np.ndarray:
        batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "64"))
        batches = []
        for start in range(0, len(texts), batch_size):
            batches.append(self._embed_api_batch(texts[start : start + batch_size]))
        return np.vstack(batches).astype("float32")

    def _embed_api_batch(self, texts: List[str], timeout: float | None = None) -> np.ndarray:
        headers = {}
        api_key = os.getenv("EMBEDDING_API_KEY", "").strip().strip('"').strip("'")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        response = self._session.post(
            f"{self.api_base}/embeddings",
            headers=headers,
            json={
                "model": self.model_name,
                "input": texts,
                "encoding_format": "float",
            },
            timeout=timeout or float(os.getenv("EMBEDDING_TIMEOUT", "120")),
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload["data"], key=lambda item: item.get("index", 0))
        vectors = np.asarray([item["embedding"] for item in data], dtype="float32")
        faiss.normalize_L2(vectors)
        return vectors

    def stats(self) -> dict:
        return {
            "provider": self.provider,
            "device": self.device,
            "api_base": self.api_base,
            "dimension": self.dimension,
            "last_error": self._last_error,
        }

    def _hashing_embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype="float32")
        for token in tokenize(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        return vector


def tokenize(text: str) -> Iterable[str]:
    """Simple tokenizer used only by the hashing fallback."""
    text = text.lower()

    for word in re.findall(r"[a-z0-9_]+", text):
        yield word

    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(phrase) <= 2:
            yield phrase
            continue
        for size in (2, 3):
            for index in range(0, len(phrase) - size + 1):
                yield phrase[index : index + size]


def resolve_embedding_device() -> str:
    configured = os.getenv("EMBEDDING_DEVICE", "auto").strip().lower()
    if configured and configured != "auto":
        return configured

    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00ad", "")
    text = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().strip('"').strip("'").lower() in {"1", "true", "yes", "on"}


def split_text(text: str, chunk_size: int = 900, overlap: int = 160) -> List[str]:
    """Recursively split text into separator-aware overlapping chunks."""
    text = clean_text(text)
    if not text:
        return []

    segments = _split_by_separators(text, chunk_size, RECURSIVE_SEPARATORS)
    return _merge_segments(segments, chunk_size, overlap)


def _split_by_separators(text: str, chunk_size: int, separators: List[str]) -> List[str]:
    if len(text) <= chunk_size:
        return [text]

    if not separators:
        return _hard_split_text(text, chunk_size)

    separator = separators[0]
    pieces = text.split(separator)
    if len(pieces) == 1:
        return _split_by_separators(text, chunk_size, separators[1:])

    segments = []
    for index, piece in enumerate(pieces):
        if not piece:
            continue
        segment = piece + (separator if index < len(pieces) - 1 else "")
        if len(segment) > chunk_size:
            segments.extend(_split_by_separators(segment, chunk_size, separators[1:]))
        else:
            segments.append(segment)
    return segments


def _merge_segments(segments: List[str], chunk_size: int, overlap: int) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for segment in segments:
        segment = clean_text(segment)
        if not segment:
            continue

        separator_len = 1 if current else 0
        if current and current_len + separator_len + len(segment) > chunk_size:
            chunk = " ".join(current).strip()
            if chunk:
                chunks.append(chunk)
            overlap_text = _tail_overlap(chunk, overlap)
            current = [overlap_text] if overlap_text else []
            current_len = len(overlap_text)

        current.append(segment)
        current_len += (1 if current_len else 0) + len(segment)

    if current:
        chunk = " ".join(current).strip()
        if chunk:
            chunks.append(chunk)

    return chunks


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return ""
    return text[-overlap:].strip()


def _hard_split_text(text: str, chunk_size: int) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end
    return chunks


def bm25_tokenize(text: str) -> List[str]:
    """Tokenize mixed Chinese/English technical text for local BM25 search."""
    text = (text or "").lower()
    tokens: List[str] = []

    for token in re.findall(r"[a-z0-9]+(?:[-_./][a-z0-9]+)*%?", text):
        tokens.append(token)
        for part in re.split(r"[-_./]", token):
            if part and part != token:
                tokens.append(part)

    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(phrase) <= 2:
            tokens.append(phrase)
            continue
        for size in (2, 3):
            for index in range(0, len(phrase) - size + 1):
                tokens.append(phrase[index : index + size])

    return tokens


def is_document_overview_query(query: str) -> bool:
    query = clean_text(query).lower()
    if not query:
        return False

    overview_phrases = (
        "讲什么",
        "写什么",
        "写的什么",
        "写得什么",
        "说什么",
        "是啥",
        "干嘛",
        "主要内容",
        "核心内容",
        "总结",
        "概括",
        "概述",
        "摘要",
        "介绍一下",
        "这篇",
        "这份",
        "这个文档",
        "这篇论文",
        "这篇文章",
        "论文内容",
        "文档内容",
        "what is this",
        "summarize",
        "summary",
        "overview",
    )
    return any(phrase in query for phrase in overview_phrases)


class BM25Index:
    """Small in-memory BM25 index over child chunks."""

    def __init__(self) -> None:
        self.enabled = env_bool("BM25_ENABLED", True)
        self.k1 = DEFAULT_BM25_K1
        self.b = DEFAULT_BM25_B
        self.doc_count = 0
        self.avg_doc_len = 0.0
        self.doc_lens: List[int] = []
        self.term_freqs: List[Counter[str]] = []
        self.idf: dict[str, float] = {}

    def rebuild(self, chunks: List[Chunk]) -> None:
        self.doc_count = len(chunks)
        self.doc_lens = []
        self.term_freqs = []
        self.idf = {}
        if not chunks:
            self.avg_doc_len = 0.0
            return

        document_frequency: Counter[str] = Counter()
        for chunk in chunks:
            tokens = bm25_tokenize(chunk.content)
            term_frequency = Counter(tokens)
            self.term_freqs.append(term_frequency)
            self.doc_lens.append(len(tokens))
            document_frequency.update(term_frequency.keys())

        self.avg_doc_len = sum(self.doc_lens) / max(self.doc_count, 1)
        self.idf = {
            term: math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    def search(self, query: str, top_k: int) -> List[tuple[int, float]]:
        if not self.enabled or not self.term_freqs or top_k <= 0:
            return []

        query_terms = bm25_tokenize(query)
        if not query_terms or self.avg_doc_len <= 0:
            return []

        query_counts = Counter(query_terms)
        scored: List[tuple[int, float]] = []
        for doc_index, term_frequency in enumerate(self.term_freqs):
            doc_len = self.doc_lens[doc_index] or 1
            score = 0.0
            length_norm = self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_len)
            for term, query_weight in query_counts.items():
                freq = term_frequency.get(term, 0)
                if not freq:
                    continue
                score += query_weight * self.idf.get(term, 0.0) * (freq * (self.k1 + 1)) / (freq + length_norm)
            if score > 0:
                scored.append((doc_index, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "algorithm": "BM25Okapi",
            "documents": self.doc_count,
            "avg_doc_len": round(self.avg_doc_len, 2),
            "k1": self.k1,
            "b": self.b,
        }


class RerankerBackend:
    """Optional rerank API.

    Supports common BGE/Jina/SiliconFlow-style rerank endpoints:
      POST {RERANK_API_BASE}/rerank
      {"model": "...", "query": "...", "documents": [...], "top_n": 5}
    """

    def __init__(self) -> None:
        self.enabled = env_bool("RERANK_ENABLED", False)
        self.provider = os.getenv("RERANK_PROVIDER", "api").strip().lower()
        self.api_base = os.getenv("RERANK_API_BASE", "").strip().rstrip("/")
        self.model_name = os.getenv("RERANK_MODEL", "rerank-v4.0-fast").strip()
        self.active_model = ""
        self._last_error = ""
        self._session = requests.Session()
        self._session.trust_env = False

        if self.enabled and not self.api_base:
            self.enabled = False
            self._last_error = "RERANK_API_BASE is empty."

    def rerank(self, query: str, results: List[SearchResult], top_k: int) -> List[SearchResult]:
        if not self.enabled or not results:
            return results[:top_k]

        try:
            ranked = self._rerank_api(query, results, top_k)
            self._last_error = ""
            return ranked
        except Exception as exc:
            self._last_error = str(exc)
            return results[:top_k]

    def _rerank_api(self, query: str, results: List[SearchResult], top_k: int) -> List[SearchResult]:
        headers = {}
        api_key = os.getenv("RERANK_API_KEY", "").strip().strip('"').strip("'")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        endpoint = self.api_base if self.api_base.endswith("/rerank") else f"{self.api_base}/rerank"
        last_error = None
        response = None
        for model_name in self._candidate_models():
            response = self._session.post(
                endpoint,
                headers=headers,
                json={
                    "model": model_name,
                    "query": query,
                    "documents": [result.content for result in results],
                    "top_n": top_k,
                    "return_documents": False,
                },
                timeout=float(os.getenv("RERANK_TIMEOUT", "60")),
            )
            if response.status_code < 400:
                self.active_model = model_name
                break

            last_error = f"{response.status_code} {response.text[:500]}"
            if response.status_code in {401, 403}:
                break
            response = None

        if response is None:
            raise RuntimeError(last_error or "Rerank API failed.")

        response.raise_for_status()
        payload = response.json()
        items = payload.get("results") or payload.get("data") or payload.get("documents") or []

        ranked = []
        for item in items:
            index = item.get("index")
            if index is None and isinstance(item.get("document"), dict):
                index = item["document"].get("index")
            if index is None:
                continue
            index = int(index)
            if index < 0 or index >= len(results):
                continue

            score = item.get("relevance_score", item.get("score", item.get("rank_score")))
            result = results[index]
            ranked.append(
                SearchResult(
                    content=result.content,
                    source=result.source,
                    page=result.page,
                    score=round(float(score), 4) if score is not None else result.score,
                    retrieval_score=result.retrieval_score if result.retrieval_score is not None else result.score,
                )
            )

        if not ranked:
            return results[:top_k]
        return ranked[:top_k]

    def _candidate_models(self) -> List[str]:
        configured = os.getenv("RERANK_MODEL", self.model_name)
        models = [item.strip() for item in configured.split(",") if item.strip()]
        if not models:
            models = ["rerank-v4.0-fast"]
        return models

    def stats(self) -> dict:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "api_base": self.api_base,
            "model": self.model_name,
            "active_model": self.active_model,
            "last_error": self._last_error,
        }


class KnowledgeBase:
    """Minimal production RAG store: PDF -> chunks -> embeddings -> FAISS."""

    def __init__(self) -> None:
        ensure_data_dirs()
        self._lock = threading.Lock()
        self.embedding = EmbeddingBackend()
        self.reranker = RerankerBackend()
        self.bm25 = BM25Index()
        self.chunks: List[Chunk] = self._load_chunks()
        self.bm25.rebuild(self.chunks)
        self.index = self._load_or_rebuild_index()

    def _load_chunks(self) -> List[Chunk]:
        if not CHUNKS_PATH.exists():
            return []
        data = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
        return [self._chunk_from_dict(item) for item in data]

    def _chunk_from_dict(self, item: dict) -> Chunk:
        content = item.get("content", "")
        page = int(item.get("page", 0) or 0)
        chunk_index = int(item.get("chunk_index", 0) or 0)
        parent_id = item.get("parent_id") or item.get("id") or str(uuid.uuid4())
        parent_content = item.get("parent_content") or content
        return Chunk(
            id=item.get("id") or str(uuid.uuid4()),
            content=content,
            source=item.get("source", ""),
            page=page,
            chunk_index=chunk_index,
            parent_id=parent_id,
            parent_content=parent_content,
            parent_index=int(item.get("parent_index", chunk_index) or 0),
            child_index=int(item.get("child_index", 0) or 0),
            chunking_strategy=item.get("chunking_strategy") or "legacy_flat",
        )

    def _save_chunks(self) -> None:
        CHUNKS_PATH.write_text(
            json.dumps([asdict(chunk) for chunk in self.chunks], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_or_rebuild_index(self):
        if INDEX_PATH.exists() and self.chunks:
            try:
                index = faiss.read_index(str(INDEX_PATH))
                if index.d == self.embedding.dimension and index.ntotal == len(self.chunks):
                    return index
            except Exception:
                pass
        return self._rebuild_index()

    def _rebuild_index(self):
        # Cosine similarity = inner product over normalized vectors.
        index = faiss.IndexFlatIP(self.embedding.dimension)
        if self.chunks:
            vectors = self.embedding.embed([chunk.content for chunk in self.chunks])
            index.add(vectors)
        faiss.write_index(index, str(INDEX_PATH))
        self.bm25.rebuild(self.chunks)
        return index

    def save_upload(self, upload_file) -> Path:
        safe_name = re.sub(r"[^a-zA-Z0-9._\-\u4e00-\u9fff]+", "_", upload_file.filename)
        target = UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe_name}"
        with target.open("wb") as output:
            shutil.copyfileobj(upload_file.file, output)
        return target

    def add_pdf(self, file_path: Path, source_name: str) -> dict:
        """Ingestion pipeline: parse PDF, create parent-child chunks, rebuild FAISS."""
        reader = PdfReader(str(file_path))
        new_chunks = self._chunks_from_reader(reader, source_name)

        with self._lock:
            self.chunks.extend(new_chunks)
            self._save_chunks()
            self.index = self._rebuild_index()

        return {
            "source": source_name,
            "pages": len(reader.pages),
            "chunks_added": len(new_chunks),
            "parent_chunks_added": len({chunk.parent_id for chunk in new_chunks}),
            "total_chunks": len(self.chunks),
        }

    def rebuild_from_uploads(self) -> dict:
        """Rebuild all indexed chunks from PDFs already saved in the upload dir."""
        all_chunks: List[Chunk] = []
        sources = []
        pages = 0

        for pdf_path in sorted(UPLOAD_DIR.glob("*.pdf")):
            source_name = self._display_source_name(pdf_path)
            reader = PdfReader(str(pdf_path))
            pages += len(reader.pages)
            sources.append(source_name)
            all_chunks.extend(self._chunks_from_reader(reader, source_name))

        with self._lock:
            self.chunks = all_chunks
            self._save_chunks()
            self.index = self._rebuild_index()

        return {
            "sources": sources,
            "source_count": len(sources),
            "pages": pages,
            "chunks": len(self.chunks),
            "parent_chunks": len({chunk.parent_id for chunk in self.chunks}),
            "chunking_strategy": CHUNKING_STRATEGY,
        }

    def delete_source(self, source_name: str) -> dict:
        """Delete one indexed document and its uploaded PDF copies."""
        source_name = source_name.strip()
        if not source_name:
            return {"source": source_name, "chunks_removed": 0, "uploads_deleted": 0}

        deleted_uploads = self._delete_upload_files(source_name)

        with self._lock:
            before = len(self.chunks)
            self.chunks = [chunk for chunk in self.chunks if chunk.source != source_name]
            chunks_removed = before - len(self.chunks)
            self._save_chunks()
            self.index = self._rebuild_index()

        return {
            "source": source_name,
            "chunks_removed": chunks_removed,
            "uploads_deleted": len(deleted_uploads),
            "deleted_uploads": deleted_uploads,
            "chunks": len(self.chunks),
            "parent_chunks": len({chunk.parent_id or chunk.id for chunk in self.chunks}),
        }

    def _chunks_from_reader(self, reader: PdfReader, source_name: str) -> List[Chunk]:
        chunks: List[Chunk] = []

        for page_number, page in enumerate(reader.pages, start=1):
            page_text = clean_text(page.extract_text() or "")
            parent_texts = split_text(
                page_text,
                chunk_size=DEFAULT_PARENT_CHUNK_SIZE,
                overlap=DEFAULT_PARENT_CHUNK_OVERLAP,
            )

            for parent_index, parent_text in enumerate(parent_texts):
                parent_id = str(uuid.uuid4())
                child_texts = split_text(
                    parent_text,
                    chunk_size=DEFAULT_CHILD_CHUNK_SIZE,
                    overlap=DEFAULT_CHILD_CHUNK_OVERLAP,
                )
                if not child_texts:
                    child_texts = [parent_text]

                for child_index, child_text in enumerate(child_texts):
                    chunks.append(
                        Chunk(
                            id=str(uuid.uuid4()),
                            content=child_text,
                            source=source_name,
                            page=page_number,
                            chunk_index=len(chunks),
                            parent_id=parent_id,
                            parent_content=parent_text,
                            parent_index=parent_index,
                            child_index=child_index,
                            chunking_strategy=CHUNKING_STRATEGY,
                        )
                    )

        return chunks

    def _display_source_name(self, file_path: Path) -> str:
        return re.sub(r"^[0-9a-f]{32}_", "", file_path.name, flags=re.IGNORECASE)

    def _upload_files_for_source(self, source_name: str) -> List[Path]:
        return [
            file_path
            for file_path in sorted(UPLOAD_DIR.glob("*.pdf"))
            if self._display_source_name(file_path) == source_name or file_path.name == source_name
        ]

    def _delete_upload_files(self, source_name: str) -> List[str]:
        deleted = []
        upload_dir = UPLOAD_DIR.resolve()
        for file_path in self._upload_files_for_source(source_name):
            resolved = file_path.resolve()
            if not resolved.is_relative_to(upload_dir):
                raise RuntimeError(f"Refusing to delete outside upload dir: {resolved}")
            resolved.unlink(missing_ok=True)
            deleted.append(resolved.name)
        return deleted

    def search(self, query: str, top_k: int = 5, min_score: float = 0.08) -> List[SearchResult]:
        """Hybrid retrieval: FAISS dense search + BM25 sparse search + RRF fusion."""
        with self._lock:
            if not self.chunks or self.index.ntotal == 0:
                return []
            overview_results = self._overview_results(top_k) if DEFAULT_OVERVIEW_BOOST and is_document_overview_query(query) else []
            query_vector = self.embedding.embed([query])
            candidate_k = int(os.getenv("RETRIEVER_CANDIDATE_K", str(max(top_k * 8, top_k))))
            candidate_k = min(candidate_k, len(self.chunks))
            scores, indices = self.index.search(query_vector, candidate_k)
            bm25_candidate_k = int(os.getenv("BM25_CANDIDATE_K", str(candidate_k)))
            bm25_candidate_k = min(bm25_candidate_k, len(self.chunks))
            bm25_hits = self.bm25.search(query, bm25_candidate_k)
            chunks = list(self.chunks)

        vector_hits: List[tuple[int, float]] = []
        for score, index in zip(scores[0], indices[0]):
            score = float(score)
            if index < 0 or not math.isfinite(score) or score < min_score:
                continue
            vector_hits.append((int(index), score))

        fused_scores = self._rrf_fuse(vector_hits, bm25_hits)
        parent_hits: dict[str, SearchResult] = {}
        for index, fused_score in sorted(fused_scores.items(), key=lambda item: item[1], reverse=True):
            if index < 0 or index >= len(chunks):
                continue
            chunk = chunks[index]
            parent_key = chunk.parent_id or chunk.id
            result = SearchResult(
                content=chunk.parent_content or chunk.content,
                source=chunk.source,
                page=chunk.page,
                score=round(fused_score, 4),
                retrieval_score=round(fused_score, 4),
            )
            existing = parent_hits.get(parent_key)
            if existing is None or result.score > existing.score:
                parent_hits[parent_key] = result

        results = sorted(parent_hits.values(), key=lambda result: result.score, reverse=True)
        results = self._merge_search_results(overview_results, results, top_k)
        return self.reranker.rerank(query, results, top_k)

    def _overview_results(self, top_k: int) -> List[SearchResult]:
        parent_chunks: dict[str, Chunk] = {}
        for chunk in self.chunks:
            parent_key = chunk.parent_id or chunk.id
            if parent_key not in parent_chunks:
                parent_chunks[parent_key] = chunk

        scored = sorted(
            parent_chunks.values(),
            key=lambda chunk: self._overview_score(chunk),
            reverse=True,
        )
        results = []
        for chunk in scored[:top_k]:
            score = self._overview_score(chunk)
            results.append(
                SearchResult(
                    content=chunk.parent_content or chunk.content,
                    source=chunk.source,
                    page=chunk.page,
                    score=round(score, 4),
                    retrieval_score=round(score, 4),
                )
            )
        return results

    def _overview_score(self, chunk: Chunk) -> float:
        text = (chunk.parent_content or chunk.content or "").lower()
        score = 1.0
        if chunk.page <= 2:
            score += 3.0
        if chunk.parent_index == 0:
            score += 2.0
        if any(marker in text for marker in ("abstract", "a b s t r a c t", "摘要")):
            score += 4.0
        if any(marker in text for marker in ("introduction", "related work", "引言", "背景")):
            score += 2.0
        if any(marker in text for marker in ("conclusion", "conclusions", "结论", "summary")):
            score += 3.0
        return score

    def _merge_search_results(
        self,
        primary: List[SearchResult],
        secondary: List[SearchResult],
        top_k: int,
    ) -> List[SearchResult]:
        merged: List[SearchResult] = []
        seen = set()
        for result in primary + secondary:
            key = (result.source, result.page, result.content[:160])
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
            if len(merged) >= top_k:
                break
        return merged

    def _rrf_fuse(
        self,
        vector_hits: List[tuple[int, float]],
        bm25_hits: List[tuple[int, float]],
    ) -> dict[int, float]:
        rrf_k = DEFAULT_RRF_K
        fused_scores: defaultdict[int, float] = defaultdict(float)

        for rank, (index, _score) in enumerate(vector_hits, start=1):
            fused_scores[index] += DEFAULT_VECTOR_WEIGHT / (rrf_k + rank)

        for rank, (index, _score) in enumerate(bm25_hits, start=1):
            fused_scores[index] += DEFAULT_BM25_WEIGHT / (rrf_k + rank)

        return dict(fused_scores)

    def clear(self) -> None:
        with self._lock:
            self.chunks = []
            self._save_chunks()
            self.index = self._rebuild_index()

    def stats(self) -> dict:
        sources = sorted({chunk.source for chunk in self.chunks})
        parent_count = len({chunk.parent_id or chunk.id for chunk in self.chunks})
        chunk_counts = Counter(chunk.source for chunk in self.chunks)
        documents = []
        for source in sources:
            source_chunks = [chunk for chunk in self.chunks if chunk.source == source]
            documents.append(
                {
                    "source": source,
                    "chunks": chunk_counts[source],
                    "parent_chunks": len({chunk.parent_id or chunk.id for chunk in source_chunks}),
                    "upload_count": len(self._upload_files_for_source(source)),
                }
            )
        return {
            "chunks": len(self.chunks),
            "parent_chunks": parent_count,
            "chunking_strategy": CHUNKING_STRATEGY,
            "parent_chunk_size": DEFAULT_PARENT_CHUNK_SIZE,
            "parent_chunk_overlap": DEFAULT_PARENT_CHUNK_OVERLAP,
            "child_chunk_size": DEFAULT_CHILD_CHUNK_SIZE,
            "child_chunk_overlap": DEFAULT_CHILD_CHUNK_OVERLAP,
            "retrieval_mode": "hybrid_vector_bm25_rrf" if self.bm25.enabled else "vector",
            "hybrid": {
                "fusion": "reciprocal_rank_fusion",
                "rrf_k": DEFAULT_RRF_K,
                "vector_weight": DEFAULT_VECTOR_WEIGHT,
                "bm25_weight": DEFAULT_BM25_WEIGHT,
            },
            "bm25": self.bm25.stats(),
            "sources": sources,
            "documents": documents,
            "source_count": len(sources),
            "embedding_provider": self.embedding.provider,
            "embedding_device": self.embedding.device,
            "embedding_api_base": self.embedding.api_base,
            "embedding_dimension": self.embedding.dimension,
            "embedding": self.embedding.stats(),
            "reranker": self.reranker.stats(),
            "data_dir": str(DATA_DIR),
            "model_cache_dir": str(MODEL_CACHE_DIR),
        }


knowledge_base = KnowledgeBase()
