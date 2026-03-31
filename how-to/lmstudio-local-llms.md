# LM Studio: Local LLMs

LM Studio runs **large language models** locally and exposes an **OpenAI-compatible API**. Your agent calls it like OpenAI—but data stays on your machine.

---

## 1. How to Install

### 1.1 Prerequisites

- macOS, Windows, or Linux
- Sufficient RAM (e.g. 16 GB+ for 7B models; more for 20B+)
- (Optional) GPU (NVIDIA, Apple Silicon, etc.) for faster inference

### 1.2 Install LM Studio

1. Go to https://lmstudio.ai/
2. Download for your OS.
3. Install and launch LM Studio.

**Headless (no GUI, for servers):**

```bash
# Mac / Linux
curl -fsSL https://lmstudio.ai/install.sh | bash
```

### 1.3 Download a Model

1. In LM Studio, open the **Discover** (or Search) tab.
2. Search for a model, e.g. `gpt-oss`, `Qwen3`, `Llama`, `Phi`.
3. Click **Download** and choose a quantization (e.g. Q4_K_M for balance of size/quality).
4. Wait for the download to complete.

**Example models:**

| Model | Size | Use Case |
|-------|------|----------|
| `openai/gpt-oss-20b` | ~12 GB | Strong reasoning, good for planning/advice |
| `qwen3-8b` | ~5 GB | General chat, smaller footprint |
| `phi-3` | ~2 GB | Fast, lightweight |

### 1.4 Enable the Local Server

1. Open the **Local Server** (or API) tab in LM Studio.
2. Select the model you want to serve.
3. Click **Start Server** (or equivalent).
4. Note the URL: usually `http://localhost:1234/v1`.

### 1.5 Verify

```bash
curl -s http://localhost:1234/v1/models
```

You should see JSON with your model’s `id`. Use that exact `id` in your backend config.

### 1.6 Python Client

```bash
pip install openai
# or, for LangChain:
pip install langchain-openai
```

---

## 2. Why Use LM Studio for Your Agent

| Benefit | Description |
|---------|-------------|
| **Local & private** | No data sent to external APIs. |
| **OpenAI-compatible** | Use the same client code as with OpenAI; just change `base_url`. |
| **Multi-role** | One model for planner, advisor, evaluator—different prompts per role. |
| **Vision models** | Load models like Qwen-VL for document OCR / image understanding. |
| **No API keys** | Free to run; no usage limits. |

---

## 3. How to Set Up and Use

### 3.1 Configure .env

```env
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=openai/gpt-oss-20b
```

Use the exact `id` from `/v1/models` for `LLM_MODEL`.

### 3.2 Call from Python (OpenAI Client)

```python
from openai import OpenAI
import os

client = OpenAI(
    base_url=os.environ.get("LLM_BASE_URL", "http://localhost:1234/v1"),
    api_key="not-used",  # LM Studio ignores it
)

resp = client.chat.completions.create(
    model=os.environ.get("LLM_MODEL", "openai/gpt-oss-20b"),
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Say hello."},
    ],
    temperature=0.2,
    max_tokens=1024,
)

print(resp.choices[0].message.content)
```

### 3.3 Call from LangChain

```python
from langchain_openai import ChatOpenAI
import os

llm = ChatOpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key="not-used",
    model=os.environ["LLM_MODEL"],
    temperature=0.2,
)

response = llm.invoke([{"role": "user", "content": "Hello"}])
```

### 3.4 Custom Agent Instructions (Role Templates)

```python
AGENT_SYSTEM_PROMPTS = {
    "planner": "You plan which tools or agents to use. Output a clear next step.",
    "advisor": "You give advice. Use the provided context. Be specific and cite sources.",
    "evaluator": "You check if answers are grounded. Point out unsupported claims.",
}

def build_messages(role: str, user_query: str, context: str):
    system = AGENT_SYSTEM_PROMPTS.get(role, "You are a helpful assistant.")
    return [
        {"role": "system", "content": system + "\n\nContext:\n" + context},
        {"role": "user", "content": user_query},
    ]
```

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection refused on :1234 | Server not started | Enable and start the server in LM Studio |
| `model not found` | Wrong model name | Get exact `id` from `curl http://localhost:1234/v1/models` |
| Very slow / OOM | Model too large for hardware | Use smaller or more quantized model |
| Responses ignore instructions | Weak or inconsistent prompts | Use clear system prompts; put context in system message |
| Empty or truncated output | `max_tokens` too low | Increase `max_tokens` (e.g. 4096–16384 for reasoning models) |
| Timeout | Long thinking models | Increase client timeout; consider streaming |

---

## 5. API Reference (Quick)

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/models` | List available models |
| `POST /v1/chat/completions` | Chat completion (OpenAI format) |
| Default URL | `http://localhost:1234/v1` |
| Auth | Not required; `api_key` can be any value |

---

## 6. Official Documentation

- **LM Studio:** https://lmstudio.ai/
- **Developer docs:** https://lmstudio.ai/docs/developer
- **OpenAI-compatible API:** https://lmstudio.ai/docs/app/api/endpoints/openai
- **Python SDK:** https://lmstudio.ai/docs/python
- **Models:** https://lmstudio.ai/models
