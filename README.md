# Marketing Agent

Enterprise marketing team AI MVP with a Python multi-agent backend, a FastAPI
SSE API, and a Next.js web UI.

## Home page:
<img width="1280" height="698" alt="image" src="https://github.com/user-attachments/assets/ccf69672-5d64-4a06-b806-0f9e0f8d6289" />

## Setting:
<img width="1280" height="697" alt="image" src="https://github.com/user-attachments/assets/58484fdc-51e1-407e-9eab-3159b6df7b69" />

## Chat:
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/8fbeccac-6cf0-4727-b008-1289350b51b6" />

## Contacts:
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/a90ce9e9-0367-402d-9690-ee6ef1fbea32" />

## OA (Events can be created through Agent chat):
<img width="1280" height="696" alt="image" src="https://github.com/user-attachments/assets/7918ffcc-1d85-4ea0-ac85-6fa1f18b7a5c" />

## Automatically collect and push industry news within 24 hours：
<img width="1280" height="698" alt="image" src="https://github.com/user-attachments/assets/ae1832b2-a6f0-4512-913e-05ffad7062e9" />

## Marketing image AI generation
<img width="1280" height="697" alt="image" src="https://github.com/user-attachments/assets/e62ecde1-6415-423f-bad4-97abf03a07bd" />

## Architecture

```text
User -> CLI/API -> Orchestrator
                  |-> Content Agent
                  |-> Analytics Agent
                  |-> Research Agent
                  -> Synthesized markdown result
```

Sub-agents are stateless per call. The CLI writes saved results to `outputs/`.


## Troubleshooting

- `ANTHROPIC_API_KEY not configured`: copy `.env.example` to `.env` and set the
  key before starting the CLI or API.
