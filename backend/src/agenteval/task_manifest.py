from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agenteval.schemas import AgentConfig, Task


def load_task_yaml(manifest_path: Path) -> Task:
    """Load and validate a task manifest using PyYAML's safe parser."""
    contents: Any = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return Task.model_validate(contents)


def load_agent_config_yaml(config_path: Path) -> AgentConfig:
    """Load and validate a vendor-neutral CLI agent configuration."""
    contents: Any = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return AgentConfig.model_validate(contents)
