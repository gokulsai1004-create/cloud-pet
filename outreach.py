"""
Who has not replied yet, and how long it has actually been.

The trap with waiting on a reply is that silence reads like refusal long
before it is one. This counts the days rather than letting the feeling do it,
and says plainly when it is still too early to conclude anything.

Read from the vault's Outreach table. Nothing leaves the machine.

    py -3 outreach.py
"""

import datetime
import io
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT = os.environ.get(
    "PET_VAULT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault"))

# Below this, a silence is not evidence of anything and the panel says so
# rather than letting it imply a no. Tune it to your own experience.
PATIENCE_DAYS = int(os.environ.get("PET_PATIENCE_DAYS", "5"))

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE = re.compile(r"(\d{1,2})\s*(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                  re.I)
LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
CLEAN = re.compile(r"\*\*|\*|`")

REPLIED = re.compile(r"\brepli|\byes\b|\bagreed\b|\banswered\b", re.I)
WAITING = re.compile(r"no reply|awaiting|await|no response|sent, ", re.I)


def parse_date(text, today):
    match = DATE.search(text or "")
    if not match:
        return None
    day, month = int(match.group(1)), MONTHS[match.group(2)[:3].lower()]
    try:
        found = datetime.date(today.year, month, day)
    except ValueError:
        return None
    if (today - found).days < -60:
        found = datetime.date(today.year - 1, month, day)
    return found


def rows(today=None):
    """Every row of the Outreach table, with days elapsed and a verdict."""
    today = today or datetime.date.today()
    path = os.path.join(VAULT, "Threads", "Outreach.md")
    try:
        with io.open(path, encoding="utf-8") as fh:
            text = fh.read()
    except Exception as exc:
        raise RuntimeError("could not read %s: %s" % (path, exc))

    out = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() in ("to", "product") or set(cells[0]) <= set("- "):
            continue
        who, what, sent, state = cells[0], cells[1], cells[2], cells[3]
        who = CLEAN.sub("", LINK.sub(r"\1", who)).strip()
        state_clean = CLEAN.sub("", LINK.sub(r"\1", state)).strip()
        when = parse_date(sent, today)
        days = (today - when).days if when else None

        if REPLIED.search(state_clean):
            verdict = "replied"
        elif WAITING.search(state_clean) or not state_clean:
            verdict = "waiting"
        else:
            verdict = "open"
        out.append({"who": who, "what": CLEAN.sub("", what).strip(),
                    "sent": sent, "days": days, "state": state_clean,
                    "verdict": verdict})
    return out, today


def render(items, today, width=64):
    lines = ["  Outreach, %s" % today.strftime("%d %B"), "  " + "-" * width]
    waiting = [i for i in items if i["verdict"] == "waiting"]
    replied = [i for i in items if i["verdict"] == "replied"]

    if replied:
        lines.append("  REPLIED")
        for i in replied:
            lines.append("    %s" % i["who"][:56])
        lines.append("")

    if waiting:
        lines.append("  NO ANSWER YET")
        for i in sorted(waiting, key=lambda x: -(x["days"] or 0)):
            age = "%d days" % i["days"] if i["days"] is not None else "no date"
            head = "    %s" % i["who"][:40]
            lines.append(head + " " * max(1, 52 - len(head)) + age)
            if i["days"] is not None and i["days"] <= PATIENCE_DAYS:
                lines.append("        too early to read anything into this")
        lines.append("")

    if not items:
        lines.append("  The table parsed to nothing. That is a parsing")
        lines.append("  failure, not an empty outreach log.")
        return "\n".join(lines)

    lines.append("  " + "-" * width)
    lines.append("  Silence under %d days is not a no." % (PATIENCE_DAYS + 1))
    return "\n".join(lines)


def main():
    try:
        items, today = rows()
    except RuntimeError as exc:
        print("\n  %s" % exc, file=sys.stderr)
        print("  Unread is not the same as nobody owing you a reply.\n",
              file=sys.stderr)
        return 2
    print()
    print(render(items, today))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
