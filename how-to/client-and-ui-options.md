# Client and UI Options (Optional)

Your agent backend exposes an API; the **client** is how users interact with it. You can use a web app, CLI, notebook, or an MCP-aware IDE—whatever fits your project.

---

## 1. How to Install (Example: Web UI)

### 1.1 Client Options

| Type | When to Use | Example Stack |
|------|-------------|---------------|
| **Web app** | Rich UI, file upload, streaming | React + Vite + Tailwind |
| **CLI** | Scripting, automation | Python `requests` + `click` |
| **Notebook** | Experiments, demos | Jupyter + `requests` |
| **IDE / MCP** | Integrate with Cursor, Claude | MCP client config |

### 1.2 Example: React + Vite Web UI

```bash
# Create project (if starting fresh)
npm create vite@latest frontend -- --template react
cd frontend
npm install
npm install axios  # or fetch for API calls

# Run dev server
npm run dev
```

### 1.3 Example: Simple Python CLI

```bash
pip install requests
```

```python
# client.py
import requests

def chat(query: str, session_id: str = None):
    resp = requests.post(
        "http://localhost:8001/api/v1/chat",
        data={"query": query, "session_id": session_id or ""},
    )
    return resp.json()

print(chat("Hello!")["answer"])
```

---

## 2. Why the Client Matters

| Aspect | Description |
|--------|-------------|
| **UX** | How easy it is to ask questions, upload files, view answers. |
| **Transparency** | Show citations, confidence, and agent steps. |
| **Control** | Profile editing, settings, session management. |
| **Thin layer** | Logic stays in the backend; client only sends requests and renders. |

---

## 3. How to Set Up and Use

### 3.1 Choose a Transport

| Transport | Use Case |
|-----------|----------|
| **HTTP POST** | Simple request/response; no streaming |
| **SSE (Server-Sent Events)** | Streaming tokens and progress updates |
| **WebSockets** | Bidirectional; more complex |

For chat with streaming, SSE is typical.

### 3.2 Connect to `/chat`

**Form data (with files):**

```javascript
const formData = new FormData();
formData.append("query", userMessage);
formData.append("session_id", sessionId);
files.forEach(f => formData.append("files", f));

const response = await fetch("http://localhost:8001/api/v1/chat", {
  method: "POST",
  body: formData,
});
```

**JSON (no files):**

```javascript
const response = await fetch("http://localhost:8001/api/v1/chat/json", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ query: userMessage, session_id: sessionId }),
});
const data = await response.json();
```

### 3.3 Handle SSE Streaming

```javascript
const eventSource = new EventSource(
  "http://localhost:8001/api/v1/chat/stream?query=" + encodeURIComponent(query)
);
eventSource.addEventListener("token", (e) => {
  const data = JSON.parse(e.data);
  appendToMessage(data.content);
});
eventSource.addEventListener("done", () => eventSource.close());
```

(Exact endpoint and event names depend on your backend.)

### 3.4 Client Responsibilities Checklist

- [ ] Send user query and session ID to `/chat`
- [ ] Display streaming or final response
- [ ] Handle errors (network, 5xx)
- [ ] File upload (if your API supports it)
- [ ] New session / clear session
- [ ] (Optional) Profile view, settings toggles

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| CORS errors | Backend not allowing frontend origin | Configure CORS in FastAPI for `http://localhost:3000` (or your origin) |
| Streaming stops early | Proxy or connection timeout | Check SSE handling; add keepalive if needed |
| Session mismatch | Different session IDs per request | Store `session_id` in state; send it on every request |
| 413 / file too large | File exceeds backend limit | Check `MAX_FILE_SIZE_MB`; compress or split files |

---

## 5. Official Documentation

- **Fetch API:** https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API
- **Server-Sent Events:** https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- **React:** https://react.dev/
- **Vite:** https://vitejs.dev/
