import csv
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from news_pipeline.tools.gold import (
    dataset_report,
    import_reviewed_csv,
    load_dataset,
    main,
    select_split,
)

CASES = (
    "nvda_buyback",
    "tesla_target",
    "tesla_fitch",
    "meta_big_move",
    "amd_acquisition",
    "avgo_roundup",
    "yaoming_junuo",
    "ningde_city",
)
STRATA = {"push": 50, "digest_hi": 50, "mention": 30, "macro": 20}


def row(n=1, **updates):
    value = {
        "id": f"event-{n:03d}",
        "event_id": str(n),
        "stratum": "push",
        "case": "",
        "title": "英伟达增加回购授权",
        "body": "来源原文\n第二行",
        "source": "wire",
        "sources": ["wire", "sec_edgar"],
        "market": "us",
        "published_at": "2026-10-06T10:30:00+08:00",
        "url": f"https://example.com/news/{n}",
        "raw_meta": {"level": "B", "evidence": [{"id": n, "original": "原文"}]},
        "tickers": ["NVDA"],
        "rule_decision": "push",
        "label": "must_push",
        "annotation_status": "reviewed",
    }
    value.update(updates)
    return value


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for value in rows:
            writer.writerow(
                {
                    key: json.dumps(item, ensure_ascii=False)
                    if key in {"sources", "tickers", "raw_meta"}
                    else item
                    for key, item in value.items()
                }
            )


def reviewed_dataset():
    rows = []
    for stratum, count in STRATA.items():
        for _ in range(count):
            n = len(rows) + 1
            rows.append(row(n, stratum=stratum, case=CASES[n - 1] if n <= 8 else ""))
    return rows


def test_import_preserves_reviewed_corrections_and_source_evidence(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "reviewed.jsonl"
    original = row(
        event_id="0007", label="drop", tickers=[], annotation_note="人工修正", case="nvda_buyback"
    )
    write_csv(source, [original])
    before = source.read_bytes()

    report = import_reviewed_csv(source, output)

    restored = load_dataset(output)
    assert restored == [{**original, "split": "train"}]
    assert source.read_bytes() == before
    assert report["sample_count"] == 1
    assert report["acceptance_ready"] is False
    assert report["dataset_hash"] == dataset_report(restored)["dataset_hash"]


@pytest.mark.parametrize("status", ["unreviewed", "seed_unreviewed", "", "Reviewed"])
def test_import_requires_explicit_review_for_every_row(tmp_path, status):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row(), row(2, annotation_status=status)])

    with pytest.raises(ValueError, match=r"row 3.*annotation_status.*reviewed"):
        import_reviewed_csv(source, output)

    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("event_id", ""),
        ("stratum", "digest_lo"),
        ("market", "hk"),
        ("source", " "),
        ("sources", []),
        ("sources", ["sec_edgar"]),
        ("sources", ["wire", 3]),
        ("url", "javascript:alert(1)"),
        ("url", "https:///missing-host"),
        ("url", "https://example.com:99999/news"),
        ("url", "https://example.com/has space"),
        ("url", "https://exa%mple.com/a"),
        ("published_at", "2026-10-06"),
        ("published_at", "2026-10-06T12:00:00"),
        ("published_at", "not-a-time"),
        ("raw_meta", []),
        ("tickers", "NVDA"),
        ("tickers", [1]),
        ("tickers", [""]),
        ("label", "push"),
        ("rule_decision", "invented"),
    ],
)
def test_import_rejects_invalid_rows_with_local_field_error(tmp_path, field, value):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row(), row(2, **{field: value})])

    with pytest.raises(ValueError, match=rf"row 3.*{field}"):
        import_reviewed_csv(source, output)

    assert not output.exists()


@pytest.mark.parametrize("field", ["id", "event_id", "url"])
def test_import_rejects_duplicate_stable_identifiers(tmp_path, field):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row(), row(2, **{field: row()[field]})])

    with pytest.raises(ValueError, match=rf"row 3.*duplicate {field}"):
        import_reviewed_csv(source, output)

    assert not output.exists()


@pytest.mark.parametrize(
    "duplicate_url",
    [
        "https://example.com/news/1",
        "https://example.com/news/1#another-section",
        "https://EXAMPLE.COM:443/news/1",
    ],
)
def test_duplicate_evidence_url_cannot_leak_across_ids_or_splits(tmp_path, duplicate_url):
    rows = [row(split="train"), row(2, url=duplicate_url, split="holdout")]
    path = tmp_path / "duplicates.jsonl"
    path.write_text("\n".join(json.dumps(value) for value in rows), encoding="utf-8")

    with pytest.raises(ValueError, match=r"row 2.*duplicate url"):
        load_dataset(path)
    with pytest.raises(ValueError, match=r"row 2.*duplicate url"):
        dataset_report(rows)
    with pytest.raises(ValueError, match=r"row 2.*duplicate url"):
        select_split(rows, "train")


