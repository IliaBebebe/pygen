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
from pathlib import Path

# Встроенный рабочий ключ GigaChat (Сбер) - 100% работает в РФ без VPN
_GIGACHAT_AUTH = "Basic MzgyMDE1ZDgtMzM2MC00NjI3LWFjZWUtNDZkOGFjZTIwNzkzOjQzMDFiZjU4LWJjMmEtNGRjNi04Y2MwLWNlNWUyOTQ2ZTcwMw=="

SYSTEM_PROMPT = """You are a Python programming assistant for computer science school classes.
Generate simple, beginner-friendly Python code that solves the task.
Strict rules:
1. Output ONLY valid, executable Python code.
2. ABSOLUTELY DO NOT DEFINE FUNCTIONS (STRICTLY NO 'def', NO 'lambda').
   Write a plain, linear sequential script from top to bottom.
   Read inputs with input() when appropriate, compute using standard variables, loops (for/while), and conditions (if/else), and output results with print().
3. Even if the user prompt mentions 'функция' or 'function', DO NOT use 'def'. Write a plain procedural script instead.
4. ABSOLUTELY NO COMMENTS (no '#' anywhere, no inline comments).
5. ABSOLUTELY NO DOCSTRINGS (no triple-quoted documentation strings).
6. No conversational text, no markdown explanations. Return raw code."""

def get_ssl_context():
    # Отключаем проверку сертификата для совместимости со Сбером на любых Linux без Минцифры
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
    words = re.findall(r"[a-zA-Z0-9_]{3,}", prompt)
    if words:
        return f"{words[0].lower()}.py"
    return "solution.py"

def generate_solution(prompt: str, custom_url: str = None) -> str:
    # 1. Если запущен локальный Ollama или указан кастомный URL
    local_model = get_local_ollama_model()
    if custom_url or local_model:
        model_name = local_model or "qwen2.5-coder:1.5b"
        url = custom_url or "http://localhost:11434/v1"
        try:
            return query_ollama(model_name, prompt, url)
        except Exception as e:
            if custom_url:
                raise RuntimeError(f"Ошибка кастомного сервера Ollama: {e}")

    # 2. Основной облачный режим: GigaChat (работает в РФ без VPN, 100% бесплатно)
    try:
        return query_gigachat(prompt)
    except Exception as err:
        raise RuntimeError(f"Ошибка генерации GigaChat: {err}")

def main():
    parser = argparse.ArgumentParser(description="Автоматический генератор Python-кода без комментариев (РФ, без VPN).")
    parser.add_argument("task", nargs="?", help="Текст задания")
    parser.add_argument("-d", "--dir", default=".", help="Папка назначения (по умолчанию: текущая)")
    parser.add_argument("-f", "--file", help="Имя выходного .py файла")
    parser.add_argument("-q", "--quiet", action="store_true", help="Тихий режим (минимум вывода)")
    parser.add_argument("--url", help="Кастомный API URL (например, локальный Ollama)")
    args = parser.parse_args()

    task = args.task
    out_dir = args.dir
    out_file = args.file

    if not task:
        task = input("Задание: ").strip()
        if not task:
            sys.exit(0)
        user_dir = input(f"Папка [{out_dir}]: ").strip()
        if user_dir:
            out_dir = user_dir
        user_file = input("Имя файла (Enter для авто): ").strip()
        if user_file:
            out_file = user_file

    if not args.quiet:
        print("[*] Generating code...")

    raw_resp = generate_solution(task, custom_url=args.url)
    code = extract_code(raw_resp)
    code = remove_comments_and_docstrings(code)

    if not out_file:
        out_file = infer_filename(task)
    if not out_file.endswith(".py"):
        out_file += ".py"

    target_dir = Path(out_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / out_file

    target_path.write_text(code, encoding="utf-8")

    if not args.quiet:
        print(f"[+] Saved to: {target_path}")
        print("\n" + code + "\n")
    else:
        print(str(target_path))

if __name__ == "__main__":
    main()
