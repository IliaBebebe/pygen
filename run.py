#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import ssl
import uuid
import re
import io
import tokenize
import ast
import time
import subprocess
from pathlib import Path

# Обеспечиваем безопасный вывод UTF-8 в консолях Windows (CP1251/CP866)
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Встроенный рабочий ключ GigaChat (Сбер) - 100% работает в РФ без VPN
_GIGACHAT_AUTH = "Basic MzgyMDE1ZDgtMzM2MC00NjI3LWFjZWUtNDZkOGFjZTIwNzkzOjQzMDFiZjU4LWJjMmEtNGRjNi04Y2MwLWNlNWUyOTQ2ZTcwMw=="
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"

CONFIG_DIR = Path.home() / ".config" / "pygen"
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = Path.home() / ".cache" / "pygen"
RECENT_FILE = CACHE_DIR / "recent.json"

SYSTEM_PROMPT = """Ты — ассистент по программированию на Python для школьных уроков информатики.
Пиши решение задачи по следующим СТРОГИМ правилам:
1. Выводи ТОЛЬКО исполняемый код Python.
2. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО создавать функции (НИКАКИХ 'def', никаких 'lambda').
   Код должен быть линейным простым скриптом, выполняющимся строго сверху вниз.
   Ввод данных через input(), стандартные циклы for/while, условия if/else, вывод через print().
3. Даже если в условии написано 'напишите функцию', НЕ используй 'def', пиши обычный линейный код.
4. ИМЕНА ПЕРЕМЕННЫХ (СТРОГО ОДНА БУКВА):
   Все переменные ДОЛЖНЫ быть названы строго одиночными буквами (условно a, b, c).
   Строго соблюдай стандартные исключения:
   - итерации циклов и индексы: i, j
   - вводные числа, размеры и длины: n, m
   - строки: s
   - массивы и списки: l
   - счетчики: k
   - любые другие переменные, суммы, ответы, результаты: строго одиночные буквы a, b, c, d, r, x, y (например: r = "", a = 0).
   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНЫ любые слова длиннее одной буквы (ЗАПРЕЩЕНО: result, res, ans, total, sum, number, count, word, flag). Запрещены нижние подчеркивания.
5. СТРОГО БЕЗ КОММЕНТАРИЕВ (никаких '#').
6. СТРОГО БЕЗ DOCSTRINGS.
7. Никаких вступлений, пояснений и маркдауна. Выдавай только чистый код."""

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"provider": "gigachat", "deepseek_api_key": ""}

def save_config(cfg: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def get_gigachat_token(auth_str: str) -> str:
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    rquid = str(uuid.uuid4())
    req = urllib.request.Request(
        url,
        data=b"scope=GIGACHAT_API_PERS",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rquid,
            "Authorization": auth_str
        },
        method="POST"
    )
    with urllib.request.urlopen(req, context=get_ssl_context(), timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["access_token"]

def query_gigachat(prompt: str, auth_str: str = _GIGACHAT_AUTH) -> str:
    token = get_gigachat_token(auth_str)
    url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
    payload = {
        "model": "GigaChat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, context=get_ssl_context(), timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

def query_deepseek(prompt: str, api_key: str, model: str = DEEPSEEK_DEFAULT_MODEL) -> str:
    if not api_key:
        cfg = load_config()
        api_key = cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("Для DeepSeek не указан API-ключ! Передайте через --key или сохраните в настройках.")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek HTTP {err.code}: {err_body}")
    except Exception as err:
        raise RuntimeError(f"Сетевая ошибка DeepSeek: {err}")

def get_local_ollama_model() -> str:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", timeout=1)
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            for m in models:
                if "code" in m.lower():
                    return m
            if models:
                return models[0]
    except Exception:
        pass
    return ""

def query_ollama(model: str, prompt: str, base_url: str = "http://localhost:11434/v1") -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

def generate_solution(prompt: str, provider: str = None, api_key: str = None, custom_url: str = None) -> str:
    cfg = load_config()
    chosen_provider = provider or cfg.get("provider") or "gigachat"

    if chosen_provider.lower() == "deepseek":
        key = api_key or cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
        return query_deepseek(prompt, api_key=key)

    if chosen_provider.lower() == "ollama" or custom_url:
        local_model = get_local_ollama_model() or "qwen2.5-coder:1.5b"
        url = custom_url or "http://localhost:11434/v1"
        return query_ollama(local_model, prompt, url)

    # По умолчанию: Сбер GigaChat (работает в РФ без VPN, 100% бесплатно)
    return query_gigachat(prompt)

def generate_code_clean(prompt: str, provider: str = None, api_key: str = None, custom_url: str = None) -> str:
    raw_resp = generate_solution(prompt, provider=provider, api_key=api_key, custom_url=custom_url)
    code = extract_code(raw_resp)
    return remove_comments_and_docstrings(code)

def remove_comments_and_docstrings(source_code: str) -> str:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source_code).readline)
        tokens_clean = []
        for tok_type, tok_string, start, end, line in tokens:
            if tok_type == tokenize.COMMENT:
                continue
            tokens_clean.append((tok_type, tok_string, start, end, line))
        source_code = tokenize.untokenize(tokens_clean)
    except Exception:
        pass

    try:
        tree = ast.parse(source_code)
        doc_lines = set()

        def mark_docstring(node):
            if (
                node.body and
                isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)
            ):
                target = node.body[0]
                for l in range(target.lineno, getattr(target, "end_lineno", target.lineno) + 1):
                    doc_lines.add(l)

        if isinstance(tree, ast.Module):
            mark_docstring(tree)
        for sub in ast.walk(tree):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                mark_docstring(sub)

        lines = source_code.splitlines()
        source_code = "\n".join(
            line for idx, line in enumerate(lines, start=1)
            if idx not in doc_lines and not line.strip().startswith("#")
        )
    except Exception:
        pass

    clean_lines = []
    prev_blank = False
    for line in source_code.splitlines():
        if line.strip().startswith("#"):
            continue
        line_clean = re.sub(r"#.*$", "", line)
        if not line_clean.strip():
            if not prev_blank:
                clean_lines.append("")
                prev_blank = True
        else:
            clean_lines.append(line_clean.rstrip())
            prev_blank = False

    return "\n".join(clean_lines).strip() + "\n"

