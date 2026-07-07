"""Batch independent items — output JSON array aligned by input index."""

from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TASKS = ("classification", "extraction", "summarization", "scoring", "validation")

DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4}|\d{2}/\d{2}/\d{4})\b")
PATH_RE = re.compile(r"\b(?:[\w.-]+/)+[\w.-]+\.py\b")
SYMBOL_RE = re.compile(r"\b([A-Za-z_][\w]*)\s*\(")


def _text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "task", "content", "message", "description"):
            if key in item and item[key]:
                return str(item[key])
        return json.dumps(item, ensure_ascii=False)
    return str(item)


def _ok(index: int, result: Any) -> dict:
    return {"index": index, "ok": True, "result": result}


def _err(index: int, message: str) -> dict:
    return {"index": index, "ok": False, "error": message}


def _classify_item(item: Any, index: int) -> dict:
    text = _text(item)
    if not text.strip():
        return _err(index, "empty item")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from scripts.agent_route import route_task

    rec = route_task(text)
    return _ok(
        index,
        {
            "complexity": rec.complexity,
            "slice_id": rec.slice_id,
            "skill": rec.skill.split("/")[-2] if "/" in rec.skill else rec.skill,
            "cursor_mode": rec.cursor_mode,
        },
    )


def _extract_item(item: Any, index: int) -> dict:
    text = _text(item)
    dates: List[str] = []
    valid_dates: List[str] = []
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import validators

    for match in DATE_RE.findall(text):
        dates.append(match)
        try:
            valid_dates.append(validators.format_date(validators.parse_date(match)))
        except (ValueError, TypeError):
            pass

    paths = PATH_RE.findall(text)
    symbols = SYMBOL_RE.findall(text)

    slice_hits: List[str] = []
    try:
        from slices.registry import SLICES

        lower = text.lower()
        for s in SLICES:
            sid = s["id"]
            name = s.get("name", "").lower()
            if sid in lower or (name and name in lower):
                slice_hits.append(sid)
    except Exception:
        pass

    return _ok(
        index,
        {
            "dates": dates,
            "valid_dates": valid_dates,
            "paths": paths,
            "symbols": symbols[:20],
            "slice_ids": slice_hits,
            "tokens": max(1, len(text) // 4),
        },
    )


def _summarize_item(item: Any, index: int, *, max_chars: int = 240) -> dict:
    text = _text(item)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    preview = text[:max_chars]
    if len(text) > max_chars:
        preview += "…"
    keywords = []
    for ln in lines[:12]:
        if re.search(r"\b(fix|bug|add|error|fail|todo|decision|must|should)\b", ln, re.I):
            keywords.append(ln[:120])
    return _ok(
        index,
        {
            "preview": preview,
            "lines": len(lines),
            "tokens": max(1, len(text) // 4),
            "highlights": keywords[:5],
        },
    )


def _score_item(item: Any, index: int) -> dict:
    text = _text(item)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from scripts.agent_route import route_task

    rec = route_task(text)
    tokens = max(1, len(text) // 4)
    words = len(text.split())
    tier_score = {
        "trivial": 10,
        "low": 25,
        "verify": 20,
        "medium": 50,
        "high": 85,
        "vision": 70,
    }.get(rec.complexity, 50)
    length_score = min(30, words // 2)
    score = min(100, tier_score + length_score)
    return _ok(
        index,
        {
            "score": score,
            "complexity": rec.complexity,
            "tokens": tokens,
            "words": words,
            "slice_id": rec.slice_id,
        },
    )


def _validate_item(item: Any, index: int) -> dict:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import validators

    checks: List[dict] = []

    def add(name: str, result) -> None:
        checks.append({"field": name, "ok": result.ok, "message": result.message})

    if isinstance(item, dict):
        if "date" in item or "request_date" in item:
            raw = item.get("date") or item.get("request_date")
            try:
                parsed = validators.parse_date(str(raw))
                add("date", validators.validate_cycle_date(parsed))
            except (ValueError, TypeError) as exc:
                checks.append({"field": "date", "ok": False, "message": str(exc)})
        if "name" in item:
            add("name", validators.validate_officer_name(str(item.get("name", ""))))
        if "email" in item:
            add("email", validators.validate_officer_email(item.get("email")))
        if "username" in item:
            add("username", validators.validate_username(str(item.get("username", ""))))
        if "password" in item:
            add("password", validators.validate_password(str(item.get("password", ""))))
        if "seniority_rank" in item:
            try:
                add("seniority_rank", validators.validate_seniority_rank(int(item["seniority_rank"])))
            except (TypeError, ValueError):
                checks.append({"field": "seniority_rank", "ok": False, "message": "invalid rank"})
        if "status" in item and "action" in item:
            add("status", validators.validate_request_status(str(item["status"]), str(item["action"])))
        if not checks:
            return _err(index, "no known validation fields in object")
        ok = all(c["ok"] for c in checks)
        return {"index": index, "ok": ok, "result": {"checks": checks}}
    if isinstance(item, str):
        try:
            parsed = validators.parse_date(item.strip())
            result = validators.validate_cycle_date(parsed)
            return _ok(index, {"date": validators.format_date(parsed), "valid": result.ok, "message": result.message})
        except (ValueError, TypeError) as exc:
            return _err(index, str(exc))
    return _err(index, "validation expects string date or object with known fields")


HANDLERS: Dict[str, Callable[[Any, int], dict]] = {
    "classification": _classify_item,
    "extraction": _extract_item,
    "summarization": lambda item, idx: _summarize_item(item, idx),
    "scoring": _score_item,
    "validation": _validate_item,
}


def process_batch(
    task: str,
    items: List[Any],
    *,
    workers: int = 0,
    options: Optional[dict] = None,
) -> List[dict]:
    task = (task or "").strip().lower()
    if task not in HANDLERS:
        raise ValueError(f"unknown task {task!r}; choose from {', '.join(TASKS)}")

    if not items:
        return []

    opts = options or {}
    max_workers = int(opts.get("workers", workers or 0))
    if max_workers <= 0:
        max_workers = min(8, max(1, len(items)))

    handler = HANDLERS[task]
    if task == "summarization":
        max_chars = int(opts.get("max_chars", 240))

        def handler(item, idx):
            return _summarize_item(item, idx, max_chars=max_chars)

    results: List[Optional[dict]] = [None] * len(items)

    if max_workers == 1 or len(items) == 1:
        for i, item in enumerate(items):
            try:
                results[i] = handler(item, i)
            except Exception as exc:
                results[i] = _err(i, str(exc))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(handler, item, i): i for i, item in enumerate(items)}
            for fut in as_completed(futures):
                i = futures[fut]
                try:
                    results[i] = fut.result()
                except Exception as exc:
                    results[i] = _err(i, str(exc))

    return [r if r is not None else _err(i, "missing result") for i, r in enumerate(results)]


def load_payload(
    *,
    input_path: str = "",
    items_json: str = "",
    stdin: bool = False,
    task: str = "",
) -> dict:
    if stdin:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    elif input_path:
        with open(input_path, encoding="utf-8") as fh:
            data = json.load(fh)
    elif items_json:
        data = {"items": json.loads(items_json)}
    else:
        data = {}

    if task and not data.get("task"):
        data["task"] = task
    if "items" not in data:
        raise ValueError("payload must include 'items' array")
    if not isinstance(data["items"], list):
        raise ValueError("'items' must be a JSON array")
    return data


def run_batch_process(
    task: str = "",
    *,
    input_path: str = "",
    items_json: str = "",
    stdin: bool = False,
    output_path: str = "",
    workers: int = 0,
    quiet: bool = False,
    full: bool = False,
) -> int:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)

    payload = load_payload(
        input_path=input_path,
        items_json=items_json,
        stdin=stdin,
        task=task,
    )
    resolved_task = (payload.get("task") or task or "").strip().lower()
    options = payload.get("options") or {}
    if workers:
        options = {**options, "workers": workers}

    try:
        raw = process_batch(resolved_task, payload["items"], workers=workers, options=options)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    from scripts.structured_output import dump_json, shape_batch_results

    out = shape_batch_results(resolved_task, raw, full=full)
    text = dump_json(out, compact=not full)
    if output_path:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if not quiet:
            print(f"batch-process: wrote {len(out)} results → {output_path}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Batch independent items → JSON array by index")
    p.add_argument("task", choices=TASKS, help="Task type")
    p.add_argument("--input", "-i", default="", help="JSON file: {task?, items[], options?}")
    p.add_argument("--items", default="", help="JSON array of items")
    p.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    p.add_argument("--output", "-o", default="", help="Write JSON array to file")
    p.add_argument("--workers", type=int, default=0, help="Parallel workers (default min(8, n))")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--full", action="store_true", help="Nested result blob (verbose)")
    ns = p.parse_args()
    raise SystemExit(
        run_batch_process(
            ns.task,
            input_path=ns.input,
            items_json=ns.items,
            stdin=ns.stdin,
            output_path=ns.output,
            workers=ns.workers,
            quiet=ns.quiet,
            full=ns.full,
        )
    )
