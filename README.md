# Marketing Agent

Enterprise marketing team AI MVP with a Python multi-agent backend, a FastAPI
SSE API, and a Next.js web UI.

The orchestrator routes requests to three specialists:

1. Content generation: social posts, blog drafts, email campaigns, ad copy
2. Campaign analytics: CSV analysis with KPI findings and recommendations
3. Market research: current web research with cited sources

Updates：

V1.3: Add automatic summary function for daily industry news
<img width="1279" height="698" alt="image" src="https://github.com/user-attachments/assets/a090dedc-8c0b-417d-9ec8-2fa25c5fe62a" />

V1.2: Add generated file preview
<img width="1279" height="698" alt="image" src="https://github.com/user-attachments/assets/13e08e22-d476-4df9-823d-467891f5093b" />

Home page:
<img width="877" height="479" alt="image" src="https://github.com/user-attachments/assets/0d57cf12-f09a-41a9-af83-c9af5676fc8f" />

Content generation(bright/dark):
<img width="874" height="476" alt="image" src="https://github.com/user-attachments/assets/66a308c8-52b0-4e96-a43e-0c929d4b92ac" />
<img width="878" height="476" alt="image" src="https://github.com/user-attachments/assets/5638e7fd-4008-47b8-b140-7c10ec4e8a1c" />

Analytics:
<img width="877" height="478" alt="image" src="https://github.com/user-attachments/assets/371239f5-e219-4006-b238-8d4c0cc948ba" />
<img width="878" height="478" alt="image" src="https://github.com/user-attachments/assets/af1fb99c-9ae4-457c-969b-0833d8e8cbcc" />

Research:
<img width="876" height="477" alt="image" src="https://github.com/user-attachments/assets/fa4c35cf-f785-4a34-91a8-5bce074125ed" />
<img width="881" height="479" alt="image" src="https://github.com/user-attachments/assets/26d417c5-2da9-4d00-86d9-0c5db429056f" />


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