def test_import_rejects_missing_headers_and_empty_input(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    source.write_text("title,label\nExample,digest\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"missing.*id"):
        import_reviewed_csv(source, output)
    write_csv(source, [row()])
    source.write_text(source.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no data rows"):
        import_reviewed_csv(source, output)
    assert not output.exists()


def test_import_refuses_existing_output_and_input_collision(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row()])
    output.write_text("preserved seed data\n", encoding="utf-8")
    before = source.read_bytes()

    with pytest.raises(FileExistsError):
        import_reviewed_csv(source, output)
    with pytest.raises(ValueError, match="different"):
        import_reviewed_csv(source, source)

    assert source.read_bytes() == before
    assert output.read_text(encoding="utf-8") == "preserved seed data\n"


def test_load_dataset_rejects_url_that_raw_article_cannot_accept(tmp_path):
    path = tmp_path / "invalid-url.jsonl"
    path.write_text(json.dumps(row(url="https://exa%mple.com/a")) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"row 1.*url.*valid HTTP"):
        load_dataset(path)


def test_import_preserves_original_url_spelling_after_validation(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    original_url = "https://EXAMPLE.COM:443/原文?q=%2f#一"
    write_csv(source, [row(url=original_url)])

    import_reviewed_csv(source, output)

    assert load_dataset(output)[0]["url"] == original_url


@pytest.mark.parametrize("reviewed", [True, False])
def test_import_handles_complete_long_body_and_restores_csv_limit(tmp_path, reviewed):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    body = "完整正文\n" * 30_000
    assert len(body) > 131_072
    write_csv(source, [row(body=body, annotation_status="reviewed" if reviewed else "unreviewed")])
    original_limit = csv.field_size_limit(131_072)
    try:
        if reviewed:
            import_reviewed_csv(source, output)
            assert load_dataset(output)[0]["body"] == body
        else:
            with pytest.raises(ValueError, match=r"row 2.*annotation_status.*reviewed"):
                import_reviewed_csv(source, output)
            assert not output.exists()
        assert csv.field_size_limit() == 131_072
    finally:
        csv.field_size_limit(original_limit)


def test_import_does_not_require_an_optional_case_column(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    value = row()
    value.pop("case")
    write_csv(source, [value])

    import_reviewed_csv(source, output)

    assert load_dataset(output) == [{**value, "split": "train"}]


def test_atomic_import_never_replaces_an_output_created_during_publish(tmp_path, monkeypatch):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row()])
    link = os.link

    def concurrent_output(temporary, target):
        target.write_text("another process owns this path\n", encoding="utf-8")
        link(temporary, target)

    monkeypatch.setattr("news_pipeline.tools.gold.os.link", concurrent_output)

    with pytest.raises(FileExistsError):
        import_reviewed_csv(source, output)

    assert output.read_text(encoding="utf-8") == "another process owns this path\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["gold.jsonl", "review.csv"]


@pytest.mark.parametrize(
    "field", ["market", "label", "annotation_status", "stratum", "rule_decision", "split"]
)
def test_structural_validation_rejects_nonstring_choices_with_row_error(tmp_path, field):
    value = row(**{field: []})
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match=rf"row 1.*{field}"):
        load_dataset(path)
    with pytest.raises(ValueError, match=rf"row 1.*{field}"):
        dataset_report([value])


def test_import_rejects_nonfinite_raw_metadata(tmp_path):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row(raw_meta={"invalid": float("nan")})])

    with pytest.raises(ValueError, match=r"row 2.*raw_meta.*finite JSON"):
        import_reviewed_csv(source, output)

    assert not output.exists()


def test_report_keeps_unreviewed_seed_cases_usable_for_regression():
    seed_path = Path(__file__).parents[2] / "eval" / "gold_events.jsonl"
    rows = [json.loads(line) for line in seed_path.read_text(encoding="utf-8").splitlines()]

    report = dataset_report(rows)

    assert report["sample_count"] == 8
    assert report["regression_ready"] is True
    assert report["acceptance_ready"] is False
    assert report["missing_known_cases"] == []
    assert any("150" in issue for issue in report["acceptance_issues"])
    assert any("reviewed" in issue for issue in report["acceptance_issues"])
    assert any("published_at" in issue for issue in report["acceptance_issues"])
    assert select_split(rows, "all") == rows
    with pytest.raises(ValueError, match="persisted split"):
        select_split(rows, "train")


