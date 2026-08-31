# Cloud Pet

**A pixel companion that lives on top of your screen, watches your laptop, and
keeps track of how long you spend talking to AI.**

<p align="center">
  <img src="docs/nimbus.gif" alt="Nimbus bobbing on screen, blinking, with a green session dot" width="180">
</p>

Nimbus floats above every window, bobs gently, blinks, and changes mood based on
what your machine is actually doing. Right-click it and it will answer a
question, research something on the web, set you a reminder, or take a note.

```
pythonw cloudpet.pyw
```

That is the whole install. **No `pip install`. No packages. Nothing to set up.**

---

## Zero dependencies, on purpose

The first version needed `psutil` and `PyGetWindow`. This one needs neither — it
asks Windows directly through `ctypes`:

| What it reads | Windows API |
|---|---|
| CPU load | `GetSystemTimes` |
| Memory pressure | `GlobalMemoryStatusEx` |
| Battery and charging | `GetSystemPowerStatus` |
| The focused window's title | `GetForegroundWindow` + `GetWindowTextW` |

If you have Python, you can run it. That matters more than it sounds: a desktop
toy that opens with a dependency error is a desktop toy nobody runs.

## Moods

The face is not decoration — every expression is a reading.

![The four moods: calm, happy, stressed, worried](docs/moods.png)

| Mood | What it means |
|---|---|
| **calm** | nothing to report |
| **happy**, pink cheeks | you are in an AI session, or it is thinking |
| **stressed**, sweat drops | CPU is over 80% |
| **worried**, raised brows | battery under 25% and not charging |

A green dot appears on its shoulder while a session is running.

## What "cloud sessions" actually measures

**Honest limitation, stated up front: this cannot read your Claude or ChatGPT
message counts.** There is no public API for consumer AI usage, so no tool can.

What it does instead is watch the title of whatever window is focused, and count
the seconds while that title contains one of these:

```python
"claude", "chatgpt", "gemini", "copilot",
"perplexity", "anthropic", "openai", "grok", "poe"
```

Browsers put the active tab's title in the window title, so reading this page in
a browser tab called "Claude" counts. It measures **focused time, not messages**
— a real proxy, not the real number. Edit `ai_keywords` at the top of
`cloudpet.pyw` to match the tools you actually use.

Double-click the pet for a readout: `cloud time 47m · cpu 12% · bat 88% · 6 projects`

## The rest of it

- **Ask AI / Research the web** — right-click, type a question. Uses a free
  Google Gemini key. "Research" turns on Google search grounding.
- **Reminders** — beeps and pops up when due, survives restarts.
- **Quick notes** — jot a line, timestamped, appended to a text file.
- **Projects folder** — point it at where you keep your work and it notices what
  you edited last: *"working on painpoint-finder ✏️"*
- **Lock screen**, open Claude.ai, open your notes.
- Drag it anywhere. It stays on top and remembers nothing it should not.

## A detail worth stealing

Google renames and retires Gemini models regularly, which breaks anything with a
model name hardcoded in it. So before its first call the pet asks Google which
models the key can actually use, then scores them — prefer `flash`, prefer a
higher version number, avoid anything `exp`, `vision` or `tts` — and picks the
winner:

```python
def score(n):
    s = 0.0
    if "flash" in n: s += 10
    if "lite" in n:  s += 1
    mm = re.search(r"(\d+(?:\.\d+)?)", n)
    if mm: s += float(mm.group(1))
    if any(bad in n for bad in ("exp", "thinking", "vision", "tts", "image")):
        s -= 20
    return s
```

It falls back to a hardcoded name if that lookup fails. The pet outlives
Google's naming decisions.

## Privacy

Worth being blunt about, because it reads window titles:

- **Everything stays on your machine.** Titles are matched against the keyword
  list and thrown away. Only a running seconds count is stored.
- **Nothing is sent anywhere** unless you explicitly use Ask AI or Research —
  and then only your typed question goes to Google, never your window titles or
  your stats.
- **Your API key is stored in plain text** in `cloudpet_key.txt` next to the
  script. That is a real limitation, not a feature. It is in `.gitignore` so it
  cannot be committed by accident, but treat that file the way you would treat a
  password.
- Delete `cloudpet_data.json` to wipe your history. Right-click → *Reset today's
  count* clears the day.

## Install

1. **Python 3.9+** from [python.org](https://python.org) — tick *"Add Python to
   PATH"* during setup.
2. Download `cloudpet.pyw`.
3. Double-click it, or run `pythonw cloudpet.pyw`.

The `.pyw` extension is what stops a black console window appearing behind it.

**Optional, for the AI features:** get a free key from
[Google AI Studio](https://aistudio.google.com/apikey), then right-click the pet
→ *Settings* → *Set AI key*.

## Start it automatically at login

Task Scheduler, and one detail catches almost everyone:

1. Task Scheduler → **Create Task** (not *Basic Task*).
2. **General** tab → select **"Run only when user is logged on"**. Anything else
   runs it invisibly, where you will never see it.
3. **Triggers** → New → *At log on*.
4. **Actions** → New:
   - **Program/script**: the full path to `pythonw.exe`, not just `pythonw`.
     Find it by running `where pythonw` in a Command Prompt.
   - **Add arguments**: `"C:\path\to\cloudpet.pyw"` — with the quotes.

Task Scheduler does not search the same places your Command Prompt does, so the
bare name `pythonw` often resolves fine when you test it and fails silently when
the task runs. The full path fixes it.

## Windows only, honestly

The float-with-no-box effect uses Tk's `-transparentcolor`, which only exists on
Windows. On macOS and Linux the code runs, but the pet sits inside a grey
rectangle and the system stats read zero — the `ctypes` calls are Windows APIs.
Making it cross-platform means a second backend for stats and a different
transparency approach.

## Tweaking

Everything adjustable lives in the `CONFIG` block at the top of the file:

```python
"cpu_stress_threshold": 80,      # when it starts sweating
"battery_low_threshold": 25,     # when it starts worrying
"pixel": 8,                      # pet size
"bob_speed_ms": 90,              # animation speed
```

The pet itself is a 13×9 ASCII grid — edit `INVADER` to redraw it entirely.

## Licence

MIT.
