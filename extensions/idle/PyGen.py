import os
import sys
import subprocess

try:
    from tkinter import simpledialog, messagebox
except ImportError:
    simpledialog = None
    messagebox = None

class PyGen:
    menudefs = [
        ('edit', [
            ('Сгенерировать решение PyGen (Alt+G)', '<<pygen-solution>>'),
        ])
    ]

    def __init__(self, editwin):
        self.editwin = editwin

    def pygen_solution_event(self, event=None):
        text = self.editwin.text
        task = ""
        try:
            task = text.get("sel.first", "sel.last").strip()
        except Exception:
            task = ""

        if not task:
            if simpledialog:
                task = simpledialog.askstring("PyGen", "Введите условие задачи:")
            else:
                task = ""

        if not task or not task.strip():
            return "break"

        def worker():
            is_win = sys.platform == "win32"
            candidates = [
                os.path.expanduser("~/.local/bin/pygen.cmd"),
                os.path.expanduser("~/.local/bin/run.py"),
                os.path.expanduser("~/.local/bin/pygen"),
            ]
            bin_path = None
            for c in candidates:
                if os.path.exists(c):
                    bin_path = c
                    break

            py_exe = sys.executable or ("python" if is_win else "python3")
            if bin_path and bin_path.endswith(".py"):
                cmd = [py_exe, bin_path, "--stdout"]
            elif bin_path:
                cmd = [bin_path, "--stdout"]
            else:
                cmd = ["pygen.cmd", "--stdout"] if is_win else ["pygen", "--stdout"]

            try:
                res = subprocess.run(
                    cmd,
                    input=task,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    shell=is_win
                )
                if res.returncode == 0 and res.stdout.strip():
                    code = res.stdout.strip()
                    def update_editor():
                        try:
                            text.delete("sel.first", "sel.last")
                        except Exception:
                            pass
                        text.insert("insert", code + "\n")
                    self.editwin.text.after(0, update_editor)
                else:
                    err = res.stderr.strip() or "Сбой генерации решения"
                    if messagebox:
                        self.editwin.text.after(0, lambda: messagebox.showerror("PyGen Ошибка", err))
            except Exception as e:
                if messagebox:
                    self.editwin.text.after(0, lambda: messagebox.showerror("PyGen Ошибка", str(e)))

        import threading
        threading.Thread(target=worker, daemon=True).start()
        return "break"