def extract_code(text: str) -> str:
    matches = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[0]
    return text.strip()

def infer_filename(prompt: str) -> str:
    latin_words = [w.lower() for w in re.findall(r"[a-zA-Z0-9_]{3,}", prompt) if w.lower() not in {"task", "python", "code"}]
    if latin_words:
        return f"{latin_words[0]}.py"

    stop_words = {"дано", "напишите", "найдите", "программа", "требуется", "посчитайте", "определите", "выведите", "для", "если"}
    rus_words = [w.lower() for w in re.findall(r"[а-яА-ЯёЁ]{3,}", prompt) if w.lower() not in stop_words]
    if not rus_words:
        rus_words = [w.lower() for w in re.findall(r"[а-яА-ЯёЁ]{3,}", prompt)]

    if rus_words:
        trans = {
            'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
            'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
            'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
            'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
            'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
        }
        word = rus_words[0]
        slug = "".join(trans.get(ch, ch) for ch in word)
        if slug:
            return f"{slug}.py"

    return "solution.py"

# --- Буфер обмена (Linux / Windows / Mac) ---
def get_clipboard_text() -> str:
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        text = r.clipboard_get()
        r.destroy()
        if text:
            return text.strip()
    except Exception:
        pass

    for cmd in [
        ["xclip", "-selection", "clipboard", "-o"],
        ["wl-paste"],
        ["xsel", "--clipboard", "--output"]
    ]:
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=1)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            continue
    return ""

