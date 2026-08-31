"""Analytics agent — campaign performance analysis via local code execution.

Anthropic ran this in a remote sandbox with the data file uploaded through the
Files API. DeepSeek has neither, so the same workflow runs against
``tools/code_exec.py``: the model writes pandas, the server executes it in a
scratch directory that holds only this task's data file, and only printed results
come back. The raw data still never enters the prompt, so large files stay out of
the context window.

See ``tools/code_exec.py`` for the security caveats of executing model-written
code on the API server.
"""
from __future__ import annotations

from pathlib import Path

from .. import llm_client
from ..domain import BRAND, kpi_block
from ..tools.code_exec import RUN_PYTHON_TOOL, enabled as code_exec_enabled, make_handler
from .base import run_agent, unavailable_markdown

TOOLS = [RUN_PYTHON_TOOL]

# Extensions the agent knows how to load, and the label shown in the brief.
_EXT_KIND = {
    ".csv": "CSV",
    ".xlsx": "Excel workbook",
    ".xls": "Excel workbook (legacy)",
    ".json": "JSON",
    ".xml": "XML",
}

SYSTEM = f"""You are the performance analyst for {BRAND}, a design-led large-furniture
brand selling direct to consumers in the United States. You analyze sales, advertising,
listing, and returns data using the run_python tool (pandas, numpy, and openpyxl are
available).

The data file named in the brief is already in the working directory of every
run_python call — open it by its bare filename. Each call is a fresh process, so
nothing carries over between calls: every script must re-import and re-load the
file, and must print whatever you need to read.

Your workflow:

1. First call: load the file with pandas based on its extension and print the
   shape, column names, dtypes, and a few rows so you know what you are working with.
   - .csv  -> pandas.read_csv
   - .xlsx / .xls -> pandas.read_excel  (openpyxl is installed)
   - .json -> pandas.read_json  (or json + pandas.json_normalize)
   Never print the raw dataset back into your reply.
2. Next calls: compute the relevant KPIs from whatever columns are present:
   - CTR = clicks / impressions
   - CVR = conversions / clicks (conversion rate)
   - AOV = revenue / orders
   - ACOS = ad spend / ad revenue         (TACOS = ad spend / total revenue)
   - ROAS = revenue / spend               (1 / ACOS)
   - CPC = spend / clicks, CPA = spend / conversions
   - Return rate = returns / orders, and returned revenue as a share of revenue
   - Net revenue = revenue - returned revenue, and net ROAS on that basis
   - Trends: day-over-day or week-over-week change per channel, campaign, or SKU.
   Skip any metric whose input columns are absent — say so rather than approximating.
3. On this product line, ALWAYS surface return rate when the data supports it. A
   channel with strong ROAS and a high return rate is usually losing money once
   freight both ways is counted, and that inversion is the finding worth reporting.
4. Group by whichever dimension the data actually supports — channel, campaign, SKU,
   or product category. Prefer the one that makes the recommendation actionable.
5. Identify the top 3-5 findings — not summary statistics, but actionable observations
   ("Amazon ACOS improved to 14% while its return rate rose to 11%, so net contribution
   fell" beats "mean ROAS was 9.4").
6. Recommend 3 concrete next actions tied to the findings.

{kpi_block()}

For large datasets, aggregate/group inside the script and print only the computed
results — do not print entire dataframes.

Output format (markdown):

## Key Metrics
(a small table — KPIs by channel, campaign, or SKU, whichever the data supports)

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
        feature="data analysis",
        retry_noun="analysis request",
        credits_for="data analysis",
    )


def run(
    client: llm_client.DeepSeek,
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

    if not code_exec_enabled():
        return (
            "## Analysis Unavailable\n\n"
            "Local code execution is disabled on this server "
            "(`MARKETING_AGENT_LOCAL_CODE_EXEC=0`), so performance data cannot be analyzed.\n\n"
            "## What to do next\n"
            "1. Re-enable local code execution on the API server, or\n"
            "2. Analyze the file outside the agent and paste the computed metrics into the chat."
        )

    kind = _EXT_KIND.get(path.suffix.lower(), "data file")
    questions = questions or []

    brief_parts = [
        f"Task: {task}",
        f"Data file: {path.name} ({kind})",
        "The file is in the working directory of every run_python call — load it there.",
    ]
    if questions:
        brief_parts.append("")
        brief_parts.append("Specific questions to answer:")
        brief_parts.extend(f"- {q}" for q in questions)
    brief = "\n".join(brief_parts)

    try:
        return run_agent(
            client=client,
            system=SYSTEM,
            user_message=brief,
            tools=TOOLS,
            client_tool_handlers={"run_python": make_handler(path)},
        )
    except llm_client.APIError as exc:
        return _analytics_unavailable(exc)
