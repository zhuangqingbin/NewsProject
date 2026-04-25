# src/news_pipeline/llm/prompts/loader.py
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PromptGuardrails(BaseModel):
    max_input_tokens: int = 4000
    retry_on_invalid_json: int = 1
    fallback_model: str | None = None


class PromptFile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    version: int
    model_target: str
    description: str = ""
    cache_segments: list[str] = Field(default_factory=list)
    system: str
    output_schema_inline: dict[str, Any] | None = None
    user_template: str
    few_shot_examples: list[dict[str, Any]] = Field(default_factory=list)
    guardrails: PromptGuardrails = Field(default_factory=PromptGuardrails)


@dataclass
class RenderedPrompt:
    name: str
    version: int
    model_target: str
    system: str
    user: str
    output_schema: dict[str, Any] | None
    guardrails: PromptGuardrails
    cache_segments: list[str]
    few_shot_examples: list[dict[str, Any]]


class PromptLoader:
    def __init__(self, dir_path: Path) -> None:
        self._dir = dir_path

    def load(self, name: str, version: str) -> "PromptHandle":
        path = self._dir / f"{name}.{version}.yaml"
        if not path.exists():
            raise FileNotFoundError(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return PromptHandle(PromptFile.model_validate(data))


class PromptHandle:
    def __init__(self, pf: PromptFile) -> None:
        self._pf = pf

    @property
    def name(self) -> str:
        return self._pf.name

    @property
    def version(self) -> int:
        return self._pf.version

    @property
    def guardrails(self) -> PromptGuardrails:
        return self._pf.guardrails

    @property
    def model_target(self) -> str:
        return self._pf.model_target

    def render(self, **vars: Any) -> RenderedPrompt:
        user = self._pf.user_template.format(**vars)
        return RenderedPrompt(
            name=self._pf.name,
            version=self._pf.version,
            model_target=self._pf.model_target,
            system=self._pf.system,
            user=user,
            output_schema=self._pf.output_schema_inline,
            guardrails=self._pf.guardrails,
            cache_segments=self._pf.cache_segments,
            few_shot_examples=self._pf.few_shot_examples,
        )
