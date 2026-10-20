from fastapi.testclient import TestClient
from scripted_llm.app import app

client = TestClient(app)


def test_chat_completion_is_openai_shaped_and_deterministic():
    body = {"model": "scripted", "messages": [{"role": "user", "content": "how much billet"}]}
    first = client.post("/v1/chat/completions", json=body).json()
    second = client.post("/v1/chat/completions", json=body).json()

    message = first["choices"][0]["message"]
    assert message["role"] == "assistant"
    assert message["content"] == second["choices"][0]["message"]["content"]
    assert "Received 3 words" in message["content"]


def test_usage_is_reported_so_the_gateway_can_attribute_cost():
    body = {
        "model": "scripted",
        "messages": [
            {"role": "system", "content": "You are a procurement assistant."},
            {"role": "user", "content": "hello"},
        ],
    }
    usage = client.post("/v1/chat/completions", json=body).json()["usage"]
    assert usage["prompt_tokens"] == 6
    assert usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_models_endpoint_lists_the_scripted_model():
    ids = [m["id"] for m in client.get("/v1/models").json()["data"]]
    assert ids == ["scripted"]
