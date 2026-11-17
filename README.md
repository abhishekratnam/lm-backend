# lm-backend — "backendless" Agent + DB stack

There is **no hand-written CRUD/business-logic API layer**. Postgres holds the data, Hasura
auto-exposes it as a typed GraphQL API, and an LLM agent composes GraphQL queries/mutations at
runtime. FastAPI is only a thin shell that hosts the agent (chat endpoint + streaming).

```
client ──natural language──▶ FastAPI /chat ──▶ Agent loop
                                    │   tools: run_graphql / get_schema
                                    ▼
                                 Hasura ──auto SQL──▶ Postgres
```

## What is deliberately missing

- No ORM models, repositories, serializers, DTOs, or per-endpoint services.
- No versioned REST resources — the "API" is Hasura's GraphQL surface, which follows the schema.
- Adding a table = one edit in `infra/postgres/init.sql`; it gets tracked and queryable on next boot.

## Stack

| layer     | tech                                        |
|-----------|---------------------------------------------|
| data      | Postgres 16                                 |
| data API  | Hasura v2 (auto GraphQL, admin secret)      |
| brain     | OpenAI-compatible LLM with tool calling     |
| shell     | FastAPI (SSE streaming, static demo UI)     |

## Quickstart

```bash
cp .env.example .env        # set LLM_API_KEY (any OpenAI-compatible provider)
docker compose up -d --build
```

- Chat UI: <http://localhost:8000/demo>
- API docs: <http://localhost:8000/docs>
- Hasura console: <http://localhost:8080/console> (admin secret: `myadminsecret`)

Ask things like:

- "Which product generated the most revenue? Include units sold."
- "Create an order for Grace Hopper with 2 USB-C hubs, status pending."
- "How many orders are pending and what is their combined total?"

## Endpoints

| endpoint     | what                                                        |
|--------------|-------------------------------------------------------------|
| `POST /chat` | SSE stream of `token` / `tool` / `done` / `error` events     |
| `POST /ask`  | JSON `{message, history?}` → `{answer, tool_calls}`          |
| `GET /healthz` | app + Hasura status                                       |
| `GET /demo`  | minimal chat UI (static page)                                |

## How it works

1. **Bootstrap** (`app/bootstrap.py`): waits for Hasura, runs `run_sql` against
   `information_schema`, tracks every public table and creates object/array relationships from
   foreign keys. Idempotent — "already tracked/exist" errors are ignored.
2. **Schema awareness** (`app/hasura/schema.py`): introspects the GraphQL schema and renders a
   compact table/relationship text that is embedded into the agent's system prompt.
3. **Agent loop** (`app/agent/agent.py`): streaming tool-calling loop — model → `run_graphql`
   (POST to Hasura) → result or error string fed back → … → final answer. Errors are returned as
   strings so the model can fix its own query and retry.

## Swapping the LLM

The agent speaks the OpenAI Chat Completions protocol, so any compatible endpoint with function
calling works via env vars.

### OpenCode models (e.g. DeepSeek Flash)

Models from your OpenCode plan are served from the OpenCode inference gateway — already set as
the default in `.env.example`. Pay-as-you-go and Go subscriptions use **different base URLs**:

```env
LLM_API_KEY=<personal or service-account key from https://opencode.ai/console>

# OpenCode Go subscription (covered by your plan):
LLM_BASE_URL=https://opencode.ai/inference/go/openai/v1

# or pay-as-you-go (billed from Console credits):
# LLM_BASE_URL=https://opencode.ai/inference/openai/v1

LLM_MODEL=deepseek-v4.1-flash
```

- Use the bare model id (no `provider/` prefix): `deepseek-v4.1-flash`, `deepseek-v4-pro`, `glm-5.3-flash`, ...
- The agent sends the required `x-opencode-session` header automatically.
- Free `-free` models are only callable from inside OpenCode itself — external clients get HTTP
  403 even with a key.
- DeepSeek models may require **Global** regions enabled in Console → Settings › Privacy,
  depending on where the requests originate.

### Other providers

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# or GLM:
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_MODEL=glm-4.6
```

## Extending the schema

Append tables to `infra/postgres/init.sql`, then `docker compose down -v && docker compose up -d --build`
(or just restart `agent-api` — bootstrap tracks new tables and FK relationships live).

## Running without Docker

Start Postgres + Hasura yourself, then:

```bash
pip install -r requirements.txt
cp .env.example .env    # HASURA_URL=http://localhost:8080/v1/graphql
uvicorn app.main:app --reload
```

## Security — read before real use

- The agent talks to Hasura with the **admin secret**, so anyone who can reach `/chat` can
  indirectly read/write everything. Never expose Hasura or this service without authentication.
- Hardening path: define Hasura **roles with row/column-level permissions**, send
  `x-hasura-role` from the client instead of the admin secret, allow-list mutation kinds,
  require user confirmation for destructive operations, and rate-limit `/chat`.
- Tradeoff: an agent is slower and less deterministic than a typed endpoint. For hot paths
  (auth, checkout), pin those flows down later with Hasura actions/events or a normal endpoint —
  the architecture mixes fine with a conventional API where you need guarantees.
