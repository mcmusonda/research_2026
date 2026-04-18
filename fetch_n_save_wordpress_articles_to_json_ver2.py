#!/usr/bin/env python3
"""
Reusable WordPress article harvester.

What this script does
- Fetches posts from a WordPress REST API
- Uses browser-like headers to reduce 403 blocking
- Saves articles into folders named after the media house
- Saves one JSON file per year inside that folder
- Avoids duplicate IDs during a run
- Skips saving empty files
- Adds polite delays and retry logic

Example output
data/
├── lusaka_times/
│   ├── 2024.json
│   └── 2025.json
└── news_diggers/
    ├── 2024.json
    └── 2025.json
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

MEDIA_HOUSES = [
    {
        "media_house": "lusaka_times",
        "api_url": "https://www.lusakatimes.com/wp-json/wp/v2/posts",
        "referer": "https://www.lusakatimes.com/",
    },
    {
        "media_house": "news_diggers",
        "api_url": "https://diggers.news/wp-json/wp/v2/posts",
        "referer": "https://diggers.news/",
    },
    # Add more media houses here
    # {
    #     "media_house": "mwebantu",
    #     "api_url": "https://www.mwebantu.com/wp-json/wp/v2/posts",
    #     "referer": "https://www.mwebantu.com/",
    # },
]

OUTPUT_BASE_DIR = Path("data")

PER_PAGE = 10                 # Start small to reduce risk of 403 blocking
MAX_RETRIES = 5
REQUEST_DELAY_SECONDS = 1.0
TIMEOUT_SECONDS = 60


# =========================
# HELPERS
# =========================

def slugify_name(name: str) -> str:
    """Convert a media house name into a safe folder name."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name


def safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get nested dict values."""
    value: Any = d
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def make_session(referer: str) -> requests.Session:
    """Create a session with browser-like headers."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
        "Referer": referer,
    })
    return session


def request_with_retries(
    session: requests.Session,
    url: str,
    params: Dict[str, Any],
    max_retries: int = MAX_RETRIES,
    timeout: int = TIMEOUT_SECONDS,
) -> Optional[requests.Response]:
    """
    Perform GET request with retry logic.
    Returns None if all retries fail.
    """
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response

        except requests.exceptions.RequestException as exc:
            last_error = exc
            wait_time = min(2 ** attempt, 30)
            print(f"[WARN] Request failed (attempt {attempt}/{max_retries}): {exc}")

            if attempt < max_retries:
                print(f"[INFO] Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

    print(f"[ERROR] Request failed after {max_retries} attempts: {last_error}")
    return None


def parse_year(date_str: Optional[str]) -> Optional[int]:
    """Extract year from WordPress ISO-like datetime string."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00")).year
    except ValueError:
        return None


def normalize_post(post: Dict[str, Any], media_house: str) -> Dict[str, Any]:
    """Keep useful fields and preserve the raw post."""
    year = parse_year(post.get("date") or post.get("modified"))

    return {
        "id": post.get("id"),
        "date": post.get("date"),
        "date_gmt": post.get("date_gmt"),
        "modified": post.get("modified"),
        "modified_gmt": post.get("modified_gmt"),
        "slug": post.get("slug"),
        "status": post.get("status"),
        "type": post.get("type"),
        "link": post.get("link"),
        "guid": safe_get(post, "guid", "rendered", default=""),
        "title": safe_get(post, "title", "rendered", default=""),
        "content": safe_get(post, "content", "rendered", default=""),
        "excerpt": safe_get(post, "excerpt", "rendered", default=""),
        "author": post.get("author"),
        "featured_media": post.get("featured_media"),
        "comment_status": post.get("comment_status"),
        "ping_status": post.get("ping_status"),
        "sticky": post.get("sticky"),
        "template": post.get("template"),
        "format": post.get("format"),
        "meta": post.get("meta", {}),
        "categories": post.get("categories", []),
        "tags": post.get("tags", []),
        "links": post.get("_links", {}),
        "year": year,
        "media_house": media_house,
        "raw": post,
    }


def save_yearly_json(
    media_folder: Path,
    posts_by_year: Dict[int, List[Dict[str, Any]]]
) -> None:
    """Save each year into a separate JSON file."""
    media_folder.mkdir(parents=True, exist_ok=True)

    for year, posts in sorted(posts_by_year.items()):
        if not posts:
            continue

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
    referer: str,
    output_base_dir: Path = OUTPUT_BASE_DIR,
    per_page: int = PER_PAGE,
    request_delay_seconds: float = REQUEST_DELAY_SECONDS,
) -> None:
    """
    Harvest all posts from a WordPress REST API and save them by year.
    """
    folder_name = slugify_name(media_house)
    media_folder = output_base_dir / folder_name

    session = make_session(referer=referer)

    # Optional cookie-establishing request
    try:
        session.get(referer, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.RequestException:
        pass

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

        if response is None:
            print(f"[ERROR] Stopping harvest for {media_house} because requests failed.")
            break

        if total_pages is None:
            total_pages_header = response.headers.get("X-WP-TotalPages")
            total_items_header = response.headers.get("X-WP-Total")

            total_pages = int(total_pages_header) if total_pages_header else None
            total_items = int(total_items_header) if total_items_header else None

            if total_pages is not None:
                print(f"[INFO] Total pages: {total_pages}")
            if total_items is not None:
                print(f"[INFO] Total items: {total_items}")

        try:
            posts = response.json()
        except ValueError:
            print(f"[ERROR] Response on page {page} is not valid JSON. Stopping.")
            break

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

    if posts_by_year:
        save_yearly_json(media_folder, posts_by_year)
        print(f"[DONE] Harvest complete for {media_house}. Total unique posts: {len(all_seen_ids)}")
    else:
        print(f"[INFO] No articles fetched for {media_house}. Nothing was saved.")


# =========================
# ENTRY POINT
# =========================

if __name__ == "__main__":
    for item in MEDIA_HOUSES:
        try:
            harvest_articles(
                api_url=item["api_url"],
                media_house=item["media_house"],
                referer=item["referer"],
            )
            print("-" * 80)
        except KeyboardInterrupt:
            print("\n[INFO] Harvest interrupted by user.")
            break
        except Exception as exc:
            print(f"[ERROR] Unexpected error while harvesting {item['media_house']}: {exc}")
            print("-" * 80)