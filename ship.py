"""
When you last shipped, per repo, and how much this week.

Counts commits instead of intentions, because a week feels productive long
after it stopped being one.

Reads the local repos with git. No network, no account, no service.

    py -3 ship.py
"""

import datetime
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.environ.get("PET_CODE", os.path.expanduser("~"))
SKIP = {"AppData", "node_modules", ".vscode", "Downloads", ".cache",
        "OneDrive", "Documents", "Pictures", "Music", "Videos"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(repo, *args, timeout=6):
    try:
        out = subprocess.run(["git", "-C", repo, "--no-optional-locks"] + list(args),
                             capture_output=True, text=True, timeout=timeout,
                             creationflags=NO_WINDOW)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def find_repos(root=ROOT, depth=2):
    """Top-level git repos under root. Shallow on purpose: a deep walk of a
    home directory is slow and finds other people's checkouts."""
    found = []
    root = os.path.abspath(root)
    for base, dirs, _names in os.walk(root):
        rel = os.path.relpath(base, root)
        if rel != "." and rel.count(os.sep) >= depth:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")
                   or d == ".git"]
        if ".git" in dirs:
            found.append(base)
            dirs[:] = []
    return sorted(found)


def survey(today=None):
    today = today or datetime.date.today()
    rows = []
    for repo in find_repos():
        stamp = git(repo, "log", "-1", "--format=%ct")
        if not stamp:
            continue
        try:
            last = datetime.date.fromtimestamp(int(stamp))
        except ValueError:
            continue
        week = git(repo, "rev-list", "--count", "--since=7.days", "HEAD") or "0"
        subject = git(repo, "log", "-1", "--format=%s") or ""
        branch = git(repo, "symbolic-ref", "--short", "HEAD") or ""
        rows.append({
            "repo": os.path.basename(repo),
            "days": (today - last).days,
            "week": int(week),
            "subject": subject,
            "branch": branch,
        })
    rows.sort(key=lambda r: (r["days"], r["repo"]))
    return rows, today


def render(rows, today, width=64):
    lines = ["  Shipping, %s" % today.strftime("%d %B"), "  " + "-" * width]
    if not rows:
        lines.append("  No git repos found under %s." % ROOT)
        lines.append("  That is a search that found nothing, not a week off.")
        return "\n".join(lines)

    total = sum(r["week"] for r in rows)
    live = [r for r in rows if r["week"]]
    for r in rows[:9]:
        when = ("today" if r["days"] == 0 else
                "yesterday" if r["days"] == 1 else "%d days ago" % r["days"])
        head = "  %-20s %s" % (r["repo"][:20], when)
        tail = "%d this week" % r["week"] if r["week"] else ""
        lines.append(head + " " * max(1, width - len(head) + 2 - len(tail)) + tail)

    lines.append("  " + "-" * width)
    lines.append("  %d commits in 7 days across %d repo%s."
                 % (total, len(live), "" if len(live) == 1 else "s"))
    if total == 0:
        lines.append("  Nothing shipped this week.")
    elif len(live) == 1:
        lines.append("  All of it in one place. That is focus or it is a rut.")
    return "\n".join(lines)


def main():
    rows, today = survey()
    print()
    print(render(rows, today))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
