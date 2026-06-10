"""Central configuration."""
from __future__ import annotations

from pathlib import Path

MODEL_ID = "claude-opus-4-8"

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
