#!/usr/bin/env python3
import argparse
import requests
import time
import sys
from typing import Optional

# ---- Config ----
REQUEST_DELAY = 0.25
DEFAULT_MAX_RESULTS = 150
BADGES_LIMIT = 15
FRIENDS_LIMIT = 10
DEFAULT_PROXY_BASE = "https://roproxy.com/"
RETRY_LIMIT = 3
RETRY_BACKOFF = 1.2
USER_AGENT = "roblox-finder/0.5 (+https://example.local/)"

# ---- API templates ----
API_TEMPLATES = {
    "search": "https://users.roblox.com/v1/users/search",
    "friends_count": "https://friends.roblox.com/v1/users/{}/friends/count",
    "friends_list": "https://friends.roblox.com/v1/users/{}/friends",
    "groups": "https://groups.roblox.com/v2/users/{}/groups/roles",
    "badges": "https://badges.roblox.com/v1/users/{}/badges?limit=100",
    "place": "https://games.roblox.com/v1/games?universeIds={}"
}

# ---- Helpers ----
def build_url(path: str, proxy_base: Optional[str]):
    if not proxy_base:
        return path
    stripped = path.replace("https://", "").replace("http://", "")
    if not proxy_base.endswith("/"):
        proxy_base += "/"
    return proxy_base + stripped

def request_json(url, params=None, proxy_base: Optional[str] = None, timeout=15):
    full_url = build_url(url, proxy_base)
    headers = {"User-Agent": USER_AGENT}
    backoff = 1.0
    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            r = requests.get(full_url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            print(f"[WARN] request exception ({e}) for {full_url}. Attempt {attempt}/{RETRY_LIMIT}", file=sys.stderr)
            time.sleep(backoff)
            backoff *= RETRY_BACKOFF
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                print(f"[WARN] Non-JSON response from {full_url}", file=sys.stderr)
                return None
        elif r.status_code in (429, 503):
            print(f"[WARN] HTTP {r.status_code} for {full_url}. Backing off {backoff}s (attempt {attempt})", file=sys.stderr)
            time.sleep(backoff)
            backoff *= RETRY_BACKOFF
            continue
        else:
            print(f"[WARN] HTTP {r.status_code} for {full_url}. Response text: {r.text[:200]}", file=sys.stderr)
            return None
    return None

# ---- Fetch functions ----
def search_users(keyword: str, limit: int, proxy_base: Optional[str]):
    results = []
    cursor = None
    per_page = 50
    while len(results) < limit:
        params = {"keyword": keyword, "limit": per_page}
        if cursor:
            params["cursor"] = cursor
        data = request_json(API_TEMPLATES["search"], params=params, proxy_base=proxy_base)
        if not data:
            break
        page = data.get("data") or data.get("users") or []
        if not page:
            break
        results.extend(page)
        cursor = data.get("nextPageCursor")
        if not cursor:
            break
        time.sleep(REQUEST_DELAY)
    return results[:limit]

def get_friends_count(user_id: int, proxy_base: Optional[str]):
    data = request_json(API_TEMPLATES["friends_count"].format(user_id), proxy_base=proxy_base)
    if not data:
        return None
    return data.get("count", 0)

# ---- PATCHED FUNCTION ----
def get_friends_list(user_id: int, proxy_base: Optional[str], limit: int = FRIENDS_LIMIT):
    """Fetch a user's friends, resolving friend IDs into names (since Roblox now returns blanks)."""
    url = API_TEMPLATES["friends_list"].format(user_id)
    params = {"limit": limit}
    data = request_json(url, params=params, proxy_base=proxy_base)
    if not data:
        print(f"[WARN] No data returned for user {user_id}", file=sys.stderr)
        return [], 0

    arr = data.get("data") or []
    total_count = data.get("count") or len(arr)
    friends = []
    user_cache = {}

    for f in arr[:limit]:
        fid = f.get("id")
        if not fid:
            continue

        # Check cache before making another request
        if fid in user_cache:
            name, display = user_cache[fid]
        else:
            user_info = request_json(f"https://users.roblox.com/v1/users/{fid}", proxy_base=proxy_base)
            time.sleep(REQUEST_DELAY / 2)
            if not user_info:
                name, display = f"Unknown ({fid})", "Unknown"
            else:
                name = user_info.get("name") or f"Unknown ({fid})"
                display = user_info.get("displayName") or name
            user_cache[fid] = (name, display)

        friends.append(display or name)

    return friends, total_count

# ---- END PATCH ----

def get_groups_list(user_id: int, proxy_base: Optional[str]):
    data = request_json(API_TEMPLATES["groups"].format(user_id), proxy_base=proxy_base)
    if not data:
        return []
    arr = data.get("data", [])
    return [item["group"]["name"] for item in arr if item.get("group") and item["group"].get("name")]

def get_badges_list(user_id: int, proxy_base: Optional[str], limit: int = BADGES_LIMIT):
    data = request_json(API_TEMPLATES["badges"].format(user_id), proxy_base=proxy_base)
    if not data:
        return [], 0
    arr = data.get("data", [])
    total_badges = len(arr)
    out = []
    place_cache = {}
    for b in arr[:limit]:
        name = b.get("name", "N/A")
        place_name = "Unknown Game"
        awarded_for = b.get("awardedFor", {})
        if "placeName" in awarded_for:
            place_name = awarded_for["placeName"]
        elif "robloxPlaceId" in b:
            place_id = b["robloxPlaceId"]
            if place_id in place_cache:
                place_name = place_cache[place_id]
            else:
                place_data = request_json(API_TEMPLATES["place"].format(place_id), proxy_base=proxy_base)
                if place_data and "data" in place_data and len(place_data["data"]) > 0:
                    place_name = place_data["data"][0].get("name", "Unknown Game")
                place_cache[place_id] = place_name
                time.sleep(REQUEST_DELAY / 2)
        out.append((name, place_name))
    return out, total_badges

