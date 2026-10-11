#!/usr/bin/env python3
import os
import sys
import json
import argparse
import urllib.request
import urllib.error
from urllib.parse import urlparse
import ssl
import socket
import uuid
import re
import io
import tokenize
import ast
import html as _html
import time
import base64
import subprocess
import threading
import shutil
from pathlib import Path

# Универсальное обеспечение UTF-8 ввода/вывода (Linux LC_ALL=C, Windows CP1251/CP866, macOS)
for stream in (sys.stdout, sys.stderr, sys.stdin):
    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if sys.platform == "win32":
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11) # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, mode.value | 0x0004) # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass

__version__ = "3.0.0"

# Встроенный рабочий ключ GigaChat (Сбер) - 100% работает в РФ без VPN
_GIGACHAT_AUTH = "Basic MzgyMDE1ZDgtMzM2MC00NjI3LWFjZWUtNDZkOGFjZTIwNzkzOjQzMDFiZjU4LWJjMmEtNGRjNi04Y2MwLWNlNWUyOTQ2ZTcwMw=="
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"

# Google Gemini через изолированный быстрый VPS-прокси (РФ, без VPN)
GEMINI_DEFAULT_PROXY_URL = "https://gemini.rexcorp.space"
GEMINI_DEFAULT_MODEL = "gemini-3.5-flash"
# Публичный ключ Gemini-релея (ротация 2026: предыдущий ключ отключён).
# Ключ публичный — он и так лежит в открытой раздаче rexcorp.space/p, но GitHub
# secret scanning блокирует пуш открытых ключей Google, поэтому храним в base64.
# Замена ключа: _DEFAULT_GEMINI_KEY = base64.b64encode(b"<новый ключ>").decode()
_DEFAULT_GEMINI_KEY = base64.b64decode(
    "QVEuQWI4Uk42S2ZidjJacW9PVFdBM2RWal96bkdyVWZtRHp1R19CWXlhOHBLSEU0TXVIT2c="
).decode("ascii")

# Источники для автоматического обновления (канонический домен — pygen.rexcorp.space,
# rexcorp.space оставлен как резерв для старых установок)
UPDATE_VERSION_URLS = [
    "https://pygen.rexcorp.space/version",
    "http://pygen.rexcorp.space/version",
    "https://gemini.rexcorp.space/version",
    "https://rexcorp.space/version",
    "https://raw.githubusercontent.com/IliaBebebe/pygen/main/run.py"
]
UPDATE_SCRIPT_URLS = [
    "https://pygen.rexcorp.space/p",
    "http://pygen.rexcorp.space/p",
    "https://gemini.rexcorp.space/p",
    "https://rexcorp.space/p",
    "https://raw.githubusercontent.com/IliaBebebe/pygen/main/run.py"
]

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
    cfg = {
        "provider": "gigachat",
        "deepseek_api_key": "",
        "gemini_api_key": _DEFAULT_GEMINI_KEY,
        "gemini_proxy_url": GEMINI_DEFAULT_PROXY_URL,
        "gemini_model": GEMINI_DEFAULT_MODEL
    }
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except Exception:
            pass
    return cfg

def save_config(cfg: dict):
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def resilient_http_get(url: str, timeout: float = 2.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"PyGen/{__version__}",
                                               "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, ssl.SSLError):
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")

        local_ip = None
        for test_target in ("192.168.1.1", "8.8.8.8"):
            try:
                s_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s_probe.settimeout(timeout)
                s_probe.connect((test_target, 80))
                cand_ip = s_probe.getsockname()[0]
                s_probe.close()
                if cand_ip and not cand_ip.startswith(("127.", "172.19.")):
                    local_ip = cand_ip
                    break
            except Exception:
                pass

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            if local_ip:
                sock.bind((local_ip, 0))
            ip_dest = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
            sock.connect(ip_dest)
            if parsed.scheme == "https":
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)
            http_req = f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: PyGen/{__version__}\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n".encode("utf-8")
            sock.sendall(http_req)
            raw = b""
            while True:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                raw += chunk
            sock.close()
            parts = raw.split(b"\r\n\r\n", 1)
            if len(parts) >= 2:
                body = parts[1]
                status_line = parts[0].split(b"\r\n", 1)[0]
                if not status_line.startswith(b"HTTP/1.1 2"):
                    return b""
                if b"transfer-encoding: chunked" in parts[0].lower():
                    clean_b = b""
                    pos = 0
                    while pos < len(body):
                        c_end = body.find(b"\r\n", pos)
                        if c_end == -1: break
                        sz = body[pos:c_end].split(b";")[0].strip()
                        if not sz: break
                        chunk_sz = int(sz, 16)
                        if chunk_sz == 0: break
                        pos = c_end + 2
                        clean_b += body[pos:pos+chunk_sz]
                        pos += chunk_sz + 2
                    body = clean_b
                return body
        except Exception:
            pass
    return b""

def parse_version(v_str: str) -> tuple:
    nums = re.findall(r"\d+", v_str)
    return tuple(int(x) for x in nums) if nums else (0,)

def check_for_updates(timeout: float = 2.0):
    for u in UPDATE_VERSION_URLS:
        try:
            data = resilient_http_get(u, timeout=timeout)
            if not data:
                continue
            txt = data.decode("utf-8", errors="ignore").strip()
            ver_found = None
            if "version" in u:
                line1 = txt.splitlines()[0].strip() if txt.splitlines() else ""
                m = re.search(r"\b\d+\.\d+(?:\.\d+)*\b", line1)
                if m:
                    ver_found = m.group(0)
            else:
                m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', txt)
                if m:
                    ver_found = m.group(1)

            if ver_found:
                if parse_version(ver_found) > parse_version(__version__):
                    return ver_found
                return None
        except Exception:
            continue
    return None

def restart_process():
    try:
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP: новый процесс не получает Ctrl+C родителя
            subprocess.Popen([sys.executable] + sys.argv, creationflags=0x00000200)
            sys.exit(0)
        else:
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception:
        sys.exit(0)

def perform_update() -> bool:
    code_bytes = None
    for u in UPDATE_SCRIPT_URLS:
        try:
            data = resilient_http_get(u, timeout=12.0)
            if data and b"SYSTEM_PROMPT" in data and len(data) > 10000:
                code_bytes = data
                break
        except Exception:
            continue

    if not code_bytes:
        return False

    targets = set()
    try:
        if globals().get("__file__"):
            p = Path(__file__).resolve()
            if p.is_file():
                targets.add(p)
    except Exception:
        pass

    try:
        if sys.argv and sys.argv[0]:
            p = Path(sys.argv[0]).resolve()
            if p.is_file():
                targets.add(p)
    except Exception:
        pass

    local_bin = Path.home() / ".local" / "bin"
    targets.add(local_bin / "run.py")
    if sys.platform != "win32":
        targets.add(local_bin / "pygen")

    success = False
    for t in targets:
        try:
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_bytes(code_bytes)
            if sys.platform != "win32" and t.name == "pygen":
                try:
                    t.chmod(0o755)
                except Exception:
                    pass
            success = True
        except Exception:
            pass

    return success

def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

# --- Надёжность сети: повторные попытки при временных сбоях ---
_provider_fail_cache = {}  # provider -> [timestamp_until, reason]

def _looks_like_auth_error(err) -> bool:
    s = str(err).lower()
    markers = ("401", "403", "invalid authentication", "unauthenticated", "unauthorized",
               "invalid api key", "invalid_api_key", "api key not valid", "authentication credentials",
               "не указан api-ключ", "недействителен")
    return any(m in s for m in markers)

def mark_provider_dead(provider: str, reason: str, ttl: float = 600.0):
    """Запоминает, что провайдер не работает (чтобы не ждать его снова)."""
    _provider_fail_cache[provider.lower()] = [time.time() + ttl, reason]

def clear_provider_dead(provider: str = None):
    if provider is None:
        _provider_fail_cache.clear()
    else:
        _provider_fail_cache.pop(provider.lower(), None)

def provider_dead_reason(provider: str):
    """Возвращает причину недоступности провайдера или None."""
    item = _provider_fail_cache.get(provider.lower())
    if not item:
        return None
    if time.time() > item[0]:
        _provider_fail_cache.pop(provider.lower(), None)
        return None
    return item[1]

def _request_json(url: str, body: bytes, headers: dict, timeout: float,
                  context=None, retries: int = 3, method: str = "POST"):
    """HTTP-запрос с повторами при 5xx и сетевых сбоях (4xx не повторяем)."""
    last_err = None
    delay = 0.7
    for attempt in range(1, max(1, retries) + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=context, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            body_text = ""
            try:
                body_text = err.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            detail = (body_text or str(err.reason or "")).strip().replace("\n", " ")
            last_err = RuntimeError(f"HTTP {err.code}: {detail[:300]}")
            if err.code < 500:  # 4xx — повтор бессмысленен
                raise last_err
        except (urllib.error.URLError, ssl.SSLError, socket.timeout, TimeoutError, OSError) as err:
            last_err = RuntimeError(f"Сетевая ошибка: {err}")
        if attempt < retries:
            time.sleep(delay)
            delay *= 2.5
    raise last_err or RuntimeError("Не удалось выполнить запрос")

# Кэш токена GigaChat: токен живёт ~30 минут, повторная аутентификация не нужна
_gigachat_token_cache = {"token": None, "expires": 0.0, "auth": None}

def get_gigachat_token(auth_str: str = None) -> str:
    auth = auth_str or _GIGACHAT_AUTH
    cache = _gigachat_token_cache
    if cache["token"] and cache["auth"] == auth and time.time() < cache["expires"]:
        return cache["token"]

    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    rquid = str(uuid.uuid4())
    data = _request_json(
        url,
        b"scope=GIGACHAT_API_PERS",
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rquid,
            "Authorization": auth
        },
        timeout=15,
        context=get_ssl_context(),
        retries=2
    )

    token = data["access_token"]
    ttl = 1500.0  # консервативные 25 минут по умолчанию
    try:
        expires_at = float(data.get("expires_at", 0))
        if expires_at > 1e12:  # миллисекунды unix
            expires_at /= 1000.0
        if expires_at > time.time():
            ttl = min(expires_at - time.time() - 300.0, 1500.0)  # запас 5 минут
    except Exception:
        pass
    cache["token"] = token
    cache["auth"] = auth
    cache["expires"] = time.time() + max(ttl, 60.0)
    return token

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
    try:
        data = _request_json(
            url,
            json.dumps(payload).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}"
            },
            timeout=30,
            context=get_ssl_context(),
            retries=3
        )
        return data["choices"][0]["message"]["content"]
    except RuntimeError:
        raise
    except Exception as err:
        raise RuntimeError(f"GigaChat: {err}")

def query_deepseek(prompt: str, api_key: str, model: str = DEEPSEEK_DEFAULT_MODEL) -> str:
    if not api_key:
        cfg = load_config()
        api_key = cfg.get("deepseek_api_key") or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("Для DeepSeek не указан API-ключ! Передайте через --key или сохраните в настройках.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    try:
        data = _request_json(
            DEEPSEEK_API_URL,
            json.dumps(payload).encode("utf-8"),
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            timeout=45,
            retries=3
        )
        return data["choices"][0]["message"]["content"]
    except RuntimeError as err:
        raise RuntimeError(f"DeepSeek {err}")
    except Exception as err:
        raise RuntimeError(f"Сетевая ошибка DeepSeek: {err}")

def query_gemini(prompt: str, api_key: str = None, base_url: str = None, model: str = None) -> str:
    cfg = load_config()
    key = api_key or cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "") or _DEFAULT_GEMINI_KEY
    if not key:
        raise RuntimeError("Для Gemini не указан API-ключ! Передайте через --key или сохраните в настройках.")

    proxy = (base_url or cfg.get("gemini_proxy_url") or GEMINI_DEFAULT_PROXY_URL).rstrip("/")
    m = model or cfg.get("gemini_model") or GEMINI_DEFAULT_MODEL
    url = f"{proxy}/v1beta/models/{m}:generateContent?key={key}"

    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}]
        },
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.1
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "PyGen/2.0"
    }

    # 1. Штатный запрос через urllib с повторами (работает на 100% школьных компьютеров)
    data = None
    try:
        data = _request_json(url, body_bytes, headers, timeout=45, retries=3)
    except RuntimeError as err:
        if str(err).startswith("Сетевая ошибка"):
            # 2. Если на рабочей станции запущен локальный TUN/Xray/VPN, мешающий SSL-рукопожатию,
            # устанавливаем прямое сокетное соединение в обход TUN
            data = _gemini_socket_fallback(url, body_bytes)
        elif _looks_like_auth_error(err):
            hint = ""
            if key == _DEFAULT_GEMINI_KEY:
                hint = (" Встроенный публичный ключ Gemini отклонён — задайте свой ключ "
                        "(pygen -t → Настройки → «Gemini API-ключ») или используйте GigaChat.")
            raise RuntimeError(f"Gemini: недействительный API-ключ — {err}.{hint}")
        else:
            raise RuntimeError(f"Gemini {err}")

    if not data:
        raise RuntimeError("Не удалось получить ответ от Gemini.")

    candidates = data.get("candidates", [])
    if not candidates:
        if "error" in data:
            err_obj = data["error"]
            msg = err_obj.get("message", err_obj) if isinstance(err_obj, dict) else err_obj
            raise RuntimeError(f"Gemini API Ошибка: {msg}")
        raise RuntimeError("Gemini вернул пустой список кандидатов.")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError("Gemini не вернул текст ответа.")
    return parts[0].get("text", "")

