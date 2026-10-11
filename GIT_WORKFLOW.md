# Git Workflow

## Project

- Product: PyGen — автономный генератор процедурного Python-кода (TUI + CLI + скрытный GUI + расширения IDE)
- Public URL: `https://pygen.rexcorp.space/` (отдельный домен с 2026-10-11)
- Local source: `C:\Users\user\Desktop\REX_PROJECTS\PyGen`
- Source of truth: GitHub `origin` -> `https://github.com/IliaBebebe/pygen.git` (branch `main`)
- Public mirror repo: `C:\Users\user\Desktop\REX_PROJECTS\rexcorp-main` (`vps` -> `rex-vps-deploy:/srv/git/rexcorp-main.git`)
- VPS runtime path: `/var/www/rexcorp/public/pygen` (Nginx static, user `www-data`, group `webdeploy`)
- Nginx vhost: `/etc/nginx/sites-available/pygen.rexcorp.space` (резервная копия конфига главного домена: `rexcorp.dynv6.net.bak-*-pygen-domain`)
- Gemini relay: `https://gemini.rexcorp.space/` -> `generativelanguage.googleapis.com` (Nginx reverse proxy; API key передаётся клиентом)
- REX Hub card: `https://hub.rexcorp.space/` (проект `rex-hub`)

## Раскладка на VPS

| Путь | Назначение |
|---|---|
| `pygen/index.html` | лендинг PyGen (`https://pygen.rexcorp.space/`) |
| `pygen/run.py`, `pygen/p`, `pygen/py` | идентичные копии `run.py` из этого репозитория |
| `pygen/version` | версия для автообновления (`pygen --update`) — совпадает с `__version__` |
| `pygen/i`, `pygen/install.sh` | Linux-установщик (`install.sh`) |
| `pygen/w`, `pygen/win` | Windows-установщик (`install.ps1`) |
| `pygen/extensions/` | расширения IDE (VS Code, IDLE, PyCharm) |
| `pygen/favicon.ico`, `pygen/robots.txt` | иконка и robots для нового домена |
| `index.html` (корень) | корпоративный лендинг REX Corp на главном домене `rexcorp.space` |
| `robots.txt`, `favicon.ico`, `rex-corp-logo.png` (корень) | ресурсы главного домена |

`1581/` удалён 2026-10-11 (вариант для класса 1581 больше не нужен, всё свелось к основному домену).

## Rules

- `run.py` остаётся одним файлом и использует **только стандартную библиотеку** (никаких `pip`-зависимостей): он распространяется через `curl | python`.
- Публичный ключ Gemini (`_DEFAULT_GEMINI_KEY`) — единственный секрет, допустимый в коде. Он хранится в **base64**, потому что GitHub secret scanning блокирует пуш открытых ключей Google (ключ при этом публичный: он лежит в открытой раздаче `pygen.rexcorp.space/p`).
  Ротация ключа: получить новый ключ → `python -c "import base64;print(base64.b64encode(b'НОВЫЙ_КЛЮЧ').decode())"` → заменить строку в `_DEFAULT_GEMINI_KEY` → проверить `python run.py --selftest` и реальный запрос `python run.py "выведи 42" -p gemini -q -d .` → обновить `C:\Users\user\Desktop\SERVER\inventory\services.md`.
- Не коммитить `.env`, кэши, логи, `__pycache__`, `tests/__pycache__`, временные отладочные файлы (`_dbg*`, `_debug*`).
- При смене `__version__` синхронно обновлять: этот репозиторий (GitHub) и зеркало `rexcorp-main` (`pygen/run.py`, `pygen/p`, `pygen/py`, `pygen/version`, `pygen/i`, `pygen/install.sh`, `pygen/w`, `pygen/win`, `pygen/index.html`).
- Старые ссылки `rexcorp.space/p`, `/py`, `/run.py`, `/i`, `/install.sh`, `/w`, `/win`, `/version` отдают `301` на новый домен (правило `location ~` в vhost главного домена). При переносе раздачи эти редиректы нужно сохранять, иначе сломается автообновление старых установок.
- Новый vhost: `listen [::]:443 ssl;` **без** `ipv6only=on` — иначе `nginx -t` падает с `duplicate listen options` (главный домен уже задаёт эту опцию).
- Если GitHub отклоняет пуш из-за secret scanning, **не** ослабляй защиту: секрет либо убирается из коммита, либо (для заведомо публичных ключей) кодируется, как описано выше.

## Local Checks

```powershell
python -m py_compile run.py codegen.py
python run.py --version
python run.py --selftest
python tests/test_pygen.py
python run.py --help
```

Ожидается: компиляция без ошибок, `21/21` проверок самотеста, `Ran 22 tests ... OK`.

## Deploy

```powershell
# 1. Исходники проекта (GitHub)
cd C:\Users\user\Desktop\REX_PROJECTS\PyGen
git status --short
git add .
git commit -m "Release PyGen: <что изменилось>"
git push origin main

# 2. Публичное зеркало (pygen.rexcorp.space)
cd C:\Users\user\Desktop\REX_PROJECTS\rexcorp-main
git fetch vps
git merge --ff-only vps/main
Copy-Item ..\PyGen\run.py      .\pygen\run.py -Force
Copy-Item ..\PyGen\run.py      .\pygen\p      -Force
Copy-Item ..\PyGen\run.py      .\pygen\py     -Force
Copy-Item ..\PyGen\index.html  .\pygen\index.html -Force
Copy-Item ..\PyGen\install.sh  .\pygen\i      -Force
Copy-Item ..\PyGen\install.sh  .\pygen\install.sh -Force
Copy-Item ..\PyGen\install.ps1 .\pygen\w      -Force
Copy-Item ..\PyGen\install.ps1 .\pygen\win    -Force
Copy-Item ..\PyGen\extensions  .\pygen\extensions -Recurse -Force
[System.IO.File]::WriteAllText("$PWD\pygen\version", "3.0.0`n", (New-Object System.Text.UTF8Encoding $false))
git add .
git commit -m "Update PyGen distribution to vX.Y.Z"
git push vps main

# 3. VPS: fast-forward pull и проверка
ssh rex-vps "runuser -u www-data -- git -C /var/www/rexcorp/public pull --ff-only && cat /var/www/rexcorp/public/pygen/version"
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" https://pygen.rexcorp.space/
curl.exe -s https://pygen.rexcorp.space/version
curl.exe -s https://pygen.rexcorp.space/p | Select-String -Pattern '__version__'
curl.exe -s -o NUL -w "%{http_code} %{redirect_url}`n" https://rexcorp.space/p
```

Expected: `https://pygen.rexcorp.space/` → `200 31127`, `/version` → `3.0.0`, `/p` содержит `__version__ = "3.0.0"`, `rexcorp.space/p` → `301` на `https://pygen.rexcorp.space/p`, `rexcorp.space/` — корпоративный лендинг REX Corp, `rexcorp.space/1581/` → `404`.

Note: production-файлы не редактируются вручную — вся выкладка идёт только через git (при необходимости локальные правки в дереве на VPS откатываются `git checkout -- .` перед `pull`).