def test_import_freezes_reproducible_stratified_train_holdout_split(tmp_path):
    rows = reviewed_dataset()
    source = tmp_path / "review.csv"
    first, second = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    write_csv(source, rows)
    report = import_reviewed_csv(source, first)
    changed = [{**value, "label": "digest", "tickers": []} for value in reversed(rows)]
    write_csv(source, changed)
    import_reviewed_csv(source, second)
    original, corrected = load_dataset(first), load_dataset(second)

    assert {value["id"]: value["split"] for value in original} == {
        value["id"]: value["split"] for value in corrected
    }
    assert report["acceptance_ready"] is True
    assert report["acceptance_issues"] == []
    assert report["split_counts"] == {"train": 120, "holdout": 30, "unassigned": 0}
    assert Counter(value["stratum"] for value in select_split(original, "holdout")) == {
        "push": 10,
        "digest_hi": 10,
        "mention": 6,
        "macro": 4,
    }
    assert len(select_split(original, "train")) == 120
    assert dataset_report(list(reversed(original)))["dataset_hash"] == report["dataset_hash"]
    assert dataset_report(corrected)["dataset_hash"] != report["dataset_hash"]


@pytest.mark.parametrize("problem", ["case", "stratum", "split", "review", "evidence"])
def test_acceptance_report_rejects_incomplete_or_changed_evidence(tmp_path, problem):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, reviewed_dataset())
    import_reviewed_csv(source, output)
    rows = load_dataset(output)
    if problem == "case":
        rows[0]["case"] = ""
    elif problem == "stratum":
        rows[0]["stratum"] = "macro"
    elif problem == "split":
        train = next(value for value in rows if value["split"] == "train")
        holdout = next(value for value in rows if value["split"] == "holdout")
        train["split"], holdout["split"] = holdout["split"], train["split"]
    elif problem == "review":
        rows[0]["annotation_status"] = "unreviewed"
    else:
        rows[0].pop("published_at")

    report = dataset_report(rows)

    assert report["acceptance_ready"] is False
    assert report["acceptance_issues"]


@pytest.mark.parametrize("content", ['{"id":', "[]\n", '{"id":"x","label":"push"}\n'])
def test_load_dataset_rejects_malformed_rows_with_line_number(tmp_path, content):
    path = tmp_path / "broken.jsonl"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="row 1"):
        load_dataset(path)


def test_load_dataset_preserves_lenient_seed_without_inventing_evidence(tmp_path):
    required = {"id", "title", "body", "market", "source", "label", "tickers", "annotation_status"}
    value = {
        key: item
        for key, item in row(annotation_status="seed_unreviewed").items()
        if key in required
    }
    path = tmp_path / "seed.jsonl"
    path.write_text("\n" + json.dumps(value) + "\n\n", encoding="utf-8")

    assert load_dataset(path) == [value]
    assert dataset_report(load_dataset(path))["acceptance_ready"] is False


def test_split_selection_rejects_unknown_split():
    with pytest.raises(ValueError, match=r"all.*train.*holdout"):
        select_split([], "test")


def test_cli_import_and_acceptance_validation(tmp_path, capsys):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, reviewed_dataset())

    assert main(["import", "--csv", str(source), "--output", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance_ready"] is True
    assert main(["validate", str(output), "--acceptance"]) == 0
    assert json.loads(capsys.readouterr().out)["sample_count"] == 150


def test_cli_reports_regression_dataset_without_claiming_acceptance(tmp_path, capsys):
    path = tmp_path / "regression.jsonl"
    path.write_text(json.dumps(row(annotation_status="seed_unreviewed")) + "\n", encoding="utf-8")

    assert main(["validate", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["acceptance_ready"] is False
    assert main(["validate", str(path), "--acceptance"]) == 1
    assert json.loads(capsys.readouterr().out)["acceptance_ready"] is False


def test_cli_import_returns_row_local_error(tmp_path, capsys):
    source, output = tmp_path / "review.csv", tmp_path / "gold.jsonl"
    write_csv(source, [row(annotation_status="unreviewed")])

    with pytest.raises(SystemExit) as error:
        main(["import", "--csv", str(source), "--output", str(output)])

    assert error.value.code == 2
    assert "row 2" in capsys.readouterr().err
    assert not output.exists()
