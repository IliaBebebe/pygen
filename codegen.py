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
from pathlib import Path

DEFAULT_OLLAMA_URL = "http://localhost:11434/v1"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"

SYSTEM_PROMPT = """You are an expert Python code generator.
Follow these rules strictly:
1. Output ONLY valid, executable Python code.
2. DO NOT write ANY comments (strictly no '#' comments, no inline comments).
3. DO NOT write docstrings (no triple-quoted documentation strings).
4. DO NOT provide conversational introductions, markdown explanations, or conclusions.
5. Return the raw code inside a single ```python ``` codeblock or as pure code."""

def remove_comments_and_docstrings(source_code: str) -> str:
    cleaned_lines = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source_code).readline)
        tokens_without_comments = []
        for tok_type, tok_string, start, end, line in tokens:
            if tok_type == tokenize.COMMENT:
                continue
            tokens_without_comments.append((tok_type, tok_string, start, end, line))
        source_code = tokenize.untokenize(tokens_without_comments)
    except Exception:
        source_code = "\n".join(
            line for line in source_code.splitlines()
            if not line.strip().startswith("#")
        )

    try:
        tree = ast.parse(source_code)
        docstring_ranges = []
        
        def check_docstring(node):
            if (
                node.body and
                isinstance(node.body[0], ast.Expr) and
                isinstance(node.body[0].value, ast.Constant) and
                isinstance(node.body[0].value.value, str)
            ):
                doc_node = node.body[0]
                docstring_ranges.append((doc_node.lineno, getattr(doc_node, "end_lineno", doc_node.lineno)))

        if isinstance(tree, ast.Module):
            check_docstring(tree)
        for subnode in ast.walk(tree):
            if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                check_docstring(subnode)

        lines = source_code.splitlines()
        filtered_lines = []
        skip_line = set()
        for start_l, end_l in docstring_ranges:
            for l_num in range(start_l, end_l + 1):
                skip_line.add(l_num)

        for idx, line in enumerate(lines, start=1):
            if idx in skip_line:
                continue
            if line.strip().startswith("#"):
                continue
            filtered_lines.append(line)

        source_code = "\n".join(filtered_lines)
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

def extract_python_code(text: str) -> str:
    matches = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if matches:
        return matches[0]
    return text.strip()

def send_chat_completion(base_url: str, api_key: str, model: str, prompt: str) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Linux-Free-CodeGen/1.0"
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }

    req = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {err.code}: {err.reason}\n{err_body}")
    except Exception as err:
        raise RuntimeError(f"Сетевая ошибка: {err}")

def infer_filename(task: str, code: str) -> str:
    first_meaningful_word = re.findall(r"[a-zA-Z0-9_]{3,}", task)
    if first_meaningful_word:
        return f"{first_meaningful_word[0].lower()}.py"
    return "solution.py"

def main():
    parser = argparse.ArgumentParser(
        description="Генератор Python-кода без комментариев (работает без root и без VPN)."
    )
    parser.add_argument("prompt", nargs="?", help="Текст задания")
    parser.add_argument("-d", "--dir", default=".", help="Папка для сохранения файла (по умолчанию: текущая)")
    parser.add_argument("-f", "--file", help="Имя выходного .py файла (по умолчанию авто)")
    parser.add_argument("-p", "--provider", choices=["openrouter", "ollama"], default="openrouter",
                        help="Провайдер ИИ: openrouter (бесплатные модели) или ollama (локально)")
    parser.add_argument("-m", "--model", help="Имя модели (по умолчанию выбрана лучшая бесплатная)")
    parser.add_argument("-k", "--key", help="API-ключ (для OpenRouter или переменная OPENROUTER_API_KEY)")
    parser.add_argument("--url", help="Кастомный base_url (например, http://localhost:11434/v1)")
    
    args = parser.parse_args()

    task = args.prompt
    out_dir = args.dir
    out_file = args.file

    if not task:
        print("=== Генератор Python-кода (без прав админа, без VPN) ===")
        task = input("Введите задание для кода: ").strip()
        if not task:
            print("Ошибка: задание не может быть пустым.")
            sys.exit(1)
        
        input_dir = input(f"Папка для сохранения [{out_dir}]: ").strip()
        if input_dir:
            out_dir = input_dir
            
        input_file = input("Имя файла (Enter для авто): ").strip()
        if input_file:
            out_file = input_file

    provider = args.provider
    if provider == "ollama":
        base_url = args.url or DEFAULT_OLLAMA_URL
        model = args.model or DEFAULT_OLLAMA_MODEL
        api_key = args.key or ""
    else:
        base_url = args.url or DEFAULT_OPENROUTER_URL
        model = args.model or DEFAULT_OPENROUTER_MODEL
        api_key = args.key or os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            print("\n[Внимание]: Для OpenRouter нужен бесплатный ключ (без VPN с сайта openrouter.ai).")
            print("Его можно передать через ключ -k, переменную OPENROUTER_API_KEY или ввести сейчас.")
            api_key = input("Введите OpenRouter API Key: ").strip()
            if not api_key:
                print("Ошибка: без ключа запрос к OpenRouter не может быть выполнен.")
                sys.exit(1)

    print(f"\n[1/3] Отправка задания модели '{model}'...")
    raw_response = send_chat_completion(base_url, api_key, model, task)

    print("[2/3] Очистка кода от комментариев и форматирование...")
    extracted_code = extract_python_code(raw_response)
    clean_code = remove_comments_and_docstrings(extracted_code)

    if not out_file:
        out_file = infer_filename(task, clean_code)
    if not out_file.endswith(".py"):
        out_file += ".py"

    target_dir = Path(out_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / out_file

    target_path.write_text(clean_code, encoding="utf-8")

    print(f"[3/3] Готово! Код сохранен в:\n-> {target_path}\n")
    print("--- Содержимое файла (без комментариев) ---")
    print(clean_code)
    print("------------------------------------------")

if __name__ == "__main__":
    main()
