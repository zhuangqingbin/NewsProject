"""Import human-reviewed event annotations without overwriting source or seed files.

``import --csv review.csv --output reviewed.jsonl`` preserves corrected annotations
and source evidence, and freezes an ID-based train/holdout split. ``validate PATH``
also accepts the smaller seed dataset for regression; ``--acceptance`` requires
the complete reviewed 150-event dataset. Neither command invokes a model.
"""

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import HttpUrl

from news_pipeline.common.enums import Market

KNOWN_CASES = (
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
_LABELS = {"must_push", "digest", "drop"}
_STATUSES = {"reviewed", "unreviewed", "seed_unreviewed"}
_RULE_DECISIONS = {"push", "digest_hi", "digest_lo", "drop"}
_EVIDENCE_FIELDS = (
    "event_id",
    "stratum",
    "sources",
    "published_at",
    "url",
    "raw_meta",
    "rule_decision",
)
_CSV_FIELDS = {
    "id",
    "title",
    "body",
    "source",
    "market",
    "tickers",
    "label",
    "annotation_status",
    *_EVIDENCE_FIELDS,
}
_SPLIT_SEED = "news-pipeline-gold-v1:42"


def _error(number: int, field: str, reason: str) -> ValueError:
    return ValueError(f"row {number}: {field} {reason}")


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    )


def _validate_row(row: Any, number: int, *, reviewed: bool = False) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise _error(number, "record", "must be a JSON object")
    for field in ("id", "source", "title", "body"):
        value = row.get(field)
        if not isinstance(value, str) or (field in {"id", "source"} and not value.strip()):
            raise _error(number, field, "must be a string (id and source must be nonempty)")
    if not row["title"].strip() and not row["body"].strip():
        raise _error(number, "title/body", "must contain article text")
    if not isinstance(row.get("market"), str) or row["market"] not in Market:
        raise _error(number, "market", "must be us or cn")
    if not isinstance(row.get("label"), str) or row["label"] not in _LABELS:
        raise _error(number, "label", "must be must_push, digest or drop")
    if not _string_list(row.get("tickers")):
        raise _error(number, "tickers", "must be a JSON list of nonempty strings")
    if reviewed and row.get("annotation_status") != "reviewed":
        raise _error(number, "annotation_status", "must be reviewed on every imported row")
    if (
        not isinstance(row.get("annotation_status"), str)
        or row["annotation_status"] not in _STATUSES
    ):
        raise _error(number, "annotation_status", "must be reviewed, unreviewed or seed_unreviewed")
    if "case" in row and not isinstance(row["case"], str):
        raise _error(number, "case", "must be a string")
    if "split" in row and (
        not isinstance(row["split"], str) or row["split"] not in {"train", "holdout"}
    ):
        raise _error(number, "split", "must be train or holdout")
    if reviewed:
        for field in _EVIDENCE_FIELDS:
            if field not in row:
                raise _error(number, field, "is required for reviewed source evidence")
    if "event_id" in row:
        value = row["event_id"]
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
            raise _error(number, "event_id", "must be a nonempty string or integer")
    if "stratum" in row and (not isinstance(row["stratum"], str) or row["stratum"] not in STRATA):
        raise _error(number, "stratum", "must be push, digest_hi, mention or macro")
    if "rule_decision" in row and (
        not isinstance(row["rule_decision"], str) or row["rule_decision"] not in _RULE_DECISIONS
    ):
        raise _error(number, "rule_decision", "must be push, digest_hi, digest_lo or drop")
    if "sources" in row and (
        not _string_list(row["sources"]) or row["source"] not in row["sources"]
    ):
        raise _error(number, "sources", "must be a JSON string list containing source")
    if "raw_meta" in row and not isinstance(row["raw_meta"], dict):
        raise _error(number, "raw_meta", "must be a JSON object")
    if "published_at" in row:
        try:
            at = datetime.fromisoformat(row["published_at"])
            if at.utcoffset() is None:
                raise ValueError("timezone is required")
        except (ValueError, TypeError) as error:
            raise _error(number, "published_at", "must be a timezone-aware ISO8601 time") from error
    if "url" in row:
        try:
            value = row["url"]
            parsed = urlsplit(value)
            if (
                not isinstance(value, str)
                or any(char.isspace() for char in value)
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
            ):
                raise ValueError("HTTP(S) URL with a host is required")
            _ = parsed.port
            HttpUrl(value)
        except (ValueError, TypeError, AttributeError) as error:
            raise _error(number, "url", "must be a valid HTTP(S) URL") from error
    try:
        json.dumps(row, allow_nan=False)
    except (ValueError, TypeError) as error:
        raise _error(number, "record/raw_meta", "must contain finite JSON values") from error
    return row


