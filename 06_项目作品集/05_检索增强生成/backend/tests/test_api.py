import pytest
from fastapi.testclient import TestClient

from app.main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_capabilities(client):
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert "backends" in data
    assert len(data["backends"]) > 0


def test_strategies(client):
    response = client.get("/api/strategies")
    assert response.status_code == 200
    data = response.json()
    assert "strategies" in data


def test_documents(client):
    response = client.get("/api/knowledge/documents")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert isinstance(data["documents"], list)
    if data["documents"]:
        doc = data["documents"][0]
        assert "id" in doc and "title" in doc and "chunk_count" in doc


def test_retrieve_fast(client):
    response = client.post(
        "/api/retrieve",
        json={"query": "液压泵压力不足怎么办？", "mode": "fast"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "液压泵压力不足怎么办？"
    assert "evidence" in data
    assert "retrieval_trace" in data
    assert "steps" in data["retrieval_trace"]


def test_retrieve_balanced(client):
    response = client.post(
        "/api/retrieve",
        json={"query": "设备压力上不去应该先查哪里？", "mode": "balanced"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "设备压力上不去应该先查哪里？"
    assert len(data["evidence"]) > 0


def test_retrieve_deep(client):
    response = client.post(
        "/api/retrieve",
        json={"query": "销售额的计算公式是什么？", "mode": "deep", "method": "data_asset_lookup_v1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "data_asset_lookup_v1"
    assert len(data["data_assets"]) > 0


def test_retrieve_plan(client):
    response = client.post(
        "/api/retrieve/plan",
        json={"query": "质量异常处理流程是什么？", "mode": "reliable"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "resolved_method" in data


def test_methods_list(client):
    response = client.get("/api/methods")
    assert response.status_code == 200
    data = response.json()
    assert "methods" in data


def test_operators_list(client):
    response = client.get("/api/operators")
    assert response.status_code == 200
    data = response.json()
    assert "operators" in data
