#!/usr/bin/env python3
"""
Classify news articles as "research related" or "not research related"
using a local Ollama model.

Features
--------
- Reads JSON files from a folder (optionally recursively)
- Supports:
    1) one article per JSON file (dict)
    2) multiple articles in a JSON file (list of dicts)
    3) newline-delimited JSON (.jsonl / .ndjson)
- Uses article title + content/body/text as input
- Sends classification prompt to local Ollama API
- Writes results to CSV

Example
-------
python classify_articles_ollama.py \
    --input-dir ./articles/lusaka_times \
    --output-csv ./classified_articles.csv \
    --model llama3.1:8b \
    --recursive

Requirements
------------
pip install requests pandas
"""

from __future__ import annotations

import argparse
import csv
import json
import html
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

import requests


OLLAMA_URL = "http://localhost:11434/api/generate"


def normalize_whitespace(text: str) -> str:
    """Collapse repeated whitespace and strip."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to a maximum number of characters."""
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."

def strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def safe_get(record: dict, candidate_keys: list[str]) -> str:
    """
    Return the first non-empty string value found among candidate keys.
    Supports:
    - plain strings
    - numbers
    - nested dicts with 'rendered'
    """
    for key in candidate_keys:
        value = record.get(key)
        if value is None:
            continue
        
        if isinstance(value, str) and value.strip():
            return value.strip()
        
        if isinstance(value, (int, float)):
            return str(value)
        
        if isinstance(value, dict):
            rendered = value.get("rendered")
            if isinstance(rendered, str) and rendered.strip():
                return rendered.strip()
            
    return ""


def extract_article_fields(record: dict) -> dict[str, str]:
    article_id = safe_get(record, ["id", "post_id", "article_id", "uuid"])
    title = safe_get(record, ["title", "headline", "post_title", "name"])
    content = safe_get(
        record,
        [
            "content",
            "text",
            "body",
            "article_text",
            "post_content",
            "description",
            "excerpt",
            "summary",
        ],
    )
    author = safe_get(record, ["author", "byline", "creator"])
    date_published = safe_get(
        record,
        ["date", "published_at", "publish_date", "created_at", "post_date"],
    )
    source_url = safe_get(record, ["url", "link", "source_url", "permalink"])

    title = normalize_whitespace(strip_html(title))
    content = normalize_whitespace(strip_html(content))

    return {
        "article_id": article_id,
        "title": title,
        "content": content,
        "author": author,
        "date_published": date_published,
        "source_url": source_url,
    }


def iter_json_objects(file_path: Path) -> Generator[Dict[str, Any], None, None]:
    """
    Yield article dicts from:
    - JSON object
    - JSON list of objects
    - JSONL / NDJSON
    """
    suffix = file_path.suffix.lower()

    try:
        if suffix in {".jsonl", ".ndjson"}:
            with file_path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if isinstance(obj, dict):
                            yield obj
                    except json.JSONDecodeError as e:
                        print(
                            f"[WARN] Skipping invalid JSON line in {file_path} "
                            f"(line {line_num}): {e}",
                            file=sys.stderr,
                        )
            return

        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            yield data
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item
        else:
            print(f"[WARN] Unsupported JSON structure in {file_path}", file=sys.stderr)

    except Exception as e:
        print(f"[ERROR] Failed to read {file_path}: {e}", file=sys.stderr)


def collect_json_files(input_dir: Path, recursive: bool) -> List[Path]:
    """
    Collect JSON/JSONL files from input directory.
    """
    patterns = ["*.json", "*.jsonl", "*.ndjson"]
    files: List[Path] = []

    if recursive:
        for pattern in patterns:
            files.extend(input_dir.rglob(pattern))
    else:
        for pattern in patterns:
            files.extend(input_dir.glob(pattern))

    return sorted(set(files))


def build_prompt(title: str, content: str) -> str:
    return f"""
Classify the following news article.

Return exactly one label only:
research related
not research related

Do not ask questions.
Do not explain.
Do not output anything else.

Title: {title}

Content: {content}
""".strip()


def normalize_label(raw_response: str) -> str:
    """
    Normalize model output to one of the allowed labels.
    """
    text = normalize_whitespace(raw_response).lower()

    if "research related" == text:
        return "research related"
    if "not research related" == text:
        return "not research related"

    # More forgiving matching
    if "not research related" in text:
        return "not research related"
    if "research related" in text:
        return "research related"

    # Fallbacks for unexpected model wording
    negatives = [
        "not related to research",
        "not about research",
        "non-research",
        "not research-based",
        "not research based",
    ]
    positives = [
        "research-based",
        "research based",
        "study-based",
        "study based",
        "based on research",
    ]

    if any(p in text for p in negatives):
        return "not research related"
    if any(p in text for p in positives):
        return "research related"

    return "unrecognized"


