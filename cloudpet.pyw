"""
Cloud Pet - a pixel-invader companion that floats on top of your screen.

Right-click menu:
  * Ask AI / Research the web  (uses your FREE Google Gemini key)
  * Reminders  (beeps + pops up when due)
  * Quick actions  (open projects folder, open Claude.ai, quick note, lock screen)
  * Settings  (projects folder, AI key)

Needs NOTHING except Python itself - no pip installs. (Standard library only.)
Rename this file from .py to .pyw so it runs with no black window.
"""

import os
import io
import json
import time
import math
import random
import datetime
import threading
import webbrowser
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# CONFIG - tweak to taste
# ---------------------------------------------------------------------------
CONFIG = {
    "ai_keywords": [
        "claude", "chatgpt", "gemini", "copilot",
        "perplexity", "anthropic", "openai", "grok", "poe",
    ],
    "transparent_color": "magenta",
    "cpu_stress_threshold": 80,
    "battery_low_threshold": 25,
    "pixel": 8,
    "bob_speed_ms": 90,
    "monitor_interval_ms": 1000,
    # Free Google Gemini model. If chat errors with a model message,
    # change this (e.g. "gemini-2.5-flash" or "gemini-1.5-flash").
    "ai_model": "gemini-2.0-flash",
    # System-wide keys. Windows gives a combo to whoever asked first, so a
    # clash is reported at startup rather than leaving you pressing a dead
    # key. ctrl+alt+space is taken on a stock Windows 11 box; these are not.
    "hotkeys": {
        "ctrl+alt+n": "boards",
        "ctrl+alt+b": "board",
        "ctrl+alt+o": "outreach",
        "ctrl+alt+s": "ship",
        "ctrl+alt+h": "hide",
    },
}

BODY = "#E8895A"
CHEEK = "#F4B49C"
EYE = "#2E1B12"
EYEW = "#FFFFFF"
SWEAT = "#8FD0FF"

INVADER = [
    "   X     X   ",
    "    X   X    ",
    "  XXXXXXXXX  ",
    " XXXXXXXXXXX ",
    "XXXXXXXXXXXXX",
    "XXXXXXXXXXXXX",
    "XX XXXXXXX XX",
    "X X  XXX  X X",
    "  X  X X  X  ",
]
GRID_W, GRID_H = 13, 9
EYE_COLS = (4, 8)
EYE_ROW = 3

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(_HERE, "cloudpet_data.json")
KEY_FILE = os.path.join(_HERE, "cloudpet_key.txt")
NOTES_FILE = os.path.join(_HERE, "cloudpet_notes.txt")


# ---------------------------------------------------------------------------
# Windows system stats via ctypes (no external packages)
# ---------------------------------------------------------------------------
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.windll.kernel32
    _u32 = ctypes.windll.user32

    class _FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    def _ft(ft):
        return (ft.high << 32) | ft.low

    class _MEMSTAT(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    class _POWER(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    _prev_cpu = {"idle": 0, "total": 0}

    def read_cpu():
        idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
        _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        i, total = _ft(idle), _ft(kern) + _ft(user)
        di = i - _prev_cpu["idle"]
        dt = total - _prev_cpu["total"]
        _prev_cpu["idle"], _prev_cpu["total"] = i, total
        if dt <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (dt - di) / dt))

    def read_ram():
        m = _MEMSTAT()
        m.dwLength = ctypes.sizeof(m)
        _k32.GlobalMemoryStatusEx(ctypes.byref(m))
        return float(m.dwMemoryLoad)

    def read_battery():
        s = _POWER()
        _k32.GetSystemPowerStatus(ctypes.byref(s))
        pct = s.BatteryLifePercent
        return (float(pct) if 0 <= pct <= 100 else None), (s.ACLineStatus == 1)

    def read_active_title():
        h = _u32.GetForegroundWindow()
        n = _u32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(h, buf, n + 1)
        return buf.value or ""
