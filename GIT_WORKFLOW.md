# Git Workflow

## Project

- Product: PyGen — автономный генератор процедурного Python-кода (TUI + CLI + скрытный GUI + расширения IDE)
- Public URL: `https://rexcorp.space/` (PyGen landing; зеркало `https://rexcorp.space/1581/`)
- Local source: `C:\Users\user\Desktop\REX_PROJECTS\PyGen`
- Source of truth: GitHub `origin` -> `https://github.com/IliaBebebe/pygen.git` (branch `main`)
- Public mirror repo: `C:\Users\user\Desktop\REX_PROJECTS\rexcorp-main` (`vps` -> `rex-vps-deploy:/srv/git/rexcorp-main.git`)
- VPS runtime path: `/var/www/rexcorp/public` (Nginx static, user `www-data`, group `webdeploy`)
- Gemini relay: `https://gemini.rexcorp.space/` -> `generativelanguage.googleapis.com` (Nginx reverse proxy; API key передаётся клиентом)

## Distribution endpoints (`/var/www/rexcorp/public`)

| Файл | Назначение |
|---|---|
| `run.py`, `p`, `py` | идентичные копии `run.py` из этого репозитория |
| `version` | версия для автообновления (`python run.py --update`) — должна совпадать с `__version__` |
| `i`, `install.sh` | Linux-установщик (`install.sh`) |
| `w`, `win` | Windows-установщик (`install.ps1`) |
| `index.html`, `1581/index.html` | лендинг PyGen (одинаковое содержимое) |
| `1581/run.py`, `1581/p`, `1581/extensions/` | копии для раздела `/1581/` |

## Rules

- `run.py` остаётся одним файлом и использует **только стандартную библиотеку** (никаких `pip`-зависимостей): он распространяется через `curl | python`.
- Публичный ключ Gemini (`_DEFAULT_GEMINI_KEY`) — единственный секрет, допустимый в коде. Он хранится в **base64**, потому что GitHub secret scanning блокирует пуш открытых ключей Google (ключ при этом публичный: он лежит в открытой раздаче `rexcorp.space/p`).
  Ротация ключа: получить новый ключ → `python -c "import base64;print(base64.b64encode(b'НОВЫЙ_КЛЮЧ').decode())"` → заменить строку в `_DEFAULT_GEMINI_KEY` → проверить `python run.py --selftest` и реальный запрос `python run.py "выведи 42" -p gemini -q -d .` → обновить `C:\Users\user\Desktop\SERVER\inventory\services.md`.
- Не коммитить `.env`, кэши, логи, `__pycache__`, `tests/__pycache__`, временные отладочные файлы (`_dbg*`, `_debug*`).
- При смене `__version__` синхронно обновлять: этот репозиторий (GitHub) и зеркало `rexcorp-main` (`run.py`, `p`, `py`, `version`, `i`, `install.sh`, `w`, `win`, `index.html`, `1581/`).
- Лендинг `index.html` на VPS и в `1581/` всегда идентичен `index.html` этого репозитория.
- Если GitHub отклоняет пуш из-за secret scanning, **не** ослабляй защиту: секрет либо убирается из коммита, либо (для заведомо публичных ключей) кодируется, как описано выше.

## Local Checks

```powershell
python -m py_compile run.py codegen.py
python run.py --version
python run.py --selftest
python tests/test_pygen.py
python run.py --help
```

Ожидается: компиляция без ошибок, `20/20` проверок самотеста, `Ran 20 tests ... OK`.

## Deploy

```powershell
# 1. Исходники проекта (GitHub)
cd C:\Users\user\Desktop\REX_PROJECTS\PyGen
git status --short
git add .
git commit -m "Release PyGen v3.0.0: modern TUI, rotated Gemini key, provider reliability"
git push origin main

# 2. Публичное зеркало (rexcorp.space)
cd C:\Users\user\Desktop\REX_PROJECTS\rexcorp-main
git fetch vps
git merge --ff-only vps/main
Copy-Item ..\PyGen\run.py      .\run.py  -Force
Copy-Item ..\PyGen\run.py      .\p       -Force
Copy-Item ..\PyGen\run.py      .\py      -Force
Copy-Item ..\PyGen\index.html  .\index.html -Force
Copy-Item ..\PyGen\install.sh  .\i       -Force
Copy-Item ..\PyGen\install.sh  .\install.sh -Force
Copy-Item ..\PyGen\install.ps1 .\w       -Force
Copy-Item ..\PyGen\install.ps1 .\win     -Force
Copy-Item ..\PyGen\run.py      .\1581\run.py -Force
Copy-Item ..\PyGen\run.py      .\1581\p      -Force
Copy-Item ..\PyGen\index.html  .\1581\index.html -Force
Copy-Item ..\PyGen\extensions  .\1581\extensions -Recurse -Force
Set-Content .\version "3.0.0"
git add .
git commit -m "Update PyGen distribution to v3.0.0"
git push vps main

# 3. VPS: fast-forward pull и проверка
ssh rex-vps "cd /var/www/rexcorp/public && git checkout -- . && git pull --ff-only && cat version"
curl.exe -s -o NUL -w "%{http_code} %{size_download}`n" https://rexcorp.space/
curl.exe -s https://rexcorp.space/version
curl.exe -s https://rexcorp.space/p | Select-String -Pattern '__version__'
```

Expected: `https://rexcorp.space/` → `200 27001`, `/version` → `3.0.0`, `/p` содержит `__version__ = "3.0.0"`.

Note: VPS working tree теряет локальные правки (`git checkout -- .`) — вся выкладка идёт только через git, production-файлы не редактируются вручную.