def classify_with_ollama(
    model: str,
    title: str,
    content: str,
    timeout: int = 300,
    temperature: float = 0.0,
    max_content_chars: int = 12000,
) -> Tuple[str, str]:
    """
    Send article title/content to Ollama and return:
    (normalized_label, raw_model_response)
    """
    trimmed_content = truncate_text(content, max_content_chars)
    prompt = build_prompt(title=title, content=trimmed_content)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
        },
    }

    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()

    data = response.json()
    raw_text = data.get("response", "").strip()
    label = normalize_label(raw_text)
    return label, raw_text


def write_csv_header(output_csv: Path) -> None:
    """
    Write CSV header.
    """
    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "file_name",
                "article_index",
                "article_id",
                "title",
                "date_published",
                "author",
                "source_url",
                "classification",
                "raw_model_response",
            ]
        )


def append_csv_row(output_csv: Path, row: List[str]) -> None:
    """
    Append one row to CSV.
    """
    with output_csv.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def process_articles(
    input_dir: Path,
    output_csv: Path,
    model: str,
    recursive: bool,
    delay_seconds: float,
    timeout: int,
    max_content_chars: int,
    skip_empty: bool,
) -> None:
    """
    Main processing loop.
    """
    files = collect_json_files(input_dir, recursive=recursive)

    if not files:
        print(f"[INFO] No JSON files found in {input_dir}")
        return

    write_csv_header(output_csv)

    total_files = 0
    total_articles = 0
    classified_ok = 0
    classified_errors = 0

    for file_path in files:
        total_files += 1
        print(f"[INFO] Processing file: {file_path}")

        for idx, obj in enumerate(iter_json_objects(file_path), start=1):
            total_articles += 1

            article = extract_article_fields(obj)
            title = article["title"]
            content = article["content"]

            if not title and not content:
                print(
                    f"[WARN] Article {idx} has empty title and content in {file_path}",
                    file=sys.stderr,
                )

            elif title and not content:
                print(
                    f"[WARN] Article {idx} has title only in {file_path}",
                    file=sys.stderr,
                )

            if skip_empty and not title and not content:
                print(
                    f"[WARN] Skipping empty article in {file_path} (index {idx})",
                    file=sys.stderr,
                )
                continue

            try:
                label, raw_response = classify_with_ollama(
                    model=model,
                    title=title,
                    content=content,
                    timeout=timeout,
                    max_content_chars=max_content_chars,
                )
                classified_ok += 1
            except requests.RequestException as e:
                label = "error"
                raw_response = f"Ollama request failed: {e}"
                classified_errors += 1
            except Exception as e:
                label = "error"
                raw_response = f"Unexpected error: {e}"
                classified_errors += 1

            append_csv_row(
                output_csv,
                [
                    file_path.name,
                    str(idx),
                    article["article_id"],
                    article["title"],
                    article["date_published"],
                    article["author"],
                    article["source_url"],
                    label,
                    raw_response,
                ],
            )

            print(
                f"  -> Article {idx}: {label}"
                + (f" [raw: {raw_response}]" if label in {"error", "unrecognized"} else "")
            )

            if delay_seconds > 0:
                time.sleep(delay_seconds)

    print("\n[SUMMARY]")
    print(f"Files processed      : {total_files}")
    print(f"Articles processed   : {total_articles}")
    print(f"Successful           : {classified_ok}")
    print(f"Errors               : {classified_errors}")
    print(f"Output CSV           : {output_csv}")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify JSON news articles using a local Ollama model."
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        help="Folder containing JSON/JSONL article files.",
    )
    parser.add_argument(
        "--output-csv",
        required=True,
        help="Path to output CSV file.",
    )
    parser.add_argument(
        "--model",
        default="llama3.2",
        help='Ollama model name, e.g. "llama3.1:8b", "mistral", "gemma3:4b".',
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search for JSON files recursively.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.0,
        help="Optional delay between requests to Ollama.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="HTTP timeout for each Ollama request in seconds.",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=12000,
        help="Maximum content characters sent to the model.",
    )
    parser.add_argument(
        "--skip-empty",
        action="store_true",
        help="Skip records with both empty title and content.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    output_csv = Path(args.output_csv).expanduser().resolve()
    
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists() or not input_dir.is_dir():
        print(f"[ERROR] Input directory does not exist: {input_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        # Quick connectivity check to Ollama
        test_payload = {
            "model": args.model,
            "prompt": 'Reply only with: ok',
            "stream": False,
            "options": {"temperature": 0},
        }
        test_response = requests.post(OLLAMA_URL, json=test_payload, timeout=180)
        test_response.raise_for_status()
    except Exception as e:
        print(
            f"[ERROR] Could not reach Ollama at {OLLAMA_URL} using model "
            f"'{args.model}'. Details: {e}",
            file=sys.stderr,
        )
        print(
            "Make sure Ollama is running and the model has been pulled, e.g.\n"
            f"  ollama pull {args.model}\n"
            "  ollama serve",
            file=sys.stderr,
        )
        sys.exit(1)

    process_articles(
        input_dir=input_dir,
        output_csv=output_csv,
        model=args.model,
        recursive=args.recursive,
        delay_seconds=args.delay_seconds,
        timeout=args.timeout,
        max_content_chars=args.max_content_chars,
        skip_empty=args.skip_empty,
    )


if __name__ == "__main__":
    main()