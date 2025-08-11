#!/usr/bin/env python3
import os, json, time, hashlib
from pathlib import Path
import feedparser, requests
from dotenv import load_dotenv

# ── Load config ────────────────────────────────────────────────────────────────
load_dotenv()
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
FEEDS = [u.strip() for u in os.environ.get("RSS_FEEDS", "").split(",") if u.strip()]
POST_LATEST_ON_FIRST_RUN = os.environ.get("POST_LATEST_ON_FIRST_RUN", "true").lower() in ("1","true","yes")
TIMEOUT_SECS = int(os.environ.get("TIMEOUT_SECS", "15"))
STATE_DIR = Path(__file__).resolve().parent / "state"
STATE_DIR.mkdir(exist_ok=True)

WATERMARK_PATH = STATE_DIR / "watermark.json"   # stores {"last_ts": float}

# ── Helpers ────────────────────────────────────────────────────────────────────
def entry_key(e) -> str:
    for k in ("id", "guid", "link"):
        v = getattr(e, k, None)
        if v: return v
    return f"{getattr(e,'title','')}_{getattr(e,'published','')}_{getattr(e,'updated','')}"

def ts_of(e) -> float:
    # best-effort: published > updated > created; else 0
    for k in ("published_parsed", "updated_parsed", "created_parsed"):
        v = getattr(e, k, None)
        if v:
            try: return time.mktime(v)
            except Exception: pass
    return 0.0

def load_watermark() -> float:
    if not WATERMARK_PATH.exists(): return None
    try:
        data = json.loads(WATERMARK_PATH.read_text())
        return float(data.get("last_ts", 0.0))
    except Exception:
        return None

def save_watermark(ts_val: float):
    WATERMARK_PATH.write_text(json.dumps({"last_ts": ts_val}))

def truncate(s: str, limit: int = 1900) -> str:
    return s if len(s) <= limit else s[:limit-1] + "…"

def post_to_discord(title: str, link: str, desc: str = ""):
    content = f"**{truncate(title, 1800)}**\n{link}"
    if desc:
        content += f"\n{truncate(desc, 1800)}"
    r = requests.post(WEBHOOK_URL, json={"content": content}, timeout=TIMEOUT_SECS)
    r.raise_for_status()

# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    if not FEEDS:
        raise SystemExit("No RSS_FEEDS set in .env")

    # Gather all items across all feeds
    items = []
    for url in FEEDS:
        f = feedparser.parse(url)
        for e in f.entries:
            items.append({
                "ts": ts_of(e),
                "key": entry_key(e),
                "title": getattr(e, "title", "(no title)"),
                "link": getattr(e, "link", url),
                "desc": getattr(e, "summary", "") or getattr(e, "description", ""),
                "feed": url,
            })

    if not items:
        print("[info] No items found in feeds.")
        return

    # Sort newest → oldest by timestamp
    items.sort(key=lambda x: x["ts"], reverse=True)
    newest = items[0]
    newest_ts = newest["ts"]

    last_ts = load_watermark()

    # First run behavior
    if last_ts is None:
        if POST_LATEST_ON_FIRST_RUN:
            # Post the single newest right now
            try:
                post_to_discord(newest["title"], newest["link"], newest["desc"])
                save_watermark(newest_ts)
                print(f"[sent:first-run] {newest['title']}")
            except Exception as ex:
                print(f"[error:first-run] {ex}")
        else:
            # Seed only (do not post backlog)
            save_watermark(newest_ts)
            print(f"[seeded] watermark set to {newest_ts}")
        return

    # Subsequent runs: only post if there exists an item strictly newer than watermark
    candidates = [it for it in items if it["ts"] > last_ts]
    if not candidates:
        print("[info] No newer items than watermark; nothing to do.")
        return

    # Choose the newest among the newer ones (global single post)
    pick = max(candidates, key=lambda x: x["ts"])
    try:
        post_to_discord(pick["title"], pick["link"], pick["desc"])
        save_watermark(pick["ts"])
        print(f"[sent] {pick['title']}")
    except Exception as ex:
        print(f"[error] {ex}")

if __name__ == "__main__":
    run()