def _unique(row: dict[str, Any], number: int, seen: dict[str, set[str]]) -> None:
    for field in ("id", "event_id", "url"):
        if field not in row:
            continue
        value = str(row[field])
        if field == "url":
            parsed = urlsplit(value)
            default_port = 443 if parsed.scheme == "https" else 80
            port = parsed.port if parsed.port != default_port else None
            value = json.dumps(
                [parsed.scheme, parsed.hostname, port, parsed.path or "/", parsed.query]
            )
        if value in seen[field]:
            raise _error(number, field, f"has duplicate {field} {value!r}")
        seen[field].add(value)


def _validate_rows(rows: list[dict[str, Any]]) -> None:
    seen: dict[str, set[str]] = {"id": set(), "event_id": set(), "url": set()}
    for number, row in enumerate(rows, 1):
        _validate_row(row, number)
        _unique(row, number, seen)


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Validate JSONL regression rows, retaining absent legacy evidence as absent."""
    rows: list[dict[str, Any]] = []
    seen: dict[str, set[str]] = {"id": set(), "event_id": set(), "url": set()}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise _error(number, "record", f"invalid JSON: {error}") from error
        rows.append(_validate_row(row, number))
        _unique(row, number, seen)
    return rows


def _split_assignments(rows: list[dict[str, Any]]) -> dict[str, str]:
    assignments = {row["id"]: "train" for row in rows}
    for stratum in STRATA:
        bucket = [row for row in rows if row.get("stratum") == stratum]
        bucket.sort(
            key=lambda row: (
                hashlib.sha256(f"{_SPLIT_SEED}:{row['id']}".encode()).hexdigest(),
                row["id"],
            )
        )
        quota = max(1, len(bucket) // 5) if len(bucket) > 1 else 0
        for row in bucket[:quota]:
            assignments[row["id"]] = "holdout"
    return assignments


def dataset_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate valid regression data from complete, frozen acceptance evidence."""
    _validate_rows(rows)
    issues: list[str] = []
    counts = Counter(row.get("stratum") for row in rows)
    strata = {key: counts[key] for key in STRATA}
    statuses = Counter(row["annotation_status"] for row in rows)
    cases = sorted({row["case"] for row in rows if row.get("case")})
    missing_cases = sorted(set(KNOWN_CASES) - set(cases))
    splits = ("train", "holdout", "unassigned")
    split_counts = {key: 0 for key in splits}
    split_strata = {key: dict.fromkeys(STRATA, 0) for key in splits}
    for row in rows:
        split = row.get("split", "unassigned")
        split_counts[split] += 1
        if row.get("stratum") in STRATA:
            split_strata[split][row["stratum"]] += 1
    if len(rows) != 150:
        issues.append(f"requires exactly 150 events; found {len(rows)}")
    if strata != STRATA:
        issues.append(f"requires strata {STRATA}; found {strata}")
    if statuses["reviewed"] != len(rows):
        issues.append("every event must have annotation_status=reviewed")
    if missing_cases:
        issues.append("missing known cases: " + ", ".join(missing_cases))
    for number, row in enumerate(rows, 1):
        missing = [field for field in _EVIDENCE_FIELDS if field not in row]
        if missing:
            issues.append(f"row {number}: missing source evidence: {', '.join(missing)}")
    if split_counts != {"train": 120, "holdout": 30, "unassigned": 0}:
        issues.append(f"requires persisted split train=120, holdout=30; found {split_counts}")
    expected = _split_assignments(rows)
    if any(row.get("split") != expected[row["id"]] for row in rows):
        issues.append("persisted split does not match the deterministic ID-based assignment")
    expected_holdout = {key: count // 5 for key, count in STRATA.items()}
    expected_train = {key: count - expected_holdout[key] for key, count in STRATA.items()}
    if split_strata["holdout"] != expected_holdout or split_strata["train"] != expected_train:
        issues.append("train and holdout must preserve strata (40/40/24/16 and 10/10/6/4)")
    canonical = json.dumps(
        sorted(rows, key=lambda row: row["id"]),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return {
        "sample_count": len(rows),
        "dataset_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "regression_ready": bool(rows),
        "strata": strata,
        "annotation_status_counts": dict(sorted(statuses.items())),
        "case_ids": cases,
        "missing_known_cases": missing_cases,
        "split_counts": split_counts,
        "split_strata": split_strata,
        "acceptance_ready": not issues,
        "acceptance_issues": issues,
    }


def select_split(rows: list[dict[str, Any]], split: str = "all") -> list[dict[str, Any]]:
    """Select persisted membership without recomputing or assigning any split."""
    if split not in {"all", "train", "holdout"}:
        raise ValueError("split must be all, train or holdout")
    _validate_rows(rows)
    if split == "all":
        return list(rows)
    if any("split" not in row for row in rows):
        raise ValueError("train/holdout selection requires a persisted split on every row")
    return [row for row in rows if row["split"] == split]


@contextmanager
def _csv_field_limit(source: Path) -> Iterator[None]:
    previous = csv.field_size_limit()
    try:
        # No field can contain more characters than this UTF-8 file has bytes.
        csv.field_size_limit(max(previous, source.stat().st_size))
        yield
    finally:
        csv.field_size_limit(previous)


def import_reviewed_csv(source: Path, output: Path) -> dict[str, Any]:
    """Atomically create a new JSONL dataset; existing outputs are never replaced."""
    if source.resolve() == output.resolve():
        raise ValueError("source and output must be different files")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}; choose a new output path")
    rows = []
    seen: dict[str, set[str]] = {"id": set(), "event_id": set(), "url": set()}
    with _csv_field_limit(source), source.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise ValueError("CSV header has duplicate columns")
        missing = _CSV_FIELDS - set(fields)
        if missing:
            raise ValueError("CSV header missing required columns: " + ", ".join(sorted(missing)))
        for number, values in enumerate(reader, 2):
            if None in values or any(value is None for value in values.values()):
                raise _error(number, "record", "column count does not match CSV header")
            row: dict[str, Any] = dict(values)
            for field in ("sources", "tickers", "raw_meta"):
                try:
                    row[field] = json.loads(row[field])
                except ValueError as error:
                    raise _error(number, field, f"invalid JSON: {error}") from error
            _validate_row(row, number, reviewed=True)
            _unique(row, number, seen)
            rows.append(row)
    if not rows:
        raise ValueError("CSV contains no data rows")
    assignments = _split_assignments(rows)
    for row in rows:
        row["split"] = assignments[row["id"]]
    report = dataset_report(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        # A same-filesystem hard link publishes the finished file atomically and
        # refuses an output created by another process after the earlier check.
        os.link(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import", help="import explicitly reviewed CSV into new JSONL")
    importer.add_argument("--csv", required=True, type=Path)
    importer.add_argument("--output", required=True, type=Path)
    validator = commands.add_parser("validate", help="report regression and acceptance readiness")
    validator.add_argument("path", type=Path)
    validator.add_argument("--acceptance", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = (
            import_reviewed_csv(args.csv, args.output)
            if args.command == "import"
            else dataset_report(load_dataset(args.path))
        )
    except (ValueError, OSError, csv.Error) as error:
        parser.error(str(error))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.command == "validate" and args.acceptance and not report["acceptance_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
