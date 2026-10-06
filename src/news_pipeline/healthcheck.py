import argparse
import os
from pathlib import Path

from shared.observability.heartbeat import heartbeat_healthy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--subsystem", choices=["news_pipeline", "quote_watcher"], default="news_pipeline"
    )
    args = parser.parse_args()
    path = Path(os.environ.get("HEARTBEAT_PATH", f"data/heartbeat_{args.subsystem}.json"))
    ok = heartbeat_healthy(path)
    print("OK" if ok else "FAIL: scheduler heartbeat is stale or missing")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
