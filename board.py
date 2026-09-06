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


RANKS = ["P0", "P1", "P2", "P3"]

# Pins live next to the pet, not in the vault: a pin is how you overrode the
# board today, not something you wrote down and meant.
PINS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    ".board_pins.json")


def load_pins():
    try:
        with io.open(PINS, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return dict((k, v) for k, v in data.items() if v in RANKS)


def save_pins(pins):
    with io.open(PINS, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(pins, indent=1, ensure_ascii=False))


def toggle_pin(pins, title, want):
    """Pin a title to a rank. Pinning the rank it already holds clears it.

    One gesture does both, because the moment you notice a pin is wrong is the
    same moment you reach for the key that set it. A rank holds one item, so
    pinning something to an occupied rank evicts what was there rather than
    silently dropping the new pin.
    """
    if pins.get(title) == want:
        del pins[title]
        return None
    for other in [k for k, v in pins.items() if v == want]:
        del pins[other]
    pins[title] = want
    return want


def urgency(item):
    """Sort key: dated first by nearness, then whatever the vault bolded, then
    the rest. Inside the undated groups, the smart pass's weight breaks ties;
    it is 0 for everything until that pass has run."""
    if item["days"] is not None:
        return (0, item["days"])
    if item.get("note"):
        return (1, item.get("weight", 0))
    return (2, item.get("weight", 0))


SMART_SYSTEM = ("You order a short list of someone's open work by which "
                "most deserves their attention next. You reply with one JSON "
                "object and nothing else.")

# What the last smart pass did, so render can say so. A pass that quietly did
# nothing would leave the board looking identical to one that worked.
SMART_NOTE = None


def smart_order(items):
    """Order the undated items with a model. Deadlines are never touched.

    The rule handles everything with a date, which is the part that actually
    matters and the part a model could get wrong. What it cannot do is order
    six things that all have no date, where today it falls back to
    alphabetical - which is not an opinion about anything. That tail is the
    only thing sent, so the call is small, and losing it costs nothing.
    """
    global SMART_NOTE
    import ask

    undated = [i for i in items if not i.get("due")]
    if len(undated) < 2:
        SMART_NOTE = None
        return None

    payload = [{"id": str(n),
                "text": (i["title"] + (" - " + i["note"] if i["note"] else ""))[:160]}
               for n, i in enumerate(undated)]
    prompt = ('Order these by which most deserves attention next. Reply with '
              '{"order":["id", ...]} using every id exactly once, nothing '
              "else.\n" + json.dumps(payload, ensure_ascii=False))

    answer = ask.ask_json(SMART_SYSTEM, prompt)
    if not answer.ok:
        SMART_NOTE = (answer.status, answer.detail)
        return SMART_NOTE

    order = answer.data.get("order")
    if not isinstance(order, list) or not order:
        SMART_NOTE = (ask.ERROR, "the reply carried no order")
        return SMART_NOTE

    # A short, duplicated or partly invented list is still worth having:
    # honour the ids that resolve and leave the rest where they were. The
    # alternative is throwing away a good ordering over one bad entry.
    placed = 0
    for position, ident in enumerate(order):
        try:
            index = int(ident)
        except Exception:
            continue
        if 0 <= index < len(undated) and "weight" not in undated[index]:
            undated[index]["weight"] = position
            placed += 1
    for item in undated:
        item.setdefault("weight", len(order) + 1)

    if not placed:
        SMART_NOTE = (ask.ERROR, "no id in the reply matched an item")
    elif placed < len(undated):
        SMART_NOTE = (ask.OK, "ordered %d of %d undated"
                      % (placed, len(undated)))
    else:
        SMART_NOTE = (ask.OK, "ordered %d undated" % placed)
    return SMART_NOTE


def rank(items, today, pins=None):
    """P0 to P3, and only one item can hold each.

    Marking four things P0 is the same as marking none: it is a list again and
    the ranking has stopped costing anything. So each label is a slot holding
    exactly one item. The nearest deadline takes the first free slot, and what
    does not fit stays unranked instead of being quietly promoted.

    A pin takes its slot before anything else, because a rule you cannot
    override gets ignored the first time it is wrong.
    """
    pins = pins if pins is not None else {}
    for item in items:
        item["days"] = (item["due"] - today).days if item["due"] else None
        item["p"] = None
        item["pinned"] = False

    items.sort(key=lambda i: (urgency(i), i["title"]))

    taken = {}
    for item in items:
        want = pins.get(item["title"])
        if want and want not in taken:
            item["p"], item["pinned"] = RANKS.index(want), True
            taken[want] = True

    for item in items:
        if item["p"] is not None:
            continue
        for slot, label in enumerate(RANKS):
            if label not in taken:
                item["p"], taken[label] = slot, True
                break

    items.sort(key=lambda i: (9 if i["p"] is None else i["p"],
                              urgency(i), i["title"]))
    return items


def board(today=None, pins=None, smart=False):
    """The day, ranked. smart is off by default on purpose: the board is worth
    having offline, instantly, and with no bill attached."""
    today = today or datetime.date.today()
    items = doing_now(VAULT, today) + open_verdicts(today)
    if smart:
        smart_order(items)
    return rank(items, today, load_pins() if pins is None else pins), today


def resolve(items, text):
    """A title from a fragment of one. Ambiguous is not a match: which of two
    things you meant to pin is the last place to guess."""
    names = [i["title"] for i in items]
    for name in names:
        if name.lower() == text.lower():
            return name, None
    hits = [n for n in names if text.lower() in n.lower()]
    if len(hits) == 1:
        return hits[0], None
    if not hits:
        return None, "nothing on the board matches %r" % text
    return None, "%r matches %d items: %s" % (text, len(hits), ", ".join(hits))


def when(days):
    if days is None:
        return ""
    return ("today" if days == 0 else
            "tomorrow" if days == 1 else
            "%d days" % days if days > 0 else
            "%d days ago" % -days)


def render(items, today, width=64):
    lines = ["  %s" % today.strftime("%A %d %B"), "  " + "-" * width]
    if not items:
        lines.append("  Nothing under Doing now. That is a real empty, not a")
        lines.append("  failure to read the vault.")
        return "\n".join(lines)

    ranked = [i for i in items if i["p"] is not None]
    rest = [i for i in items if i["p"] is None]

    for item in ranked:
        label = RANKS[item["p"]] + ("*" if item["pinned"] else " ")
        head = "  %s %s" % (label, item["title"][:44])
        lines.append(head + (" " * max(1, 54 - len(head))) + when(item["days"]))
        if item["note"] and item["p"] <= 1:
            lines.append("        %s" % item["note"][:56])

    # Two things due the same day is the case the ranking exists for, so the
    # board owns the choice out loud instead of letting the order imply it.
    if (len(ranked) > 1 and ranked[0]["days"] is not None
            and ranked[1]["days"] == ranked[0]["days"]):
        lines.append("")
        lines.append("  Both due %s. P0 is the one you do first."
                     % when(ranked[0]["days"]))

    if rest:
        lines.append("")
        lines.append("  then")
        for item in rest[:4]:
            head = "     %s" % item["title"][:44]
            lines.append(head + (" " * max(1, 54 - len(head)))
                         + when(item["days"]))
        if len(rest) > 4:
            lines.append("     and %d more" % (len(rest) - 4))

    if any(i["pinned"] for i in ranked):
        lines.append("")
        lines.append("  * pinned by you, not by the deadline")

    if SMART_NOTE:
        status, detail = SMART_NOTE
        lines.append("")
        if status == "OK":
            lines.append("  smart pass: %s" % detail)
        else:
            # Say it. A board that silently fell back looks exactly like one
            # where the model agreed with the alphabet.
            lines.append("  smart pass %s: %s" % (status, detail))
            lines.append("  the undated list is in its usual order")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--smart", action="store_true",
                    help="order the undated tail with claude -p")
    ap.add_argument("--pin", nargs=2, metavar=("RANK", "TITLE"),
                    help="hold a title at a rank; the same pin again clears it")
    ap.add_argument("--unpin", metavar="TITLE")
    ap.add_argument("--pins", action="store_true", help="list current pins")
    args = ap.parse_args()

    if args.pins:
        pins = load_pins()
        if not pins:
            print("  No pins. The board is ranking on deadlines alone.")
        for title, held in sorted(pins.items(), key=lambda kv: kv[1]):
            print("  %s  %s" % (held, title))
        return 0

    if not os.path.isdir(VAULT):
        print("  Vault not found at %s" % VAULT, file=sys.stderr)
        print("  Set PET_VAULT. Not showing an empty board, because empty"
              " and unreadable are different answers.", file=sys.stderr)
        return 2

    items, today = board(smart=args.smart)

    if args.pin or args.unpin:
        pins = load_pins()
        text = args.pin[1] if args.pin else args.unpin
        title, problem = resolve(items, text)
        if problem:
            print("  %s" % problem, file=sys.stderr)
            return 2
        if args.unpin:
            pins.pop(title, None)
            print("  unpinned %s" % title)
        else:
            want = args.pin[0].upper()
            if want not in RANKS:
                print("  rank must be one of %s" % ", ".join(RANKS),
                      file=sys.stderr)
                return 2
            held = toggle_pin(pins, title, want)
            print("  %s %s" % ("unpinned" if held is None else held, title))
        save_pins(pins)
        items, today = board(pins=pins, smart=args.smart)

    if args.json:
        print(json.dumps(
            [dict((k, v.isoformat() if isinstance(v, datetime.date) else v)
                  for k, v in i.items()) for i in items], indent=1))
    else:
        print()
        print(render(items, today))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
