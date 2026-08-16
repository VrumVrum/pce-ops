# -*- coding: utf-8 -*-
"""
Autonomous dev.to publisher — the owner asked for agents that PUBLISH by
themselves and create backlinks, not paste-ready drafts. This does it through
dev.to's OFFICIAL publishing API (https://dev.to/api/articles), so it is his own
account authorising programmatic access via the platform's own key — exactly the
pattern as the Kaggle/HuggingFace/Zenodo tokens already in use, not impersonation
and not a ToS violation.

WHAT IT DOES, with zero clicks once a key exists:
  1. reads the next un-published article from automation/syndication-queue/*.md
     (front-matter: title, tags, canonical_url, cover; body below the '---')
  2. publishes it to dev.to via the API (published:true)
  3. records the resulting live URL as an earned brand surface in
     automation/syndication-log.jsonl (so nothing is published twice and every
     backlink is tracked)

THE ONE INPUT IT NEEDS (irreducible — it's the owner's account, only he can mint
the key): DEVTO_API_KEY. Get it at https://dev.to/settings/extensions -> "DEV
Community API Keys" -> Generate. Paste once; the publisher then runs forever from
a cron/routine. No key = it prints exactly this and exits without doing anything.

§3/anti-spam: publishes only genuine, owner-queued articles (one per run, real
content), sets canonical_url so Google credits the owner's domain, never mass-
sprays. dev.to links are nofollow — the value is a brand mention + an AI-crawlable
surface + a canonical authority signal, and that is stated honestly, not sold as
a dofollow backlink.
"""
import os, sys, json, glob, time, urllib.request, urllib.error, datetime

sys.stdout.reconfigure(encoding="utf-8")
ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(ROOT, "syndication-queue")
LOG = os.path.join(ROOT, "syndication-log.jsonl")
API = "https://dev.to/api/articles"


def parse_article(path):
    """front-matter (key: value lines) above a '---' separator, body below."""
    raw = open(path, encoding="utf-8").read()
    if "\n---\n" not in raw:
        raise ValueError(f"{path}: missing '---' separating front-matter from body")
    fm, body = raw.split("\n---\n", 1)
    meta = {}
    for line in fm.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    if not meta.get("title"):
        raise ValueError(f"{path}: no title in front-matter")
    return meta, body.strip()


def already_published(slug):
    if not os.path.exists(LOG):
        return False
    for l in open(LOG, encoding="utf-8"):
        try:
            if json.loads(l).get("source_file") == slug:
                return True
        except Exception:
            pass
    return False


def publish(meta, body, key):
    article = {
        "title": meta["title"],
        "body_markdown": body,
        "published": True,
        "tags": meta.get("tags", ""),
    }
    if meta.get("canonical_url"):
        article["canonical_url"] = meta["canonical_url"]
    if meta.get("cover") or meta.get("main_image"):
        article["main_image"] = meta.get("cover") or meta.get("main_image")
    data = json.dumps({"article": article}).encode()
    req = urllib.request.Request(API, data=data, method="POST",
                                 headers={"api-key": key, "Content-Type": "application/json",
                                          "User-Agent": "pce-syndication/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def main():
    key = os.environ.get("DEVTO_API_KEY", "").strip()
    if not key:
        print("DEVTO_API_KEY not set. This is the ONE input the autonomous publisher needs.")
        print("Get it: https://dev.to/settings/extensions -> DEV Community API Keys -> Generate.")
        print("Then: set DEVTO_API_KEY and this publishes the next queued article with zero clicks.")
        return 2
    pending = sorted(glob.glob(os.path.join(QUEUE, "*.md")))
    for path in pending:
        name = os.path.basename(path)
        if already_published(name):
            continue
        meta, body = parse_article(path)
        try:
            res = publish(meta, body, key)
        except urllib.error.HTTPError as e:
            print(f"FAILED {name}: HTTP {e.code} {e.read()[:200].decode('utf-8','replace')}")
            return 1
        url = res.get("url", "?")
        row = {"source_file": name, "devto_url": url, "title": meta["title"],
               "canonical": meta.get("canonical_url"), "published_utc":
               datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        open(LOG, "a", encoding="utf-8").write(json.dumps(row) + "\n")
        print(f"PUBLISHED {name} -> {url}")
        return 0
    print("No un-published articles in the queue. Add a *.md to automation/syndication-queue/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
