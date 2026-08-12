#!/usr/bin/env python3
"""
Benchmark: natural language → Cisco IOS-XE CLI command crafting.

Scores model outputs against accept/reject patterns in cases.json.
Does NOT execute commands on devices — command generation only.

Usage:
  python3 bench_cli_crafting.py --models llama3.1:8b network-specialist:latest
  python3 bench_cli_crafting.py --models llama3.1:8b --ollama-url http://127.0.0.1:11434
  python3 bench_cli_crafting.py --control-only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CASES_FILE = Path(__file__).resolve().parent / "cases.json"


def normalize(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:ios|bash|sh|text)?\s*", "", text, flags=re.I)
    text = re.sub(r"```\s*$", "", text)
    text = text.replace("`", "")
    return text.strip()


def lines(text: str) -> list[str]:
    return [ln.strip() for ln in normalize(text).splitlines() if ln.strip()]


def matches_any(command: str, patterns: Iterable[str]) -> bool:
    cmd = command.lower()
    for pat in patterns:
        if pat.lower() in cmd:
            return True
        if re.search(pat, command, re.I):
            return True
    return False


@dataclass
class CaseResult:
    case_id: str
    score: str  # pass | partial | fail | error
    model_output: str
    detail: str


def score_case(case: dict, output: str) -> CaseResult:
    case_id = case["id"]
    if not output.strip():
        return CaseResult(case_id, "fail", output, "empty output")

    out_lines = lines(output)
    for ln in out_lines:
        for bad in case.get("reject", []):
            if bad.lower() in ln.lower():
                return CaseResult(case_id, "fail", output, f"rejected pattern: {bad}")

    accept = case.get("accept", [])
    for ln in out_lines:
        if matches_any(ln, accept):
            return CaseResult(case_id, "pass", output, f"matched: {ln}")

    # partial: show command but not in accept list
    if any(ln.lower().startswith("show ") for ln in out_lines):
        return CaseResult(case_id, "partial", output, "show command but not in accept list")

    return CaseResult(case_id, "fail", output, "no acceptable command")


def ollama_chat(
    base_url: str,
    model: str,
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    num_ctx: int = 4096,
    timeout: int = 120,
) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": num_ctx, "num_predict": 256},
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return (data.get("message") or {}).get("content") or ""


def run_control(cases: dict) -> dict[str, list[CaseResult]]:
    ref = cases.get("control_reference", {}).get("answers", {})
    results = []
    case_by_id = {c["id"]: c for c in cases["cases"]}
    for case_id, answer in ref.items():
        case = case_by_id.get(case_id)
        if not case:
            continue
        results.append(score_case(case, answer))
    return {"control (Cursor agent)": results}


def run_models(
    cases: dict,
    models: list[str],
    ollama_url: str,
    num_ctx: int,
) -> dict[str, list[CaseResult]]:
    out: dict[str, list[CaseResult]] = {}
    system_tpl = cases["system_prompt"]
    for model in models:
        model_results: list[CaseResult] = []
        print(f"\n{'=' * 60}\nModel: {model}\n{'=' * 60}", file=sys.stderr)
        for case in cases["cases"]:
            system = system_tpl.format(device=case["device"])
            user = case["prompt"]
            t0 = time.time()
            try:
                raw = ollama_chat(
                    ollama_url, model, system, user, num_ctx=num_ctx
                )
                elapsed = time.time() - t0
                result = score_case(case, raw)
                result.detail += f" ({elapsed:.1f}s)"
                print(
                    f"  [{result.score:7}] {case['id']}: {lines(raw)[:2]!r}",
                    file=sys.stderr,
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                result = CaseResult(case["id"], "error", "", str(e))
                print(f"  [error  ] {case['id']}: {e}", file=sys.stderr)
            model_results.append(result)
        out[model] = model_results
    return out


def summarize(all_results: dict[str, list[CaseResult]]) -> None:
    print("\n" + "=" * 72)
    print(f"{'Model':<42} {'Pass':>6} {'Part':>6} {'Fail':>6} {'Err':>5} {'Score':>7}")
    print("-" * 72)
    for name, results in all_results.items():
        counts = {"pass": 0, "partial": 0, "fail": 0, "error": 0}
        for r in results:
            counts[r.score] = counts.get(r.score, 0) + 1
        # pass=1, partial=0.5
        score = counts["pass"] + 0.5 * counts["partial"]
        max_score = len(results)
        pct = 100.0 * score / max_score if max_score else 0
        print(
            f"{name:<42} {counts['pass']:>6} {counts['partial']:>6} "
            f"{counts['fail']:>6} {counts['error']:>5} {pct:>6.1f}%"
        )
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="CLI crafting benchmark")
    parser.add_argument(
        "--models",
        nargs="*",
        default=["llama3.1:8b", "network-specialist:latest"],
        help="Ollama model tags to test",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
        help="Ollama base URL",
    )
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument(
        "--control-only",
        action="store_true",
        help="Score control_reference answers only",
    )
    parser.add_argument(
        "--json-out",
        help="Write detailed results JSON to this path",
    )
    args = parser.parse_args()

    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    all_results: dict[str, list[CaseResult]] = {}

    all_results.update(run_control(cases))

    if not args.control_only:
        all_results.update(
            run_models(cases, args.models, args.ollama_url, args.num_ctx)
        )

    summarize(all_results)

    if args.json_out:
        serializable = {
            model: [
                {
                    "case_id": r.case_id,
                    "score": r.score,
                    "output": r.model_output,
                    "detail": r.detail,
                }
                for r in res
            ]
            for model, res in all_results.items()
        }
        Path(args.json_out).write_text(
            json.dumps(serializable, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nWrote {args.json_out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
