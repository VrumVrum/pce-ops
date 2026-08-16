#!/usr/bin/env python3
"""
Autonomous Mastodon syndicator.

Reads automation/syndication-log.jsonl (written by devto_publish.py). For each
article that was published to dev.to but NOT yet tooted, it posts ONE short
status to Mastodon that links to the OWNER domain (projectcostestimator.com) —
not the dev.to mirror — so the distribution + AI crawl surface points at the
site we want to grow. Idempotent: a per-source marker in
automation/mastodon-log.jsonl means an article is tooted exactly once, ever.

Nofollow (all Mastodon links are), but it is REAL distribution and ChatGPT /
Perplexity crawl Mastodon — a second autonomous surface per article, free.

Requires two env vars (never hard-coded, never logged):
  MASTODON_TOKEN     the access token from /settings/applications/new
  MASTODON_INSTANCE  optional, defaults to https://mastodon.social

No token -> prints how to get one and exits 2 (so a scheduled run stays honest
about being blind rather than silently doing nothing).
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYND_LOG = HERE / "syndication-log.jsonl"
TOOT_LOG = HERE / "mastodon-log.jsonl"
OWNER = "https://projectcostestimator.com"


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def already_tooted(source_file, tooted):
    return any(t.get("source_file") == source_file for t in tooted)


def compose(entry):
    """A short, honest status. Links to the owner domain, not the dev.to mirror."""
    title = entry.get("title", "New post").strip()
    # Keep it under Mastodon's 500-char limit with room to spare.
    if len(title) > 200:
        title = title[:197] + "..."
    return (
        f"{title}\n\n"
        f"Full write-up + the free calculator behind it:\n{OWNER}\n\n"
        f"#buildinpublic #webdev #indiehackers"
    )


def toot(instance, token, status):
    req = urllib.request.Request(
        f"{instance.rstrip('/')}/api/v1/statuses",
        data=json.dumps({"status": status, "visibility": "public"}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    token = os.environ.get("MASTODON_TOKEN")
    instance = os.environ.get("MASTODON_INSTANCE", "https://mastodon.social")
    if not token:
        print(
            "MASTODON_TOKEN not set.\n"
            "  1. Sign up:  https://mastodon.social/auth/sign_up\n"
            "  2. New app:  https://mastodon.social/settings/applications/new "
            "(scope: write:statuses)\n"
            "  3. Copy 'Your access token' and set MASTODON_TOKEN.",
            file=sys.stderr,
        )
        sys.exit(2)

    published = read_jsonl(SYND_LOG)
    tooted = read_jsonl(TOOT_LOG)
    pending = [e for e in published if not already_tooted(e.get("source_file", ""), tooted)]

    if not pending:
        print("Nothing new to toot (all syndicated articles already posted).")
        return

    posted = 0
    for entry in pending:
        status = compose(entry)
        try:
            res = toot(instance, token, status)
        except urllib.error.HTTPError as e:
            print(f"FAILED {entry.get('source_file')}: HTTP {e.code} {e.read().decode('utf-8')[:200]}",
                  file=sys.stderr)
            continue
        url = res.get("url", "")
        with TOOT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "source_file": entry.get("source_file", ""),
                "toot_url": url,
                "title": entry.get("title", ""),
            }) + "\n")
        print(f"TOOTED {entry.get('source_file')} -> {url}")
        posted += 1

    if posted == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
