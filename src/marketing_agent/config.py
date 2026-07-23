"""Central configuration."""
from __future__ import annotations

import os
from pathlib import Path

MODEL_ID = "claude-opus-4-8"

# Cheap, fast model used to extract long-term marketing profile facts from
# prompts. Kept separate from the orchestrator/sub-agent model so memory
# learning never pays Opus rates.
MEMORY_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"

_FALSEY = {"0", "false", "no", "off", ""}


def memory_llm_extraction_enabled() -> bool:
    """Whether long-term memory should use LLM extraction (default: on).

    Set ``MARKETING_AGENT_MEMORY_LLM=0`` to force the deterministic heuristic
    fallback (used by tests and offline runs). LLM extraction also silently
    degrades to heuristics whenever no API key/client is available.
    """
    return os.environ.get("MARKETING_AGENT_MEMORY_LLM", "1").strip().lower() not in _FALSEY

# Max output token caps. Streaming is enabled in the loop, so these can be generous.
ORCHESTRATOR_MAX_TOKENS = 16000
SUBAGENT_MAX_TOKENS = 16000

# Effort levels per agent (Opus 4.8 supports low|medium|high|xhigh|max).
ORCHESTRATOR_EFFORT = "high"
SUBAGENT_EFFORT = "medium"

# Cap how many tool-use rounds a sub-agent can run before we bail out.
MAX_TOOL_ROUNDS = 12

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data"
