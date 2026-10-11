# REX Project Agent Instructions

This folder is application source for a REX Corp project. VPS inventory, deployment notes, Nginx/systemd context, and cross-service scripts belong in `C:\Users\user\Desktop\SERVER`.

## Deployment Workflow

- Use Git as the default deployment path. Do not deploy by copying this whole folder with `rsync` over the production runtime directory.
- Keep secrets and runtime data out of Git: `.env`, `.env.*`, private keys, tokens, SQLite/database files, uploads, logs, `node_modules`, virtualenvs, build output, and local backups.
- Before deploying, inspect `git status` and the intended diff. Commit only intentional source changes, then push to the configured remote such as `vps`.
- On the VPS, update the runtime tree with a fast-forward pull, run the project-specific install step if needed, restart or reload only the affected service, and verify with status/logs plus an HTTP check.
- If `rsync` is ever needed for a narrow one-off transfer, do not use `--delete` against production paths and explicitly exclude secrets, databases, uploads, and runtime directories.

For service names, domains, ports, and server paths, read `C:\Users\user\Desktop\SERVER\inventory\services.md`.
"Не борись с ошибками! Каждый раз, когда ты сталкиваешься с одной и той же ошибкой дважды, изучи веб и найди 3–5 возможных способов её исправления. Затем выбери самое эффективное решение и реализуй его."
