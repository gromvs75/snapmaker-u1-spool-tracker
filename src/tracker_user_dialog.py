"""Native export dialogs retained from 1.3.3, without importing its Store."""
import subprocess
import sys
import logging

def _mac_dialog(title, message, buttons=None):
    # User supplied spool names are passed as argv, never interpolated into AppleScript.
    script = '''on run argv
set dialogTitle to item 1 of argv
set dialogText to item 2 of argv
if (count of argv) > 2 then
set cancelLabel to item 3 of argv
set proceedLabel to item 4 of argv
try
set resultButton to button returned of (display dialog dialogText with title dialogTitle buttons {cancelLabel, proceedLabel} default button cancelLabel with icon caution)
return resultButton
on error number -128
return cancelLabel
end try
else
display dialog dialogText with title dialogTitle buttons {"OK"} default button "OK" with icon caution
return "OK"
end if
end run'''
    args = ["osascript", "-e", script, title, message]
    if buttons:
        args.extend(buttons)
    return subprocess.check_output(args, text=True, timeout=120).strip()

def _windows_dialog(title, message, buttons=None):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        if not buttons:
            messagebox.showerror(title, message, parent=root)
            return "OK"
        result = {"choice": buttons[0]}
        window = tk.Toplevel(root)
        window.title(title)
        window.resizable(False, False)
        window.attributes("-topmost", True)
        tk.Label(window, text=message, justify="left", wraplength=580, padx=24, pady=20).pack()
        bar = tk.Frame(window)
        bar.pack(padx=20, pady=15)
        def choose(value):
            result["choice"] = value
            window.destroy()
        tk.Button(bar, text=buttons[0], command=lambda: choose(buttons[0]), width=19).pack(side="left", padx=6)
        tk.Button(bar, text=buttons[1], command=lambda: choose(buttons[1]), width=19).pack(side="left", padx=6)
        window.protocol("WM_DELETE_WINDOW", lambda: choose(buttons[0]))
        window.grab_set()
        root.wait_window(window)
        return result["choice"]
    finally:
        root.destroy()

def export_dialog(message, allow_proceed=False):
    buttons=('Отменить экспорт','Продолжить экспорт') if allow_proceed else None
    try:
        if sys.platform=='darwin':result=_mac_dialog('Snapmaker U1 — проверка экспорта',message,buttons)
        elif sys.platform=='win32':result=_windows_dialog('Snapmaker U1 — проверка экспорта',message,buttons)
        else:
            print(message,file=sys.stderr)
            return False
        return bool(buttons and result==buttons[1])
    except Exception:
        logging.getLogger('tracker20').exception('Export dialog failed')
        return False
