#!/usr/bin/env python3
"""Acquisition actuator for projectcostestimator.com.

The cloud routine (pce-authority-traffic) runs in a decide-only sandbox: it gates
venues and writes complete actuation specs to
VrumVrum/scopebit:docs/OS/worklog/acquisition-queue.json. This script EXECUTES those
specs from GitHub Actions (or any machine with a gh-authenticated environment):

  github-pr items : fork -> branch -> insert entry_line into the named section ->
                    commit -> push -> open PR (disclosure line enforced, refused if absent)
  form-post items : plain curl POST of form_fields, HTTP status recorded

Results go to data/ACQUISITION-RESULTS.json (committed by the workflow). This script
NEVER writes back to the scopebit queue — the cloud routine reconciles results into
the queue + offsite-submissions.md tracker on its next cycle (it already reads
pce-ops raw files).

Hard rules:
  - Every github-pr pr_body MUST contain the exact disclosure line below, or the item
    is recorded failed and never executed.
  - Max 2 github-pr executions per run (anti-spam cap).
  - Ids already present in the results file are skipped (idempotent across runs that
    happen before the routine's reconcile cycle).
  - Target repo archived at run time -> failed, not executed.
  - Target file already containing our domain -> failed (duplicate guard).

Auth: GH_TOKEN or GH_PAT env var (the workflow maps secrets.GH_PAT -> GH_TOKEN so the
preinstalled gh CLI picks it up natively).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

QUEUE_REPO = "VrumVrum/scopebit"
QUEUE_PATH = "docs/OS/worklog/acquisition-queue.json"
QUEUE_REF = "master"
RESULTS_FILE = "data/ACQUISITION-RESULTS.json"
DISCLOSURE = "Disclosure: I'm affiliated with this project."
OUR_DOMAIN = "projectcostestimator.com"
MAX_GITHUB_PR_PER_RUN = 2
GIT_USER = "pce-ops-bot"
GIT_EMAIL = "ops@projectcostestimator.com"


def log(msg: str) -> None:
    print(f"[actuator] {msg}", flush=True)


def token() -> str:
    return os.environ.get("GH_TOKEN") or os.environ.get("GH_PAT") or ""


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    env_tok = token()
    env = dict(os.environ)
    if env_tok:
        env["GH_TOKEN"] = env_tok
    return subprocess.run(["gh"] + args, check=check, capture_output=True, text=True, env=env)


def fetch_queue(queue_file: str | None) -> list[dict]:
    if queue_file:
        with open(queue_file, encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        url = f"https://api.github.com/repos/{QUEUE_REPO}/contents/{QUEUE_PATH}?ref={QUEUE_REF}"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.raw+json"})
        tok = token()
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("queue is neither a list nor an object with an 'items' list")
    return items


def load_results(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return data
    return {"results": []}


def save_results(path: str, results: dict) -> None:
    results["generated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def record(results: dict, item: dict, status: str, detail: str) -> None:
    results["results"] = [r for r in results["results"] if r.get("id") != item.get("id")]
    results["results"].append(
        {
            "id": item.get("id"),
            "kind": item.get("kind"),
            "venue": item.get("venue"),
            "status": status,
            "result": detail,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    log(f"{item.get('id')}: {status} - {detail}")


def validate_github_pr(item: dict) -> str | None:
    for field in ("id", "repo", "entry_line", "pr_title", "pr_body"):
        if not item.get(field):
            return f"missing required field '{field}'"
    if DISCLOSURE not in item["pr_body"]:
        return f'pr_body lacks the mandatory disclosure line "{DISCLOSURE}" (refused, not executed)'
    return None


def find_section_bounds(lines: list[str], heading: str) -> tuple[int, int] | None:
    """Return (heading_index, end_index) — end is the line index AFTER the section's content."""
    pat = re.compile(r"^(#{1,6})\s*(.+?)\s*#*\s*$")
    start = level = None
    fallback = None
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        text = m.group(2).strip().lower()
        if text == heading.strip().lower():
            start, level = i, len(m.group(1))
            break
        if fallback is None and heading.strip().lower() in text:
            fallback = (i, len(m.group(1)))
    if start is None and fallback is not None:
        start, level = fallback
    if start is None:
        return None
    # Section content ends at the NEXT heading of ANY level: the entry belongs with the
    # heading's direct items, before any subsection (## Business has ### Finance etc.).
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if pat.match(lines[i]):
            end = i
            break
    return start, end


def insert_entry(file_path: str, heading: str | None, entry_line: str) -> str | None:
    with open(file_path, encoding="utf-8") as fh:
        content = fh.read()
    if OUR_DOMAIN in content:
        return f"duplicate guard: {OUR_DOMAIN} already present in {os.path.basename(file_path)}"
    lines = content.splitlines()
    if heading:
        bounds = find_section_bounds(lines, heading)
        if bounds is None:
            return f"section heading '{heading}' not found"
        _, end = bounds
        while end > 0 and lines[end - 1].strip() == "":
            end -= 1
        lines.insert(end, entry_line)
    else:
        lines.append(entry_line)
    with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return None


