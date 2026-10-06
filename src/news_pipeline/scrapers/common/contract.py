"""Validate source structures before interpreting their contents."""

from collections.abc import Sequence
from typing import Any, cast

import pandas as pd


class SourceContractError(Exception):
    """The upstream schema is missing fields or has changed their types."""


def require_columns(df: pd.DataFrame, cols: Sequence[str], *, source: str) -> None:
    missing = [col for col in cols if col not in df.columns]
    if missing:
        raise SourceContractError(f"{source}: missing columns {missing}, got {list(df.columns)}")


def require_json_path(payload: object, path: str, *, source: str) -> Any:
    value = payload
    for key in path.split(".") if path else []:
        if not isinstance(value, dict) or key not in value:
            raise SourceContractError(f"{source}: missing JSON path {path}")
        value = value[key]
    return value


def require_json_list(payload: object, path: str, *, source: str) -> list[Any]:
    value = require_json_path(payload, path, source=source)
    if not isinstance(value, list):
        raise SourceContractError(f"{source}: JSON path {path} must be a list")
    return value


def require_json_mapping(payload: object, path: str, *, source: str) -> dict[str, Any]:
    value = require_json_path(payload, path, source=source)
    if not isinstance(value, dict):
        raise SourceContractError(f"{source}: JSON path {path} must be an object")
    return cast(dict[str, Any], value)


def require_json_string(payload: object, path: str, *, source: str) -> str:
    value = require_json_path(payload, path, source=source)
    if not isinstance(value, str):
        raise SourceContractError(f"{source}: JSON path {path} must be a string")
    return value
