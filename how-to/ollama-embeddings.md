# Ollama Embeddings

Ollama runs **embedding models** locally so your agent can convert text into vectors for semantic search—without sending data to external APIs.

---

## 1. How to Install

### 1.1 Prerequisites

- macOS, Windows, or Linux
- ~2–4 GB disk space for the embedding model
- (Optional) GPU for faster inference

### 1.2 Install Ollama

1. Go to https://ollama.com/download
2. Download the installer for your OS.
3. Run the installer.
4. Ollama usually starts automatically. If not:

```bash
ollama serve
```

### 1.3 Pull an Embedding Model

```bash
ollama pull mxbai-embed-large
```

This model produces **1024-dimensional** vectors, which you’ll use for Neo4j’s vector index.

**Other embedding models** (check dimensions before use):

| Model | Dimensions | Use Case |
|-------|------------|----------|
| `mxbai-embed-large` | 1024 | General purpose, good quality |
| `nomic-embed-text` | 768 | Smaller, faster |
| `all-minilm` | 384 | Very fast, lower quality |

### 1.4 Verify

```bash
ollama list
ollama run mxbai-embed-large "embed this"
```

You should see an embedding vector in the output.

### 1.5 Install Python Client

```bash
pip install langchain-ollama
```

---

## 2. Why Use Ollama for Embeddings

| Benefit | Description |
|---------|-------------|
| **Local & private** | Text never leaves your machine. |
| **No API keys** | No external service or billing. |
| **Fixed dimensions** | Consistent vector size (e.g. 1024) for Neo4j index. |
| **Swap models** | Change models as long as dimensions match your index. |
| **Integration** | Works with LangChain and other frameworks. |

---

## 3. How to Set Up and Use

### 3.1 Ensure Ollama Is Running

```bash
ollama serve
```

Default URL: `http://localhost:11434`

### 3.2 Use from Python (LangChain)

```python
from langchain_ollama import OllamaEmbeddings

emb = OllamaEmbeddings(
    model="mxbai-embed-large",
    base_url="http://localhost:11434",  # optional if using default
)

# Single query
vector = emb.embed_query("What courses has Alice taken?")
print(len(vector))  # 1024

# Batch (for document chunks)
texts = ["chunk 1", "chunk 2", "chunk 3"]
vectors = emb.embed_documents(texts)
```

### 3.3 Embedding Adapter (Swappable)

```python
class EmbeddingService:
    def __init__(self, model: str = "mxbai-embed-large"):
        from langchain_ollama import OllamaEmbeddings
        self._emb = OllamaEmbeddings(model=model)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._emb.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._emb.embed_query(text)
```

Use this adapter so you can switch to another provider (e.g. OpenAI) by changing the implementation.

### 3.4 Wire into Neo4j

1. **Ingest:** For each document chunk, call `embed_documents(chunks)` and store vectors as `embedding` on `:Chunk` nodes.
2. **Query:** Call `embed_query(user_question)` and run Neo4j vector search with that embedding.
3. Ensure the Neo4j vector index `vector.dimensions` matches `len(vector)` (1024 for `mxbai-embed-large`).

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| "couldn't connect to Ollama" | Server not running | Run `ollama serve` |
| "model not found" | Model not pulled | `ollama pull mxbai-embed-large`; check spelling |
| Dimension mismatch with Neo4j | Index uses wrong size | Use `len(vector)` (e.g. 1024); recreate index with that value |
| Timeouts on many chunks | Too many requests | Batch calls; add retry/backoff; reduce concurrency |
| Wrong base URL | Custom port or host | Set `base_url` in `OllamaEmbeddings` or `OLLAMA_URL` in `.env` |

---

## 5. API Reference (Quick)

| Action | Command / Code |
|--------|----------------|
| Start server | `ollama serve` |
| List models | `ollama list` |
| Pull model | `ollama pull mxbai-embed-large` |
| Embed (Python) | `emb.embed_query(text)` or `emb.embed_documents(texts)` |
| Default URL | `http://localhost:11434` |

---

## 6. Official Documentation

- **Ollama:** https://ollama.com/
- **Docs:** https://github.com/ollama/ollama/blob/main/docs/api.md
- **Models:** https://ollama.com/library
- **LangChain Ollama:** https://python.langchain.com/docs/integrations/text_embedding/ollama
