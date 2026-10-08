import os
import sys
import subprocess
import threading
import queue

try:
    from tkinter import simpledialog, messagebox
    import tkinter as tk
except ImportError:
    simpledialog = None
    messagebox = None
    tk = None

class PyGen:
    menudefs = [
        ('edit', [
            None,
            ('PyGen: Сгенерировать решение (Alt+G)', '<<pygen-solution>>'),
        ]),
        ('format', [
            None,
            ('PyGen: Сгенерировать решение (Alt+G)', '<<pygen-solution>>'),
        ]),
        ('run', [
            None,
            ('PyGen: Сгенерировать решение (Alt+G)', '<<pygen-solution>>'),
        ]),
    ]

    def __init__(self, editwin):
        self.editwin = editwin
        self._bind_events()
        self._add_menubar_entry()

    def _bind_events(self):
        text = getattr(self.editwin, "text", None)
        top = getattr(self.editwin, "top", None)
        if not text:
            return

        try:
            text.bind("<<pygen-solution>>", self.pygen_solution_event)
        except Exception:
            pass

        key_seqs = (
            "<Alt-Key-g>", "<Alt-Key-G>", "<Alt-g>", "<Alt-G>",
            "<Alt-Key-Cyrillic_pe>", "<Alt-Key-Cyrillic_PE>",
            "<Control-Alt-Key-g>", "<Control-Alt-Key-G>",
        )

        for seq in key_seqs:
            try:
                text.event_add("<<pygen-solution>>", seq)
            except Exception:
                pass

        for target in (text, top):
            if not target:
                continue
            for seq in key_seqs:
                try:
                    target.bind(seq, self.pygen_solution_event)
                except Exception:
                    pass
            try:
                target.bind("<Alt-KeyPress>", self._check_alt_key, add="+")
            except Exception:
                pass

    def _check_alt_key(self, event):
        if not event:
            return
        code = getattr(event, "keycode", 0)
        sym = getattr(event, "keysym", "").lower()
        if code == 71 or sym in ("g", "cyrillic_pe"):
            self.pygen_solution_event(event)
            return "break"

    def _add_menubar_entry(self):
        menubar = getattr(self.editwin, "menubar", None)
        if not menubar or not tk:
            return

        try:
            end_val = menubar.index("end")
            count = (end_val + 1) if end_val is not None else 0
            for i in range(count):
                try:
                    lbl = menubar.tk.call(menubar._w, "entrycget", i, "-label")
                    if lbl == "PyGen":
                        return
                except Exception:
                    pass

            m = tk.Menu(menubar, tearoff=False)
            m.add_command(
                label="Сгенерировать решение (Alt+G)",
                command=self.pygen_solution_event,
                accelerator="Alt+G"
            )
            m.add_command(
                label="Решить из буфера обмена",
                command=self.solve_from_clipboard
            )
            m.add_separator()
            m.add_command(
                label="Открыть скрытный GUI (Заметки)",
                command=self.open_gui
            )
            menubar.add_cascade(label="PyGen", menu=m)
        except Exception:
            pass

    def pygen_solution_event(self, event=None):
        text = getattr(self.editwin, "text", None)
        if not text:
            return "break"

        task = ""
        try:
            task = text.get("sel.first", "sel.last").strip()
        except Exception:
            task = ""

        if not task:
            parent_win = getattr(self.editwin, "top", None) or text
            if simpledialog:
                task = simpledialog.askstring(
                    "PyGen",
                    "Введите условие задачи (или выделите текст):",
                    parent=parent_win
                )
            else:
                task = ""

        if not task or not task.strip():
            return "break"

        self._run_solve(task)
        return "break"

    def solve_from_clipboard(self, event=None):
        text = getattr(self.editwin, "text", None)
        if not text:
            return "break"
        task = ""
        try:
            task = text.clipboard_get().strip()
        except Exception:
            task = ""
        if not task:
            parent_win = getattr(self.editwin, "top", None) or text
            if messagebox:
                messagebox.showwarning("PyGen", "Буфер обмена пуст!", parent=parent_win)
            return "break"
        self._run_solve(task)
        return "break"

    def _run_solve(self, task):
        text = getattr(self.editwin, "text", None)
        if not text:
            return

        res_q = queue.Queue()

        def worker():
            is_win = sys.platform == "win32"
            candidates = [
                os.path.expanduser("~/.local/bin/run.py"),
                os.path.expanduser("~/.local/bin/pygen.cmd"),
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

            kwargs = {
                "input": task,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "capture_output": True,
                "timeout": 35,
            }
            if is_win:
                kwargs["creationflags"] = 0x08000000

            try:
                res = subprocess.run(cmd, **kwargs)
                if res.returncode == 0 and res.stdout.strip():
                    res_q.put((res.stdout.strip(), None))
                else:
                    err = res.stderr.strip() or "Сбой генерации решения"
                    res_q.put((None, err))
            except Exception as e:
                res_q.put((None, str(e)))

        def check_result():
            try:
                code, err = res_q.get_nowait()
                if code:
                    try:
                        text.delete("sel.first", "sel.last")
                    except Exception:
                        pass
                    text.insert("insert", code + "\n")
                    try:
                        text.clipboard_clear()
                        text.clipboard_append(code)
                    except Exception:
                        pass
                else:
                    parent_win = getattr(self.editwin, "top", None) or text
                    if messagebox:
                        messagebox.showerror("PyGen Ошибка", err or "Сбой генерации", parent=parent_win)
            except queue.Empty:
                text.after(50, check_result)

        threading.Thread(target=worker, daemon=True).start()
        text.after(20, check_result)

    def open_gui(self, event=None):
        def _launch():
            is_win = sys.platform == "win32"
            run_py = os.path.expanduser("~/.local/bin/run.py")
            if os.path.exists(run_py):
                cmd = [sys.executable, run_py, "--gui"]
            else:
                cmd = ["pygen.cmd", "--gui"] if is_win else ["pygen", "--gui"]
            try:
                if is_win:
                    subprocess.Popen(cmd, creationflags=0x08000000)
                else:
                    subprocess.Popen(cmd, start_new_session=True)
            except Exception:
                pass

        threading.Thread(target=_launch, daemon=True).start()
        return "break"
