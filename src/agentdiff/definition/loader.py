"""Read `agentdiff.yaml` and produce resolved `AgentDefinition` objects.

The YAML uses camelCase and relative paths (the user-facing contract,
HANDOFF.md sec 3.6). The internal `AgentDefinition` model uses
snake_case and absolute paths. We parse the YAML into a wire-format
model that mirrors the YAML 1:1, then translate to `AgentDefinition`.
This separation means validation errors point at the keys users
actually wrote, not at internal renames.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from agentdiff.definition import DefinitionError
from agentdiff.definition.schema import AgentDefinition, EvalThresholds

_SUPPORTED_API_VERSION = "agentdiff/v1"


class _WireBase(BaseModel):
    """Wire-format base: camelCase keys, reject unknowns, allow Python init.

    `populate_by_name=True` lets us construct these in tests using
    snake_case kwargs while still accepting camelCase from YAML.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class _WireSchemas(_WireBase):
    input: str
    output: str


class _WireThresholds(_WireBase):
    min_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    max_regression_pct: float | None = Field(default=None, ge=0.0, le=1.0)


class _WireAgent(_WireBase):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    provider: Literal["claude", "openai"]
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    schemas: _WireSchemas
    evals: list[str] = Field(min_length=1)
    thresholds: dict[str, _WireThresholds]


class _WireConfig(_WireBase):
    api_version: str
    agents: list[_WireAgent]


def load_agents(repo_path: Path) -> list[AgentDefinition]:
    """Load all agent definitions declared in `<repo_path>/agentdiff.yaml`.

    Path fields on the returned `AgentDefinition` objects are absolute
    (resolved against `repo_path` and the agent's `path` directory).
    """
    config_file = repo_path / "agentdiff.yaml"
    if not config_file.is_file():
        raise DefinitionError(f"agentdiff.yaml not found at {config_file}")

    try:
        raw = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DefinitionError(f"{config_file}: not valid YAML: {e}") from e

    if not isinstance(raw, dict):
        raise DefinitionError(
            f"{config_file}: top-level must be a mapping, got {type(raw).__name__}"
        )

    try:
        wire = _WireConfig.model_validate(raw)
    except ValidationError as e:
        raise DefinitionError(f"{config_file}: validation failed:\n{e}") from e

    if wire.api_version != _SUPPORTED_API_VERSION:
        raise DefinitionError(
            f"{config_file}: unsupported apiVersion {wire.api_version!r}; "
            f"expected {_SUPPORTED_API_VERSION!r}"
        )

    seen_names: set[str] = set()
    agents: list[AgentDefinition] = []
    for wire_agent in wire.agents:
        if wire_agent.name in seen_names:
            raise DefinitionError(f"{config_file}: duplicate agent name {wire_agent.name!r}")
        seen_names.add(wire_agent.name)
        agents.append(_resolve(wire_agent, repo_path))

    return agents


def _resolve(wire: _WireAgent, repo_root: Path) -> AgentDefinition:
    agent_dir = (repo_root / wire.path).resolve()
    try:
        thresholds = {
            name: EvalThresholds(
                min_pass_rate=t.min_pass_rate,
                max_regression_pct=t.max_regression_pct,
            )
            for name, t in wire.thresholds.items()
        }
    except ValidationError as e:
        raise DefinitionError(f"agent {wire.name!r}: thresholds invalid:\n{e}") from e

    return AgentDefinition(
        name=wire.name,
        path=agent_dir,
        provider=wire.provider,
        model=wire.model,
        prompt_path=(agent_dir / wire.prompt).resolve(),
        input_schema_path=(agent_dir / wire.schemas.input).resolve(),
        output_schema_path=(agent_dir / wire.schemas.output).resolve(),
        eval_files=[(agent_dir / e).resolve() for e in wire.evals],
        thresholds=thresholds,
    )
