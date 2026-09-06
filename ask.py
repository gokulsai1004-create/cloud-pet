"""One small structured question to Claude, headless, or an honest refusal.

`claude -p` runs Claude from a script and exits. The catch is that a fresh
session loads the whole environment before it sees your question - CLAUDE.md,
memory, skills, plugins, MCP tool definitions - and you pay for all of it on
every call, for a job that needs none of it. Four flags strip it back to the
question:

    --setting-sources ""     no CLAUDE.md, no memory files
    --tools ""               no tool definitions
    --strict-mcp-config      no MCP servers picked up from other configs
    --system-prompt "..."    your one line instead of the default

Three rules here, and they matter more than the prompt:

**Never the only answer.** Everything that calls this has a deterministic
answer of its own and uses this to improve it. A model that is unreachable,
out of credit, rate limited or talking nonsense must cost you nothing.

**BLOCKED is not ERROR is not OK.** Could not ask, asked and got something
unusable, and got an answer are three different outcomes. Collapsing them into
"no result" is how you end up believing a silent failure.

**"Mostly JSON" is not a contract.** The reply may come back fenced, prefixed
with prose, or truncated, so it is parsed defensively and rejected loudly.

    py -3 ask.py        ask one throwaway question and report what happened
"""

import json
import os
import re
import subprocess
import sys

OK, BLOCKED, ERROR = "OK", "BLOCKED", "ERROR"

# Small, cheap, and entirely capable of ordering a short list.
MODEL = os.environ.get("PET_ASK_MODEL", "claude-haiku-4-5-20251001")
TIMEOUT = int(os.environ.get("PET_ASK_TIMEOUT", "90"))

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*|\s*```\s*$")


class Answer(object):
    """status is OK, BLOCKED or ERROR. data is only ever set when OK."""

    def __init__(self, status, data=None, detail="", cost=None):
        self.status = status
        self.data = data
        self.detail = detail
        self.cost = cost

    def __repr__(self):
        return "Answer(%s, %s)" % (self.status, self.detail or self.data)

    @property
    def ok(self):
        return self.status == OK


def carve(text):
    """The first balanced JSON object in a reply, or None.

    A model told to answer in JSON usually does, and sometimes wraps it in a
    fence or a sentence first. Scanning to the matching brace handles both
    without accepting a truncated object.
    """
    text = FENCE.sub("", (text or "").strip())
    start = text.find("{")
    if start < 0:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except Exception:
                    return None
    return None


def ask_json(system, prompt, model=MODEL, timeout=TIMEOUT):
    """Ask once, expect one JSON object back."""
    cmd = ["claude", "-p",
           "--model", model,
           "--output-format", "json",
           "--setting-sources", "",
           "--tools", "",
           "--strict-mcp-config",
           "--system-prompt", system,
           prompt]

    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, creationflags=NO_WINDOW,
                             encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return Answer(BLOCKED, detail="the claude CLI is not on PATH")
    except subprocess.TimeoutExpired:
        return Answer(BLOCKED, detail="claude did not answer in %ds" % timeout)
    except Exception as exc:
        return Answer(BLOCKED, detail="could not run claude: %s" % exc)

    raw = (out.stdout or "").strip()
    envelope = carve(raw)
    if envelope is None:
        detail = (out.stderr or raw or "no output").strip()[:200]
        return Answer(BLOCKED, detail="claude returned no envelope: " + detail)

    # is_error covers the whole class of "the question never reached a model":
    # no credit, no auth, rate limited, bad flag. None of those are the
    # model's answer, and none of them should read as one.
    if envelope.get("is_error"):
        return Answer(BLOCKED,
                      detail=str(envelope.get("result") or "claude reported an error"),
                      cost=envelope.get("total_cost_usd"))

    cost = envelope.get("total_cost_usd")
    data = carve(envelope.get("result") or "")
    if data is None:
        return Answer(ERROR, detail="reply was not JSON: %s"
                      % (envelope.get("result") or "")[:160], cost=cost)
    return Answer(OK, data=data, cost=cost)


def main():
    system = ("You rank items by urgency. You reply with one JSON object and "
              "nothing else.")
    prompt = ('Rank these and reply with {"order":[...]} listing the ids most '
              'urgent first, nothing else.\n'
              '[{"id":"a","text":"reply to someone waiting on me"},'
              '{"id":"b","text":"tidy the README"},'
              '{"id":"c","text":"fix the crash three people reported"}]')

    answer = ask_json(system, prompt)
    print()
    print("  %-8s %s" % (answer.status, answer.detail or answer.data))
    if answer.cost is not None:
        print("  cost     $%.4f" % answer.cost)
    if answer.status == BLOCKED:
        print()
        print("  Blocked is not the same as no answer. Whatever asked this")
        print("  should carry on with its own ordering and say that it did.")
    print()
    return 0 if answer.ok else 1


if __name__ == "__main__":
    sys.exit(main())
