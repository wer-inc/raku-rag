#!/usr/bin/env python3
"""Report whether the repository has enough evidence for a paid pilot.

The script is intentionally read-only. It combines the production-readiness ledger with explicit
evidence files so operators cannot accidentally mark billed, live, or human-gated work complete from
code alone.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_LEDGER = Path("specs/prod-readiness/ledger.json")
DEFAULT_GATE = Path("specs/prod-readiness/paid-pilot-gate.json")


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def evidence_status(path: Path) -> str:
    if not path.exists():
        return "missing"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("status:"):
            value = line.split(":", 1)[1].strip().lower()
            return value or "unknown"
    return "unknown"


def build_report(
    *,
    repo_root: Path,
    ledger_path: Path = DEFAULT_LEDGER,
    gate_path: Path = DEFAULT_GATE,
) -> dict[str, Any]:
    ledger = load_json(repo_root / ledger_path)
    gate = load_json(repo_root / gate_path)
    units = {unit["id"]: unit for unit in ledger.get("units", []) if isinstance(unit, dict)}
    requirements: list[dict[str, Any]] = []
    for req in gate.get("requirements", []):
        if not isinstance(req, dict):
            continue
        accepted = tuple(str(s).lower() for s in req.get("accepted_statuses", []))
        kind = str(req.get("kind", ""))
        actual = "unknown"
        source = ""
        if kind == "ledger_unit":
            source = str(req.get("ledger_unit", ""))
            unit = units.get(source)
            actual = str(unit.get("status", "missing")).lower() if unit else "missing"
        elif kind == "evidence_file":
            source = str(req.get("evidence_file", ""))
            actual = evidence_status(repo_root / source)
        else:
            actual = "invalid-kind"
        ready = actual in accepted
        requirements.append(
            {
                "id": str(req.get("id", "")),
                "title": str(req.get("title", "")),
                "kind": kind,
                "source": source,
                "status": actual,
                "accepted_statuses": list(accepted),
                "ready": ready,
            }
        )
    counts = Counter("ready" if req["ready"] else req["status"] for req in requirements)
    return {
        "schema_version": 1,
        "readiness_label": gate.get("readiness_label", "paid-pilot-ready"),
        "ready": all(req["ready"] for req in requirements) and bool(requirements),
        "summary": dict(sorted(counts.items())),
        "requirements": requirements,
    }


def render_markdown(report: dict[str, Any]) -> str:
    status = "READY" if report["ready"] else "NOT READY"
    lines = [
        f"# {report['readiness_label']}: {status}",
        "",
        "## Summary",
    ]
    for key, value in report["summary"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Requirements",
            "| ID | Status | Required | Source | Title |",
            "|---|---|---|---|---|",
        ]
    )
    for req in report["requirements"]:
        required = ", ".join(req["accepted_statuses"])
        mark = "OK" if req["ready"] else "BLOCKED"
        lines.append(
            f"| {req['id']} | {mark}: {req['status']} | {required} | "
            f"{req['source']} | {req['title']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repository root")
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="ledger JSON path")
    parser.add_argument("--gate", default=str(DEFAULT_GATE), help="paid pilot gate JSON path")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--fail-on-not-ready", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(
        repo_root=Path(args.repo_root),
        ledger_path=Path(args.ledger),
        gate_path=Path(args.gate),
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_markdown(report), end="")
    return 1 if args.fail_on_not_ready and not report["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
