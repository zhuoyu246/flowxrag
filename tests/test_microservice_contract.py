from __future__ import annotations

import sys
from pathlib import Path

import pytest


def test_only_faiss_vector_store_is_supported():
    from backend.core.config import Settings

    assert Settings(vector_store="FAISS").vector_store == "faiss"
    with pytest.raises(ValueError, match="VECTOR_STORE=faiss"):
        Settings(vector_store="milvus")


def test_grpc_contract_exposes_required_rag_methods():
    generated_path = Path(__file__).parents[1] / "rag-service" / "grpc"
    sys.path.insert(0, str(generated_path))
    try:
        import rag_pb2

        methods = rag_pb2.DESCRIPTOR.services_by_name["RagService"].methods_by_name
        assert {"Chat", "Search", "IndexDocument", "Health"}.issubset(methods)
    finally:
        sys.path.remove(str(generated_path))
