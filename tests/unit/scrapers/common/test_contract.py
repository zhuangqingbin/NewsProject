from importlib import import_module

import pandas as pd
import pytest


def test_missing_dataframe_column_reports_source_and_columns():
    contract = import_module("news_pipeline.scrapers.common.contract")
    with pytest.raises(contract.SourceContractError, match=r"wire: missing columns.*链接"):
        contract.require_columns(pd.DataFrame(columns=["标题"]), ["标题", "链接"], source="wire")


@pytest.mark.parametrize(
    "payload", [{}, {"data": None}, {"data": {"items": None}}, {"data": {"items": {}}}]
)
def test_missing_or_wrong_json_list_reports_path(payload):
    contract = import_module("news_pipeline.scrapers.common.contract")
    with pytest.raises(contract.SourceContractError, match=r"wire.*data.items"):
        contract.require_json_list(payload, "data.items", source="wire")


def test_empty_json_list_and_complete_dataframe_are_valid():
    contract = import_module("news_pipeline.scrapers.common.contract")
    assert contract.require_json_list({"data": {"items": []}}, "data.items", source="wire") == []
    contract.require_columns(pd.DataFrame(columns=["标题"]), ["标题"], source="wire")


@pytest.mark.parametrize("value", [None, 1, []])
def test_string_field_type_changes_are_contract_errors(value):
    contract = import_module("news_pipeline.scrapers.common.contract")
    with pytest.raises(contract.SourceContractError, match=r"wire.*title"):
        contract.require_json_string({"title": value}, "title", source="wire")


def test_mapping_and_string_fields_are_validated():
    contract = import_module("news_pipeline.scrapers.common.contract")
    assert contract.require_json_mapping({"data": {}}, "data", source="wire") == {}
    assert contract.require_json_string({"title": ""}, "title", source="wire") == ""
    with pytest.raises(contract.SourceContractError, match=r"wire.*data"):
        contract.require_json_mapping({"data": []}, "data", source="wire")
