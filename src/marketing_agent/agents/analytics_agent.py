"""Analytics agent — campaign performance analysis via server-side code execution."""
from __future__ import annotations

from pathlib import Path

import anthropic

from .base import run_agent

MAX_INLINE_CSV_BYTES = 200 * 1024
MAX_INLINE_CSV_LINES = 250

SYSTEM = """You are a marketing analytics specialist. You analyze campaign performance data
using the code_execution tool (pandas is available in the sandbox).

The user will paste the CSV contents directly in their message. Your workflow:

1. Write the CSV contents to /tmp/data.csv in the sandbox, then load it with pandas.
   Inspect columns and dtypes first.
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

TOOLS = [{"type": "code_execution_20260120", "name": "code_execution"}]


def run(
    client: anthropic.Anthropic,
    task: str,
    csv_path: str,
    questions: list[str] | None = None,
) -> str:
    path = Path(csv_path)
    if not path.is_absolute():
        # Resolve relative paths against the current working directory.
        path = path.resolve()

    if not path.exists():
        return f"Error: CSV not found at {path}."

    size = path.stat().st_size
    if size > MAX_INLINE_CSV_BYTES:
        preview_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[
            :MAX_INLINE_CSV_LINES
        ]
        return (
            f"Error: CSV is too large to inline safely ({size} bytes). "
            f"Please upload a CSV under {MAX_INLINE_CSV_BYTES // 1024} KB or narrow it "
            f"to the relevant rows/columns. Previewed {len(preview_lines)} lines from "
            f"{path.name}; no analysis was run to avoid excessive token usage."
        )

    csv_text = path.read_text(encoding="utf-8", errors="replace")
    questions = questions or []

    parts = [
        f"Task: {task}",
        f"CSV filename: {path.name}",
        "",
        "CSV contents (inline below — write this to /tmp/data.csv in the sandbox and analyze):",
        "```csv",
        csv_text,
        "```",
    ]
    if questions:
        parts.append("")
        parts.append("Specific questions to answer:")
        parts.extend(f"- {q}" for q in questions)

    return run_agent(
        client=client,
        system=SYSTEM,
        user_message="\n".join(parts),
        tools=TOOLS,
    )
