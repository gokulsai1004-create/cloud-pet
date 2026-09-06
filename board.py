"""
What actually matters today, read from the vault.

Nimbus watches the machine: CPU, memory, battery, the focused window. That
tells you what the laptop is doing, never what you are supposed to be doing.
This reads the Obsidian vault instead and ranks the day P0 to P3, so it is a
decision rather than a list.

Nothing leaves the machine. No API key, no network, no account. Same rule as
the rest of the pet: it reads what is already on disk.

    py -3 board.py            print the board
    py -3 board.py --json     machine readable
"""

import argparse
import datetime
import io
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Point PET_VAULT at your own notes. The default sits next to the pet, so a
# fresh clone reads nobody else's.
VAULT = os.environ.get(
    "PET_VAULT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault"))
COUNCIL = os.path.join(os.path.expanduser("~"), ".council")

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

# "14 Sept", "21 Sep", "5 September" - the way dates are actually written in
# the vault, rather than any format a parser would prefer.
DATE = re.compile(
    r"\b(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    re.I)

# A line that is only a wiki link and a dash carries no commitment.
LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*")


def read(path):
    try:
        with io.open(path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return ""


def _dates_in(text, today):
    out = []
    for day, month in DATE.findall(text):
        month = MONTHS[month[:3].lower()]
        try:
            found = datetime.date(today.year, month, int(day))
        except ValueError:
            continue
        if (today - found).days > 200:
            found = datetime.date(today.year + 1, month, int(day))
        out.append(found)
    return sorted(out)


def find_date(text, today):
    """The date that is actually a deadline, not merely a date on the line.

    "applied 31 Aug, decision due **14 Sept**" contains two dates. The first
    is history and the second is the commitment, and taking the soonest gave
    the answer "6 days ago" for something 8 days away. So: a date inside the
    bold segment wins, because the vault bolds what matters; failing that the
    soonest date still ahead; and only if every date has passed does a past
    one count, since then it is genuinely overdue.
    """
    bold = " ".join(BOLD.findall(text))
    for candidate in _dates_in(bold, today):
        return candidate

    dates = _dates_in(text, today)
    ahead = [d for d in dates if d >= today]
    if ahead:
        return ahead[0]
    return dates[-1] if dates else None


def doing_now(vault, today):
    """Bullets under the Doing now heading of the index."""
    text = read(os.path.join(vault, "Index.md"))
    items = []
    inside = False
    for line in text.splitlines():
        if line.strip().lower().startswith("## "):
            inside = "doing now" in line.lower()
            continue
        if not inside or not line.strip().startswith("-"):
            continue
        body = line.strip().lstrip("-").strip()
        title = (LINK.search(body).group(1) if LINK.search(body)
                 else body.split(" - ")[0])
        note = BOLD.search(body)
        items.append({
            "title": title.split("|")[-1].strip(),
            "note": (note.group(1) if note else "").strip(),
            "due": find_date(body, today),
            "source": "Index.md",
        })
    return items


def open_verdicts(today):
    """Council ideas whose next test has not been logged."""
    index = read(os.path.join(COUNCIL, "index.md"))
    out = []
    for line in index.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or cells[0] in ("slug", "---") or "-" * 3 in cells[0]:
            continue
        slug, title, verdict = cells[0], cells[1], cells[2]
        ledger = read(os.path.join(COUNCIL, slug, "assumptions.md"))
        untested = ledger.count("| untested |")
        if untested:
            out.append({
                "title": "%s: %s, %d assumption%s untested"
                         % (title, verdict, untested, "" if untested == 1 else "s"),
                "note": "next test not run",
                "due": None,
                "source": "council",
            })
    return out


def rank(items, today):
    """P0 to P3. Nearness decides, because a deadline is the only thing here
    that cannot be moved by wanting it moved."""
    for item in items:
        days = (item["due"] - today).days if item["due"] else None
        item["days"] = days
        if days is not None and days <= 2:
            item["p"] = 0
        elif days is not None and days <= 9:
            item["p"] = 1
        elif days is not None:
            item["p"] = 2
        elif item.get("note"):
            # No date, but something on the line was bolded. A commitment with
            # no deadline can still be the most live thing you have, so an
            # emphasised line is not background just because nobody dated it.
            item["p"] = 2
        else:
            item["p"] = 3
    items.sort(key=lambda i: (i["p"], i["days"] if i["days"] is not None else 999,
                              i["title"]))
    return items


def board(today=None):
    today = today or datetime.date.today()
    items = doing_now(VAULT, today) + open_verdicts(today)
    return rank(items, today), today


def render(items, today, width=64):
    lines = ["  %s" % today.strftime("%A %d %B"), "  " + "-" * width]
    if not items:
        lines.append("  Nothing in the vault's Doing now. That is a real empty,")
        lines.append("  not a failure to read it.")
        return "\n".join(lines)

    labels = {0: "P0", 1: "P1", 2: "P2", 3: "P3"}
    shown = 0
    for item in items:
        if item["p"] <= 2 or shown < 6:
            when = ""
            if item["days"] is not None:
                when = ("today" if item["days"] == 0 else
                        "tomorrow" if item["days"] == 1 else
                        "%d days" % item["days"] if item["days"] > 0 else
                        "%d days ago" % -item["days"])
            head = "  %s  %s" % (labels[item["p"]], item["title"][:44])
            lines.append(head + (" " * max(1, 54 - len(head))) + when)
            if item["note"] and item["p"] <= 1:
                lines.append("        %s" % item["note"][:56])
            shown += 1
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(VAULT):
        print("  Vault not found at %s" % VAULT, file=sys.stderr)
        print("  Set PET_VAULT. Not showing an empty board, because empty"
              " and unreadable are different answers.", file=sys.stderr)
        return 2

    items, today = board()
    if args.json:
        print(json.dumps(
            [{k: (v.isoformat() if isinstance(v, datetime.date) else v)
              for k, v in i.items()} for i in items], indent=1))
    else:
        print()
        print(render(items, today))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
