"""Global hotkeys on Windows, through the Win32 API and nothing else.

The pet is only useful if reaching it is cheaper than the thing you would
otherwise do. Right-clicking a 100-pixel cloud to find out what is due today
is not cheaper than opening the vault, so the boards need a key.

RegisterHotKey posts WM_HOTKEY to the *thread* that registered it, not to a
window, so this owns a thread with a real GetMessage loop and hands presses
back through a queue. Tk keeps its own loop on the main thread and the two do
not mix: poll() is the seam, called from the pet's existing tick.

A combo another program already owns cannot be taken, and Windows says so at
registration time rather than failing later. Those land in .problems and get
reported, because a hotkey that silently never bound is indistinguishable from
one you keep pressing wrong.

    py -3 hotkeys.py        bind the defaults and print presses until Ctrl-C
"""

import queue
import sys
import threading

MOD = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002,
       "shift": 0x0004, "win": 0x0008}

# MOD_NOREPEAT: holding the combo fires once, not once per repeat.
NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08, "insert": 0x2D,
    "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _n in range(1, 13):
    NAMED_KEYS["f%d" % _n] = 0x6F + _n


def parse(combo):
    """"ctrl+alt+space" to (modifiers, virtual key). None if unparseable."""
    parts = [p.strip().lower() for p in str(combo).split("+") if p.strip()]
    if not parts:
        return None

    mods, key = 0, None
    for part in parts:
        if part in MOD:
            mods |= MOD[part]
        elif key is None:
            key = part
        else:
            return None            # two non-modifier keys is not a combo

    if key is None:
        return None
    if key in NAMED_KEYS:
        code = NAMED_KEYS[key]
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        code = ord(key.upper())
    else:
        return None

    # A bare key would swallow that key everywhere on the machine.
    if not mods:
        return None
    return mods | NOREPEAT, code


class Hotkeys(object):
    """System-wide keys, delivered to the main thread through a queue.

    bindings maps a combo to any label you like; poll() gives the labels of
    the presses since the last call. Labels rather than callbacks on purpose:
    a callback would run on the hotkey thread, and Tk objects touched from a
    second thread crash in ways that look like anything but that.
    """

    def __init__(self, bindings):
        self.bindings = dict(bindings)
        self.problems = []
        self.bound = []
        self._events = queue.Queue()
        self._thread = None
        self._thread_id = None

    def start(self):
        if sys.platform != "win32":
            self.problems.append("global hotkeys are Windows-only here")
            return self
        self._thread = threading.Thread(target=self._run, name="hotkeys",
                                        daemon=True)
        self._thread.start()
        return self

    def _run(self):
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                          wintypes.UINT, wintypes.UINT]
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()

        ids = {}
        for index, (combo, label) in enumerate(sorted(self.bindings.items()), 1):
            parsed = parse(combo)
            if not parsed:
                self.problems.append("%s is not a combo I understand" % combo)
                continue
            mods, code = parsed
            if user32.RegisterHotKey(None, index, mods, code):
                ids[index] = label
                self.bound.append(combo)
            else:
                # Almost always ERROR_HOTKEY_ALREADY_REGISTERED: something
                # else on the machine holds it, and it holds it first.
                self.problems.append(
                    "%s is already taken by another program" % combo)

        if not ids:
            return

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                label = ids.get(msg.wParam)
                if label:
                    self._events.put(label)

        for index in ids:
            user32.UnregisterHotKey(None, index)

    def poll(self):
        """Labels pressed since the last call. Never blocks."""
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def stop(self):
        if not self._thread_id:
            return
        import ctypes
        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)


DEFAULTS = {
    "ctrl+alt+space": "boards",
    "ctrl+alt+b": "board",
    "ctrl+alt+h": "hide",
}


def main():
    keys = Hotkeys(DEFAULTS).start()
    import time
    time.sleep(0.4)                # let registration finish before reporting

    for combo in sorted(keys.bound):
        print("  bound   %s" % combo)
    for problem in keys.problems:
        print("  BLOCKED %s" % problem)
    if not keys.bound:
        print("\n  Nothing bound. That is a refusal by Windows, not a quiet"
              " success.")
        return 2

    print("\n  Press one. Ctrl-C to stop.")
    try:
        while True:
            for label in keys.poll():
                print("  ->", label)
            time.sleep(0.05)
    except KeyboardInterrupt:
        keys.stop()
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