def set_clipboard_text(text: str) -> bool:
    try:
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(text)
        r.update()
        r.destroy()
        return True
    except Exception:
        pass

    for cmd in [
        ["xclip", "-selection", "clipboard"],
        ["wl-copy"],
        ["xsel", "--clipboard", "--input"]
    ]:
        try:
            res = subprocess.run(cmd, input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
            if res.returncode == 0:
                return True
        except Exception:
            continue
    return False

# --- Умное сканирование директорий и недавних папок ---
def get_known_directories() -> dict:
    home = Path.home()
    dirs = {}

    for d in (home / "Рабочий стол", home / "Desktop"):
        if d.exists():
            dirs["desktop"] = d
            break
    if "desktop" not in dirs:
        dirs["desktop"] = home / "Desktop"

    for d in (home / "Загрузки", home / "Downloads"):
        if d.exists():
            dirs["downloads"] = d
            break
    if "downloads" not in dirs:
        dirs["downloads"] = home / "Downloads"

    for d in (home / "Документы", home / "Documents"):
        if d.exists():
            dirs["docs"] = d
            break
    if "docs" not in dirs:
        dirs["docs"] = home / "Documents"

    dirs["home"] = home
    dirs["current"] = Path.cwd()
    return dirs

def get_recent_directories() -> list:
    if RECENT_FILE.exists():
        try:
            data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
            return [Path(p) for p in data.get("recent_dirs", []) if Path(p).exists()]
        except Exception:
            pass
    return []

def save_recent_directory(target_dir: Path):
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        recent = []
        if RECENT_FILE.exists():
            try:
                data = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
                recent = data.get("recent_dirs", [])
            except Exception:
                recent = []
        target_str = str(target_dir.resolve())
        if target_str in recent:
            recent.remove(target_str)
        recent.insert(0, target_str)
        recent = recent[:10]
        RECENT_FILE.write_text(json.dumps({"recent_dirs": recent}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def find_active_project_dir() -> Path:
    known = get_known_directories()
    candidates = [known["current"], known["desktop"], known["downloads"], known["docs"]]
    py_files = []
    for base in candidates:
        if not base.exists():
            continue
        try:
            for p in base.glob("*.py"):
                if p.is_file():
                    py_files.append((p.stat().st_mtime, p.parent))
            for sub in base.iterdir():
                if sub.is_dir() and not sub.name.startswith("."):
                    for p in sub.glob("*.py"):
                        if p.is_file():
                            py_files.append((p.stat().st_mtime, p.parent))
        except Exception:
            continue
    if py_files:
        py_files.sort(key=lambda x: x[0], reverse=True)
        return py_files[0][1]
    return None

def resolve_target_dir(choice: str) -> Path:
    known = get_known_directories()
    c = choice.strip().lower()

    if c in ("2", "desktop", "dt", "рабочий стол", "рабочий_стол"):
        p = known["desktop"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    if c in ("3", "home", "~", "домашняя", "домашняя папка"):
        return known["home"]

    if c in ("4", "docs", "documents", "документы"):
        p = known["docs"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    if c in ("5", "downloads", "dl", "загрузки"):
        p = known["downloads"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    if c in ("1", ".", "current", "текущая", ""):
        return known["current"]

    custom_p = Path(choice).expanduser().resolve()
    custom_p.mkdir(parents=True, exist_ok=True)
    return custom_p

def has_stdin_data() -> bool:
    if sys.platform == "win32":
        try:
            import msvcrt
            import ctypes
            from ctypes import wintypes
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            avail = wintypes.DWORD()
            res = ctypes.windll.kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
            return bool(res and avail.value > 0)
        except Exception:
            return False
    else:
        try:
            import select
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            return bool(r)
        except Exception:
            return False

# --- Многострочный ввод с защитой от разрыва переносами ---
def read_multiline_task(args) -> str:
    # 1. Если аргумент уже передан напрямую в командной строке:
    task_raw = getattr(args, "task", None)
    if isinstance(task_raw, list):
        task_str = " ".join(task_raw).strip()
    elif isinstance(task_raw, str):
        task_str = task_raw.strip()
    else:
        task_str = ""

    if task_str:
        return task_str

    # 2. Если запрошен буфер обмена (-c / --clip)
    if getattr(args, "clip", False):
        clip = get_clipboard_text()
        if clip:
            if not getattr(args, "quiet", False):
                print("[✓] Задание прочитано из буфера обмена:")
                preview = clip if len(clip) < 150 else clip[:147] + "..."
                print(f"    {preview}\n")
            return clip
        else:
            if not getattr(args, "quiet", False):
                print("[!] Буфер обмена пуст, переходим к ручному вводу.")

    # 3. Если передано через конвейер (pipe) и данные действительно есть:
    if not sys.stdin.isatty():
        if has_stdin_data():
            return sys.stdin.read().strip()
        return ""

    # 4. Интерактивный ввод с устранением разрывов строк при вставке
    print("=== PyGen: Генератор решений ===")
    print("Вставьте или введите условие задачи.")
    print("(При вставке многострочного текста нажмите Enter еще раз или Ctrl+D для отправки):")

    lines = []
    while True:
        try:
            line = sys.stdin.readline()
            if not line: # EOF (Ctrl+D)
                break
            line_str = line.rstrip("\r\n")
            if not line_str:
                if not lines:
                    continue
                # Проверяем, есть ли еще данные в буфере терминала (debounce вставки)
                if sys.platform != "win32":
                    import select
                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r:
                        lines.append("")
                        continue
                # Пустая строка и нет больше данных -> конец ввода
                break
            else:
                lines.append(line_str)
        except (EOFError, KeyboardInterrupt):
            break

    return "\n".join(lines).strip()

# --- Скрытный компактный GUI интерфейс ---
def launch_stealth_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        print("[!] Модуль tkinter не найден. На Linux установите: apt install python3-tk или используйте CLI.")
        sys.exit(1)

    cfg = load_config()
    known = get_known_directories()
    recent = get_recent_directories()
    default_dir = recent[0] if recent else known["desktop"]

    root = tk.Tk()
    root.title("Заметки")
    root.geometry("420x280")
    root.minsize(360, 220)

    # Неприметное темное оформление
    bg_color = "#202124"
    fg_color = "#e8eaed"
    entry_bg = "#2d2f34"
    accent_color = "#8ab4f8"

    root.configure(bg=bg_color)

    # Прозрачность для незаметности (95%)
    try:
        root.wm_attributes("-alpha", 0.95)
    except Exception:
        pass

    # Защита от захвата экрана на Windows (WDA_EXCLUDEFROMCAPTURE)
    if sys.platform == "win32":
        try:
            import ctypes
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)
        except Exception:
            pass

    # Переменные GUI
    current_target_dir = tk.StringVar(value=str(default_dir))
    provider_var = tk.StringVar(value=cfg.get("provider", "gigachat"))
    status_var = tk.StringVar(value="Готов к работе")

    # Верхний заголовок
    top_frame = tk.Frame(root, bg=bg_color)
    top_frame.pack(fill=tk.X, padx=8, pady=(6, 2))

    lbl_title = tk.Label(top_frame, text="Черновик / Задание:", bg=bg_color, fg="#9aa0a6", font=("sans-serif", 9))
    lbl_title.pack(side=tk.LEFT)

    lbl_help = tk.Label(top_frame, text="Ctrl+Enter: Решить | Esc: Скрыть", bg=bg_color, fg="#70757a", font=("sans-serif", 8))
    lbl_help.pack(side=tk.RIGHT)

    # Поле ввода текста задания (поддерживает любые переносы строк)
    txt_task = tk.Text(root, height=5, bg=entry_bg, fg=fg_color, insertbackground=fg_color,
                       relief=tk.FLAT, font=("monospace", 9), wrap=tk.WORD)
    txt_task.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)
    txt_task.focus_set()

    # Панель выбора провайдера и папки
    mid_frame = tk.Frame(root, bg=bg_color)
    mid_frame.pack(fill=tk.X, padx=8, pady=4)

    # Провайдер
    tk.Label(mid_frame, text="ИИ:", bg=bg_color, fg="#9aa0a6", font=("sans-serif", 8)).pack(side=tk.LEFT)
    rb_giga = tk.Radiobutton(mid_frame, text="GigaChat", variable=provider_var, value="gigachat",
                             bg=bg_color, fg=fg_color, selectcolor=entry_bg, activebackground=bg_color,
                             font=("sans-serif", 8))
    rb_giga.pack(side=tk.LEFT, padx=(2, 6))

    rb_deep = tk.Radiobutton(mid_frame, text="DeepSeek", variable=provider_var, value="deepseek",
                             bg=bg_color, fg=fg_color, selectcolor=entry_bg, activebackground=bg_color,
                             font=("sans-serif", 8))
    rb_deep.pack(side=tk.LEFT, padx=2)

    # Кнопки быстрых папок
    def set_dir(p: Path):
        p.mkdir(parents=True, exist_ok=True)
        current_target_dir.set(str(p))

    def choose_dir_dialog():
        selected = filedialog.askdirectory(initialdir=current_target_dir.get(), title="Выберите папку для сохранения")
        if selected:
            current_target_dir.set(selected)

    btn_browse = tk.Button(mid_frame, text="Обзор...", bg=entry_bg, fg=fg_color, relief=tk.FLAT,
                           font=("sans-serif", 8), command=choose_dir_dialog)
    btn_browse.pack(side=tk.RIGHT, padx=2)

    btn_dt = tk.Button(mid_frame, text="Рабочий стол", bg=entry_bg, fg=fg_color, relief=tk.FLAT,
                       font=("sans-serif", 8), command=lambda: set_dir(known["desktop"]))
    btn_dt.pack(side=tk.RIGHT, padx=2)

    # Строка текущего пути
    path_frame = tk.Frame(root, bg=bg_color)
    path_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
    lbl_path = tk.Label(path_frame, textvariable=current_target_dir, bg=bg_color, fg="#70757a",
                        font=("sans-serif", 8), anchor="w")
    lbl_path.pack(fill=tk.X)

    # Нижняя панель действий
    bot_frame = tk.Frame(root, bg=bg_color)
    bot_frame.pack(fill=tk.X, padx=8, pady=(2, 6))

    lbl_status = tk.Label(bot_frame, textvariable=status_var, bg=bg_color, fg=accent_color, font=("sans-serif", 8))
    lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True, anchor="w")

    def execute_generation(event=None):
        task_text = txt_task.get("1.0", tk.END).strip()
        if not task_text:
            status_var.set("Введите задание!")
            return "break"

        status_var.set("Генерация решения...")
        root.update()

        def run_thread():
            import threading
            prov = provider_var.get()
            target_p = Path(current_target_dir.get()).resolve()
            target_p.mkdir(parents=True, exist_ok=True)
            save_recent_directory(target_p)

            # Сохранение выбора провайдера в конфиг
            cfg["provider"] = prov
            save_config(cfg)

            try:
                code = generate_code_clean(task_text, provider=prov)
                out_name = infer_filename(task_text)
                target_file = target_p / out_name
                target_file.write_text(code, encoding="utf-8")

                # Автоматически копируем в буфер обмена
                set_clipboard_text(code)

                def onSuccess():
                    status_var.set(f"Сохранено в {out_name} и скопировано в буфер ✓")
                root.after(0, onSuccess)
            except Exception as e:
                def onError(err=str(e)):
                    status_var.set("Ошибка!")
                    messagebox.showerror("PyGen Ошибка", err)
                root.after(0, onError)

        import threading
        threading.Thread(target=run_thread, daemon=True).start()
        return "break"

    btn_solve = tk.Button(bot_frame, text="⚡ Решить", bg="#303846", fg="#c2e7ff",
                          activebackground="#404c5e", relief=tk.FLAT, font=("sans-serif", 9, "bold"),
                          padx=12, pady=2, command=execute_generation)
    btn_solve.pack(side=tk.RIGHT)

    # Горячие клавиши
    root.bind("<Control-Return>", execute_generation)
    txt_task.bind("<Control-Return>", execute_generation)
    root.bind("<Escape>", lambda e: root.iconify()) # Boss key: свернуть по Esc

    root.mainloop()

# --- Выбор директории в CLI ---
def choose_save_directory_cli(preset_flag=None) -> Path:
    if preset_flag:
        return resolve_target_dir(preset_flag)

    known = get_known_directories()
    recent = get_recent_directories()
    active = find_active_project_dir()

    options = []
    if active and active != known["current"]:
        options.append((f"Активная рабочая папка (.py)", active))
    if recent and recent[0] != active and recent[0] != known["current"]:
        options.append((f"Последняя использованная", recent[0]))

    options.append(("Текущая папка (.)", known["current"]))
    options.append(("Рабочий стол (Desktop)", known["desktop"]))
    options.append(("Загрузки (Downloads)", known["downloads"]))
    options.append(("Документы (Documents)", known["docs"]))
    options.append(("Домашняя папка (~)", known["home"]))

    print("\nКуда сохранить решение?")
    for idx, (label, path_obj) in enumerate(options, 1):
        print(f"  {idx}. {label}: {path_obj}")
    print(f"  {len(options) + 1}. Ввести свой путь вручную")

    preset_choice = input(f"Выбор [1-{len(options)+1}] (Enter = 1): ").strip()
    if not preset_choice:
        return options[0][1]

    try:
        idx = int(preset_choice)
        if 1 <= idx <= len(options):
            return options[idx - 1][1]
    except ValueError:
        pass

    if preset_choice == str(len(options) + 1):
        custom = input("Введите путь к папке: ").strip()
        p = Path(custom).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    p = Path(preset_choice).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

# --- Встроенные шаблоны расширений для автономной установки ---
VSCODE_PACKAGE_JSON = """{
  "name": "pygen",
  "displayName": "PyGen Code Assistant",
  "description": "Скрытый генератор чистого Python-кода без функций и комментариев",
  "version": "1.0.0",
  "publisher": "pygen",
  "engines": {
    "vscode": "^1.60.0"
  },
  "categories": [
    "Programming Languages",
    "Snippets"
  ],
  "activationEvents": [
    "onCommand:pygen.generate",
    "onCommand:pygen.gui"
  ],
  "main": "./extension.js",
  "contributes": {
    "commands": [
      {
        "command": "pygen.generate",
        "title": "PyGen: Сгенерировать решение"
      },
      {
        "command": "pygen.gui",
        "title": "PyGen: Открыть скрытый GUI"
      }
    ],
    "keybindings": [
      {
        "command": "pygen.generate",
        "key": "ctrl+alt+g",
        "mac": "cmd+alt+g"
      }
    ],
    "menus": {
      "editor/context": [
        {
          "command": "pygen.generate",
          "group": "modification@1"
        },
        {
          "command": "pygen.gui",
          "group": "modification@2"
        }
      ]
    }
  }
}"""

VSCODE_EXTENSION_JS = """const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');
const fs = require('fs');

function findPyGenCommand() {
    const isWin = process.platform === 'win32';
    const candidates = [
        path.join(os.homedir(), '.local', 'bin', isWin ? 'pygen.cmd' : 'pygen'),
        path.join(os.homedir(), '.local', 'bin', 'pygen'),
        path.join(os.homedir(), '.local', 'bin', 'run.py'),
        isWin ? 'pygen.cmd' : 'pygen',
        'pygen'
    ];
    for (const c of candidates) {
        if (fs.existsSync(c)) {
            return c;
        }
    }
    return isWin ? 'pygen.cmd' : 'pygen';
}

function activate(context) {
    const isWin = process.platform === 'win32';

    let genCommand = vscode.commands.registerCommand('pygen.generate', async function () {
        const editor = vscode.window.activeTextEditor;
        let task = '';

        if (editor && !editor.selection.isEmpty) {
            task = editor.document.getText(editor.selection);
        }

        if (!task || !task.trim()) {
            task = await vscode.window.showInputBox({
                prompt: 'PyGen: Введите условие задачи (или выделите текст в редакторе)',
                placeHolder: 'Например: дано n целых чисел, найти сумму положительных'
            });
        }

        if (!task || !task.trim()) {
            return;
        }

        vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "PyGen генерирует решение...",
            cancellable: false
        }, async () => {
            return new Promise((resolve) => {
                const pyCmd = findPyGenCommand();
                let child;
                if (pyCmd.endsWith('.py')) {
                    const pyExe = isWin ? 'python' : 'python3';
                    child = spawn(pyExe, [pyCmd, '--stdout'], { stdio: ['pipe', 'pipe', 'pipe'] });
                } else {
                    child = spawn(pyCmd, ['--stdout'], { shell: isWin, stdio: ['pipe', 'pipe', 'pipe'] });
                }

                let stdoutData = '';
                let stderrData = '';

                child.stdout.on('data', chunk => { stdoutData += chunk.toString(); });
                child.stderr.on('data', chunk => { stderrData += chunk.toString(); });

                child.on('error', err => {
                    vscode.window.showErrorMessage('PyGen не найден. Запустите скрипт установки');
                    resolve();
                });

                child.on('close', code => {
                    resolve();
                    if (code === 0 && stdoutData.trim()) {
                        if (editor) {
                            editor.edit(editBuilder => {
                                if (!editor.selection.isEmpty) {
                                    editBuilder.replace(editor.selection, stdoutData);
                                } else {
                                    editBuilder.insert(editor.selection.active, stdoutData + '\\n');
                                }
                            });
                            vscode.window.showInformationMessage('PyGen: Решение успешно вставлено!');
                        }
                    } else {
                        vscode.window.showErrorMessage('PyGen ошибка: ' + (stderrData.trim() || 'Сбой генерации'));
                    }
                });

                child.stdin.write(task);
                child.stdin.end();
            });
        });
    });

    let guiCommand = vscode.commands.registerCommand('pygen.gui', function () {
        const pyCmd = findPyGenCommand();
        if (pyCmd.endsWith('.py')) {
            const pyExe = isWin ? 'python' : 'python3';
            spawn(pyExe, [pyCmd, '--gui'], { detached: true, stdio: 'ignore' }).unref();
        } else {
            spawn(pyCmd, ['--gui'], { shell: isWin, detached: true, stdio: 'ignore' }).unref();
        }
    });

    context.subscriptions.push(genCommand, guiCommand);
}

function deactivate() {}

module.exports = { activate, deactivate };"""

IDLE_PYGEN_PY = r'''import os
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
'''

PYCHARM_TOOLS_XML = """<toolSet name="External Tools">
  <tool name="PyGen: Решить из буфера" description="Генерирует решение задачи из буфера обмена и сохраняет в проект" showInMainMenu="true" showInEditor="true" showInProject="true" showInSearchPopup="true" disabled="false" useConsole="false" showConsoleOnStdOut="false" showConsoleOnStdErr="false" synchronizeAfterRun="true">
    <exec>
      <option name="COMMAND" value="$USER_HOME$/.local/bin/pygen" />
      <option name="PARAMETERS" value="--clip" />
      <option name="WORKING_DIRECTORY" value="$ProjectFileDir$" />
    </exec>
  </tool>
  <tool name="PyGen: Скрытый GUI" description="Открыть компактный скрытный интерфейс PyGen" showInMainMenu="true" showInEditor="true" showInProject="true" showInSearchPopup="true" disabled="false" useConsole="false" showConsoleOnStdOut="false" showConsoleOnStdErr="false" synchronizeAfterRun="false">
    <exec>
      <option name="COMMAND" value="$USER_HOME$/.local/bin/pygen" />
      <option name="PARAMETERS" value="--gui" />
      <option name="WORKING_DIRECTORY" value="$ProjectFileDir$" />
    </exec>
  </tool>
</toolSet>"""

def install_system():
    is_win = sys.platform == "win32"
    home = Path.home()
    local_bin = home / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("      🚀 Установка PyGen (без прав администратора / sudo)     ")
    print("=" * 60)
    print(f"[*] Платформа: {sys.platform} (Python {sys.version.split()[0]})")

    # 1. Получаем байты скрипта для установки
    code_bytes = None
    try:
        f_name = globals().get("__file__")
        if f_name and not str(f_name).startswith("<"):
            f_path = Path(f_name).resolve()
            if f_path.is_file():
                code_bytes = f_path.read_bytes()
    except Exception:
        pass

    if not code_bytes:
        try:
            if sys.argv and sys.argv[0] and not str(sys.argv[0]).startswith("<"):
                arg_path = Path(sys.argv[0]).resolve()
                if arg_path.is_file():
                    code_bytes = arg_path.read_bytes()
        except Exception:
            pass

    if not code_bytes:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        urls = [
            "https://raw.githubusercontent.com/IliaBebebe/pygen/main/run.py",
            "https://rexcorp.space/p",
        ]
        for u in urls:
            try:
                req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                data = urllib.request.urlopen(req, context=ctx, timeout=12).read()
                if data and len(data) > 1000:
                    code_bytes = data
                    break
            except Exception:
                continue

    target_py = local_bin / "run.py"
    target_py.write_bytes(code_bytes)

    if not is_win:
        target_bin = local_bin / "pygen"
        target_bin.write_bytes(code_bytes)
        target_bin.chmod(0o755)

        gui_launcher = local_bin / "pygen-gui"
        gui_launcher.write_text("#!/usr/bin/env bash\nexec \"$HOME/.local/bin/pygen\" --gui \"$@\"\n", encoding="utf-8")
        gui_launcher.chmod(0o755)
    else:
        cmd_pygen = local_bin / "pygen.cmd"
        cmd_pygen.write_text("@echo off\npython \"%~dp0run.py\" %*\n", encoding="ascii")

        cmd_gui = local_bin / "pygen-gui.cmd"
        cmd_gui.write_text("@echo off\npython \"%~dp0run.py\" --gui %*\n", encoding="ascii")

        ps_pygen = local_bin / "pygen.ps1"
        ps_pygen.write_text("& python \"$PSScriptRoot\\run.py\" @args\n", encoding="ascii")

        ps_gui = local_bin / "pygen-gui.ps1"
        ps_gui.write_text("& python \"$PSScriptRoot\\run.py\" --gui @args\n", encoding="ascii")

    print(f"[1/5] Исполняемые файлы установлены в: {local_bin}")

    # 2. Настройка PATH
    if is_win:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS)
            try:
                curr_path, _ = winreg.QueryValueEx(key, "Path")
            except Exception:
                curr_path = ""
            bin_str = str(local_bin)
            if bin_str.lower() not in curr_path.lower():
                new_path = f"{bin_str};{curr_path}" if curr_path else bin_str
                winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                print(f"[2/5] Каталог {local_bin} добавлен в User PATH (реестр Windows)")
            else:
                print(f"[2/5] Каталог {local_bin} уже присутствует в User PATH")
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[2/5] Запись в реестр PATH пропущена: {e}")
    else:
        add_line = 'export PATH="$HOME/.local/bin:$PATH"\n'
        for rc in [home / ".bashrc", home / ".zshrc", home / ".profile"]:
            if rc.exists():
                content = rc.read_text(encoding="utf-8", errors="ignore")
                if ".local/bin" not in content:
                    rc.write_text(content + add_line, encoding="utf-8")
        print(f"[2/5] Каталог {local_bin} добавлен в ~/.bashrc")

    # 3. Ярлык на Рабочем столе
    desktop_dir = home / "Desktop" if (home / "Desktop").exists() else home / "Рабочий стол"
    if is_win:
        try:
            lnk_path = desktop_dir / "Заметки.lnk"
            vbs_script = f'Set oWS = WScript.CreateObject("WScript.Shell")\nSet oLink = oWS.CreateShortcut("{lnk_path}")\noLink.TargetPath = "{local_bin}\\\\pygen-gui.cmd"\noLink.IconLocation = "shell32.dll,70"\noLink.WindowStyle = 7\noLink.Description = "Компактный редактор PyGen"\noLink.Save\n'
            vbs_file = local_bin / "_create_shortcut.vbs"
            vbs_file.write_text(vbs_script, encoding="cp1251")
            subprocess.run(["cscript", "//nologo", str(vbs_file)], check=False)
            vbs_file.unlink(missing_ok=True)
            print(f"[3/5] Ярлык создан на Рабочем столе: {lnk_path}")
        except Exception:
            print("[3/5] Пропуск создания ярлыка на Рабочем столе")
    else:
        apps_dir = home / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = apps_dir / "pygen.desktop"
        desktop_file.write_text(f"""[Desktop Entry]
Name=Заметки
Comment=Скрытный черновик и генератор кода
Exec={local_bin}/pygen --gui
Icon=text-editor
Terminal=false
Type=Application
Categories=Utility;Development;
""", encoding="utf-8")
        desktop_file.chmod(0o755)
        print(f"[3/5] Создан desktop-ярлык: {desktop_file}")

    # 4. VS Code
    vscode_ext = home / ".vscode" / "extensions" / "pygen"
    vscode_ext.mkdir(parents=True, exist_ok=True)
    (vscode_ext / "package.json").write_text(VSCODE_PACKAGE_JSON, encoding="utf-8")
    (vscode_ext / "extension.js").write_text(VSCODE_EXTENSION_JS, encoding="utf-8")
    print(f"[4/5] [✓] VS Code: расширение установлено в {vscode_ext} (Ctrl+Alt+G)")

    # 5. IDLE
    idle_dir = home / ".idlerc"
    idle_dir.mkdir(parents=True, exist_ok=True)
    (idle_dir / "PyGen.py").write_text(IDLE_PYGEN_PY, encoding="utf-8")
    (idle_dir / "pygen_idle.py").write_text("from .PyGen import PyGen\n", encoding="utf-8")

    user_sites = []
    try:
        res = subprocess.run([sys.executable, "-m", "site", "--user-site"], stdout=subprocess.PIPE, text=True)
        if res.stdout.strip():
            user_sites.append(Path(res.stdout.strip()))
    except Exception:
        pass

    if is_win:
        appdata_py = home / "AppData" / "Roaming" / "Python"
        if appdata_py.exists():
            for d in appdata_py.iterdir():
                if d.is_dir() and d.name.lower().startswith("python"):
                    user_sites.append(d / "site-packages")
    else:
        local_lib = home / ".local" / "lib"
        if local_lib.exists():
            for d in local_lib.iterdir():
                if d.is_dir() and d.name.lower().startswith("python"):
                    user_sites.append(d / "site-packages")

        import shutil
        for py_name in ["python3", "python3.7", "python3.8", "python3.9", "python3.10", "python3.11", "python3.12", "python3.13"]:
            py_bin = shutil.which(py_name)
            if py_bin:
                try:
                    r = subprocess.run([py_bin, "-m", "site", "--user-site"], stdout=subprocess.PIPE, text=True, timeout=5)
                    if r.stdout.strip():
                        user_sites.append(Path(r.stdout.strip()))
                except Exception:
                    pass
                ver = py_name.replace("python", "")
                if ver:
                    user_sites.append(home / ".local" / "lib" / f"python{ver}" / "site-packages")

    try:
        import idlelib
        idlelib_dir = Path(idlelib.__file__).parent
        (idlelib_dir / "PyGen.py").write_text(IDLE_PYGEN_PY, encoding="utf-8")
        def_path = idlelib_dir / "config-extensions.def"
        if def_path.exists():
            def_text = def_path.read_text(encoding="utf-8", errors="ignore")
            if "[PyGen]" not in def_text:
                def_chunk = "\n\n[PyGen]\nenable= True\nenable_shell= True\nenable_editor= True\n\n[PyGen_cfgBindings]\npygen-solution= <Control-Alt-Key-g>\n"
                def_path.write_text(def_text + def_chunk, encoding="utf-8")
    except Exception:
        pass

    for usp in set(user_sites):
        try:
            usp.mkdir(parents=True, exist_ok=True)
            (usp / "PyGen.py").write_text(IDLE_PYGEN_PY, encoding="utf-8")
            (usp / "pygen_idle.py").write_text("from .PyGen import PyGen\n", encoding="utf-8")
            (usp / "pygen.pth").write_text(str(idle_dir) + "\n", encoding="utf-8")
        except Exception:
            pass

    cfg_idle = idle_dir / "config-extensions.cfg"
    idle_cfg_chunk = "[PyGen]\nenable=True\nenable_editor=True\nenable_shell=True\n\n[PyGen_cfgBindings]\npygen-solution=<Control-Alt-Key-g>\n"
    if not cfg_idle.exists():
        cfg_idle.write_text(idle_cfg_chunk, encoding="utf-8")
    else:
        text = cfg_idle.read_text(encoding="utf-8", errors="ignore")
        if "[PyGen]" not in text:
            cfg_idle.write_text(text + "\n" + idle_cfg_chunk, encoding="utf-8")
        else:
            cfg_idle.write_text(text.replace("<Alt-Key-g>", "<Control-Alt-Key-g>"), encoding="utf-8")
    print(f"      [✓] IDLE: расширение установлено для всех версий Python (Ctrl+Alt+G / Alt+G)")

    # 6. PyCharm
    jb_bases = []
    if is_win:
        appdata = os.environ.get("APPDATA")
        localappdata = os.environ.get("LOCALAPPDATA")
        if appdata: jb_bases.append(Path(appdata) / "JetBrains")
        if localappdata: jb_bases.append(Path(localappdata) / "JetBrains")
    else:
        jb_bases.append(home / ".config" / "JetBrains")

    jb_found = False
    for jb in jb_bases:
        if jb.exists():
            for ide in jb.iterdir():
                if ide.is_dir() and ("pycharm" in ide.name.lower() or "idea" in ide.name.lower()):
                    tools_dir = ide / "tools"
                    tools_dir.mkdir(parents=True, exist_ok=True)
                    target_xml = tools_dir / "External Tools.xml"
                    if not target_xml.exists():
                        target_xml.write_text(PYCHARM_TOOLS_XML, encoding="utf-8")
                        jb_found = True
                        print(f"      [✓] PyCharm ({ide.name}): добавлены External Tools")
    if not jb_found:
        print("      [-] PyCharm: каталоги настроек пока не созданы")

    print("\n" + "=" * 60)
    print("          🎉 Установка успешно завершена!                 ")
    print("=" * 60)
    print("\n📌 Способы использования:")
    if is_win:
        print("1. В терминале (CMD / PowerShell):")
        print("   pygen \"задание\" -dt        # Сохранить на Рабочий стол")
        print("   pygen -c                 # Решить задание ПРЯМО ИЗ БУФЕРА ОБМЕНА")
        print("   pygen                    # Интерактивный многострочный ввод")
        print("\n2. Скрытный компактный GUI:")
        print("   pygen -g                 # Открыть окно (Ctrl+Enter - решить, Esc - скрыть)")
        print("   (На Windows окно автоматически защищено от программ захвата экрана!)")
    else:
        print("1. В терминале (CLI):")
        print("   pygen \"задание\" -dt")
        print("   pygen -c -dt")
        print("\n2. Скрытный GUI:")
        print("   pygen -g")

    print("\n3. В редакторах кода:")
    print("   - VS Code: выделите условие -> Ctrl+Alt+G")
    print("   - IDLE:    выделите условие -> Alt+G")
    print("   - PyCharm: Меню Tools -> External Tools -> PyGen: Решить из буфера\n")

# --- CLI Точка входа ---
def main():
    parser = argparse.ArgumentParser(
        description="PyGen: Быстрый и незаметный генератор чистого Python-кода (РФ, без VPN, без sudo)."
    )
    parser.add_argument("task", nargs="*", help="Текст задания")
    parser.add_argument("-g", "--gui", action="store_true", help="Запустить скрытный компактный GUI интерфейс")
    parser.add_argument("-c", "--clip", action="store_true", help="Прочитать задание прямо из буфера обмена")
    parser.add_argument("-p", "--provider", choices=["gigachat", "deepseek", "ollama"],
                        help="Провайдер ИИ: gigachat (по умолчанию, бесплатно) или deepseek")
    parser.add_argument("--deepseek", action="store_true", help="Использовать DeepSeek")
    parser.add_argument("-k", "--key", help="API-ключ (для DeepSeek)")
    parser.add_argument("-d", "--dir", help="Папка назначения или пресет (desktop, home, docs, downloads)")
    parser.add_argument("-dt", "--desktop", action="store_true", help="Сохранить на Рабочий стол")
    parser.add_argument("--home", action="store_true", help="Сохранить в Домашнюю папку (~)")
    parser.add_argument("--docs", action="store_true", help="Сохранить в Документы")
    parser.add_argument("--downloads", action="store_true", help="Сохранить в Загрузки")
    parser.add_argument("-f", "--file", help="Имя выходного .py файла")
    parser.add_argument("-q", "--quiet", action="store_true", help="Тихий режим (выводит только путь к файлу)")
    parser.add_argument("--stdout", action="store_true", help="Вывести ТОЛЬКО сгенерированный код в stdout (для IDE)")
    parser.add_argument("--install", action="store_true", help="Автоматическая установка PyGen, CLI и расширений IDE в систему")
    parser.add_argument("--url", help="Кастомный API URL (например, локальный Ollama)")
    args = parser.parse_args()

    # Запуск автоустановки
    if args.install:
        install_system()
        sys.exit(0)

    # Запуск GUI, если указан флаг
    if args.gui:
        launch_stealth_gui()
        sys.exit(0)

    # Определение провайдера
    provider = args.provider
    if args.deepseek:
        provider = "deepseek"

    # Получение задания
    task = read_multiline_task(args)
    if not task:
        if not args.quiet and not args.stdout:
            print("Ошибка: задание не может быть пустым.")
        sys.exit(0)

    # Режим вывода чистого кода в stdout (для интеграции с IDE)
    if args.stdout:
        try:
            code = generate_code_clean(task, provider=provider, api_key=args.key, custom_url=args.url)
            sys.stdout.write(code)
            sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Ошибка: {e}\n")
            sys.exit(1)
        sys.exit(0)

    # Выбор папки для сохранения
    target_dir = None
    if args.desktop:
        target_dir = resolve_target_dir("desktop")
    elif args.home:
        target_dir = resolve_target_dir("home")
    elif args.docs:
        target_dir = resolve_target_dir("docs")
    elif args.downloads:
        target_dir = resolve_target_dir("downloads")
    elif args.dir:
        target_dir = resolve_target_dir(args.dir)

    out_file = args.file

    if not target_dir:
        if args.task or args.clip or not sys.stdin.isatty():
            # Если задание передано флагом/пайпом, но папка не указана -> текущая папка
            target_dir = Path(".").resolve()
        else:
            # Интерактивный режим выбора
            target_dir = choose_save_directory_cli()
            user_file = input("Имя файла (Enter для авто): ").strip()
            if user_file:
                out_file = user_file

    if not target_dir:
        target_dir = Path(".").resolve()

    if not args.quiet:
        print("[*] Генерация решения...")

    code = generate_code_clean(task, provider=provider, api_key=args.key, custom_url=args.url)

    if not out_file:
        out_file = infer_filename(task)
    if not out_file.endswith(".py"):
        out_file += ".py"

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / out_file
    target_path.write_text(code, encoding="utf-8")

    save_recent_directory(target_dir)

    # Копируем также в буфер обмена для удобства
    set_clipboard_text(code)

    if not args.quiet:
        print(f"[+] Сохранено в: {target_path}")
        print(f"[+] Код также скопирован в буфер обмена!")
        print("\n" + code + "\n")
    else:
        print(str(target_path))

if __name__ == "__main__":
    main()