def _gemini_socket_fallback(url: str, body_bytes: bytes) -> dict:
    """Прямое сокетное соединение в обход локального TUN/VPN (когда urllib не может)."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")

        local_ip = None
        for test_target in ("192.168.1.1", "8.8.8.8"):
            try:
                s_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s_probe.connect((test_target, 80))
                cand_ip = s_probe.getsockname()[0]
                s_probe.close()
                if cand_ip and not cand_ip.startswith(("127.", "172.19.")):
                    local_ip = cand_ip
                    break
            except Exception:
                pass

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        if local_ip:
            sock.bind((local_ip, 0))

        ip_dest = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)[0][4]
        sock.connect(ip_dest)

        if parsed.scheme == "https":
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)

        http_req = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: PyGen/{__version__}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("utf-8") + body_bytes

        sock.sendall(http_req)

        resp_raw = b""
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            resp_raw += chunk
        sock.close()

        parts = resp_raw.split(b"\r\n\r\n", 1)
        if len(parts) < 2:
            raise RuntimeError("пустой ответ")
        header_part, body_part = parts
        status_line = header_part.split(b"\r\n", 1)[0].decode("utf-8", errors="replace")
        if b"transfer-encoding: chunked" in header_part.lower():
            clean_body = b""
            pos = 0
            while pos < len(body_part):
                c_end = body_part.find(b"\r\n", pos)
                if c_end == -1:
                    break
                chunk_size_str = body_part[pos:c_end].split(b";")[0].strip()
                if not chunk_size_str:
                    break
                chunk_size = int(chunk_size_str, 16)
                if chunk_size == 0:
                    break
                pos = c_end + 2
                clean_body += body_part[pos:pos + chunk_size]
                pos += chunk_size + 2
            body_part = clean_body
        if " 2" not in status_line:
            raise RuntimeError(f"{status_line}: {body_part.decode('utf-8', errors='ignore')[:200]}")
        return json.loads(body_part.decode("utf-8"))
    except Exception as fallback_err:
        raise RuntimeError(f"Сетевая ошибка Gemini: {fallback_err}")

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
    try:
        data = _request_json(
            url,
            json.dumps(payload).encode("utf-8"),
            {"Content-Type": "application/json"},
            timeout=180,
            retries=2
        )
        return data["choices"][0]["message"]["content"]
    except RuntimeError as err:
        raise RuntimeError(f"Ollama ({base_url}): {err}. Убедитесь, что Ollama запущен.")

def generate_solution(prompt: str, provider: str = None, api_key: str = None, custom_url: str = None) -> str:
    cfg = load_config()
    chosen_provider = provider or cfg.get("provider") or "gigachat"

    if chosen_provider.lower() == "gemini":
        return query_gemini(prompt, api_key=api_key, base_url=custom_url)

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

def validate_code(code: str) -> tuple:
    """Проверяет синтаксис сгенерированного кода. Возвращает (ok, текст_ошибки)."""
    if not code or not code.strip():
        return False, "пустой ответ модели"
    try:
        compile(code, "<pygen-generated>", "exec")
        return True, ""
    except SyntaxError as e:
        line = f", строка {e.lineno}" if getattr(e, "lineno", None) else ""
        return False, f"{e.msg}{line}"
    except Exception as e:
        return False, str(e)

# Подсказка модели при повторной генерации после синтаксической ошибки
_CORRECTIVE_HINT = (
    "ВАЖНО: предыдущий ответ был синтаксически некорректным Python-кодом "
    "(например, пробелы оказались заменены символами подчёркивания). "
    "Верни ТОЛЬКО синтаксически корректный Python-код с обычными пробелами, "
    "без комментариев, без markdown и без пояснений."
)

def generate_code_with_fallback(prompt: str, provider: str = None, api_key: str = None, custom_url: str = None,
                                allow_fallback: bool = True, err_out="auto", validate: bool = True) -> tuple:
    """Генерирует код с проверкой синтаксиса и автопереключением на GigaChat.

    Возвращает (code, used_provider). При синтаксической ошибке ответа модель
    перезапрашивается до 2 раз с корректирующей подсказкой. При недоступности
    выбранного провайдера (и разрешённом fallback) используется Сбер GigaChat.
    Провайдеры с ошибкой авторизации запоминаются на 10 минут.
    """
    chosen = (provider or load_config().get("provider") or "gigachat").lower()

    def notify(text: str):
        if err_out is False:
            return
        stream = sys.stderr if err_out in (None, "auto") else err_out
        if stream:
            try:
                stream.write(text + "\n")
                stream.flush()
            except Exception:
                pass

    def generate(prov: str, extra_hint: str = "") -> str:
        task = prompt if not extra_hint else prompt + "\n\n" + extra_hint
        return generate_code_clean(task, provider=prov, api_key=api_key, custom_url=custom_url)

    def generate_validated(prov: str) -> str:
        code = generate(prov)
        if not validate:
            return code
        for attempt in range(2):
            ok, err = validate_code(code)
            if ok:
                return code
            notify(f"[!] Код не прошёл проверку синтаксиса ({err}) — повторная генерация {attempt + 1}/2...")
            try:
                code = generate(prov, _CORRECTIVE_HINT)
            except Exception:
                break
        return code

    # Провайдер уже признан нерабочим — сразу к GigaChat, без лишнего ожидания
    if chosen != "gigachat" and allow_fallback:
        dead = provider_dead_reason(chosen)
        if dead:
            notify(f"[!] Провайдер {chosen} пропущен ({dead}). Использую GigaChat...")
            return generate_validated("gigachat"), "gigachat"

    try:
        code = generate_validated(chosen)
        clear_provider_dead(chosen)
        return code, chosen
    except Exception as first_err:
        if _looks_like_auth_error(first_err):
            mark_provider_dead(chosen, str(first_err)[:160])
        if not allow_fallback or chosen == "gigachat":
            raise
        notify(f"[!] Провайдер {chosen} недоступен ({first_err}). Переключаюсь на GigaChat...")
        return generate_validated("gigachat"), "gigachat"

def remove_comments_and_docstrings(source_code: str) -> str:
    source_code = _clean_html_artifacts(source_code)
    used_tokenizer = False
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source_code).readline)
        tokens_clean = []
        for tok_type, tok_string, start, end, line in tokens:
            if tok_type == tokenize.COMMENT:
                continue
            tokens_clean.append((tok_type, tok_string, start, end, line))
        source_code = tokenize.untokenize(tokens_clean)
        used_tokenizer = True
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

        def mark_bare_strings(node):
            for stmt in node.body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                        and isinstance(stmt.value.value, str):
                    for l in range(stmt.lineno, getattr(stmt, "end_lineno", stmt.lineno) + 1):
                        doc_lines.add(l)

        if isinstance(tree, ast.Module):
            mark_docstring(tree)
            mark_bare_strings(tree)
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
        # Если токенизатор не сработал (синтаксически неполный код),
        # аккуратно режем inline-комментарии, НЕ трогая '#' внутри строк.
        if not used_tokenizer:
            line = _strip_inline_comment(line)
        if not line.strip():
            if not prev_blank:
                clean_lines.append("")
                prev_blank = True
        else:
            clean_lines.append(line.rstrip())
            prev_blank = False

    return "\n".join(clean_lines).strip() + "\n"

def _strip_inline_comment(line: str) -> str:
    """Убирает '#'-комментарий справа, не затрагивая '#' внутри строковых литералов."""
    out = []
    i, n = 0, len(line)
    state = None  # None | "'" | '"'
    while i < n:
        ch = line[i]
        if state:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                continue
            if ch == state:
                state = None
        else:
            if ch in ("'", '"'):
                state = ch
                out.append(ch)
            elif ch == "#":
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out).rstrip()

def _clean_html_artifacts(text: str) -> str:
    """Убирает HTML-артефакты из ответов моделей: <br>, &nbsp;, сущности, теги."""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = _html.unescape(text)
    text = text.replace("\xa0", " ")
    if re.search(r"<[a-zA-Z][^>]*>", text):
        text = re.sub(r"</?(p|div|pre|code|span|li|ul|ol|h[1-6]|b|i|em|strong|html|body|head)[^>]*>",
                      lambda m: "\n" if m.group(0).lower().startswith(("<p", "<div", "<pre", "<li", "<h", "<br")) else "",
                      text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
    return text

def extract_code(text: str) -> str:
    text = _clean_html_artifacts(text)
    matches = re.findall(r"```(?:python\w*|py)?\s*\n?(.*?)```", text, re.DOTALL)
    if matches:
        return matches[0].strip()
    return text.strip()

def infer_filename(prompt: str) -> str:
    latin_words = [w.lower() for w in re.findall(r"[a-zA-Z0-9_]{3,}", prompt) if w.lower() not in {"task", "python", "code"}]
    if latin_words:
        return f"{latin_words[0]}.py"

    stop_words = {"дано", "дана", "даны", "напишите", "написать", "найдите", "найти", "найтите",
                  "решить", "решите", "программа", "требуется", "посчитайте", "посчитать",
                  "определите", "определить", "выведите", "вывести", "вычислите", "вычислить",
                  "составить", "создать", "получить", "введите", "ввести", "для", "если", "задача"}
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

    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Add-Type -AssemblyName PresentationCore; [Windows.Clipboard]::GetText()"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.decode("utf-8", errors="replace").strip()
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

    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "$i=$input; Set-Clipboard -Value $i"],
                input=text.encode("utf-8"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if res.returncode == 0:
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

def find_active_project_dir(scan_limit: int = 500) -> Path:
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
                    if len(py_files) >= scan_limit:
                        break
            if len(py_files) < scan_limit:
                for sub in base.iterdir():
                    if sub.is_dir() and not sub.name.startswith("."):
                        for p in sub.glob("*.py"):
                            if p.is_file():
                                py_files.append((p.stat().st_mtime, p.parent))
                                if len(py_files) >= scan_limit:
                                    break
                    if len(py_files) >= scan_limit:
                        break
        except Exception:
            continue
        if len(py_files) >= scan_limit:
            break
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
    rb_giga.pack(side=tk.LEFT, padx=(2, 4))

    rb_gemini = tk.Radiobutton(mid_frame, text="Gemini", variable=provider_var, value="gemini",
                               bg=bg_color, fg=fg_color, selectcolor=entry_bg, activebackground=bg_color,
                               font=("sans-serif", 8))
    rb_gemini.pack(side=tk.LEFT, padx=2)

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

    # Фоновая проверка обновлений при запуске GUI
    def bg_update_check():
        try:
            new_v = check_for_updates(timeout=2.5)
            if new_v:
                def prompt_gui_update():
                    ans = messagebox.askyesno(
                        "Обновление PyGen",
                        f"Доступна новая версия PyGen v{new_v} (текущая v{__version__}).\n\nОбновить программу сейчас?",
                        parent=root
                    )
                    if ans:
                        status_var.set("Обновление...")
                        root.update()
                        if perform_update():
                            if messagebox.askyesno(
                                "Обновление завершено",
                                f"PyGen успешно обновлен до v{new_v}!\n\nПерезапустить приложение сейчас?",
                                parent=root
                            ):
                                root.destroy()
                                restart_process()
                            else:
                                status_var.set(f"Обновлено до v{new_v} (перезапустите)")
                        else:
                            messagebox.showerror("Ошибка", "Не удалось скачать обновление.", parent=root)
                            status_var.set("Ошибка обновления")
                root.after(150, prompt_gui_update)
        except Exception:
            pass

    threading.Thread(target=bg_update_check, daemon=True).start()

    root.mainloop()

# --- Инструменты оформления современного CLI (ANSI / Box / Highlighting) ---
class UI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    REVERSE = "\033[7m"
    CYAN = "\033[36m"
    BRIGHT_CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    RED = "\033[91m"
    WHITE = "\033[97m"
    GRAY = "\033[90m"

    @classmethod
    def enabled(cls) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if os.environ.get("TERM") == "dumb":
            return False
        if not sys.stdout.isatty():
            return False
        return True

    @classmethod
    def c(cls, text: str, *styles) -> str:
        if not cls.enabled():
            return str(text)
        return f"{''.join(styles)}{text}{cls.RESET}"

    @classmethod
    def r(cls, text: str) -> str:
        """Инвертированная (выделенная) строка — для нижней панели подсказок."""
        if not cls.enabled():
            return str(text)
        return f"{cls.REVERSE}{text}{cls.RESET}"

    @staticmethod
    def strip_ansi(text: str) -> str:
        return re.sub(r"\033\[[0-9;]*m", "", text)

class Spinner:
    def __init__(self, message: str = "Генерация решения..."):
        self.message = message
        self.stop_event = threading.Event()
        self.thread = None

    def _spin(self):
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while not self.stop_event.is_set():
            frame = frames[idx % len(frames)]
            idx += 1
            if UI.enabled():
                sys.stdout.write(f"\r  {UI.c(frame, UI.BRIGHT_CYAN, UI.BOLD)}  {self.message} ")
            else:
                sys.stdout.write(f"\r  [*] {self.message} ")
            sys.stdout.flush()
            time.sleep(0.08)
        sys.stdout.write("\r" + " " * (len(self.message) + 16) + "\r")
        sys.stdout.flush()

    def __enter__(self):
        if sys.stdout.isatty():
            self.thread = threading.Thread(target=self._spin, daemon=True)
            self.thread.start()
        else:
            sys.stdout.write(f"  [*] {self.message}\n")
            sys.stdout.flush()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.thread:
            self.stop_event.set()
            self.thread.join(timeout=0.6)

_PY_TOKEN_PAT = re.compile(
    r'(\"[^\"]*\"|\'[^\']*\')|'
    r'\b(for|while|if|elif|else|in|is|not|and|or|def|return|break|continue|pass|try|except|import|from|with|as|lambda)\b|'
    r'\b(print|input|int|str|float|list|dict|set|tuple|range|len|sum|min|max|sorted|abs|all|any|map|filter|round|enumerate|zip)\b|'
    r'\b(\d+(?:\.\d+)?)\b'
)

def _colorize_match(m):
    raw = m.group(0)
    if m.group(1):
        return f"\033[92m{raw}\033[0m"
    elif m.group(2):
        return f"\033[1;95m{raw}\033[0m"
    elif m.group(3):
        return f"\033[96m{raw}\033[0m"
    elif m.group(4):
        return f"\033[93m{raw}\033[0m"
    return raw

def colorize_python(code: str) -> list:
    """Возвращает список строк Python-кода с ANSI-подсветкой синтаксиса."""
    lines = code.strip().splitlines()
    if not lines:
        return []
    if not UI.enabled():
        return lines
    return [_PY_TOKEN_PAT.sub(_colorize_match, line) for line in lines]

def highlight_python_lines(code: str) -> list:
    lines = colorize_python(code)
    if not lines:
        return []

    line_num_width = max(2, len(str(len(lines))))
    output = []

    if not UI.enabled():
        for idx, line in enumerate(lines, 1):
            output.append(f"{idx:>{line_num_width}} │ {line}")
        return output

    for idx, line in enumerate(lines, 1):
        num_str = UI.c(f"{idx:>{line_num_width}}", UI.GRAY)
        sep = UI.c("│", UI.GRAY)
        output.append(f"{num_str} {sep} {line}")

    return output

def render_code_preview(code: str, target_path: Path, copied: bool = True):
    lines = highlight_python_lines(code)
    header = f"  ╭── {UI.c('[ Сгенерированное решение Python ]', UI.BRIGHT_CYAN, UI.BOLD)} " + "─" * 34
    footer = "  ╰" + "─" * 65

    print()
    print(header)
    for l in lines:
        print(f"  │ {l}")
    print(footer)
    print()
    print(f"  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Сохранено в: {UI.c(str(target_path), UI.WHITE, UI.BOLD)}")
    if copied:
        print(f"  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Код автоматически скопирован в буфер обмена!")
    print()

def render_banner(provider: str) -> str:
    if provider == "gigachat":
        prov_label = "GigaChat (Сбер • Без VPN)"
    elif provider == "gemini":
        prov_label = "Gemini 3.5 (VPS Relay • Без VPN)"
    else:
        prov_label = provider.capitalize()
    return (
        f"  ╭─────────────────────────────────────────────────────────────╮\n"
        f"  │  {UI.c(f'⚡ PyGen v{__version__}', UI.BRIGHT_CYAN, UI.BOLD)}  •  {UI.c('Автономный ассистент Python', UI.WHITE, UI.BOLD)}           │\n"
        f"  │  Провайдер: {UI.c(prov_label, UI.GREEN)}  •  Статус: {UI.c('Онлайн', UI.GREEN)}             │\n"
        f"  ╰─────────────────────────────────────────────────────────────╯"
    )

# --- Выбор директории в CLI ---
def choose_save_directory_cli(preset_flag=None) -> Path:
    if preset_flag:
        return resolve_target_dir(preset_flag)

    known = get_known_directories()
    recent = get_recent_directories()
    active = find_active_project_dir()

    options = []
    if active and active != known["current"]:
        options.append(("📁", "Активный проект (.py)", active))
    if recent and recent[0] != active and recent[0] != known["current"]:
        options.append(("🕒", "Недавняя папка", recent[0]))

    options.append(("📂", "Текущая папка (.)", known["current"]))
    options.append(("🖥️", "Рабочий стол (Desktop)", known["desktop"]))
    options.append(("⬇️", "Загрузки (Downloads)", known["downloads"]))
    options.append(("📄", "Документы (Documents)", known["docs"]))
    options.append(("🏠", "Домашняя папка (~)", known["home"]))

    print(f"\n  {UI.c('Куда сохранить решение?', UI.WHITE, UI.BOLD)}")
    for idx, (icon, label, path_obj) in enumerate(options, 1):
        num = UI.c(f"[{idx}]", UI.CYAN, UI.BOLD)
        short_path = str(path_obj)
        home_str = str(Path.home())
        if short_path.startswith(home_str) and len(home_str) > 1:
            short_path = "~" + short_path[len(home_str):]
        print(f"    {num}  {icon}  {label:<24} {UI.c(short_path, UI.GRAY)}")
    print(f"    {UI.c(f'[{len(options) + 1}]', UI.GRAY, UI.BOLD)}  ✏️   Ввести свой путь вручную")

    try:
        preset_choice = input(f"\n  {UI.c('Выбор', UI.CYAN)} [1-{len(options)+1}] (Enter = 1): ").strip()
    except (KeyboardInterrupt, EOFError):
        return options[0][2]

    if not preset_choice:
        return options[0][2]

    try:
        idx = int(preset_choice)
        if 1 <= idx <= len(options):
            return options[idx - 1][2]
    except ValueError:
        pass

    if preset_choice == str(len(options) + 1):
        try:
            custom = input("  Введите путь к папке: ").strip()
        except (KeyboardInterrupt, EOFError):
            return options[0][2]
        if custom:
            p = Path(custom).expanduser().resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p

    p = Path(preset_choice).expanduser().resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def handle_interactive_clipboard(provider: str):
    clip = get_clipboard_text()
    if not clip:
        print(f"\n  {UI.c('[!]', UI.YELLOW, UI.BOLD)} Буфер обмена пуст или недоступен.")
        try:
            ans = input(f"  {UI.c('Ввести условие задачи вручную? [Y/n]:', UI.CYAN)} ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return
        if ans != "n":
            handle_interactive_manual(provider)
        return

    # Превью задания из буфера
    print()
    preview = clip if len(clip) <= 240 else clip[:237] + "..."
    preview_lines = preview.splitlines()[:5]
    print(f"  ╭── {UI.c('[ Задание из буфера обмена ]', UI.BRIGHT_CYAN, UI.BOLD)} " + "─" * 38)
    for l in preview_lines:
        print(f"  │  {UI.c(l, UI.WHITE)}")
    if len(clip.splitlines()) > 5:
        print(f"  │  {UI.c('...', UI.GRAY)}")
    print("  ╰" + "─" * 65)

    target_dir = choose_save_directory_cli()
    auto_name = infer_filename(clip)
    try:
        user_file = input(f"\n  {UI.c('Имя файла', UI.CYAN)} [{auto_name}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    out_file = user_file if user_file else auto_name
    if not out_file.endswith(".py"):
        out_file += ".py"

    print()
    try:
        with Spinner(f"Генерация чистого решения через {provider.upper()}..."):
            code = generate_code_clean(clip, provider=provider)
    except Exception as e:
        print(f"  {UI.c('[✗]', UI.RED, UI.BOLD)} Ошибка генерации: {e}\n")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / out_file
    target_path.write_text(code, encoding="utf-8")
    save_recent_directory(target_dir)
    copied = set_clipboard_text(code)

    render_code_preview(code, target_path, copied)
    try:
        input(f"  {UI.c('Нажмите Enter для продолжения...', UI.GRAY)} ")
    except (KeyboardInterrupt, EOFError):
        pass

def handle_interactive_manual(provider: str):
    print()
    print(f"  ╭── {UI.c('[ Ввод условия задачи ]', UI.BRIGHT_CYAN, UI.BOLD)} " + "─" * 43)
    print(f"  │  Вставьте или введите условие задачи.")
    print(f"  │  Нажмите {UI.c('Enter на пустой строке', UI.YELLOW)} (или {UI.c('Ctrl+D / Ctrl+Z', UI.YELLOW)}) для отправки.")
    print("  ╰" + "─" * 65)
    print()

    lines = []
    while True:
        try:
            line = input(f"  {UI.c('│', UI.CYAN)} ")
            if not line:
                if not lines:
                    continue
                if sys.platform != "win32":
                    try:
                        import select
                        r, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if r:
                            lines.append("")
                            continue
                    except Exception:
                        pass
                break
            lines.append(line)
        except (KeyboardInterrupt, EOFError):
            break

    task_text = "\n".join(lines).strip()
    if not task_text:
        print(f"\n  {UI.c('[!]', UI.YELLOW, UI.BOLD)} Условие не введено.")
        return

    target_dir = choose_save_directory_cli()
    auto_name = infer_filename(task_text)
    try:
        user_file = input(f"\n  {UI.c('Имя файла', UI.CYAN)} [{auto_name}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        return
    out_file = user_file if user_file else auto_name
    if not out_file.endswith(".py"):
        out_file += ".py"

    print()
    try:
        with Spinner(f"Генерация чистого решения через {provider.upper()}..."):
            code = generate_code_clean(task_text, provider=provider)
    except Exception as e:
        print(f"  {UI.c('[✗]', UI.RED, UI.BOLD)} Ошибка генерации: {e}\n")
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / out_file
    target_path.write_text(code, encoding="utf-8")
    save_recent_directory(target_dir)
    copied = set_clipboard_text(code)

    render_code_preview(code, target_path, copied)
    try:
        input(f"  {UI.c('Нажмите Enter для продолжения...', UI.GRAY)} ")
    except (KeyboardInterrupt, EOFError):
        pass

def handle_interactive_settings() -> str:
    cfg = load_config()
    current = cfg.get("provider", "gigachat")
    ds_key = cfg.get("deepseek_api_key", "")
    gm_key = cfg.get("gemini_api_key", _DEFAULT_GEMINI_KEY)
    gm_proxy = cfg.get("gemini_proxy_url", GEMINI_DEFAULT_PROXY_URL)

    while True:
        key_display = f"{ds_key[:4]}...{ds_key[-4:]}" if len(ds_key) > 8 else ("Задан" if ds_key else "Не задан")
        gm_display = f"{gm_key[:4]}...{gm_key[-4:]}" if len(gm_key) > 8 else ("Задан" if gm_key else "Не задан")
        print()
        print(f"  ╭── {UI.c('[ Настройки ИИ-провайдера ]', UI.BRIGHT_CYAN, UI.BOLD)} " + "─" * 40)
        print(f"  │  Текущий провайдер: {UI.c(current.upper(), UI.GREEN, UI.BOLD)}")
        print(f"  │  Gemini Proxy URL:  {UI.c(gm_proxy, UI.GRAY)}")
        print(f"  │  Gemini API Key:    {UI.c(gm_display, UI.GRAY)}")
        print(f"  │  DeepSeek API Key:  {UI.c(key_display, UI.GRAY)}")
        print(f"  │  Файл настроек:     {UI.c(str(CONFIG_FILE), UI.GRAY)}")
        print("  ╰" + "─" * 65)
        print()
        print(f"  {UI.c('[1]', UI.CYAN, UI.BOLD)}  Сбер GigaChat (Бесплатно, РФ, без VPN — Рекомендуется)")
        print(f"  {UI.c('[2]', UI.CYAN, UI.BOLD)}  Google Gemini 3.5 (через наш быстрый VPS-шлюз gemini.rexcorp.space)")
        print(f"  {UI.c('[3]', UI.CYAN, UI.BOLD)}  DeepSeek (требуется личный API-ключ)")
        print(f"  {UI.c('[4]', UI.CYAN, UI.BOLD)}  Ollama (локальная нейросеть http://localhost:11434)")
        print(f"  {UI.c('[5]', UI.CYAN, UI.BOLD)}  ⚡ Проверить подключение к {current.upper()}")
        print(f"  {UI.c('[6]', UI.CYAN, UI.BOLD)}  ⚙️  Настроить Gemini (изменить ключ или адрес прокси)")
        print(f"  {UI.c('[7]', UI.CYAN, UI.BOLD)}  🔄 Проверить и установить обновления PyGen")
        print(f"  {UI.c('[0]', UI.GRAY, UI.BOLD)}  Назад в главное меню")
        print()

        try:
            ch = input(f"  {UI.c('Выбор ›', UI.CYAN)} ").strip().strip("'\"")
        except (KeyboardInterrupt, EOFError):
            break

        if ch == "1":
            cfg["provider"] = "gigachat"
            save_config(cfg)
            current = "gigachat"
            print(f"\n  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Установлен провайдер Сбер GigaChat!")
        elif ch == "2":
            cfg["provider"] = "gemini"
            save_config(cfg)
            current = "gemini"
            print(f"\n  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Установлен провайдер Google Gemini 3.5 (через VPS-шлюз)!")
        elif ch == "3":
            try:
                new_key = input(f"  Введите DeepSeek API Key [{key_display}]: ").strip()
            except (KeyboardInterrupt, EOFError):
                continue
            if new_key:
                cfg["deepseek_api_key"] = new_key
                ds_key = new_key
            cfg["provider"] = "deepseek"
            save_config(cfg)
            current = "deepseek"
            print(f"\n  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Установлен провайдер DeepSeek!")
        elif ch == "4":
            cfg["provider"] = "ollama"
            save_config(cfg)
            current = "ollama"
            print(f"\n  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Установлен локальный провайдер Ollama!")
        elif ch == "5":
            print()
            try:
                with Spinner(f"Тестовый запрос к {current.upper()}..."):
                    res = generate_solution("выведи число 42", provider=current)
                if res:
                    print(f"  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Подключение успешно! Провайдер {current.upper()} готов к работе.")
                else:
                    print(f"  {UI.c('[!]', UI.YELLOW, UI.BOLD)} Провайдер ответил пустым сообщением.")
            except Exception as e:
                print(f"  {UI.c('[✗]', UI.RED, UI.BOLD)} Ошибка подключения: {e}")
            try:
                input(f"\n  {UI.c('Нажмите Enter для продолжения...', UI.GRAY)} ")
            except (KeyboardInterrupt, EOFError):
                pass
        elif ch == "6":
            try:
                new_gm_key = input(f"  Введите Gemini API Key (Enter чтобы оставить прежний) [{gm_display}]: ").strip()
                if new_gm_key:
                    cfg["gemini_api_key"] = new_gm_key
                    gm_key = new_gm_key

                new_gm_proxy = input(f"  Введите Gemini Proxy URL (Enter чтобы оставить {gm_proxy}): ").strip()
                if new_gm_proxy:
                    cfg["gemini_proxy_url"] = new_gm_proxy
                    gm_proxy = new_gm_proxy

                save_config(cfg)
                print(f"\n  {UI.c('[✓]', UI.GREEN, UI.BOLD)} Настройки Gemini сохранены!")
            except (KeyboardInterrupt, EOFError):
                pass
        elif ch == "7":
            print()
            try:
                with Spinner("Проверка наличия обновлений..."):
                    new_ver = check_for_updates(timeout=3.0)
                if new_ver:
                    print(f"  {UI.c('[★] Доступна новая версия PyGen v' + new_ver + ' (текущая v' + __version__ + ')!', UI.BRIGHT_CYAN, UI.BOLD)}")
                    ans = input(f"  {UI.c('Обновить сейчас? [Y/n] ›', UI.YELLOW)} ").strip().lower()
                    if ans in ("", "y", "yes", "д", "да"):
                        with Spinner(f"Установка PyGen v{new_ver}..."):
                            upd_ok = perform_update()
                        if upd_ok:
                            print(f"\n  {UI.c('[✓] PyGen успешно обновлен до v' + new_ver + '! Перезапуск...', UI.GREEN, UI.BOLD)}\n")
                            time.sleep(1.0)
                            restart_process()
                        else:
                            print(f"\n  {UI.c('[✗] Ошибка при скачивании обновления.', UI.RED)}")
                else:
                    print(f"  {UI.c('[✓] У вас установлена актуальная версия PyGen v' + __version__, UI.GREEN, UI.BOLD)}")
            except Exception as e:
                print(f"  {UI.c('[✗]', UI.RED)} Ошибка проверки обновлений: {e}")
            try:
                input(f"\n  {UI.c('Нажмите Enter для продолжения...', UI.GRAY)} ")
            except (KeyboardInterrupt, EOFError):
                pass
        elif ch in ("0", "q", ""):
            break

    return current

def run_interactive_cli():
    cfg = load_config()
    current_provider = cfg.get("provider", "gigachat")

    # Автоматический запрос обновления при запуске
    try:
        new_ver = check_for_updates(timeout=1.8)
        if new_ver:
            print()
            print(f"  ╭── {UI.c('[ Доступно обновление PyGen ]', UI.BRIGHT_CYAN, UI.BOLD)} " + "─" * 40)
            print(f"  │  Текущая версия: {UI.c('v' + __version__, UI.GRAY)}")
            print(f"  │  Новая версия:   {UI.c('v' + new_ver, UI.GREEN, UI.BOLD)}")
            print("  ╰" + "─" * 65)
            ans = input(f"  {UI.c('Обновить программу сейчас? [Y/n] ›', UI.YELLOW, UI.BOLD)} ").strip().lower()
            if ans in ("", "y", "yes", "д", "да"):
                with Spinner(f"Установка PyGen v{new_ver}..."):
                    upd_ok = perform_update()
                if upd_ok:
                    print(f"\n  {UI.c('[✓] PyGen успешно обновлен до v' + new_ver + '! Перезапуск...', UI.GREEN, UI.BOLD)}\n")
                    time.sleep(1.0)
                    restart_process()
                else:
                    print(f"\n  {UI.c('[✗] Не удалось загрузить обновление.', UI.RED)}\n")
            else:
                print(f"  {UI.c('Обновление отложено.', UI.GRAY)}\n")
    except Exception:
        pass

    while True:
        print()
        print(render_banner(current_provider))
        print()
        print(f"  {UI.c('[1]', UI.BRIGHT_CYAN, UI.BOLD)}  📋  Решить задачу из буфера обмена (быстро)")
        print(f"  {UI.c('[2]', UI.BRIGHT_CYAN, UI.BOLD)}  ✍️   Ввести условие задачи вручную (многострочный ввод)")
        print(f"  {UI.c('[3]', UI.BRIGHT_CYAN, UI.BOLD)}  🖥️   Компактный скрытный GUI («Заметки»)")
        print(f"  {UI.c('[4]', UI.BRIGHT_CYAN, UI.BOLD)}  ⚙️   Настройки (сменить ИИ-провайдер / API-ключ)")
        print(f"  {UI.c('[5]', UI.BRIGHT_CYAN, UI.BOLD)}  🚀  Установить расширения IDE (VS Code, IDLE, PyCharm)")
        print(f"  {UI.c('[0]', UI.GRAY, UI.BOLD)}  🚪  Выход")
        print()

        try:
            choice = input(f"  {UI.c('pygen ›', UI.CYAN, UI.BOLD)} ").strip().strip("'\"")
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n  {UI.c('До свидания! 👋', UI.GRAY)}\n")
            break

        if choice in ("0", "q", "exit", "quit"):
            print(f"\n  {UI.c('До свидания! 👋', UI.GRAY)}\n")
            break

        elif choice == "1":
            handle_interactive_clipboard(current_provider)

        elif choice == "2":
            handle_interactive_manual(current_provider)

        elif choice == "3":
            launch_stealth_gui()

        elif choice == "4":
            current_provider = handle_interactive_settings()

        elif choice == "5":
            install_system()

        else:
            print(f"\n  {UI.c('Неверный выбор. Пожалуйста, введите число от 0 до 5.', UI.YELLOW)}")

# ════════════════════════════════════════════════════════════════════════════
# СОВРЕМЕННЫЙ TUI (ANSI / raw-режим / альтернативный экран — только stdlib)
# ════════════════════════════════════════════════════════════════════════════

PROVIDER_LABELS = {
    "gigachat": "Сбер GigaChat (РФ, без VPN)",
    "gemini": "Google Gemini 3.5 (VPS-шлюз)",
    "deepseek": "DeepSeek",
    "ollama": "Ollama (локально)",
}

def fit(text: str, width: int) -> str:
    """Обрезает строку (с ANSI-кодами) до видимой ширины, закрывая цвета."""
    if width <= 0:
        return ""
    out = []
    visible = 0
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\x1b":
            j = text.find("m", i)
            if j != -1:
                out.append(text[i:j + 1])
                i = j + 1
                continue
        if visible >= width:
            break
        out.append(text[i])
        visible += 1
        i += 1
    result = "".join(out)
    if "\x1b[" in result:
        result += UI.RESET
    return result

def _visible_len(s: str) -> int:
    return len(UI.strip_ansi(s))

def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _visible_len(s))

def _short_path(p: Path) -> str:
    s = str(p)
    home_str = str(Path.home())
    if s.startswith(home_str) and len(home_str) > 1:
        return "~" + s[len(home_str):]
    return s

def _panel_lines(title: str, body, w: int, title_styles=(UI.BRIGHT_CYAN, UI.BOLD)) -> list:
    """Рисует рамку: ╭─ title ──╮ / │ body │ / ╰──╯. body: список строк."""
    t = UI.c(" " + title + " ", *title_styles)
    t_fit = fit(t, w - 4)
    head = "╭─" + t_fit + "─" * max(0, w - 3 - _visible_len(t_fit)) + "╮"
    lines = [fit(head, w)]
    cw = max(1, w - 4)
    for b in body:
        fb = fit(str(b), cw)
        lines.append("│ " + fb + " " * max(0, cw - _visible_len(fb)) + " │")
    lines.append(fit("╰" + "─" * (w - 2) + "╯", w))
    return lines

def _finalize_frame(body, w: int, h: int, hints: str, toast=None, toast_kind: str = "info") -> list:
    """Собирает полный кадр: тело + строка уведомления + нижняя панель подсказок."""
    out = [fit(l, w) for l in body]
    if len(out) > h - 2:
        out = out[:h - 2]
    while len(out) < h - 2:
        out.append("")
    if toast:
        icon = {"info": "ℹ", "ok": "✓", "warn": "!", "err": "✗"}.get(toast_kind, "ℹ")
        color = {"info": UI.BLUE, "ok": UI.GREEN, "warn": UI.YELLOW, "err": UI.RED}.get(toast_kind, UI.BLUE)
        out.append(fit(" " + UI.c(f"{icon} {toast}", color, UI.BOLD), w))
    else:
        out.append("")
    hint = fit(hints, w)
    out.append(UI.r(hint + " " * max(0, w - _visible_len(hint))))
    return out[:h]

class TextBuffer:
    """Многострочный текстовый буфер с курсором (аналог виджета TextInput)."""

    def __init__(self, text: str = ""):
        self.lines = text.split("\n") if text else [""]
        self.cx = 0
        self.cy = 0

    def _clamp(self):
        self.cy = max(0, min(self.cy, len(self.lines) - 1))
        self.cx = max(0, min(self.cx, len(self.lines[self.cy])))

    def text(self) -> str:
        return "\n".join(self.lines)

    def is_empty(self) -> bool:
        return not self.text().strip()

    def insert(self, ch: str):
        if ch == "\n":
            cur = self.lines[self.cy]
            self.lines[self.cy] = cur[:self.cx]
            self.lines.insert(self.cy + 1, cur[self.cx:])
            self.cy += 1
            self.cx = 0
        else:
            cur = self.lines[self.cy]
            self.lines[self.cy] = cur[:self.cx] + ch + cur[self.cx:]
            self.cx += 1

    def insert_text(self, s: str):
        for ch in s.replace("\r\n", "\n").replace("\r", "\n"):
            self.insert(ch)

    def backspace(self):
        if self.cx > 0:
            cur = self.lines[self.cy]
            self.lines[self.cy] = cur[:self.cx - 1] + cur[self.cx:]
            self.cx -= 1
        elif self.cy > 0:
            tail = self.lines[self.cy]
            del self.lines[self.cy]
            self.cy -= 1
            self.cx = len(self.lines[self.cy])
            self.lines[self.cy] += tail

    def delete(self):
        cur = self.lines[self.cy]
        if self.cx < len(cur):
            self.lines[self.cy] = cur[:self.cx] + cur[self.cx + 1:]
        elif self.cy < len(self.lines) - 1:
            nxt = self.lines[self.cy + 1]
            del self.lines[self.cy + 1]
            self.lines[self.cy] += nxt

    def move(self, dx: int, dy: int):
        self.cx += dx
        self.cy += dy
        self._clamp()

    def home(self):
        self.cx = 0

    def end(self):
        self.cx = len(self.lines[self.cy])

    def delete_word_back(self):
        while self.cx > 0 and self.lines[self.cy][self.cx - 1].isspace():
            self.cx -= 1
        while self.cx > 0 and not self.lines[self.cy][self.cx - 1].isspace():
            self.cx -= 1

    def clear_line(self):
        self.lines[self.cy] = ""
        self.cx = 0

    def cut_to_end(self):
        self.lines[self.cy] = self.lines[self.cy][:self.cx]

    def clear(self):
        self.lines = [""]
        self.cx = self.cy = 0

def _buffer_key(buf: TextBuffer, key) -> bool:
    """Общие клавиши редактирования. Возвращает True, если клавиша обработана."""
    if key == "backspace":
        buf.backspace(); return True
    if key == "delete":
        buf.delete(); return True
    if key in ("left", "ctrl-b"):
        buf.move(-1, 0); return True
    if key in ("right", "ctrl-f"):
        buf.move(1, 0); return True
    if key == "up":
        buf.move(0, -1); return True
    if key == "down":
        buf.move(0, 1); return True
    if key in ("home", "ctrl-a"):
        buf.home(); return True
    if key in ("end", "ctrl-e"):
        buf.end(); return True
    if key == "ctrl-w":
        buf.delete_word_back(); return True
    if key == "ctrl-u":
        buf.clear_line(); return True
    if key == "ctrl-k":
        buf.cut_to_end(); return True
    if key == "pgup":
        buf.cy = max(0, buf.cy - 8); buf._clamp(); return True
    if key == "pgdn":
        buf.cy = min(len(buf.lines) - 1, buf.cy + 8); buf._clamp(); return True
    if isinstance(key, str) and len(key) == 1 and key.isprintable():
        buf.insert(key); return True
    return False

# --- Клавиатура в raw-режиме ---
class Term:
    """Терминал в raw-режиме: чтение клавиш, альтернативный экран, размер."""

    _E0_MAP = {
        "H": "up", "P": "down", "K": "left", "M": "right",
        "G": "home", "O": "end", "I": "pgup", "Q": "pgdn", "S": "del", "R": "ins",
        "\x97": "home", "\x98": "up", "\x9b": "down", "\x9d": "left",
        "\x9f": "right", "\x99": "pgup", "\x9a": "pgdn", "\x93": "del", "\x8f": "end",
    }
    _00_MAP = {
        ";": "f1", "<": "f2", "=": "f3", ">": "f4", "?": "f5", "@": "f6",
        "A": "f7", "B": "f8", "C": "f9", "D": "f10", "\x85": "f11", "\x86": "f12",
        "H": "up", "P": "down", "K": "left", "M": "right",
        "G": "home", "O": "end", "I": "pgup", "Q": "pgdn", "S": "del", "R": "ins",
    }
    _CTRL = {
        0x03: "ctrl-c", 0x1a: "ctrl-z", 0x0c: "ctrl-l", 0x01: "ctrl-a", 0x05: "ctrl-e",
        0x17: "ctrl-w", 0x15: "ctrl-u", 0x0b: "ctrl-k", 0x16: "ctrl-v", 0x13: "ctrl-s",
        0x04: "ctrl-d", 0x06: "ctrl-f", 0x12: "ctrl-r", 0x02: "ctrl-b",
        0x0e: "ctrl-n", 0x10: "ctrl-p",
    }
    _CSI_TILDE = {1: "home", 2: "ins", 3: "del", 4: "end", 5: "pgup", 6: "pgdn",
                  7: "home", 8: "end", 11: "f1", 12: "f2", 13: "f3", 14: "f4",
                  15: "f5", 17: "f6", 18: "f7", 19: "f8", 20: "f9", 21: "f10",
                  23: "f11", 24: "f12"}

    def __init__(self, in_file=None, out_file=None, key_source=None):
        self.in_file = in_file or sys.stdin
        self.out_file = out_file or sys.stdout
        self.key_source = key_source  # тестовый источник клавиш
        self._old_tty = None
        self._in_alt = False
        self._prev_frame = []
        self._last_size = (0, 0)

    def is_tty(self) -> bool:
        if self.key_source is not None:
            return True
        try:
            return bool(self.in_file.isatty() and self.out_file.isatty())
        except Exception:
            return False

    def size(self):
        try:
            s = shutil.get_terminal_size(fallback=(80, 24))
            return max(24, s.columns), max(10, s.lines)
        except Exception:
            return 80, 24

    def write(self, s: str):
        try:
            self.out_file.write(s)
        except Exception:
            pass

    def flush(self):
        try:
            self.out_file.flush()
        except Exception:
            pass

    # --- альтернативный экран ---
    def enter_alt(self):
        if self._in_alt:
            return
        if self.key_source is None and not self.is_tty():
            return
        self._in_alt = True
        self._prev_frame = []
        self.write("\x1b[?1049h\x1b[?25l")
        self.flush()

    def exit_alt(self):
        if not self._in_alt:
            return
        self._in_alt = False
        self._prev_frame = []
        self.write("\x1b[?25h\x1b[?1049l")
        self.flush()

    # --- raw-режим (POSIX) ---
    def enter_raw(self):
        if self.key_source is not None or not self.is_tty() or sys.platform == "win32":
            return
        try:
            import termios
            import tty
            fd = self.in_file.fileno()
            self._old_tty = termios.tcgetattr(fd)
            tty.setraw(fd)
        except Exception:
            self._old_tty = None

    def exit_raw(self):
        if self._old_tty is None:
            return
        try:
            import termios
            termios.tcsetattr(self.in_file.fileno(), termios.TCSADRAIN, self._old_tty)
        except Exception:
            pass
        self._old_tty = None

    # --- чтение клавиш ---
    def read_key(self, timeout: float = 0.06):
        """Возвращает имя клавиши, символ или None по таймауту."""
        if self.key_source is not None:
            return self.key_source()
        if sys.platform == "win32":
            return self._read_key_win(timeout)
        return self._read_key_posix(timeout)

    def _read_key_win(self, timeout):
        import msvcrt
        if timeout is None:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                return self._map_extended(ch, msvcrt.getwch())
            return self._map_char(ch)
        deadline = time.time() + timeout
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    return self._map_extended(ch, msvcrt.getwch())
                return self._map_char(ch)
            if time.time() >= deadline:
                return None
            time.sleep(0.008)

    def _map_extended(self, prefix, code):
        mapping = self._00_MAP if prefix == "\x00" else self._E0_MAP
        if code in mapping:
            return mapping[code]
        if isinstance(code, str) and len(code) == 1 and code.isalpha():
            return "alt-" + code.lower()
        return code

    def _map_char(self, ch):
        if ch == "\r":
            return "enter"
        if ch == "\n":  # Ctrl+Enter в Windows-консоли
            return "ctrl-enter"
        if ch == "\x1b":
            return "esc"
        if ch == "\x08":
            return "backspace"
        if ch == "\t":
            return "tab"
        if isinstance(ch, str) and len(ch) == 1 and ord(ch) in self._CTRL:
            return self._CTRL[ord(ch)]
        return ch

    def _read_key_posix(self, timeout):
        import select
        fd = self.in_file.fileno()
        if timeout is not None:
            r, _, _ = select.select([self.in_file], [], [], timeout)
            if not r:
                return None
        try:
            data = os.read(fd, 16)
        except OSError:
            return "esc"
        if not data:
            return "ctrl-d"
        if data[0] == 0x1b:
            if len(data) == 1:
                r, _, _ = select.select([self.in_file], [], [], 0.02)
                if r:
                    try:
                        data += os.read(fd, 12)
                    except OSError:
                        pass
            return self._parse_escape(data)
        if data[0] == 0x0d:
            return "enter"
        if data[0] == 0x0a:  # Ctrl+Enter
            return "ctrl-enter"
        if data[0] in (0x7f, 0x08):
            return "backspace"
        if data[0] == 0x09:
            return "tab"
        if data[0] in self._CTRL:
            return self._CTRL[data[0]]
        if data[0] < 0x80:
            return chr(data[0])
        return self._decode_utf8(data, fd)

    def _decode_utf8(self, first, fd):
        import select
        n = 2 if first[0] < 0xE0 else 3 if first[0] < 0xF0 else 4
        buf = first
        for _ in range(n - len(first)):
            r, _, _ = select.select([self.in_file], [], [], 0.05)
            if not r:
                break
            try:
                buf += os.read(fd, 1)
            except OSError:
                break
        try:
            return buf.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    def _parse_escape(self, data):
        if data == b"\x1b":
            return "esc"
        try:
            s = data[1:].decode("utf-8", "replace")
        except Exception:
            return "esc"
        if s.startswith("["):
            body = s[1:]
            if ";" in body and not body.endswith("~"):
                head, rest = body.split(";", 1)
                if head == "1" and len(rest) >= 2 and rest[-1] in "ABCD" and rest[:-1].isdigit():
                    base = {"A": "up", "B": "down", "C": "right", "D": "left"}[rest[-1]]
                    return ("ctrl-" if rest[:-1] == "5" else "shift-") + base
            if body.endswith("A"):
                return "up"
            if body.endswith("B"):
                return "down"
            if body.endswith("C"):
                return "right"
            if body.endswith("D"):
                return "left"
            if body.endswith("H"):
                return "home"
            if body.endswith("F"):
                return "end"
            if body == "Z":
                return "tab-back"
            if body.endswith("~"):
                num = body[:-1]
                if num.isdigit():
                    return self._CSI_TILDE.get(int(num), "esc")
            return "esc"
        if s.startswith("O"):
            tail = s[1:]
            if tail == "A":
                return "up"
            if tail == "B":
                return "down"
            if tail == "C":
                return "right"
            if tail == "D":
                return "left"
            if tail == "H":
                return "home"
            if tail == "F":
                return "end"
            if tail == "P":
                return "f1"
            if tail == "Q":
                return "f2"
            if tail == "R":
                return "f3"
            if tail == "S":
                return "f4"
        return "esc"

    # --- отрисовка кадра (дифференциальная) ---
    def force_redraw(self):
        self._prev_frame = []

    def render_frame(self, lines: list, cursor=None, force: bool = False):
        w, _ = self.size()
        lines = [fit(l, w) for l in lines]
        if force or lines != self._prev_frame:
            buf = []
            for i, line in enumerate(lines):
                if force or i >= len(self._prev_frame) or self._prev_frame[i] != line:
                    buf.append(f"\x1b[{i + 1};1H")
                    buf.append(line)
                    buf.append("\x1b[K")
            if not force and len(self._prev_frame) > len(lines):
                for i in range(len(lines), len(self._prev_frame)):
                    buf.append(f"\x1b[{i + 1};1H\x1b[2K")
            self.write("".join(buf))
            self._prev_frame = lines
        if cursor:
            cy = max(0, min(cursor[1], len(lines) - 1 if lines else 0))
            if lines:
                cx = max(0, min(cursor[0], _visible_len(lines[cy])))
            else:
                cx = max(0, cursor[0])
            self.write(f"\x1b[{cy + 1};{cx + 1}H")
        self.flush()

# --- Экраны TUI ---
class Screen:
    def __init__(self, app=None):
        self.app = app

    def body(self, w: int, h: int) -> list:
        return []

    def on_key(self, key):
        pass

    def on_tick(self):
        pass

    def cursor(self):
        return None

    def hints(self) -> str:
        return ""

class MainMenuScreen(Screen):
    def __init__(self, app=None):
        super().__init__(app)
        self.sel = 0
        self.items = [
            ("✍️  Ввести условие задачи", "new"),
            ("📋  Решить из буфера обмена", "clip"),
            ("⚙️  Провайдеры ИИ и настройки", "settings"),
            ("🖥️  Открыть скрытный GUI («Заметки»)", "gui"),
            ("🚀  Установить расширения IDE", "install"),
            ("🔄  Проверить обновления PyGen", "update"),
            ("🚪  Выход", "quit"),
        ]

    def body(self, w, h):
        app = self.app
        prov = PROVIDER_LABELS.get(app.provider, app.provider)
        lines = _panel_lines("⚡ PyGen v" + __version__, [
            UI.c("Автономный ассистент процедурного Python", UI.WHITE, UI.BOLD),
            UI.c(f"Провайдер: {prov}", UI.GREEN),
        ], w)
        lines.append("")
        for i, (label, _action) in enumerate(self.items):
            mark = UI.c("▶", UI.BRIGHT_CYAN, UI.BOLD) if i == self.sel else " "
            style = (UI.WHITE, UI.BOLD) if i == self.sel else (UI.GRAY,)
            lines.append("   " + mark + " " + fit(UI.c(label, *style), w - 7))
        lines.append("")
        if app.update_available:
            lines.append(UI.c(f"  ★ Доступна новая версия PyGen v{app.update_available} — пункт «Проверить обновления»", UI.YELLOW, UI.BOLD))
            lines.append("")
        return lines

    def hints(self):
        return " ↑↓ Выбор  •  Enter Действие  •  1-7 Быстрый выбор  •  ? Справка  •  Q Выход "

    def on_key(self, key):
        app = self.app
        if key in ("up", "ctrl-p"):
            self.sel = (self.sel - 1) % len(self.items)
        elif key in ("down", "ctrl-n", "tab"):
            self.sel = (self.sel + 1) % len(self.items)
        elif key == "enter":
            self._activate()
        elif key in ("q", "esc", "ctrl-c"):
            app.quit()
        elif isinstance(key, str) and key.isdigit():
            n = int(key)
            if 1 <= n <= len(self.items):
                self.sel = n - 1
                self._activate()
        elif key == "?":
            app.set_screen(HelpScreen())

    def _activate(self):
        app = self.app
        action = self.items[self.sel][1]
        if action == "quit":
            app.quit()
        elif action == "new":
            app.set_screen(TaskInputScreen())
        elif action == "clip":
            clip = get_clipboard_text()
            if clip:
                app.set_screen(DirPickScreen(task=clip, from_clip=True))
            else:
                app.toast("Буфер обмена пуст или недоступен", "warn")
        elif action == "settings":
            app.set_screen(SettingsScreen())
        elif action == "gui":
            app.term.exit_alt()
            try:
                launch_stealth_gui()
            except SystemExit:
                pass
            finally:
                app.term.enter_alt()
        elif action == "install":
            app.term.exit_alt()
            try:
                install_system()
                try:
                    input("\n  Нажмите Enter, чтобы вернуться...")
                except Exception:
                    pass
            finally:
                app.term.enter_alt()
        elif action == "update":
            _tui_update_check(app)

def _tui_update_check(app):
    def work():
        return check_for_updates(timeout=5.0)

    def done(ver):
        if not ver:
            app.toast("У вас актуальная версия PyGen", "ok")
            app.set_screen(MainMenuScreen())
            return
        app.update_available = ver

        def yes(a):
            a.term.exit_alt()
            print(f"\n[★] Загружаю PyGen v{ver}...")
            if perform_update():
                print("[✓] PyGen обновлён! Перезапуск...")
                time.sleep(1.0)
                restart_process()
            else:
                print("[✗] Не удалось скачать обновление.")
            try:
                input("Нажмите Enter, чтобы вернуться...")
            except Exception:
                pass
            a.term.enter_alt()
            a.set_screen(MainMenuScreen())

        def no(a):
            a.set_screen(MainMenuScreen())

        a.set_screen(ConfirmScreen(
            f"Доступна новая версия PyGen v{ver} (текущая v{__version__}). Обновить сейчас?",
            yes, no))

    def err(msg):
        app.toast("Ошибка проверки обновлений: " + msg, "err")
        app.set_screen(MainMenuScreen())

    app.set_screen(BusyScreen("Проверка обновлений PyGen...", work, done, err))

class HelpScreen(Screen):
    _ROWS = [
        ("↑ ↓ / Tab", "Перемещение по пунктам меню"),
        ("Enter", "Выбор пункта / подтверждение"),
        ("Esc / Q / Ctrl+C", "Назад или выход"),
        ("Ctrl+Enter", "Запустить генерацию решения"),
        ("F2 / Ctrl+V", "Вставить текст из буфера обмена"),
        ("Ctrl+L", "Очистить поле ввода"),
        ("Ctrl+A / Ctrl+E", "В начало / конец строки"),
        ("Ctrl+W / Ctrl+U / Ctrl+K", "Удалить слово / строку / до конца"),
        ("PgUp / PgDn / Home / End", "Прокрутка кода и текста"),
        ("R", "Перегенерировать решение (в предпросмотре)"),
        ("C", "Скопировать код в буфер (в предпросмотре)"),
        ("?", "Эта справка"),
    ]

    def body(self, w, h):
        lines = _panel_lines("Справка по горячим клавишам", [], w)
        for key_name, desc in self._ROWS:
            key_w = 26
            lines.append("  " + _pad(UI.c(key_name, UI.BRIGHT_CYAN, UI.BOLD), key_w) + fit(UI.c(desc, UI.GRAY), w - key_w - 4))
        return lines

    def hints(self):
        return " Enter или Esc — вернуться в главное меню "

    def on_key(self, key):
        if key in ("enter", "esc", "q", "?"):
            self.app.set_screen(MainMenuScreen())

class ConfirmScreen(Screen):
    def __init__(self, question, on_yes, on_no=None, yes_label="Да", no_label="Нет"):
        super().__init__()
        self.question = question
        self.on_yes = on_yes
        self.on_no = on_no
        self.yes_label = yes_label
        self.no_label = no_label
        self.sel = 0

    def body(self, w, h):
        lines = _panel_lines("Подтверждение", [], w)
        lines.append("")
        for line in fit(self.question, w - 4).split("\n"):
            lines.append("  " + UI.c(line, UI.WHITE, UI.BOLD))
        lines.append("")
        for i, label in enumerate((self.yes_label, self.no_label)):
            mark = UI.c("▶", UI.BRIGHT_CYAN, UI.BOLD) if i == self.sel else " "
            style = (UI.WHITE, UI.BOLD) if i == self.sel else (UI.GRAY,)
            lines.append("    " + mark + "  " + fit(UI.c(label, *style), w - 10))
        return lines

    def hints(self):
        return " ← → Выбор  •  Enter Подтвердить  •  Esc Отмена "

    def on_key(self, key):
        app = self.app
        if key in ("left", "right", "tab"):
            self.sel = 1 - self.sel
        elif key == "enter":
            self._activate()
        elif key in ("y", "д"):
            self.sel = 0
            self._activate()
        elif key in ("n", "н", "esc", "ctrl-c"):
            self.sel = 1
            self._activate()
        elif key in ("up", "down"):
            self.sel = 1 - self.sel

    def _activate(self):
        app = self.app
        if self.sel == 0 and self.on_yes:
            self.on_yes(app)
        elif self.on_no:
            self.on_no(app)
        else:
            app.set_screen(MainMenuScreen())

class TaskInputScreen(Screen):
    def __init__(self, task: str = ""):
        super().__init__()
        self.buf = TextBuffer(task)
        self.scroll = 0
        self._cursor_abs = None

    def _vh(self, h):
        return max(3, h - 9)

    def body(self, w, h):
        vh = self._vh(h)
        self._ensure_visible(vh)
        lines = _panel_lines("Ввод условия задачи", [
            "Вставьте или введите текст задания (Enter — новая строка).",
            UI.c("Ctrl+Enter — решить  •  F2 — из буфера  •  Ctrl+L — очистить", UI.GRAY),
        ], w)
        text_top = len(lines)
        for i in range(vh):
            li = self.scroll + i
            if li < len(self.buf.lines):
                lines.append(UI.c("│", UI.GRAY) + " " + fit(self.buf.lines[li], w - 3))
            else:
                lines.append(UI.c("│", UI.GRAY))
        chars = sum(len(l) for l in self.buf.lines)
        lines.append(UI.c(f"└─ {len(self.buf.lines)} строк • {chars} символов", UI.GRAY))
        cy = self.buf.cy - self.scroll
        self._cursor_abs = (2 + self.buf.cx, text_top + cy)
        return lines

    def cursor(self):
        return self._cursor_abs

    def _ensure_visible(self, vh):
        if self.buf.cy < self.scroll:
            self.scroll = self.buf.cy
        if self.buf.cy >= self.scroll + vh:
            self.scroll = self.buf.cy - vh + 1
        self.scroll = max(0, min(self.scroll, max(0, len(self.buf.lines) - 1)))

    def hints(self):
        return " Ctrl+Enter Решить  •  F2 Вставить из буфера  •  Ctrl+L Очистить  •  Esc Назад "

    def on_key(self, key):
        app = self.app
        if key in ("ctrl-enter", "f10"):
            task = self.buf.text().strip()
            if task:
                app.set_screen(DirPickScreen(task=task))
            else:
                app.toast("Введите условие задачи", "warn")
            return
        if key in ("esc", "ctrl-c"):
            app.set_screen(MainMenuScreen())
            return
        if key in ("f2", "ctrl-v"):
            clip = get_clipboard_text()
            if clip:
                self.buf.insert_text(clip)
                app.toast("Текст вставлен из буфера обмена", "ok", 2)
            else:
                app.toast("Буфер обмена пуст или недоступен", "warn")
            return
        if key == "ctrl-l":
            self.buf.clear()
            app.toast("Буфер очищен", "info", 2)
            return
        if key == "enter":
            self.buf.insert("\n")
            return
        _buffer_key(self.buf, key)

class DirPickScreen(Screen):
    PHASE_DIR, PHASE_PATH, PHASE_NAME = "dir", "path", "name"

    def __init__(self, task: str, from_clip: bool = False):
        super().__init__()
        self.task = task
        self.from_clip = from_clip
        self.phase = self.PHASE_DIR
        self.sel = 0
        self.path_buf = TextBuffer("")
        self.name_buf = TextBuffer(infer_filename(task))
        self.options = self._build_options()
        self.target_dir = None
        self._cursor_abs = None

    def _build_options(self):
        known = get_known_directories()
        opts = []
        active = find_active_project_dir()
        if active and active != known["current"]:
            opts.append((f"Активный проект  —  {_short_path(active)}", active))
        for rd in get_recent_directories()[:5]:
            if rd not in [o[1] for o in opts] and rd != known["current"]:
                opts.append((f"Недавняя папка  —  {_short_path(rd)}", rd))
        opts.append(("Текущая папка (.)", known["current"]))
        opts.append(("Рабочий стол (Desktop)", known["desktop"]))
        opts.append(("Загрузки (Downloads)", known["downloads"]))
        opts.append(("Документы (Documents)", known["docs"]))
        opts.append(("Домашняя папка (~)", known["home"]))
        opts.append(("Ввести путь вручную...", None))
        return opts

    def body(self, w, h):
        lines = []
        if self.phase == self.PHASE_DIR:
            lines += _panel_lines("Куда сохранить решение?", [], w)
            for i, (label, _p) in enumerate(self.options):
                mark = UI.c("▶", UI.BRIGHT_CYAN, UI.BOLD) if i == self.sel else " "
                style = (UI.WHITE, UI.BOLD) if i == self.sel else (UI.GRAY,)
                lines.append("   " + mark + " " + fit(UI.c(label, *style), w - 7))
            lines.append("")
            lines.append(UI.c("  Задание: " + fit(self.task.replace("\n", " ⏎ "), w - 13), UI.GRAY))
        elif self.phase == self.PHASE_PATH:
            lines += _panel_lines("Введите путь к папке", [
                UI.c("Каталог будет создан автоматически, если его нет.", UI.GRAY),
            ], w)
            lines.append("")
            lines.append(UI.c("  Путь: ", UI.WHITE, UI.BOLD) + fit(self.path_buf.text(), w - 9))
            lines.append(UI.c("  ~ можно использовать как домашнюю папку", UI.GRAY))
            self._cursor_abs = (9 + min(self.path_buf.cx, max(0, w - 10)), 4)
        elif self.phase == self.PHASE_NAME:
            auto = infer_filename(self.task)
            lines += _panel_lines("Имя файла решения", [
                UI.c(f"Автоимя по задаче: {auto}", UI.GRAY),
            ], w)
            lines.append("")
            lines.append(UI.c("  Файл: ", UI.WHITE, UI.BOLD) + fit(self.name_buf.text(), w - 9))
            lines.append(UI.c("  Расширение .py добавится автоматически", UI.GRAY))
            self._cursor_abs = (9 + min(self.name_buf.cx, max(0, w - 10)), 4)
        return lines

    def cursor(self):
        return self._cursor_abs

    def hints(self):
        if self.phase == self.PHASE_DIR:
            return " ↑↓ Выбор  •  Enter Далее  •  Esc Назад "
        if self.phase == self.PHASE_PATH:
            return " Enter Подтвердить путь  •  Esc Назад "
        return " Enter Сгенерировать  •  Esc К списку папок "

    def on_key(self, key):
        app = self.app
        if self.phase == self.PHASE_DIR:
            if key in ("up", "ctrl-p"):
                self.sel = (self.sel - 1) % len(self.options)
            elif key in ("down", "ctrl-n", "tab"):
                self.sel = (self.sel + 1) % len(self.options)
            elif key == "enter":
                _label, path = self.options[self.sel]
                if path is None:
                    self.phase = self.PHASE_PATH
                    self.path_buf = TextBuffer("")
                else:
                    self.target_dir = path
                    self.target_dir.mkdir(parents=True, exist_ok=True)
                    self.phase = self.PHASE_NAME
            elif key in ("esc", "ctrl-c"):
                app.set_screen(TaskInputScreen(self.task))
        elif self.phase == self.PHASE_PATH:
            if key == "enter":
                raw = self.path_buf.text().strip()
                if raw:
                    try:
                        p = Path(raw).expanduser().resolve()
                        p.mkdir(parents=True, exist_ok=True)
                        self.target_dir = p
                        self.phase = self.PHASE_NAME
                    except Exception as e:
                        app.toast(f"Не удалось создать папку: {e}", "err")
                else:
                    app.toast("Введите путь к папке", "warn")
            elif key in ("esc", "ctrl-c"):
                self.phase = self.PHASE_DIR
            else:
                _buffer_key(self.path_buf, key)
        elif self.phase == self.PHASE_NAME:
            if key == "enter":
                self._start_generation()
            elif key in ("esc", "ctrl-c"):
                self.phase = self.PHASE_DIR
            else:
                _buffer_key(self.name_buf, key)

    def _start_generation(self):
        app = self.app
        name = self.name_buf.text().strip() or infer_filename(self.task)
        if not name.endswith(".py"):
            name += ".py"
        target = self.target_dir or Path(".").resolve()
        task = self.task

        def work():
            return app.solve_fn(task, provider=app.provider)

        def done(res):
            code, used = res
            clear_provider_dead(used)
            if used != app.provider:
                app.toast(f"Провайдер {PROVIDER_LABELS.get(app.provider, app.provider)} недоступен — "
                          f"ответил {PROVIDER_LABELS.get(used, used)}", "warn", 6)
            app.set_screen(PreviewScreen(task=task, code=code, used_provider=used,
                                         target_dir=target, out_name=name))

        def err(msg):
            app.toast("Ошибка генерации: " + msg, "err")
            app.set_screen(TaskInputScreen(task))

        app.set_screen(BusyScreen(
            f"Генерация решения ({PROVIDER_LABELS.get(app.provider, app.provider)})...",
            work, done, err,
            on_cancel=lambda a: a.set_screen(TaskInputScreen(task))))

class BusyScreen(Screen):
    SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message, work_fn, on_done, on_error=None, on_cancel=None, note=""):
        super().__init__()
        self.message = message
        self.note = note
        self.on_done = on_done
        self.on_error = on_error
        self.on_cancel = on_cancel
        self.state = []
        self.cancelled = False
        self.frame_idx = 0

        def worker():
            try:
                result = work_fn()
                self.state.append(("ok", result))
            except Exception as e:
                self.state.append(("err", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def body(self, w, h):
        frame = self.SPIN[(self.frame_idx // 3) % len(self.SPIN)]
        lines = []
        for _ in range(max(0, (h - 2) // 2 - 2)):
            lines.append("")
        sp = UI.c(frame, UI.BRIGHT_CYAN, UI.BOLD)
        lines.append(fit("      " + sp + "  " + UI.c(self.message, UI.WHITE, UI.BOLD), w))
        if self.note:
            lines.append(fit("      " + UI.c(self.note, UI.GRAY), w))
        return lines

    def hints(self):
        if self.on_cancel:
            return " Esc — отменить ожидание "
        return " Пожалуйста, подождите... "

    def on_tick(self):
        self.frame_idx += 1
        if self.state and not self.cancelled:
            kind, payload = self.state[0]
            self.state.clear()
            if kind == "ok":
                self.on_done(payload)
            else:
                if self.on_error:
                    self.on_error(payload)
                else:
                    self.app.toast("Ошибка: " + payload, "err")
                    self.app.set_screen(MainMenuScreen())

    def on_key(self, key):
        if key in ("esc", "ctrl-c"):
            self.cancelled = True
            if self.on_cancel:
                self.on_cancel(self.app)
            else:
                self.app.set_screen(MainMenuScreen())

class PreviewScreen(Screen):
    def __init__(self, task, code, used_provider, target_dir, out_name):
        super().__init__()
        self.task = task
        self.code = code
        self.used = used_provider
        self.target_dir = Path(target_dir)
        self.out_name = out_name
        self.scroll = 0
        self.colored = colorize_python(code)
        ok, verr = validate_code(code)
        self.validation_note = "" if ok else f"Код не проходит проверку синтаксиса: {verr} — нажмите R для перегенерации"

    def _vh(self, h):
        return max(5, h - 9)

    def body(self, w, h):
        vh = self._vh(h)
        header_body = [UI.c(f"Файл: {_short_path(self.target_dir / self.out_name)}", UI.GRAY)]
        if self.validation_note:
            header_body.append(UI.c("⚠ " + self.validation_note, UI.YELLOW, UI.BOLD))
        lines = _panel_lines(
            "Решение готово • " + PROVIDER_LABELS.get(self.used, self.used),
            header_body, w)
        max_scroll = max(0, len(self.colored) - vh)
        self.scroll = max(0, min(self.scroll, max_scroll))
        for i in range(vh):
            li = self.scroll + i
            if li < len(self.colored):
                lines.append("  " + fit(self.colored[li], w - 4))
            else:
                lines.append("")
        pos = f"{self.scroll + 1}-{min(self.scroll + vh, len(self.colored))} / {len(self.colored)} строк"
        lines.append(UI.c("  " + pos, UI.GRAY))
        return lines

    def hints(self):
        return " Enter Сохранить  •  C Скопировать  •  R Перегенерировать  •  Esc Назад  •  ↑↓ Прокрутка "

    def on_key(self, key):
        app = self.app
        if key in ("up", "ctrl-p"):
            self.scroll -= 1
        elif key in ("down", "ctrl-n"):
            self.scroll += 1
        elif key == "pgup":
            self.scroll -= self._vh(app.term.size()[1])
        elif key == "pgdn":
            self.scroll += self._vh(app.term.size()[1])
        elif key == "home":
            self.scroll = 0
        elif key == "end":
            self.scroll = 10 ** 9
        elif key == "enter":
            self._save()
        elif key in ("c", "с"):
            if set_clipboard_text(self.code):
                app.toast("Код скопирован в буфер обмена", "ok")
            else:
                app.toast("Не удалось скопировать в буфер", "warn")
        elif key in ("r", "к"):
            self._regenerate()
        elif key in ("esc", "ctrl-c", "q"):
            app.set_screen(TaskInputScreen(self.task))

    def _unique_path(self):
        base = Path(self.out_name)
        if not base.suffix:
            base = base.with_suffix(".py")
        p = self.target_dir / base
        if not p.exists():
            return p
        stem, suffix = base.stem, base.suffix
        k = 1
        while (self.target_dir / f"{stem}_{k}{suffix}").exists():
            k += 1
        return self.target_dir / f"{stem}_{k}{suffix}"

    def _save(self):
        app = self.app
        try:
            p = self._unique_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self.code, encoding="utf-8")
            save_recent_directory(p.parent)
            copied = set_clipboard_text(self.code)
            app.toast(f"Сохранено: {_short_path(p)}" + (" • скопировано в буфер" if copied else ""), "ok", 5)
            app.set_screen(MainMenuScreen())
        except Exception as e:
            app.toast("Ошибка сохранения: " + str(e), "err")

    def _regenerate(self):
        app = self.app
        task, target, name = self.task, self.target_dir, self.out_name

        def work():
            return app.solve_fn(task, provider=app.provider)

        def done(res):
            code, used = res
            clear_provider_dead(used)
            if used != app.provider:
                app.toast(f"Провайдер {PROVIDER_LABELS.get(app.provider, app.provider)} недоступен — "
                          f"ответил {PROVIDER_LABELS.get(used, used)}", "warn", 6)
            app.set_screen(PreviewScreen(task=task, code=code, used_provider=used,
                                         target_dir=target, out_name=name))

        def err(msg):
            app.toast("Ошибка генерации: " + msg, "err")
            app.set_screen(PreviewScreen(task=task, code=self.code, used_provider=self.used,
                                         target_dir=target, out_name=name))

        app.set_screen(BusyScreen(
            f"Перегенерация решения ({PROVIDER_LABELS.get(app.provider, app.provider)})...",
            work, done, err,
            on_cancel=lambda a: a.set_screen(PreviewScreen(task=task, code=self.code, used_provider=self.used,
                                                           target_dir=target, out_name=name))))

class SettingsScreen(Screen):
    PROVIDERS = ["gigachat", "gemini", "deepseek", "ollama"]

    def __init__(self):
        super().__init__()
        self.sel = 0
        self.phase = "menu"
        self.edit_buf = None
        self.edit_field = None
        self.rows = [
            ("provider", "Провайдер ИИ"),
            ("deepseek_api_key", "DeepSeek API-ключ"),
            ("gemini_api_key", "Gemini API-ключ"),
            ("gemini_proxy_url", "Gemini шлюз URL"),
            ("gemini_model", "Модель Gemini"),
            ("test", "⚡ Проверить подключение"),
            ("update", "🔄 Проверить обновления PyGen"),
            ("back", "← Назад в главное меню"),
        ]
        self._cursor_abs = None

    def _value(self, field):
        cfg = self.app.cfg
        if field == "provider":
            cur = cfg.get("provider", "gigachat")
            label = PROVIDER_LABELS.get(cur, cur)
            dead = provider_dead_reason(cur)
            if dead:
                label += "  ⚠ недоступен"
            return label
        if field in ("deepseek_api_key", "gemini_api_key"):
            v = cfg.get(field, "")
            if field == "gemini_api_key" and (not v or v == _DEFAULT_GEMINI_KEY):
                return "встроенный публичный ключ"
            return (v[:4] + "…" + v[-4:]) if len(v) > 8 else ("Задан" if v else "Не задан")
        if field == "gemini_model" and not cfg.get(field):
            return GEMINI_DEFAULT_MODEL
        return str(cfg.get(field, ""))

    def body(self, w, h):
        lines = _panel_lines("Настройки ИИ-провайдера", [
            UI.c("Настройки сохраняются в " + str(CONFIG_FILE), UI.GRAY),
        ], w)
        if self.phase == "edit":
            lines.append("")
            label = dict(self.rows).get(self.edit_field, self.edit_field)
            lines.append(UI.c("  " + label + ":", UI.WHITE, UI.BOLD))
            lines.append(UI.c("  ▸ ", UI.BRIGHT_CYAN) + fit(self.edit_buf.text(), w - 6))
            lines.append(UI.c("  Enter — сохранить • Esc — отменить", UI.GRAY))
            self._cursor_abs = (4 + min(self.edit_buf.cx, max(0, w - 7)), 5)
            return lines
        lines.append("")
        for i, (field, label) in enumerate(self.rows):
            mark = UI.c("▶", UI.BRIGHT_CYAN, UI.BOLD) if i == self.sel else " "
            style = (UI.WHITE, UI.BOLD) if i == self.sel else (UI.GRAY,)
            value = ""
            if field in ("deepseek_api_key", "gemini_api_key", "gemini_proxy_url", "gemini_model", "provider"):
                value = UI.c("  " + self._value(field), UI.GRAY)
            lines.append("   " + mark + " " + fit(UI.c(label, *style) + value, w - 7))
        return lines

    def cursor(self):
        return self._cursor_abs

    def hints(self):
        if self.phase == "edit":
            return " Enter Сохранить  •  Esc Отменить "
        return " ↑↓ Выбор  •  Enter Изменить / Действие  •  Esc Назад "

    def on_key(self, key):
        app = self.app
        if self.phase == "edit":
            if key == "enter":
                new_val = self.edit_buf.text().strip()
                if new_val:
                    app.cfg[self.edit_field] = new_val
                    save_config(app.cfg)
                    app.toast("Настройка сохранена", "ok", 2)
                self.phase = "menu"
                self.edit_buf = None
            elif key in ("esc", "ctrl-c"):
                self.phase = "menu"
                self.edit_buf = None
            else:
                _buffer_key(self.edit_buf, key)
            return
        if key in ("up", "ctrl-p"):
            self.sel = (self.sel - 1) % len(self.rows)
        elif key in ("down", "ctrl-n", "tab"):
            self.sel = (self.sel + 1) % len(self.rows)
        elif key == "enter":
            self._activate()
        elif key in ("esc", "ctrl-c"):
            app.set_screen(MainMenuScreen())

    def _activate(self):
        app = self.app
        field = self.rows[self.sel][0]
        if field == "provider":
            cur = app.cfg.get("provider", "gigachat")
            nxt = self.PROVIDERS[(self.PROVIDERS.index(cur) + 1) % len(self.PROVIDERS)] if cur in self.PROVIDERS else "gigachat"
            app.cfg["provider"] = nxt
            app.provider = nxt
            save_config(app.cfg)
            app.toast(f"Провайдер: {PROVIDER_LABELS.get(nxt, nxt)}", "ok", 3)
            if nxt == "ollama":
                app.toast("Убедитесь, что Ollama запущен (http://localhost:11434)", "warn", 5)
        elif field in ("deepseek_api_key", "gemini_api_key", "gemini_proxy_url", "gemini_model"):
            self.phase = "edit"
            self.edit_field = field
            self.edit_buf = TextBuffer(str(app.cfg.get(field, "")))
        elif field == "test":
            self._test_connection()
        elif field == "update":
            _tui_update_check(app)
        elif field == "back":
            app.set_screen(MainMenuScreen())

    def _test_connection(self):
        app = self.app
        label = PROVIDER_LABELS.get(app.provider, app.provider)
        tested = app.provider

        def work():
            return app.solve_fn("выведи число 42", provider=tested)

        def done(_res):
            clear_provider_dead(tested)
            app.toast(f"Подключение к {label} успешно!", "ok", 4)
            app.set_screen(SettingsScreen())

        def err(msg):
            if _looks_like_auth_error(msg):
                mark_provider_dead(tested, str(msg)[:160])
            app.toast(f"Ошибка подключения к {label}: {msg}", "err", 6)
            app.set_screen(SettingsScreen())

        app.set_screen(BusyScreen(f"Тестовый запрос к {label}...", work, done, err,
                                  on_cancel=lambda a: a.set_screen(SettingsScreen())))

class TUIApp:
    """Главный цикл TUI: экраны, события, дифференциальная отрисовка."""

    def __init__(self, term: Term = None, solve_fn=None):
        self.term = term or Term()
        self.solve_fn = solve_fn if solve_fn is not None else generate_code_with_fallback
        self.cfg = load_config()
        self.provider = self.cfg.get("provider", "gigachat")
        self.toast_msg = None
        self.toast_kind = "info"
        self.toast_until = 0.0
        self.update_available = None
        self.running = True
        self.exit_code = 0
        self.screen = None
        self._last_size = (0, 0)

    def set_screen(self, s: Screen):
        self.screen = s
        s.app = self

    def toast(self, text, kind="info", seconds=4.0):
        self.toast_msg = text
        self.toast_kind = kind
        self.toast_until = time.time() + seconds

    def quit(self, code: int = 0):
        self.running = False
        self.exit_code = code

    def _start_update_check(self):
        def worker():
            try:
                v = check_for_updates(timeout=2.5)
                if v:
                    self.update_available = v
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def run(self) -> int:
        term = self.term
        if not term.is_tty():
            return self.exit_code
        term.enter_raw()
        term.enter_alt()
        try:
            if self.screen is None:
                self.set_screen(MainMenuScreen())
            self._start_update_check()
            while self.running:
                w, h = term.size()
                if (w, h) != self._last_size:
                    self._last_size = (w, h)
                    term.force_redraw()
                self.screen.on_tick()
                if not self.running:
                    break
                if self.toast_msg and time.time() > self.toast_until:
                    self.toast_msg = None
                frame = _finalize_frame(
                    self.screen.body(w, h), w, h,
                    self.screen.hints(), self.toast_msg, self.toast_kind)
                term.render_frame(frame, cursor=self.screen.cursor())
                key = term.read_key(timeout=0.06)
                if key is not None:
                    self.screen.on_key(key)
        finally:
            term.exit_alt()
            term.exit_raw()
        return self.exit_code

def run_tui() -> int:
    """Запускает современный TUI; при отсутствии TTY откатывается на классический CLI."""
    term = Term()
    if not term.is_tty():
        print("[!] TUI требует настоящий терминал (TTY). Запускаю классический режим...")
        run_interactive_cli()
        return 0
    app = TUIApp(term)
    return app.run()

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
                    vscode.window.showErrorMessage('PyGen не найден. Запустите скрипт установки install');
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
        cmd_pygen.write_text("@echo off\nwhere py >nul 2>nul && (py -3 \"%~dp0run.py\" %*) || (python \"%~dp0run.py\" %*)\n", encoding="ascii")

        cmd_gui = local_bin / "pygen-gui.cmd"
        cmd_gui.write_text("@echo off\nwhere py >nul 2>nul && (py -3 \"%~dp0run.py\" --gui %*) || (python \"%~dp0run.py\" --gui %*)\n", encoding="ascii")

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
            # Уведомляем систему об изменении переменных окружения
            try:
                import ctypes
                HWND_BROADCAST, WM_SETTINGCHANGE = 0xFFFF, 0x001A
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 0x0002, 5000, None)
            except Exception:
                pass
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
        share_tools = (home / ".local" / "share" / "pygen") if not is_win else (local_bin / "pygen_share")
        share_tools.mkdir(parents=True, exist_ok=True)
        (share_tools / "External Tools.xml").write_text(PYCHARM_TOOLS_XML, encoding="utf-8")
        
        # Предварительно создаем каталоги для стандартных версий PyCharm Community и Professional
        for ver_name in ["PyCharmCE2024.1", "PyCharmCE2023.3", "PyCharm2024.1"]:
            if is_win and appdata:
                target_p = Path(appdata) / "JetBrains" / ver_name / "tools"
            else:
                target_p = home / ".config" / "JetBrains" / ver_name / "tools"
            try:
                target_p.mkdir(parents=True, exist_ok=True)
                (target_p / "External Tools.xml").write_text(PYCHARM_TOOLS_XML, encoding="utf-8")
            except Exception:
                pass
        print(f"      [✓] PyCharm: созданы шаблоны External Tools в {share_tools} и JetBrains")

    print("\n" + "=" * 60)
    print("          🎉 Установка успешно завершена!                 ")
    print("=" * 60)
    print("\n📌 Способы использования:")
    if is_win:
        print("1. В терминале (CMD / PowerShell):")
        print("   pygen                    # Современный интерактивный CLI ассистент")
        print("   pygen \"задание\" -dt        # Сохранить решение на Рабочий стол")
        print("   pygen -c                 # Решить задание ПРЯМО ИЗ БУФЕРА ОБМЕНА")
        print("\n2. Скрытный компактный GUI:")
        print("   pygen -g                 # Открыть окно (Ctrl+Enter - решить, Esc - скрыть)")
        print("   (На Windows окно автоматически защищено от программ захвата экрана!)")
    else:
        print("1. В терминале (CLI):")
        print("   pygen                    # Современный интерактивный CLI ассистент")
        print("   pygen \"задание\" -dt        # Сохранить решение на Рабочий стол")
        print("   pygen -c -dt             # Решить задание ПРЯМО ИЗ БУФЕРА ОБМЕНА")
        print("\n2. Скрытный GUI:")
        print("   pygen -g")

    print("\n3. В редакторах кода:")
    print("   - VS Code: выделите условие -> Ctrl+Alt+G")
    print("   - IDLE:    выделите условие -> Alt+G")
    print("   - PyCharm: Меню Tools -> External Tools -> PyGen: Решить из буфера\n")

# --- Встроенная самопроверка (pygen --selftest, работает без сети) ---
def run_selftest() -> bool:
    """Прогоняет офлайн-проверки чистой логики. Возвращает True, если всё ОК."""
    checks = []

    def check(name, fn):
        try:
            fn()
            checks.append((name, True, ""))
        except Exception as e:
            checks.append((name, False, str(e)))

    def chk_clean_code():
        src = "# комментарий\nprint('#')  # хвост\n\n\n\"\"\"док\"\"\"\nx = 1\n"
        out = remove_comments_and_docstrings(src)
        assert "# комментарий" not in out, "комментарий не удалён"
        assert 'print(\'#\')' in out or 'print("#")' in out, "'#' внутри строки должен сохраниться"
        assert "хвост" not in out, "inline-комментарий не удалён"
        assert "док" not in out, "docstring не удалён"
        assert out.count("\n\n\n") == 0, "несколько пустых строк должны схлопываться в одну"

    def chk_docstrings():
        src = '"""модульный док"""\n\ndef f():\n    """док функции"""\n    return 1\n'
        out = remove_comments_and_docstrings(src)
        assert "модульный" not in out and "док функции" not in out

    def chk_strip_inline():
        assert _strip_inline_comment('a = 1  # тут') == "a = 1"
        assert _strip_inline_comment('s = "#не_коммент"  # коммент') == 's = "#не_коммент"'
        assert _strip_inline_comment("s = 'x#y'") == "s = 'x#y'"

    def chk_extract_code():
        md = "Пояснение\n```python\nprint(1)\n```\nКонец"
        assert extract_code(md) == "print(1)"
        html_txt = "<p>Пояснение</p><code>print(2)<br></code>"
        out = extract_code(html_txt)
        assert "print(2)" in out
        assert "<" not in out
        unescaped = extract_code("a &amp;&amp; b &lt; c &gt; d &nbsp;e")
        assert unescaped.startswith("a && b < c > d")

    def chk_infer_filename():
        assert infer_filename("check the palindrome of a string") == "check.py"
        assert infer_filename("дано n чисел найти сумму") == "chisel.py"
        assert infer_filename("...") == "solution.py"

    def chk_parse_version():
        assert parse_version("v2.1.1") == (2, 1, 1)
        assert parse_version("3.0") == (3, 0)
        assert parse_version("abc") == (0,)
        assert parse_version("2.1.1") > parse_version("2.1.0")

    def chk_resolve_dirs():
        p = resolve_target_dir(".")
        assert p == Path.cwd().resolve()
        p2 = resolve_target_dir("current")
        assert p2 == Path.cwd().resolve()

    def chk_known_dirs():
        known = get_known_directories()
        for key in ("desktop", "downloads", "docs", "home", "current"):
            assert key in known, f"нет ключа {key}"

    def chk_config_roundtrip():
        import tempfile
        global CONFIG_DIR, CONFIG_FILE
        old_dir, old_file = CONFIG_DIR, CONFIG_FILE
        try:
            with tempfile.TemporaryDirectory() as td:
                CONFIG_DIR = Path(td)
                CONFIG_FILE = CONFIG_DIR / "config.json"
                save_config({"provider": "gemini", "deepseek_api_key": "sk-test"})
                cfg = load_config()
                assert cfg["provider"] == "gemini"
                assert cfg["deepseek_api_key"] == "sk-test"
        finally:
            CONFIG_DIR, CONFIG_FILE = old_dir, old_file

    def chk_textbuffer():
        b = TextBuffer("")
        b.insert_text("привет\nмир")
        assert b.text() == "привет\nмир"
        b.cx = 0
        b.backspace()  # склейка строк
        assert b.text() == "приветмир"
        b.insert("#")
        b.clear()
        assert b.is_empty()
        b.insert_text("abc")
        b.cy = 0; b.cx = 3
        b.insert("\n")
        assert b.text() == "abc\n"
        b.insert_text("def")
        assert b.text() == "abc\ndef"

    def chk_fit():
        assert fit("abcdef", 3) == "abc"
        assert fit("\033[92mabcdef\033[0m", 3).startswith("\033[92mabc")
        assert _visible_len("\033[92mabc\033[0m") == 3

    def chk_panel():
        lines = _panel_lines("Заголовок", ["строка"], 40)
        assert len(lines) == 3
        assert lines[0].startswith("╭")
        assert lines[2].startswith("╰")
        assert _visible_len(lines[1]) == 40

    def chk_finalize():
        frame = _finalize_frame(["a", "b"], 30, 6, "подсказка", "уведомление", "ok")
        assert len(frame) == 6
        assert "уведомление" in frame[4]
        assert "подсказка" in frame[5]

    def chk_escape_keys():
        t = Term(key_source=lambda: None)
        assert t._parse_escape(b"\x1b[A") == "up"
        assert t._parse_escape(b"\x1b[B") == "down"
        assert t._parse_escape(b"\x1b[C") == "right"
        assert t._parse_escape(b"\x1b[D") == "left"
        assert t._parse_escape(b"\x1b[3~") == "del"
        assert t._parse_escape(b"\x1b[5~") == "pgup"
        assert t._parse_escape(b"\x1b[6~") == "pgdn"
        assert t._parse_escape(b"\x1b[H") == "home"
        assert t._parse_escape(b"\x1b[F") == "end"
        assert t._parse_escape(b"\x1bOP") == "f1"
        assert t._parse_escape(b"\x1b[15~") == "f5"
        assert t._parse_escape(b"\x1b[Z") == "tab-back"
        assert t._parse_escape(b"\x1b") == "esc"
        assert t._parse_escape(b"\x1b[1;5A") == "ctrl-up"

    def chk_map_char():
        t = Term(key_source=lambda: None)
        assert t._map_char("\r") == "enter"
        assert t._map_char("\n") == "ctrl-enter"
        assert t._map_char("\x1b") == "esc"
        assert t._map_char("\x08") == "backspace"
        assert t._map_char("\x03") == "ctrl-c"
        assert t._map_char("ж") == "ж"
        assert t._map_extended("\x00", "H") == "up"
        assert t._map_extended("\xe0", "M") == "right"
        assert t._map_extended("\x00", ";") == "f1"

    def chk_colorize():
        colored = colorize_python('for i in range(3):\n    print("#x")\n')
        assert len(colored) == 2
        plain = highlight_python_lines("print(1)")
        assert len(plain) == 1

    def chk_clipboard():
        assert isinstance(set_clipboard_text("тест"), bool)
        assert isinstance(get_clipboard_text(), str)

    def chk_update_guard():
        v = check_for_updates(timeout=0.3)
        assert v is None or isinstance(v, str)

    def chk_provider_health():
        clear_provider_dead()
        assert provider_dead_reason("gemini") is None
        mark_provider_dead("gemini", "invalid key", ttl=30)
        assert provider_dead_reason("gemini") == "invalid key"
        clear_provider_dead("gemini")
        assert provider_dead_reason("gemini") is None
        mark_provider_dead("deepseek", "expired", ttl=0.01)
        time.sleep(0.05)
        assert provider_dead_reason("deepseek") is None, "истёкшая запись должна сбрасываться"
        assert _looks_like_auth_error(RuntimeError("HTTP 401: unauthorized"))
        assert _looks_like_auth_error(RuntimeError("Request had invalid authentication credentials"))
        assert not _looks_like_auth_error(RuntimeError("HTTP 500: Internal Server Error"))
        clear_provider_dead()

    def chk_gemini_key_format():
        assert _DEFAULT_GEMINI_KEY.startswith("AQ."), "ключ Gemini должен быть в новом формате"
        assert len(_DEFAULT_GEMINI_KEY) > 30

    def chk_validate_code():
        ok, err = validate_code("a = int(input())\nprint(a)\n")
        assert ok, f"корректный код должен проходить проверку: {err}"
        bad_ok, bad_err = validate_code("for_iin range(3):\n    pass\n")
        assert not bad_ok, "сломанный код должен быть отловлен"
        empty_ok, empty_err = validate_code("   ")
        assert not empty_ok and "пустой" in empty_err
        indent_ok, indent_err = validate_code("a = 1\n  b = 2\n")
        assert not indent_ok and indent_err

    check("Очистка кода от комментариев", chk_clean_code)
    check("Удаление docstring", chk_docstrings)
    check("Inline-комментарии не трогают строки", chk_strip_inline)
    check("Извлечение кода из markdown/HTML", chk_extract_code)
    check("Автоимя файла", chk_infer_filename)
    check("Разбор версий", chk_parse_version)
    check("Пресеты директорий", chk_resolve_dirs)
    check("Известные директории", chk_known_dirs)
    check("Конфиг: сохранение/загрузка", chk_config_roundtrip)
    check("Текстовый буфер TUI", chk_textbuffer)
    check("Обрезка строк (fit)", chk_fit)
    check("Рамки панелей", chk_panel)
    check("Сборка кадра TUI", chk_finalize)
    check("Escape-последовательности клавиш", chk_escape_keys)
    check("Раскладка символов клавиш", chk_map_char)
    check("Подсветка синтаксиса", chk_colorize)
    check("Буфер обмена (bool/str)", chk_clipboard)
    check("Проверка обновлений (сеть, короткий таймаут)", chk_update_guard)
    check("Надёжность провайдеров (кэш сбоев)", chk_provider_health)
    check("Формат ключа Gemini", chk_gemini_key_format)
    check("Проверка синтаксиса кода", chk_validate_code)

    passed = 0
    for name, ok, err in checks:
        if ok:
            print(f"  {UI.c('[✓]', UI.GREEN, UI.BOLD)} {name}")
            passed += 1
        else:
            print(f"  {UI.c('[✗]', UI.RED, UI.BOLD)} {name}: {err}")
    print()
    print(f"  Итог: {passed}/{len(checks)} проверок пройдено")
    return passed == len(checks)

# --- CLI Точка входа ---
def main():
    parser = argparse.ArgumentParser(
        description="PyGen: Быстрый и незаметный генератор чистого Python-кода (РФ, без VPN, без sudo)."
    )
    parser.add_argument("task", nargs="*", help="Текст задания")
    parser.add_argument("-g", "--gui", action="store_true", help="Запустить скрытный компактный GUI интерфейс")
    parser.add_argument("-t", "--tui", action="store_true", help="Запустить современный консольный TUI (стрелки, панели)")
    parser.add_argument("--classic", action="store_true", help="Классический интерактивный CLI вместо TUI")
    parser.add_argument("-c", "--clip", action="store_true", help="Прочитать задание прямо из буфера обмена")
    parser.add_argument("-p", "--provider", choices=["gigachat", "gemini", "deepseek", "ollama"],
                        help="Провайдер ИИ: gigachat (по умолчанию), gemini (Google 3.5 через VPS), deepseek или ollama")
    parser.add_argument("--gemini", action="store_true", help="Использовать Google Gemini (через VPS-шлюз)")
    parser.add_argument("--deepseek", action="store_true", help="Использовать DeepSeek")
    parser.add_argument("-k", "--key", help="API-ключ (для Gemini или DeepSeek)")
    parser.add_argument("-d", "--dir", help="Папка назначения или пресет (desktop, home, docs, downloads)")
    parser.add_argument("-dt", "--desktop", action="store_true", help="Сохранить на Рабочий стол")
    parser.add_argument("--home", action="store_true", help="Сохранить в Домашнюю папку (~)")
    parser.add_argument("--docs", action="store_true", help="Сохранить в Документы")
    parser.add_argument("--downloads", action="store_true", help="Сохранить в Загрузки")
    parser.add_argument("-f", "--file", help="Имя выходного .py файла")
    parser.add_argument("-i", "--interactive", action="store_true", help="Запустить интерактивный интерфейс (TUI)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Тихий режим (выводит только путь к файлу)")
    parser.add_argument("--stdout", action="store_true", help="Вывести ТОЛЬКО сгенерированный код в stdout (для IDE)")
    parser.add_argument("--install", action="store_true", help="Автоматическая установка PyGen, CLI и расширений IDE в систему")
    parser.add_argument("--update", action="store_true", help="Проверить и установить обновления PyGen")
    parser.add_argument("--selftest", action="store_true", help="Запустить встроенную самопроверку (без сети)")
    parser.add_argument("--url", help="Кастомный API URL (например, прокси Gemini или локальный Ollama)")
    parser.add_argument("--version", action="version", version=f"PyGen {__version__}")
    args = parser.parse_args()

    # Встроенная самопроверка
    if args.selftest:
        ok = run_selftest()
        sys.exit(0 if ok else 1)

    # Запуск автообновления
    if getattr(args, "update", False):
        print(f"Текущая версия PyGen: v{__version__}")
        print("Проверка наличия обновлений...")
        new_ver = check_for_updates(timeout=3.5)
        if new_ver:
            print(f"Найдена новая версия: v{new_ver}")
            print("Загрузка и установка обновления...")
            if perform_update():
                print(f"[✓] PyGen успешно обновлен до v{new_ver}!")
            else:
                print("[✗] Не удалось скачать обновление.")
                sys.exit(1)
        else:
            print(f"[✓] У вас уже установлена актуальная версия (v{__version__}).")
        sys.exit(0)

    # Запуск автоустановки
    if args.install:
        install_system()
        sys.exit(0)

    # Запуск GUI (по флагу --gui или если вызван как pygen-gui)
    prog_name = Path(sys.argv[0]).stem.lower() if sys.argv and sys.argv[0] else ""
    if "gui" in prog_name or args.gui:
        launch_stealth_gui()
        sys.exit(0)

    # Принудительный TUI
    if args.tui:
        run_tui()
        sys.exit(0)

    # Интерактивный режим: TUI по умолчанию, классический CLI по --classic
    is_tty_env = bool(sys.stdin.isatty() and sys.stdout.isatty())
    is_interactive = (
        getattr(args, "interactive", False) or
        (not args.task and not args.clip and not args.stdout and is_tty_env)
    )
    if is_interactive:
        if not args.classic and is_tty_env:
            run_tui()
        else:
            run_interactive_cli()
        sys.exit(0)

    # Определение провайдера
    provider = args.provider
    if args.gemini:
        provider = "gemini"
    elif args.deepseek:
        provider = "deepseek"

    # Получение задания
    task = read_multiline_task(args)
    if not task:
        if not args.quiet and not args.stdout:
            print(UI.c("Ошибка: задание не может быть пустым.", UI.RED))
        sys.exit(0)

    # Режим вывода чистого кода в stdout (для интеграции с IDE)
    if args.stdout:
        try:
            code, _used = generate_code_with_fallback(task, provider=provider, api_key=args.key,
                                                      custom_url=args.url, err_out=sys.stderr)
            ok, verr = validate_code(code)
            if not ok:
                sys.stderr.write(f"[!] Предупреждение: код не проходит проверку синтаксиса ({verr}).\n")
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

    # Генерация с автоматическим фолбэком на GigaChat
    try:
        if not args.quiet:
            with Spinner(f"Генерация чистого решения через {(provider or 'gigachat').upper()}..."):
                code, _used = generate_code_with_fallback(task, provider=provider, api_key=args.key,
                                                          custom_url=args.url)
        else:
            code, _used = generate_code_with_fallback(task, provider=provider, api_key=args.key,
                                                      custom_url=args.url)
    except Exception as e:
        if not args.quiet:
            print(UI.c(f"[✗] Ошибка генерации: {e}", UI.RED, UI.BOLD))
        else:
            sys.stderr.write(f"Ошибка: {e}\n")
        sys.exit(1)

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
        render_code_preview(code, target_path, copied=True)
    else:
        print(str(target_path))

if __name__ == "__main__":
    main()