def execute_github_pr(item: dict) -> tuple[str, str]:
    """Returns (status, detail)."""
    repo = item["repo"]
    section_spec = item.get("section") or ""
    if "#" in section_spec:
        rel_file, heading = section_spec.split("#", 1)
        rel_file = rel_file.strip() or "README.md"
    else:
        rel_file, heading = "README.md", section_spec.strip()

    info = json.loads(gh(["api", f"repos/{repo}"]).stdout)
    if info.get("archived"):
        return "failed", "target repo is archived (gate re-check at run time)"
    base_branch = info["default_branch"]

    fork = json.loads(gh(["api", "-X", "POST", f"repos/{repo}/forks"]).stdout)
    fork_full = fork["full_name"]  # never assume the name: collisions get suffixed (Public-APIs-1)
    fork_owner = fork_full.split("/")[0]
    for _ in range(12):
        ready = gh(["api", f"repos/{fork_full}"], check=False)
        if ready.returncode == 0:
            break
        time.sleep(5)
    else:
        return "failed", f"fork {fork_full} not ready after 60s"

    branch = re.sub(r"[^A-Za-z0-9._-]+", "-", f"pce-{item['id']}")
    workdir = tempfile.mkdtemp(prefix="acq-")
    try:
        tok = token()
        fork_url = f"https://x-access-token:{tok}@github.com/{fork_full}.git"
        run(["git", "clone", "--depth", "10", fork_url, workdir])
        run(["git", "remote", "add", "upstream", f"https://github.com/{repo}.git"], cwd=workdir)
        run(["git", "fetch", "--depth", "10", "upstream", base_branch], cwd=workdir)
        run(["git", "checkout", "-B", branch, f"upstream/{base_branch}"], cwd=workdir)

        target_file = os.path.join(workdir, rel_file)
        if not os.path.exists(target_file):
            return "failed", f"target file '{rel_file}' not found in {repo}"
        err = insert_entry(target_file, heading or None, item["entry_line"])
        if err:
            return "failed", err

        run(["git", "-c", f"user.name={GIT_USER}", "-c", f"user.email={GIT_EMAIL}",
             "commit", "-am", item["pr_title"]], cwd=workdir)
        run(["git", "push", "-u", "origin", branch, "--force-with-lease"], cwd=workdir)

        pr = gh(["pr", "create", "--repo", repo, "--head", f"{fork_owner}:{branch}",
                 "--base", base_branch, "--title", item["pr_title"],
                 "--body", item["pr_body"]], check=False)
        if pr.returncode != 0:
            return "failed", f"gh pr create failed: {pr.stderr.strip()[:300]}"
        return "done", pr.stdout.strip().splitlines()[-1]
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        detail = detail.replace(token(), "***") if token() else detail
        return "failed", f"git step failed: {detail[:300]}"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def execute_form_post(item: dict) -> tuple[str, str]:
    url = item.get("url")
    fields = item.get("form_fields") or {}
    if not url or not isinstance(fields, dict) or not fields:
        return "failed", "missing url or form_fields"
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-m", "60", "-X", "POST"]
    for key, value in fields.items():
        cmd += ["--data-urlencode", f"{key}={value}"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    code = proc.stdout.strip()
    if proc.returncode != 0:
        return "failed", f"curl exit {proc.returncode}"
    ok = code.isdigit() and 200 <= int(code) < 400
    return ("done" if ok else "failed"), f"HTTP {code}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute queued acquisition specs.")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse the queue and print planned actions, execute nothing")
    parser.add_argument("--queue-file", help="read the queue from a local file instead of the GitHub API")
    parser.add_argument("--results-file", default=RESULTS_FILE)
    parser.add_argument("--max-github-pr", type=int, default=MAX_GITHUB_PR_PER_RUN)
    args = parser.parse_args()

    try:
        items = fetch_queue(args.queue_file)
    except Exception as exc:  # infra failure: fail loudly, execute nothing
        log(f"FATAL: cannot fetch queue: {exc}")
        return 1

    queued = [i for i in items if i.get("status") == "queued"]
    if not queued:
        log("queue empty (no items with status 'queued') - nothing to do")
        return 0

    results = load_results(args.results_file)
    already = {r.get("id") for r in results["results"]}
    executed_prs = 0
    dirty = False

    for item in queued:
        iid = item.get("id")
        kind = item.get("kind")
        if iid in already:
            log(f"{iid}: already in results file, skipping (waiting on routine reconcile)")
            continue

        if kind == "github-pr":
            problem = validate_github_pr(item)
            if args.dry_run:
                plan = problem or (f"would fork {item.get('repo')}, insert entry into "
                                   f"section '{item.get('section') or 'README.md (end)'}', open PR "
                                   f"'{item.get('pr_title')}'")
                log(f"DRY-RUN {iid}: {plan}")
                continue
            if problem:
                record(results, item, "failed", problem)
                dirty = True
                continue
            if executed_prs >= args.max_github_pr:
                log(f"{iid}: github-pr cap ({args.max_github_pr}/run) reached, left queued for next run")
                continue
            executed_prs += 1
            status, detail = execute_github_pr(item)
            record(results, item, status, detail)
            dirty = True
        elif kind == "form-post":
            if args.dry_run:
                log(f"DRY-RUN {iid}: would POST {len(item.get('form_fields') or {})} fields to {item.get('url')}")
                continue
            status, detail = execute_form_post(item)
            record(results, item, status, detail)
            dirty = True
        else:
            if args.dry_run:
                log(f"DRY-RUN {iid}: unknown kind '{kind}' (would record failed)")
                continue
            record(results, item, "failed", f"unknown kind '{kind}'")
            dirty = True

    if dirty and not args.dry_run:
        save_results(args.results_file, results)
        log(f"results written to {args.results_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
