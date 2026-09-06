"""What a headless Claude call costs, bare against stripped, on this machine.

`claude -p` starts a fresh session, and a fresh session loads the whole
environment before it sees the question: CLAUDE.md, memory, skills, plugins,
MCP tool definitions. You pay for all of it on every call, and none of it
helps with a small structured job.

This asks the same question twice and prints what each way actually cost. The
number is worth having first-hand, because it depends entirely on how much you
have installed and someone else's figure says nothing about your machine.

    py -3 measure_ask.py
"""

import json
import os
import subprocess
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MODEL = "claude-haiku-4-5-20251001"
SYSTEM = ("You rank items by urgency. You reply with one JSON object and "
          "nothing else.")

QUESTION = (
    'Rank these by urgency and reply with {"order":[...]} listing the ids '
    'most urgent first, nothing else.\n'
    '[{"id":"a","text":"reply to the founder who is waiting on me"},'
    '{"id":"b","text":"tidy the README"},'
    '{"id":"c","text":"fix the crash three people reported"}]')

# The flags that strip the environment. Each removes a different source: the
# settings files, the tool definitions, and any MCP server config lying around.
STRIPPED = ["--setting-sources", "", "--tools", "", "--strict-mcp-config",
            "--system-prompt", SYSTEM]

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(label, extra):
    cmd = (["claude", "-p", "--model", MODEL, "--output-format", "json"]
           + extra + [QUESTION])
    started = time.time()
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                             creationflags=NO_WINDOW,
                             encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"label": label, "error": str(exc)}
    took = time.time() - started

    if out.returncode != 0:
        return {"label": label, "took": took,
                "error": (out.stderr or out.stdout or "").strip()[:400]}
    try:
        data = json.loads(out.stdout)
    except Exception:
        return {"label": label, "took": took,
                "error": "reply was not JSON: " + out.stdout.strip()[:200]}

    usage = data.get("usage") or {}
    return {
        "label": label,
        "took": took,
        "cost": data.get("total_cost_usd"),
        "in": usage.get("input_tokens", 0),
        "cache_read": usage.get("cache_read_input_tokens", 0),
        "cache_write": usage.get("cache_creation_input_tokens", 0),
        "out": usage.get("output_tokens", 0),
        "reply": (data.get("result") or "").strip()[:120],
    }


def line(r):
    if r.get("error"):
        print("  %-10s FAILED after %.1fs" % (r["label"], r.get("took", 0)))
        print("    %s" % r["error"].replace("\n", "\n    "))
        return
    total_in = r["in"] + r["cache_read"] + r["cache_write"]
    print("  %-10s %7.1fs  %9s  in %7d (cache read %6d, write %5d)  out %4d"
          % (r["label"], r["took"],
             "$%.4f" % r["cost"] if r["cost"] is not None else "?",
             total_in, r["cache_read"], r["cache_write"], r["out"]))
    print("             reply: %s" % r["reply"])


def main():
    print("\n  Same question, two ways. Model: %s\n" % MODEL)
    bare = run("bare", [])
    line(bare)
    stripped = run("stripped", STRIPPED)
    line(stripped)

    if bare.get("cost") and stripped.get("cost"):
        print("\n  %.4f -> %.4f, %.0fx cheaper"
              % (bare["cost"], stripped["cost"],
                 bare["cost"] / max(stripped["cost"], 1e-9)))
    else:
        print("\n  One of the two did not return a cost, so there is no ratio")
        print("  to report. That is a failed measurement, not a small saving.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
