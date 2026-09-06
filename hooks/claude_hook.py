"""Claude Code hook bridge: put a finished session in the pet's inbox.

Claude Code runs long enough that you look away, and then it either finishes
or it stops to ask you something. Both are invisible until you happen to look
back at the terminal. This appends one line per event to a file the pet tails,
so Nimbus says it out loud instead.

Two kinds, wired to two hooks:

    done   Stop           the session finished, here is what it did
    ask    PreToolUse     it is waiting on you, here is the question

The hook is on the critical path of every turn, so it never fails one: every
error is swallowed and the exit code is always 0. A pet that breaks your
session is worse than no pet.

    py -3 claude_hook.py done < payload.json
"""

import io
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")

# Its own directory, not ~/.claude itself: a watcher on the whole folder wakes
# for every transcript write, which is constant.
INBOX_DIR = os.path.join(HOME, ".claude", "pet")
INBOX = os.path.join(INBOX_DIR, "inbox.jsonl")

# The tail is enough. Reading a 24 MB transcript to quote its last paragraph
# would put seconds on the end of every turn.
TAIL_BYTES = 300000
MAX_INBOX = 200000
KEEP_LINES = 60

# Nothing matching these reaches the file or the screen. A transcript quotes
# whatever you pasted into the session, and people paste keys into sessions.
SECRETS = [
    r"sk-[A-Za-z0-9_\-]{16,}",
    r"gh[pousr]_[A-Za-z0-9]{16,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"xox[abprs]-[A-Za-z0-9\-]{10,}",
    r"AKIA[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_\-]{30,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
    r"-----BEGIN[^-]{0,40}PRIVATE KEY-----",
    r"(?i)\b(api[_-]?key|secret|password|passwd|token|bearer)\b\s*[:=]\s*\S+",
    r"[A-Za-z0-9+/]{40,}={0,2}",
]


def redact(text):
    for pattern in SECRETS:
        text = re.sub(pattern, "[redacted]", text or "")
    return text


def flatten(text):
    """Markdown down to something a speech bubble can render."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"<[^>]*>", " ", text)
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        # A table row and a horizontal rule carry nothing once flattened.
        if stripped.count("|") >= 2 or re.match(r"^[-=_*\s]{3,}$", stripped):
            continue
        kept.append(line)
    return "\n".join(kept)


def fit(text, width=80):
    text = redact(" ".join(str(text or "").split()))
    return text[:width - 1].rstrip() + "…" if len(text) > width else text


def tail_entries(path):
    """Parsed JSONL records from the end of a transcript, newest first."""
    if not path or not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read().decode("utf-8", "ignore")
    except Exception:
        return []
    out = []
    for line in reversed(raw.splitlines()):
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def session_name(entries, cwd):
    """What to call this session.

    The title Claude Code writes into the transcript, or the folder. Verified
    against a real transcript rather than assumed: this version writes
    `custom-title`, and a hook that reads a field nobody writes reports nothing
    while looking like it works.
    """
    for entry in entries:
        if entry.get("type") == "custom-title":
            title = (entry.get("customTitle") or "").strip()
            if title:
                return fit(title, 40)
    folder = os.path.basename((cwd or "").rstrip("\\/"))
    return fit(folder or "claude", 40)


def last_prompt(entries):
    for entry in entries:
        if entry.get("type") == "last-prompt":
            return fit(entry.get("lastPrompt"), 90)
    return ""


def assistant_text(entry):
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, list):
        return ""
    out = ""
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            out += block.get("text", "") + "\n"
    return out.strip()


def what_it_did(entries, limit=4):
    """Points describing the last substantive thing the session said.

    Its own bullets when it wrote any, its opening sentences otherwise. Short
    replies are skipped: "on it" is not a summary of anything.
    """
    checked = 0
    for entry in entries:
        if checked >= 12:
            break
        if entry.get("type") != "assistant":
            continue
        text = assistant_text(entry)
        if len(text) < 60:
            continue
        checked += 1

        body = flatten(text)
        points = []
        for line in body.splitlines():
            stripped = line.strip()
            if re.match(r"^([-*•]|\d+[.)])\s+", stripped):
                point = re.sub(r"^([-*•]|\d+[.)])\s+", "", stripped)
                point = point.strip(" :—-")
                if len(point) > 6:
                    points.append(point)
        if len(points) >= 2:
            return [fit(p) for p in points[:limit]]

        flat = " ".join(body.split())
        if len(flat) >= 120:
            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat)
                         if len(s.strip()) > 12]
            if sentences:
                return [fit(s) for s in sentences[:limit]]
    return []


def the_question(payload, limit=4):
    """(question, options) when the session has put a choice on screen.

    Claude Code renders its pickers through AskUserQuestion and its plan
    approval through ExitPlanMode, so the PreToolUse payload carries both
    before you see them.
    """
    tool = payload.get("tool_name") or ""
    args = payload.get("tool_input")
    if not isinstance(args, dict):
        args = {}

    if tool == "ExitPlanMode":
        return "wants to start building", ["approve the plan, or send it back"]

    questions = args.get("questions")
    if not isinstance(questions, list) or not questions:
        return "", []

    first = questions[0] if isinstance(questions[0], dict) else {}
    question = fit(first.get("question") or first.get("header"), 90)
    if len(questions) > 1:
        question = "%s (1 of %d)" % (question, len(questions))

    options = []
    for option in (first.get("options") or []):
        if isinstance(option, dict) and option.get("label"):
            options.append(fit(option["label"]))
    return question, options[:limit]


def append(event):
    """One line onto the inbox, trimming it if it has grown."""
    os.makedirs(INBOX_DIR, exist_ok=True)
    with io.open(INBOX, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    # Nothing else prunes this file, and it would otherwise grow for months.
    if os.path.getsize(INBOX) > MAX_INBOX:
        with io.open(INBOX, encoding="utf-8") as fh:
            lines = fh.readlines()[-KEEP_LINES:]
        with io.open(INBOX, "w", encoding="utf-8", newline="\n") as fh:
            fh.writelines(lines)


def main():
    kind = (sys.argv[1] if len(sys.argv) > 1 else "done").strip()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    cwd = payload.get("cwd") or ""
    entries = tail_entries(payload.get("transcript_path", ""))

    if kind == "ask":
        hint, points = the_question(payload)
        if not hint and not points:
            return 0          # not a question worth interrupting for
    else:
        hint, points = last_prompt(entries), what_it_did(entries)

    append({
        "ts": int(time.time()),
        "kind": kind,
        "session": session_name(entries, cwd),
        "session_id": payload.get("session_id") or "",
        "hint": hint,
        "points": points,
        "cwd": cwd,
    })
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A hook that fails a turn is worse than a hook that says nothing.
        sys.exit(0)
