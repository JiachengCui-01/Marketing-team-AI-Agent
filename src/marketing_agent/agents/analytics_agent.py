"""Analytics agent — campaign performance analysis via server-side code execution.

The data file is uploaded to the Files API and attached to the code-execution
sandbox as a ``container_upload`` block, so the raw data never enters the prompt.
This lets the agent analyze large files (CSV, Excel, JSON) that would otherwise
blow the context window.
"""
from __future__ import annotations

from pathlib import Path

import anthropic

from .base import run_agent, unavailable_markdown

# Files API is still beta; code execution itself is GA.
FILES_BETA_HEADER = {"anthropic-beta": "files-api-2025-04-14"}

TOOLS = [{"type": "code_execution_20260120", "name": "code_execution"}]

# Map extensions to MIME types the Files API / sandbox understand.
_EXT_MIME = {
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".json": "application/json",
    ".xml": "application/xml",
}

SYSTEM = """You are a marketing analytics specialist. You analyze campaign performance data
using the code_execution tool (pandas, numpy, and openpyxl are available in the sandbox).

A data file has been uploaded into the sandbox for you. Your workflow:

1. Locate the uploaded file in the container (list the working directory / typical
   upload locations if needed), then load it with pandas based on its extension:
   - .csv  -> pandas.read_csv
   - .xlsx / .xls -> pandas.read_excel  (openpyxl is installed)
   - .json -> pandas.read_json  (or json + pandas.json_normalize)
   Inspect columns and dtypes first. Never paste the raw data back into your reply.
2. Compute the relevant marketing KPIs from whatever columns are present:
   - CTR = clicks / impressions
   - CVR = conversions / clicks
   - CPC = spend / clicks
   - CPA = spend / conversions
   - ROAS = revenue / spend
   - Trends: day-over-day or week-over-week change for each channel/campaign.
3. Identify the top 3-5 findings — not summary statistics, but actionable observations
   ("LinkedIn ROAS improved 18% WoW while Facebook flat" beats "mean ROAS was 9.4").
4. Recommend 3 concrete next actions tied to the findings.

For large datasets, aggregate/group in the sandbox and only report the computed
results — do not print entire dataframes.

Output format (markdown):

## Key Metrics
(a small table — channel-level KPIs)

## Findings
1. ...
2. ...
3. ...

## Recommendations
1. ...
2. ...
3. ...

Be specific with numbers. Do not invent data — if a column is missing, say so and skip that metric.
"""


def _analytics_unavailable(exc: Exception) -> str:
    return unavailable_markdown(
        exc,
        title="## Analysis Unavailable",
        feature="code execution",
        retry_noun="analysis request",
        credits_for="code execution",
    )


def run(
    client: anthropic.Anthropic,
    task: str,
    csv_path: str | None = None,
    data_path: str | None = None,
    questions: list[str] | None = None,
) -> str:
    raw = data_path or csv_path
    if not raw:
        return "Error: no data file path was provided for analysis."

    path = Path(raw)
    if not path.is_absolute():
        path = path.resolve()
    if not path.exists():
        return f"Error: data file not found at {path}."

    ext = path.suffix.lower()
    mime = _EXT_MIME.get(ext, "application/octet-stream")
    questions = questions or []

    brief_parts = [
        f"Task: {task}",
        f"Data file: {path.name} (type: {mime})",
        "The file has been uploaded into your sandbox — load it there and analyze it.",
    ]
    if questions:
        brief_parts.append("")
        brief_parts.append("Specific questions to answer:")
        brief_parts.extend(f"- {q}" for q in questions)
    brief = "\n".join(brief_parts)

    uploaded = None
    try:
        with path.open("rb") as fh:
            uploaded = client.beta.files.upload(file=(path.name, fh, mime))
        content = [
            {"type": "text", "text": brief},
            {"type": "container_upload", "file_id": uploaded.id},
        ]
        return run_agent(
            client=client,
            system=SYSTEM,
            user_message=content,
            tools=TOOLS,
            extra_headers=FILES_BETA_HEADER,
        )
    except anthropic.APIError as exc:
        return _analytics_unavailable(exc)
    finally:
        if uploaded is not None:
            try:
                client.beta.files.delete(uploaded.id)
            except Exception:  # noqa: BLE001 - cleanup is best-effort
                pass