else:
    def read_cpu():
        return 0.0

    def read_ram():
        return 0.0

    def read_battery():
        return None, False

    def read_active_title():
        return ""


def _beep():
    try:
        import winsound
        winsound.MessageBeep()
    except Exception:
        pass


def _today():
    return datetime.date.today().isoformat()


def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    if data.get("date") != _today():
        data = {"date": _today(), "ai_seconds": 0,
                "projects_folder": data.get("projects_folder", ""),
                "reminders": data.get("reminders", [])}
    data.setdefault("projects_folder", "")
    data.setdefault("reminders", [])
    return data


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


class CloudPet:
    def __init__(self, root):
        self.root = root
        self.cfg = CONFIG
        self.data = load_data()
        self.PX = self.cfg["pixel"]

        root.overrideredirect(True)
        root.wm_attributes("-topmost", True)
        tc = self.cfg["transparent_color"]
        root.config(bg=tc)
        try:
            root.wm_attributes("-transparentcolor", tc)
        except tk.TclError:
            pass

        self.W = GRID_W * self.PX + 56
        self.H = GRID_H * self.PX + 110
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = (sw - self.W) // 2
        y = max(40, sh // 5)
        root.geometry(f"{self.W}x{self.H}+{x}+{y}")
        self.canvas = tk.Canvas(root, width=self.W, height=self.H,
                                bg=tc, highlightthickness=0)
        self.canvas.pack()

        self.ox = (self.W - GRID_W * self.PX) // 2
        self.oy = 80

        # state
        self.tick = 0
        self.blink = False
        self.next_blink = time.time() + random.uniform(2, 5)
        self.mood = "calm"
        self.cpu = 0.0
        self.ram = 0.0
        self.battery = None
        self.charging = False
        self.in_session = False
        self.session_start = None
        self.thinking = False
        self._model_cache = None
        self.project_name = None
        self.project_count = 0
        self._last_proj_mtime = 0
        self.speech = "hi! i'm nimbus \u2601"
        self.speech_until = time.time() + 4
        self._panels = {}
        self.hidden = False
        try:
            import hotkeys as _hotkeys
            self.hotkeys = _hotkeys.Hotkeys(self.cfg["hotkeys"]).start()
        except Exception:
            self.hotkeys = None
        self.claude_seen = []
        # None means the inbox has not been read yet. The first pass seeks to
        # the end: a pet that starts up and announces every session you ran
        # last week is not information.
        self.claude_at = None

        self.canvas.bind("<Button-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<Button-3>", self._menu)
        self.canvas.bind("<Double-Button-1>",
                         lambda e: self._say(self._status_line(), 6))

        self._build_menu(root)

        read_cpu()
        self._animate()
        self._monitor()
        self._pump_hotkeys()
        # Registration runs on another thread; give it a moment to answer.
        root.after(1200, self._hotkey_report)

    def _build_menu(self, root):
        m = tk.Menu(root, tearoff=0)
        m.add_command(label="What matters today", command=self._show_board)
        m.add_command(label="Who hasn't replied", command=self._show_outreach)
        m.add_command(label="What I shipped", command=self._show_ship)
        m.add_command(label="What Claude just did", command=self._show_claude)
        m.add_command(label="Hotkeys", command=self._show_hotkeys)
        m.add_separator()
        m.add_command(label="Ask AI\u2026", command=lambda: self._ask_ai(False))
        m.add_command(label="Research the web\u2026", command=lambda: self._ask_ai(True))
        m.add_separator()

        rem = tk.Menu(m, tearoff=0)
        rem.add_command(label="Add reminder\u2026", command=self._add_reminder)
        rem.add_command(label="Show reminders", command=self._show_reminders)
        m.add_cascade(label="Reminders", menu=rem)

        act = tk.Menu(m, tearoff=0)
        act.add_command(label="Open projects folder", command=self._open_projects)
        act.add_command(label="Open Claude.ai", command=lambda: webbrowser.open("https://claude.ai"))
        act.add_command(label="Quick note\u2026", command=self._quick_note)
        act.add_command(label="Open my notes", command=self._open_notes)
        if IS_WINDOWS:
            act.add_command(label="Lock screen", command=self._lock_screen)
        m.add_cascade(label="Quick actions", menu=act)
        m.add_separator()

        st = tk.Menu(m, tearoff=0)
        st.add_command(label="Set projects folder\u2026", command=self._set_projects)
        st.add_command(label="Set AI key\u2026", command=self._set_key)
        m.add_cascade(label="Settings", menu=st)

        m.add_command(label="How am I doing?",
                      command=lambda: self._say(self._status_line(), 6))
        m.add_command(label="Reset today's count", command=self._reset)
        m.add_separator()
        m.add_command(label="Quit", command=self._quit)
        self.menu = m

    # interaction ------------------------------------------------------
    def _start_drag(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        x = self.root.winfo_x() + e.x - self._dx
        y = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{x}+{y}")

    def _menu(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _quit(self):
        save_data(self.data)
        self.root.destroy()

    def _reset(self):
        self.data["ai_seconds"] = 0
        save_data(self.data)
        self._say("reset! fresh skies \u2601", 4)

    # settings ---------------------------------------------------------
    def _set_projects(self):
        d = filedialog.askdirectory(title="Choose your projects folder")
        if d:
            self.data["projects_folder"] = d
            save_data(self.data)
            self._last_proj_mtime = 0
            self._say("watching your projects \U0001F4C1", 4)

    def _set_key(self):
        k = simpledialog.askstring("AI key",
                                   "Paste your free Google Gemini API key:",
                                   show="*")
        if k:
            try:
                with open(KEY_FILE, "w", encoding="utf-8") as f:
                    f.write(k.strip())
                self._say("ai key saved \U0001F511", 4)
            except Exception as e:
                messagebox.showerror("Cloud Pet", str(e))

    def _load_key(self):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return None

    # quick actions ----------------------------------------------------
    def _open_projects(self):
        f = self.data.get("projects_folder")
        if f and os.path.isdir(f):
            try:
                os.startfile(f)
            except Exception as e:
                messagebox.showerror("Cloud Pet", str(e))
        else:
            messagebox.showinfo("Cloud Pet",
                                "Set a projects folder first:\nright-click \u2192 Settings.")

    def _quick_note(self):
        note = simpledialog.askstring("Quick note", "Jot something down:")
        if not note:
            return
        try:
            with open(NOTES_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M}] {note}\n")
            self._say("noted! \U0001F4DD", 3)
        except Exception as e:
            messagebox.showerror("Cloud Pet", str(e))

    def _open_notes(self):
        if os.path.exists(NOTES_FILE):
            try:
                os.startfile(NOTES_FILE)
            except Exception as e:
                messagebox.showerror("Cloud Pet", str(e))
        else:
            messagebox.showinfo("Cloud Pet", "No notes yet \u2014 add one first.")

    def _lock_screen(self):
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception:
            pass

    # reminders --------------------------------------------------------
    def _add_reminder(self):
        text = simpledialog.askstring("Reminder", "Remind me to\u2026")
        if not text:
            return
        mins = simpledialog.askinteger("Reminder", "In how many minutes?",
                                       minvalue=1, initialvalue=10)
        if not mins:
            return
        self.data.setdefault("reminders", []).append(
            {"text": text, "due": time.time() + mins * 60})
        save_data(self.data)
        self._say(f"ok! nudging you in {mins}m \u23F0", 4)

    def _show_reminders(self):
        rem = self.data.get("reminders", [])
        if not rem:
            messagebox.showinfo("Reminders", "No reminders set.")
            return
        now = time.time()
        lines = []
        for r in sorted(rem, key=lambda x: x.get("due", 0)):
            left = max(0, int((r.get("due", 0) - now) // 60))
            lines.append(f"\u2022 {r.get('text','')}  (in ~{left}m)")
        messagebox.showinfo("Reminders", "\n".join(lines))

    def _check_reminders(self):
        rem = self.data.get("reminders", [])
        if not rem:
            return
        now = time.time()
        due = [r for r in rem if r.get("due", 0) <= now]
        if not due:
            return
        self.data["reminders"] = [r for r in rem if r.get("due", 0) > now]
        save_data(self.data)
        for r in due:
            _beep()
            self._say("\u23F0 " + r.get("text", ""), 8)
            try:
                messagebox.showinfo("Reminder \u23F0", r.get("text", ""))
            except Exception:
                pass

    # claude code -----------------------------------------------------
    CLAUDE_INBOX = os.path.join(os.path.expanduser("~"), ".claude", "pet",
                                "inbox.jsonl")

    def _check_claude(self):
        """Say what a Claude Code session just did, or what it is asking.

        The hook appends a line per event and this reads from wherever it
        stopped last time, so the cost of an idle inbox is one stat() per
        tick. The file gets trimmed when it grows, which shows up here as a
        size smaller than the offset - that is a rewrite, not new events, so
        the offset resets rather than seeking past the end.
        """
        try:
            size = os.path.getsize(self.CLAUDE_INBOX)
        except Exception:
            return
        if self.claude_at is None:
            self.claude_at = size
            return
        if size < self.claude_at:
            self.claude_at = 0
        if size == self.claude_at:
            return

        try:
            with io.open(self.CLAUDE_INBOX, encoding="utf-8") as fh:
                fh.seek(self.claude_at)
                fresh = fh.read()
                self.claude_at = fh.tell()
        except Exception:
            return

        events = []
        for line in fresh.splitlines():
            try:
                event = json.loads(line)
            except Exception:
                continue
            if isinstance(event, dict) and event.get("session"):
                events.append(event)
        if not events:
            return

        self.claude_seen = (self.claude_seen + events)[-12:]
        latest = events[-1]
        name = latest.get("session", "claude")[:18]
        _beep()
        if latest.get("kind") == "ask":
            # A question is blocking the session, so it holds the bubble
            # longer than a finished one, which is merely news.
            self._say("%s asks \u2753" % name, 10)
        else:
            self._say("%s done \u2714" % name, 6)

    def _show_claude(self):
        """The last few sessions, newest first."""
        if not self.claude_seen:
            self._panel("Claude",
                        "  Nothing yet.\n\n"
                        "  Either no session has finished since Nimbus\n"
                        "  started, or the hook is not installed. It is not\n"
                        "  the same as Claude having done nothing.")
            return

        lines = []
        for event in reversed(self.claude_seen):
            ago = int(time.time() - event.get("ts", time.time()))
            when = ("just now" if ago < 60 else
                    "%dm ago" % (ago // 60) if ago < 3600 else
                    "%dh ago" % (ago // 3600))
            lines.append("  %s  %s  (%s)"
                         % ("ASKS" if event.get("kind") == "ask" else "DONE",
                            event.get("session", ""), when))
            if event.get("hint"):
                lines.append("    %s" % event["hint"])
            for point in event.get("points", []):
                lines.append("      - %s" % point)
            lines.append("")
        self._panel("Claude", "\n".join(lines))

    # speech / status --------------------------------------------------
    def _say(self, text, seconds=4):
        self.speech = text
        self.speech_until = time.time() + seconds

    def _status_line(self):
        mins = int(self.data["ai_seconds"]) // 60
        parts = [f"cloud time {mins}m", f"cpu {self.cpu:.0f}%"]
        if self.battery is not None:
            parts.append(f"bat {self.battery:.0f}%")
        if self.data.get("projects_folder"):
            parts.append(f"{self.project_count} projects")
        n = len(self.data.get("reminders", []))
        if n:
            parts.append(f"{n} reminders")
        return " \u00b7 ".join(parts)

    def _idle_lines(self):
        base = ["just floating here \u2601", "your laptop looks comfy",
                "beep boop \u2728", "right-click me for tricks!",
                "ask me anything \u2014 right-click \u2192 Ask AI"]
        if self.project_name:
            base.append(f"how's {self.project_name} going?")
        return base

    # monitoring -------------------------------------------------------
    def _ai_active(self):
        t = read_active_title().lower()
        return any(k in t for k in self.cfg["ai_keywords"])

    def _scan_projects(self):
        folder = self.data.get("projects_folder")
        if not folder or not os.path.isdir(folder):
            return
        latest_name, latest_mtime, count = None, 0, 0
        try:
            for e in os.scandir(folder):
                if e.name.startswith("."):
                    continue
                count += 1
                try:
                    m = e.stat().st_mtime
                except Exception:
                    continue
                if m > latest_mtime:
                    latest_mtime, latest_name = m, e.name
        except Exception:
            return
        self.project_count = count
        self.project_name = latest_name
        if latest_mtime > self._last_proj_mtime:
            if self._last_proj_mtime and not self.thinking:
                self._say(f"working on {latest_name} \u270F\uFE0F", 4)
            self._last_proj_mtime = latest_mtime

    def _update_mood(self):
        if self.thinking:
            self.mood = "happy"
        elif self.cpu >= self.cfg["cpu_stress_threshold"]:
            self.mood = "stressed"
        elif self.in_session:
            self.mood = "happy"
        elif self.battery is not None and self.battery <= self.cfg["battery_low_threshold"] and not self.charging:
            self.mood = "worried"
        else:
            self.mood = "calm"

    def _monitor(self):
        now = time.time()
        delta = now - getattr(self, "_last_mon", now)
        self._last_mon = now

        self.cpu = read_cpu()
        self.ram = read_ram()
        self.battery, self.charging = read_battery()

        active = self._ai_active()
        if active:
            self.data["ai_seconds"] += delta
            if not self.in_session:
                self.in_session = True
                self.session_start = now
                self._say("ooh, a cloud session! \u2601", 4)
        else:
            if self.in_session:
                self.in_session = False
                dur = int(now - (self.session_start or now))
                self._say(f"nice one \u2014 {dur // 60}m {dur % 60}s \u2601", 4)
                save_data(self.data)

        self._check_reminders()
        self._check_claude()

        self._proj_ctr = getattr(self, "_proj_ctr", 0) + 1
        if self._proj_ctr % 5 == 0:
            self._scan_projects()

        self._save_ctr = getattr(self, "_save_ctr", 0) + 1
        if self._save_ctr % 10 == 0:
            save_data(self.data)

        self._update_mood()

        if now > self.speech_until and not self.thinking and random.random() < 0.12:
            self._say(random.choice(self._idle_lines()), 3.5)

        self.root.wm_attributes("-topmost", True)
        self.root.after(self.cfg["monitor_interval_ms"], self._monitor)

    # AI chat / research (Google Gemini, free) -------------------------
    def _ask_ai(self, web=False):
        key = self._load_key()
        if not key:
            messagebox.showinfo(
                "Cloud Pet",
                "First add your free Gemini API key:\n"
                "right-click \u2192 Settings \u2192 Set AI key.")
            return
        prompt = "What should I research on the web?" if web else "What do you want to ask?"
        q = simpledialog.askstring("Research" if web else "Ask AI", prompt)
        if not q:
            return
        self.thinking = True
        self._say("researching\u2026 \U0001F50E" if web else "thinking\u2026 \U0001F914", 999)
        threading.Thread(target=self._call_ai, args=(q, key, web), daemon=True).start()

    def _resolve_model(self, key):
        """Ask Google which models this key can use, and pick a good one.
        This makes the pet survive Google renaming/retiring models."""
        if self._model_cache:
            return self._model_cache
        try:
            import re
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key}, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            candidates = []
            for m in data.get("models", []):
                short = m.get("name", "").split("/")[-1]
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods and "gemini" in short:
                    candidates.append(short)

            def score(n):
                s = 0.0
                if "flash" in n:
                    s += 10
                if "lite" in n:
                    s += 1
                mm = re.search(r"(\d+(?:\.\d+)?)", n)
                if mm:
                    s += float(mm.group(1))
                if any(bad in n for bad in ("exp", "thinking", "vision", "tts", "image")):
                    s -= 20
                return s

            candidates.sort(key=score, reverse=True)
            if candidates:
                self._model_cache = candidates[0]
                return self._model_cache
        except Exception:
            pass
        return self.cfg["ai_model"]

    def _call_ai(self, q, key, web=False):
        try:
            model = self._resolve_model(key)
            payload = {"contents": [{"parts": [{"text": q}]}]}
            if web:
                payload["tools"] = [{"google_search": {}}]
            body = json.dumps(payload).encode("utf-8")
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                   + model + ":generateContent")
            req = urllib.request.Request(
                url, data=body,
                headers={"content-type": "application/json",
                         "x-goog-api-key": key},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            cands = data.get("candidates") or [{}]
            parts = cands[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            if not text:
                text = "(The AI sent an empty reply.)"
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8")
            except Exception:
                detail = ""
            text = (f"The AI rejected the request (error {e.code}).\n\n"
                    + detail +
                    "\n\nCopy this whole message to your helper to fix it.")
        except Exception as e:
            text = ("Couldn't reach the AI.\n\n" + str(e) +
                    "\n\nCheck your API key or internet.")
        self.root.after(0, lambda: self._ai_done(text))

    def _ai_done(self, text):
        self.thinking = False
        self._say("done! \u2601", 5)
        _beep()
        win = tk.Toplevel(self.root)
        win.title("Answer")
        win.geometry("460x340")
        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True)
        sb = tk.Scrollbar(frame)
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, wrap="word", font=("Segoe UI", 10),
                      yscrollcommand=sb.set, padx=10, pady=10)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        win.attributes("-topmost", True)

    # the day ----------------------------------------------------------
    def _show_board(self, at=""):
        """The vault's Doing now, ranked P0 to P3.

        Nimbus already knows what the laptop is doing. This is the only thing
        it knows about what you are doing, and it comes off the disk: no
        network, no key, no account. If the vault cannot be read it says so
        rather than showing an empty board, because empty and unreadable are
        different answers.
        """
        def work():
            try:
                import board as _board
            except Exception as exc:
                return "  board.py did not load: %s" % exc, None
            try:
                items, today = _board.board()
                return _board.render(items, today), items
            except Exception as exc:
                return ("  Could not read the vault.\n  %s\n\n"
                        "  This is not an empty day, it is an unread one."
                        % exc), None

        def done(result):
            text, items = result
            if items:
                urgent = ([i for i in items if i["p"] == 0]
                          or [i for i in items if i["p"] == 1])
                if urgent:
                    self._say(urgent[0]["title"][:22], 6)
            self._panel("Today", text, at)

        self._in_background("Today", at, work, done)

    def _show_outreach(self, at=""):
        """Who owes a reply, and how long it has actually been.

        Counting the days rather than letting the feeling do it. A silence
        that later turned into a yes looked identical to a refusal while it
        lasted, so the panel refuses to let a short one read as one.
        """
        self._board_panel("Outreach", "outreach",
                          lambda mod: mod.render(*mod.rows()), at)

    def _show_ship(self, at=""):
        """Commits, not intentions."""
        self._board_panel("Shipping", "ship",
                          lambda mod: mod.render(*mod.survey()), at)

    def _board_panel(self, title, module, run, at=""):
        """Shared plumbing. A panel that cannot read its source says so
        instead of rendering an empty one, because empty and unreadable are
        different answers and only one of them is news."""
        def work():
            try:
                mod = __import__(module)
            except Exception as exc:
                return "  %s.py did not load: %s" % (module, exc)
            try:
                return run(mod)
            except Exception as exc:
                return ("  Could not read the source for this panel.\n  %s\n\n"
                        "  Unread is not the same as nothing there." % exc)

        self._in_background(title, at, work,
                            lambda text: self._panel(title, text, at))

    def _in_background(self, title, at, work, done):
        """Read on a worker thread, draw on the main one.

        Shipping runs git once per repository and the vault sits on disk, so
        doing this inline froze the whole pet until the last subprocess came
        back - long enough that a keypress looked like it had done nothing.
        Tk is not thread-safe, so the worker only ever returns a value and
        after() does the drawing.
        """
        self._panel(title, "  reading\u2026", at)

        def run():
            try:
                result = work()
            except Exception as exc:
                result = "  %s" % exc
            self.root.after(0, lambda: done(result))

        threading.Thread(target=run, daemon=True).start()

    def _panel(self, title, text, at=""):
        # One window per title. A hotkey gets pressed again when you want the
        # panel refreshed, not when you want a second copy of it, and three
        # presses of the boards key would otherwise leave nine windows open.
        old = self._panels.pop(title, None)
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass

        win = tk.Toplevel(self.root)
        self._panels[title] = win
        win.bind("<Destroy>",
                 lambda e, t=title: self._panels.pop(t, None)
                 if e.widget is self._panels.get(t) else None)
        win.title(title)
        win.geometry("520x300" + at)
        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True)
        sb = tk.Scrollbar(frame)
        sb.pack(side="right", fill="y")
        txt = tk.Text(frame, wrap="none", font=("Consolas", 10),
                      yscrollcommand=sb.set, padx=10, pady=10)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        win.attributes("-topmost", True)

    # hotkeys ----------------------------------------------------------
    def _pump_hotkeys(self):
        """Drain the hotkey thread, on the main thread.

        Faster than the monitor tick, because this one is a key press and a
        second of lag makes a shortcut feel broken. An empty queue costs
        nothing, and it is almost always empty.
        """
        if self.hotkeys:
            for action in self.hotkeys.poll():
                try:
                    self._hotkey(action)
                except Exception:
                    # A key that fires and then silently does nothing is the
                    # worst of both worlds: it looks broken and leaves no
                    # trace of why.
                    import traceback
                    try:
                        with io.open(os.path.join(_HERE, "cloudpet_error.log"),
                                     "a", encoding="utf-8") as fh:
                            fh.write("hotkey %s\n%s\n"
                                     % (action, traceback.format_exc()))
                    except Exception:
                        pass
                    self._say("hotkey failed \u2014 see log", 6)
        self.root.after(120, self._pump_hotkeys)

    def _hotkey(self, action):
        if action == "hide":
            self._toggle_hidden()
        elif action == "boards":
            self._show_all_boards()
        elif action == "board":
            self._show_board()
        elif action == "outreach":
            self._show_outreach()
        elif action == "ship":
            self._show_ship()

    def _toggle_hidden(self):
        self.hidden = not self.hidden
        if self.hidden:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.root.wm_attributes("-topmost", True)
            self._say("back \u2601", 3)

    def _show_all_boards(self):
        """All three, down the left rather than on top of each other.

        Panels stay up while the pet is hidden - a Toplevel does not go with a
        withdrawn root - so hiding the cloud does not cost you the boards.
        """
        height = self.root.winfo_screenheight()
        step = min(310, max(200, (height - 120) // 3))
        for index, show in enumerate((self._show_board, self._show_outreach,
                                      self._show_ship)):
            show(at="+30+%d" % (30 + index * step))

    def _hotkey_report(self):
        """Say once, at startup, when a key did not bind.

        A shortcut that silently never registered looks exactly like one you
        keep pressing wrong, and you would go on pressing it for weeks.
        """
        if self.hotkeys and self.hotkeys.problems:
            self._say("a hotkey is taken \u2014 see menu", 8)

    def _show_hotkeys(self):
        if not self.hotkeys:
            self._panel("Hotkeys", "  Hotkeys did not load at all.")
            return
        lines = ["  Global keys", "  " + "-" * 44]
        for combo in sorted(self.hotkeys.bound):
            lines.append("  %-18s %s"
                         % (combo, self.cfg["hotkeys"].get(combo, "")))
        if self.hotkeys.problems:
            lines.append("")
            lines.append("  BLOCKED")
            for problem in self.hotkeys.problems:
                lines.append("    %s" % problem)
            lines.append("")
            lines.append("  Windows gives a combo to whoever asked first.")
            lines.append("  Change it in CONFIG['hotkeys'] and restart.")
        self._panel("Hotkeys", "\n".join(lines))

    # animation --------------------------------------------------------
    def _animate(self):
        self.tick += 1
        now = time.time()
        if now >= self.next_blink:
            self.blink = True
            self.next_blink = now + random.uniform(2.5, 6)
            self.root.after(150, self._end_blink)
        self._render()
        self.root.after(self.cfg["bob_speed_ms"], self._animate)

    def _end_blink(self):
        self.blink = False

    def _draw_bubble(self, x, y, text):
        c = self.canvas
        w = min(200, 16 + len(text) * 5)
        c.create_rectangle(x - w / 2, y - 15, x + w / 2, y + 15,
                           fill="#fffaf7", outline=CHEEK, width=2)
        c.create_polygon(x - 6, y + 14, x + 6, y + 14, x, y + 22,
                         fill="#fffaf7", outline="#fffaf7")
        c.create_text(x, y, text=text, fill=EYE,
                      font=("Segoe UI", 8), width=w - 12)

    def _cell(self, col, row, color, oy):
        px = self.PX
        x0 = self.ox + col * px
        y0 = oy + row * px
        self.canvas.create_rectangle(x0, y0, x0 + px, y0 + px,
                                     fill=color, outline=color)

    def _render(self):
        c = self.canvas
        c.delete("all")
        px = self.PX
        amp = 4 if self.mood == "happy" else 3
        bob = int(round(math.sin(self.tick / 6.0) * amp))
        oy = self.oy + bob
        cx = self.W / 2

        if time.time() < self.speech_until:
            self._draw_bubble(cx, oy - 30, self.speech)

        for r, line in enumerate(INVADER):
            for col, ch in enumerate(line):
                if ch == "X":
                    self._cell(col, r, BODY, oy)

        if self.mood == "happy":
            self._cell(2, 4, CHEEK, oy)
            self._cell(10, 4, CHEEK, oy)

        if self.mood == "worried":
            self._cell(EYE_COLS[0], EYE_ROW - 1, EYE, oy)
            self._cell(EYE_COLS[1], EYE_ROW - 1, EYE, oy)

        for ecol in EYE_COLS:
            x0 = self.ox + ecol * px
            y0 = oy + EYE_ROW * px
            if self.blink:
                c.create_rectangle(x0, y0 + px * 0.45, x0 + px, y0 + px * 0.7,
                                   fill=EYE, outline=EYE)
            else:
                c.create_rectangle(x0, y0, x0 + px, y0 + px, fill=EYE, outline=EYE)
                c.create_rectangle(x0 + px * 0.15, y0 + px * 0.15,
                                   x0 + px * 0.5, y0 + px * 0.5,
                                   fill=EYEW, outline=EYEW)

        if self.mood == "stressed":
            self._cell(12, 2, SWEAT, oy)
            self._cell(12, 3, SWEAT, oy)

        if self.in_session or self.thinking:
            x0 = self.ox + 12 * px
            c.create_oval(x0, oy - px, x0 + px, oy, fill="#5fd07a", outline="#ffffff")


def main():
    try:
        root = tk.Tk()
        root.title("Cloud Pet")
        CloudPet(root)
        root.mainloop()
    except Exception:
        import traceback
        err = traceback.format_exc()
        try:
            messagebox.showerror("Cloud Pet error", err)
        except Exception:
            try:
                with open(os.path.join(_HERE, "cloudpet_error.log"), "w",
                          encoding="utf-8") as f:
                    f.write(err)
            except Exception:
                pass


if __name__ == "__main__":
    main()
