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
            bin_path = os.path.expanduser("~/.local/bin/pygen")
            cmd = ["python3", bin_path, "--stdout"] if os.path.exists(bin_path) else ["pygen", "--stdout"]
            try:
                res = subprocess.run(
                    cmd,
                    input=task,
                    text=True,
                    capture_output=True,
                    timeout=30
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
