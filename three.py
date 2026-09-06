"""Open all three Nimbus boards at once, for a look at them together."""

import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import board as B
import outreach as O
import ship as S

PANELS = [
    ("Today", B.render(*B.board()), "+24+40"),
    ("Outreach", O.render(*O.rows()), "+24+318"),
    ("Shipping", S.render(*S.survey()), "+24+596"),
]

root = tk.Tk()
for index, (title, text, geo) in enumerate(PANELS):
    # The root must be a real window, not withdrawn. A hidden root under a
    # hidden-window process takes its children with it and nothing appears.
    win = root if index == 0 else tk.Toplevel(root)
    win.title(title)
    win.geometry("580x250" + geo)
    box = tk.Text(win, wrap="none", font=("Consolas", 9), padx=10, pady=8)
    box.insert("1.0", text)
    box.config(state="disabled")
    box.pack(fill="both", expand=True)
    win.attributes("-topmost", True)
    win.lift()
root.after(25000, root.destroy)
root.mainloop()
