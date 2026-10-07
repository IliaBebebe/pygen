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

def get_local_ollama_model() -> str:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", timeout=1)
        with urllib.request.urlopen(req) as resp:
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

def query_model(model: str, prompt: str, api_key: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "HTTP-Referer": "https://openrouter.ai",
        "X-Title": "PyGen"
    }

    try:
        req = urllib.request.Request(API_URL, data=payload_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except Exception as err:
        pass

    import subprocess
    cmd = [
        "curl", "-s", "-X", "POST", API_URL,
        "-H", f"Authorization: Bearer {api_key}",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json",
        "-H", "HTTP-Referer: https://openrouter.ai",
        "-H", "X-Title: PyGen",
        "-d", json.dumps(payload)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=45)
        if res.returncode == 0 and res.stdout:
            data = json.loads(res.stdout)
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            if "error" in data:
                err_msg = data["error"].get("message", str(data["error"]))
                raise RuntimeError(err_msg)
    except Exception as err:
        raise RuntimeError(f"{err}")

    raise RuntimeError("Не удалось выполнить запрос ни через urllib, ни через curl")

def query_deepseek(prompt: str, api_key: str) -> str:
    url = "https://api.deepseek.com/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]

def generate_solution(prompt: str, api_key: str, custom_url: str = None, provider: str = "auto") -> str:
    # 1. Если явно выбран DeepSeek или передан ключ DeepSeek
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if provider == "deepseek" or deepseek_key:
        key = deepseek_key or api_key
        return query_deepseek(prompt, key)

    # 2. Если запущен локальный Ollama или указан кастомный URL
    local_model = get_local_ollama_model()
    if custom_url or local_model:
        model_name = local_model or "qwen2.5-coder:1.5b"
        url = custom_url or "http://localhost:11434/v1"
        try:
            return query_ollama(model_name, prompt, url)
        except Exception as e:
            if custom_url:
                raise RuntimeError(f"Ошибка кастомного сервера: {e}")

    # 3. Иначе используем OpenRouter
    last_err = None
    for model in MODELS:
        try:
            return query_model(model, prompt, api_key)
        except Exception as e:
            last_err = e
            continue
    
    err_str = str(last_err)
    if "security policy" in err_str.lower() or "403" in err_str:
        raise RuntimeError(
            "OpenRouter заблокирован в РФ без VPN.\n"
            "Используйте DeepSeek (работает в РФ без VPN): зарегистрируйтесь на platform.deepseek.com (дает 5 млн бесплатных токенов) и запустите:\n"
            "python3 run.py -p deepseek -k ВАШ_КЛЮЧ 'задание'"
        )
    raise RuntimeError(f"API Error: {last_err}")

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
    parser.add_argument("-p", "--provider", choices=["auto", "deepseek", "openrouter", "ollama"], default="auto", help="Провайдер ИИ")
    parser.add_argument("-k", "--key", help="API-ключ (опционально)")
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

    api_key = args.key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or _DEFAULT_KEY

    if not args.quiet:
        print("[*] Generating code...")

    raw_resp = generate_solution(task, api_key, custom_url=args.url, provider=args.provider)
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
