# Docker for Local Services

Docker lets you run infrastructure (databases, caches) in isolated containers so your agent stack is reproducible across machines. This guide focuses on running **Neo4j** via Docker, which is used for graph and vector memory.

---

## 1. How to Install

### 1.1 Prerequisites

- **macOS:** macOS 10.15+ (Catalina or newer)
- **Windows:** Windows 10/11 with WSL2, or Windows Server
- **Linux:** Most modern distros (Ubuntu, Debian, Fedora, etc.)
- **Disk:** ~2–3 GB for Docker Desktop; add space for images and volumes

### 1.2 Install Docker Desktop (macOS / Windows)

1. Go to https://www.docker.com/products/docker-desktop/
2. Download Docker Desktop for your OS.
3. Run the installer and follow the prompts.
4. Start Docker Desktop and wait until the whale icon shows "Docker Desktop is running".
5. Verify:

```bash
docker --version
docker compose version
```

### 1.3 Install Docker Engine (Linux)

```bash
# Ubuntu/Debian (example)
sudo apt-get update
sudo apt-get install docker.io docker-compose-plugin
sudo usermod -aG docker $USER
# Log out and back in, then:
docker run hello-world
```

For other distros, see: https://docs.docker.com/engine/install/

---

## 2. Why Use Docker for Your Agent

| Benefit | Description |
|---------|--------------|
| **Reproducibility** | Anyone with Docker can run the same Neo4j with one command; no manual DB install. |
| **Isolation** | Database versions and data are isolated from your host; no conflicts with other projects. |
| **Easy reset** | `docker compose down -v` removes containers and volumes; start fresh without touching code. |
| **Portability** | Same `docker-compose.yml` works on macOS, Windows, and Linux. |
| **Version pinning** | Use `neo4j:5-community` and get the same image everywhere. |

---

## 3. How to Set Up and Use

### 3.1 Create docker-compose.yml

Create a file named `docker-compose.yml` in your project (e.g. in a `docker/` folder or project root):

```yaml
version: "3.9"

services:
  neo4j:
    image: neo4j:5-community
    container_name: agent-neo4j
    ports:
      - "7474:7474"   # Neo4j Browser (HTTP)
      - "7687:7687"   # Bolt protocol (used by your backend)
    environment:
      - NEO4J_AUTH=neo4j/your-secure-password
      - NEO4J_PLUGINS=["apoc"]   # Optional: APOC procedures for utilities
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    restart: unless-stopped

volumes:
  neo4j_data:
  neo4j_logs:
```

**Important:** Replace `your-secure-password` with a real password. Use the same value in your backend `.env` as `NEO4J_PASSWORD`.

### 3.2 Start Neo4j

```bash
# From the directory containing docker-compose.yml
docker compose up -d

# Check status
docker compose ps
```

You should see the `neo4j` container with status `running`.

### 3.3 Verify

**Option 1 – HTTP:**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7474
# Expect 200 or 304
```

**Option 2 – Neo4j Browser:**

1. Open http://localhost:7474 in a browser.
2. Connect with:
   - **Username:** `neo4j`
   - **Password:** the value you set in `NEO4J_AUTH` (after the `/`)

**Option 3 – Bolt from Python:**

```python
from neo4j import GraphDatabase
driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "your-secure-password"))
driver.verify_connectivity()
```

### 3.4 Useful Commands

| Command | Purpose |
|---------|---------|
| `docker compose up -d` | Start services in background |
| `docker compose down` | Stop and remove containers (keeps volumes) |
| `docker compose down -v` | Stop and remove containers and volumes (deletes data) |
| `docker compose ps` | List running containers |
| `docker compose logs -f neo4j` | Follow Neo4j logs |
| `docker compose restart neo4j` | Restart Neo4j container |

---

## 4. Common Pitfalls and Fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `docker compose: command not found` | Docker not installed or not on PATH | Install Docker Desktop/Engine; restart terminal |
| `neo4j` container keeps restarting | `NEO4J_AUTH` mismatch with existing volume data | `docker compose down -v` then `docker compose up -d` with correct password |
| `bind: address already in use` | Another process using 7474 or 7687 | Stop other Neo4j/containers, or change ports: `"17474:7474"`, `"17687:7687"` |
| Backend gets "connection refused" | Container not ready or wrong port | Wait 10–20 seconds after `up -d`; verify with `curl http://localhost:7474` |
| "Authentication failed" in Neo4j Browser | Wrong password | Use the exact password from `NEO4J_AUTH`; if unsure, reset: `down -v` and `up -d` |

---

## 5. Multi-Service Example

You can add more services to the same `docker-compose.yml`:

```yaml
services:
  neo4j:
    image: neo4j:5-community
    # ... (as above)

  # Example: Redis for caching (optional)
  # redis:
  #   image: redis:7-alpine
  #   ports:
  #     - "6379:6379"
```

Use `docker compose up -d` to start all defined services.

---

## 6. Official Documentation

- **Docker Docs:** https://docs.docker.com/
- **Docker Desktop:** https://docs.docker.com/desktop/
- **Docker Compose:** https://docs.docker.com/compose/
- **Neo4j Docker:** https://neo4j.com/docs/operations-manual/current/docker/
