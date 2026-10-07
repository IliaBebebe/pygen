#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import re
import io
import tokenize
import ast
import base64
from pathlib import Path

# Built-in configuration (works without VPN, 100% free models)
_DEFAULT_KEY = base64.b64decode(
    b"c2stb3ItdjEtNzcxMDM2Nzk1ZTMzYmMzZDA3NjEwMjAxYTE1NDE2NTFmZWEyNGEzNzc5NzBkY2U2NjA3OTAxM2M2MjlmNzQ2Zg=="
).decode("utf-8")

API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free"
]

SYSTEM_PROMPT = """You are an expert Python programmer.
Generate code that solves the user's task.
Strict rules:
1. Output ONLY valid, executable Python code.
2. ABSOLUTELY NO COMMENTS (no '#' anywhere, no inline comments).
3. ABSOLUTELY NO DOCSTRINGS (no multiline strings explaining functions/classes).
4. No conversational text, no markdown explanations. Return raw code."""

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

def query_model(model: str, prompt: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PyGen/1.0"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

def generate_solution(prompt: str, api_key: str) -> str:
    last_err = None
    for model in MODELS:
        try:
            return query_model(model, prompt, api_key)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Не удалось получить ответ: {last_err}")

def infer_filename(prompt: str) -> str:
    words = re.findall(r"[a-zA-Z0-9_]{3,}", prompt)
    if words:
        return f"{words[0].lower()}.py"
    return "solution.py"

def main():
    parser = argparse.ArgumentParser(description="Автоматический генератор Python-кода без комментариев.")
    parser.add_argument("task", nargs="?", help="Текст задания")
    parser.add_argument("-d", "--dir", default=".", help="Папка назначения (по умолчанию: текущая)")
    parser.add_argument("-f", "--file", help="Имя выходного .py файла")
    parser.add_argument("-q", "--quiet", action="store_true", help="Тихий режим (минимум вывода)")
    parser.add_argument("-k", "--key", help="API-ключ (опционально, уже встроен рабочий)")
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

    api_key = args.key or os.environ.get("OPENROUTER_API_KEY") or _DEFAULT_KEY

    if not args.quiet:
        print("[*] Генерация решения...")

    raw_resp = generate_solution(task, api_key)
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
        print(f"[+] Сохранено в: {target_path}")
        print("\n" + code + "\n")
    else:
        print(str(target_path))

if __name__ == "__main__":
    main()
