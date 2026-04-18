#!/usr/bin/env python3
"""
Reusable WordPress API harvester for news articles.

Features
- API endpoint defined as a variable for easy reuse across media houses
- Saves output by year
- Creates a folder per media house, e.g.:
    lusaka_times/2024.json
    lusaka_times/2025.json
- Handles pagination
- Retries on temporary failures
- Avoids duplicate posts within a run
- Can be adapted for other WordPress-based media APIs

Example API:
https://lusakatimes.com/lwp-json/wp/v2/posts
"""

from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import requests


# =========================
# CONFIGURATION
# =========================

MEDIA_HOUSE = "lusaka_times"
API_URL = "https://lusakatimes.com/wp-json/wp/v2/posts"

# Change these if needed
OUTPUT_BASE_DIR = Path("data")
PER_PAGE = 10                 # WordPress usually allows up to 100
REQUEST_DELAY_SECONDS = 0.5    # polite delay between requests
MAX_RETRIES = 5
TIMEOUT_SECONDS = 60


# =========================
# HELPERS
# =========================

def slugify_name(name: str) -> str:
    """
    Convert a media house name into a safe folder name.
    Example: 'News Diggers' -> 'news_diggers'
    """
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """
    Safely get nested dict values.
    """
    value: Any = d
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def request_with_retries(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    max_retries: int = MAX_RETRIES,
    timeout: int = TIMEOUT_SECONDS,
) -> requests.Response:
    """
    Perform GET request with retry logic for transient failures.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            wait_time = min(2 ** attempt, 30)
            print(f"[WARN] Request failed (attempt {attempt}/{max_retries}): {exc}")
            if attempt < max_retries:
                print(f"[INFO] Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

    raise RuntimeError(f"Request failed after {max_retries} attempts: {last_error}")


def normalize_post(post: Dict[str, Any], media_house: str) -> Dict[str, Any]:
    """
    Keep the most useful fields and preserve the raw post.
    Adapt this function if another API has different fields.
    """
    date_str = post.get("date") or post.get("modified")
    year = None
    if date_str:
        try:
            year = datetime.fromisoformat(date_str.replace("Z", "+00:00")).year
        except ValueError:
            year = None

    normalized = {
        "id": post.get("id"),
        "date": post.get("date"),
        "modified": post.get("modified"),
        "slug": post.get("slug"),
        "status": post.get("status"),
        "type": post.get("type"),
        "link": post.get("link"),
        "title": safe_get(post, "title", "rendered", default=""),
        "content": safe_get(post, "content", "rendered", default=""),
        "excerpt": safe_get(post, "excerpt", "rendered", default=""),
        "author": post.get("author"),
        "featured_media": post.get("featured_media"),
        "categories": post.get("categories", []),
        "tags": post.get("tags", []),
        "year": year,
        "media_house": media_house,
        "raw": post,
    }
    return normalized


def save_yearly_json(
    media_folder: Path,
    posts_by_year: Dict[int, List[Dict[str, Any]]]
) -> None:
    """
    Save each year into a separate JSON file.
    """
    media_folder.mkdir(parents=True, exist_ok=True)

    for year, posts in sorted(posts_by_year.items()):
        output_file = media_folder / f"{year}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
        print(f"[SAVED] {output_file} ({len(posts)} articles)")


# =========================
# MAIN HARVESTER
# =========================

def harvest_articles(
    api_url: str,
    media_house: str,
    output_base_dir: Path = OUTPUT_BASE_DIR,
    per_page: int = PER_PAGE,
    request_delay_seconds: float = REQUEST_DELAY_SECONDS,
) -> None:
    """
    Harvest all posts from a WordPress REST API and save them by year.
    """
    folder_name = slugify_name(media_house)
    media_folder = output_base_dir / folder_name

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ArticleHarvester/1.0)"
    })

    all_seen_ids: Set[int] = set()
    posts_by_year: Dict[int, List[Dict[str, Any]]] = defaultdict(list)

    page = 1
    total_pages: Optional[int] = None
    total_items: Optional[int] = None

    print(f"[INFO] Starting harvest for: {media_house}")
    print(f"[INFO] API URL: {api_url}")

    while True:
        params = {
            "page": page,
            "per_page": per_page,
        }

        response = request_with_retries(session, api_url, params=params)

        if total_pages is None:
            total_pages_header = response.headers.get("X-WP-TotalPages")
            total_items_header = response.headers.get("X-WP-Total")

            total_pages = int(total_pages_header) if total_pages_header else None
            total_items = int(total_items_header) if total_items_header else None

            if total_pages is not None:
                print(f"[INFO] Total pages: {total_pages}")
            if total_items is not None:
                print(f"[INFO] Total items: {total_items}")

        posts = response.json()

        if not posts:
            print("[INFO] No more posts returned. Stopping.")
            break

        added_this_page = 0

        for post in posts:
            post_id = post.get("id")
            if post_id is None:
                continue

            if post_id in all_seen_ids:
                continue

            all_seen_ids.add(post_id)

            normalized = normalize_post(post, media_house)

            year = normalized.get("year")
            if year is None:
                print(f"[WARN] Skipping post with unknown year: id={post_id}")
                continue

            posts_by_year[year].append(normalized)
            added_this_page += 1

        print(
            f"[INFO] Page {page}"
            + (f"/{total_pages}" if total_pages else "")
            + f": fetched {len(posts)} posts, added {added_this_page}"
        )

        if total_pages is not None and page >= total_pages:
            break

        page += 1
        time.sleep(request_delay_seconds)

    save_yearly_json(media_folder, posts_by_year)
    print(f"[DONE] Harvest complete for {media_house}. Total unique posts: {len(all_seen_ids)}")


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    harvest_articles(
        api_url=API_URL,
        media_house=MEDIA_HOUSE,
    )