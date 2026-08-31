"""Central configuration."""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Model provider: DeepSeek (OpenAI-compatible chat-completions API).
# ``llm_client`` translates the Anthropic-shaped calls the agents make into this
# dialect, so only the model IDs and endpoint live here.
# ---------------------------------------------------------------------------

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_TIMEOUT_SECONDS = float(os.environ.get("DEEPSEEK_TIMEOUT", "300"))

# Reasoning model driving the orchestrator, the OA copilot, and the sub-agents.
MODEL_ID = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

# Cheap, fast model used to extract long-term marketing profile facts from
# prompts. Kept separate from the orchestrator/sub-agent model so memory
# learning never pays the reasoning-model rate.
MEMORY_EXTRACTION_MODEL = os.environ.get("DEEPSEEK_FAST_MODEL", "deepseek-v4-flash")

# Cheap, fast model used to plan clarifying questions before a task runs.
CLARIFY_MODEL = MEMORY_EXTRACTION_MODEL

# The text models reject image content, so requests carrying an image are routed
# to the vision model instead (see ``llm_client._resolve_model``).
VISION_MODEL = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
VISION_CAPABLE_MODELS = {VISION_MODEL}

_FALSEY = {"0", "false", "no", "off", ""}


def memory_llm_extraction_enabled() -> bool:
    """Whether long-term memory should use LLM extraction (default: on).

    Set ``MARKETING_AGENT_MEMORY_LLM=0`` to force the deterministic heuristic
    fallback (used by tests and offline runs). LLM extraction also silently
    degrades to heuristics whenever no API key/client is available.
    """
    return os.environ.get("MARKETING_AGENT_MEMORY_LLM", "1").strip().lower() not in _FALSEY


def clarify_llm_enabled() -> bool:
    """Whether the LLM-driven clarification planner is enabled (default: on).

    Set ``MARKETING_AGENT_CLARIFY_LLM=0`` to disable it; the frontend then
    falls back to its heuristic clarification flow. Also degrades gracefully
    whenever no API key/client is available.
    """
    return os.environ.get("MARKETING_AGENT_CLARIFY_LLM", "1").strip().lower() not in _FALSEY

# Max output token caps. Streaming is enabled in the loop, so these can be generous.
ORCHESTRATOR_MAX_TOKENS = 16000
SUBAGENT_MAX_TOKENS = 16000

# Thinking effort per agent. ``llm_client`` maps these onto DeepSeek's
# ``thinking.effort`` (low|medium|high).
ORCHESTRATOR_EFFORT = "high"
SUBAGENT_EFFORT = "medium"

# Cap how many tool-use rounds a sub-agent can run before we bail out.
MAX_TOOL_ROUNDS = 12

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = PROJECT_ROOT / "data"
