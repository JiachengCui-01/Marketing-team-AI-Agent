# Marketing Agent

Enterprise marketing team AI MVP with a Python multi-agent backend, a FastAPI
SSE API, and a Next.js web UI.

The orchestrator routes requests to three specialists:

1. Content generation: social posts, blog drafts, email campaigns, ad copy
2. Campaign analytics: CSV analysis with KPI findings and recommendations
3. Market research: current web research with cited sources

## API Notes

- `/api/upload` accepts CSV files only.
- Uploads are capped at 2 MB and stored under `tmp/uploads/`.
- Web sessions are in-memory, single-process, TTL-limited, and capped to avoid
  unbounded growth.
- SSE streams emit `result`, `error`, or `cancelled` terminal events.

## Architecture

```text
User -> CLI/API -> Orchestrator
                  |-> Content Agent
                  |-> Analytics Agent
                  |-> Research Agent
                  -> Synthesized markdown result
```

Sub-agents are stateless per call. The CLI writes saved results to `outputs/`.

## Layout

```text
src/marketing_agent/
  cli.py
  config.py
  orchestrator.py
  conversation.py
  tools/delegation_tools.py
  agents/

server/
  main.py
  routes.py
  sessions.py
  streaming.py
  uploads.py

web/
  app/
  components/
  lib/

tests/
```

## Troubleshooting

- `ANTHROPIC_API_KEY not configured`: copy `.env.example` to `.env` and set the
  key before starting the CLI or API.
- `Connection error. Is the API server running on :8000?`: start FastAPI with
  `uvicorn server.main:app --reload`.
- CSV rejected by upload: confirm the file has a `.csv` extension, an allowed CSV
  content type, non-empty content, and is under 2 MB.
- Large analytics CSV rejected by the agent: narrow the file to relevant rows and
  columns before analysis to keep prompt token usage bounded.
