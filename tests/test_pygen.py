#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты PyGen (unittest, только stdlib).

Запуск:
    python tests/test_pygen.py
или из корня репозитория:
    python -m unittest discover -s tests
"""
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from io import StringIO

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import run  # noqa: E402  (импорт основного модуля)


def make_key_source(keys):
    """Источник клавиш для Term: по очереди отдаёт ключи; ('pause', t) — пауза."""
    queue = list(keys)

    def source():
        if not queue:
            return None
        item = queue.pop(0)
        if isinstance(item, tuple) and item and item[0] == "pause":
            time.sleep(item[1])
            return None
        return item

    return source


class TUIFlowTestBase(unittest.TestCase):
    """База для тестов TUI: виртуальный терминал, временный конфиг и рабочая папка."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.old_cwd = Path.cwd()
        os.chdir(self.tmp)

        # изоляция конфига и кэша
        self._old_cfg_dir, self._old_cfg_file = run.CONFIG_DIR, run.CONFIG_FILE
        self._old_cache_dir, self._old_recent_file = run.CACHE_DIR, run.RECENT_FILE
        run.CONFIG_DIR = self.tmp / ".config" / "pygen"
        run.CONFIG_FILE = run.CONFIG_DIR / "config.json"
        run.CACHE_DIR = self.tmp / ".cache" / "pygen"
        run.RECENT_FILE = run.CACHE_DIR / "recent.json"
        run.save_config({"provider": "gigachat", "deepseek_api_key": "",
                         "gemini_api_key": "",
                         "gemini_proxy_url": run.GEMINI_DEFAULT_PROXY_URL,
                         "gemini_model": run.GEMINI_DEFAULT_MODEL})

        # без сети и без сюрпризов окружения
        self._old_check = run.check_for_updates
        run.check_for_updates = lambda timeout=2.5: None
        self._old_recent = run.get_recent_directories
        run.get_recent_directories = lambda: []
        self._old_active = run.find_active_project_dir
        run.find_active_project_dir = lambda scan_limit=500: None

    def tearDown(self):
        run.check_for_updates = self._old_check
        run.get_recent_directories = self._old_recent
        run.find_active_project_dir = self._old_active
        run.CONFIG_DIR, run.CONFIG_FILE = self._old_cfg_dir, self._old_cfg_file
        run.CACHE_DIR, run.RECENT_FILE = self._old_cache_dir, self._old_recent_file
        os.chdir(self.old_cwd)
        self._tmp.cleanup()

    def run_app(self, keys, solve_fn=None):
        """Запускает TUIApp с виртуальными клавишами и возвращает (app, history)."""
        term = run.Term(out_file=StringIO(), key_source=make_key_source(keys))
        if solve_fn is None:
            solve_fn = lambda prompt, provider=None, api_key=None, custom_url=None: ("print(1)\n", provider or "gigachat")
        app = run.TUIApp(term, solve_fn=solve_fn)
        history = []
        orig_set = app.set_screen

        def traced(s):
            history.append(type(s).__name__)
            orig_set(s)

        app.set_screen = traced
        app.run()
        return app, history


class TestTUIBasicFlow(TUIFlowTestBase):
    def test_full_generation_flow(self):
        """Главный сценарий: меню → ввод задачи → папка → имя → генерация → сохранение → выход."""
        keys = [
            "enter",          # «Ввести условие задачи»
            "п", "р", "и", "в", "е", "т",   # текст задачи
            "ctrl-enter",     # решить
            "enter",          # текущая папка
            "enter",          # автоимя файла
            ("pause", 0.35),  # ждём завершения генерации (BusyScreen)
            "enter",          # сохранить в Preview
            "q",              # выход из главного меню
        ]
        app, history = self.run_app(keys)
        self.assertEqual(app.exit_code, 0)
        for screen in ("MainMenuScreen", "TaskInputScreen", "DirPickScreen",
                       "BusyScreen", "PreviewScreen"):
            self.assertIn(screen, history, f"экран {screen} не был посещён: {history}")

        saved = sorted(self.tmp.glob("*.py"))
        self.assertTrue(saved, "файл решения не сохранён")
        self.assertEqual(saved[0].read_text(encoding="utf-8"), "print(1)\n")

    def test_cancel_from_task_input(self):
        """Esc из ввода задачи возвращает в меню без генерации."""
        keys = ["enter", "esc", "q"]
        app, history = self.run_app(keys)
        self.assertEqual(app.exit_code, 0)
        self.assertNotIn("BusyScreen", history)
        self.assertFalse(list(self.tmp.glob("*.py")), "файл не должен создаваться")

    def test_custom_path_and_unique_filename(self):
        """Ручной путь + сохранение; повторное сохранение создаёт суффикс _1."""
        keys = [
            "enter", "з", "а", "д", "а", "ч", "а",
            "ctrl-enter",
            "down", "down", "down", "down", "down",  # «Ввести путь вручную...»
            "enter",
            "s", "u", "b", "d", "i", "r",           # путь subdir
            "enter",
            "enter",                                 # автоимя
            ("pause", 0.35),
            "enter",                                 # сохранить
            # снова то же самое → уникальное имя
            "enter", "з", "а", "д", "а", "ч", "а",
            "ctrl-enter",
            "down", "down", "down", "down", "down",
            "enter", "s", "u", "b", "d", "i", "r", "enter",
            "enter",
            ("pause", 0.35),
            "enter",
            "q",
        ]
        app, history = self.run_app(keys)
        self.assertEqual(app.exit_code, 0)
        subdir = self.tmp / "subdir"
        files = sorted(subdir.glob("*.py"))
        self.assertEqual(len(files), 2, f"ожидалось 2 файла (обычный и _1), найдено: {files}")
        self.assertEqual(files[0].name, "zadacha.py")
        self.assertEqual(files[1].name, "zadacha_1.py")

    def test_preview_scroll_and_regenerate(self):
        """Прокрутка кода, перегенерация и копирование в предпросмотре."""
        calls = {"n": 0}

        def solve(prompt, provider=None, api_key=None, custom_url=None):
            calls["n"] += 1
            lines = [f"print({i})" for i in range(30)]
            return ("\n".join(lines) + "\n", provider or "gigachat")

        keys = [
            "enter", "т", "е", "с", "т",
            "ctrl-enter", "enter", "enter",
            ("pause", 0.35),
            "down", "down",        # прокрутка вниз
            "pgdn",
            "home",
            "r",                   # перегенерировать
            ("pause", 0.35),
            "enter",               # сохранить
            "q",
        ]
        app, history = self.run_app(keys, solve_fn=solve)
        self.assertEqual(app.exit_code, 0)
        self.assertGreaterEqual(calls["n"], 2, "перегенерация не вызвана")
        self.assertGreaterEqual(history.count("PreviewScreen"), 2)

    def test_settings_provider_cycle_and_edit(self):
        """Смена провайдера и редактирование ключа в настройках."""
        keys = [
            "down", "down",   # «Провайдеры ИИ и настройки»
            "enter",          # открыть настройки (sel=0 — провайдер)
            "enter",          # переключить gigachat → gemini
            "down", "enter",  # DeepSeek API-ключ → редактирование
            "s", "k", "-", "t", "e", "s", "t",
            "enter",          # сохранить ключ
            "esc",            # назад в меню
            "q",
        ]
        app, history = self.run_app(keys)
        self.assertEqual(app.exit_code, 0)
        self.assertEqual(app.cfg["provider"], "gemini")
        self.assertEqual(app.cfg["deepseek_api_key"], "sk-test")
        cfg = run.load_config()
        self.assertEqual(cfg["provider"], "gemini")
        self.assertEqual(cfg["deepseek_api_key"], "sk-test")

    def test_busy_cancel(self):
        """Отмена ожидания генерации (Esc в BusyScreen) не создаёт файл."""
        def slow_solve(prompt, provider=None, api_key=None, custom_url=None):
            time.sleep(1.5)
            return ("print(1)\n", provider or "gigachat")

        keys = [
            "enter", "т", "ctrl-enter", "enter", "enter",
            ("pause", 0.15),
            "esc",             # отмена во время генерации
            "esc",             # из TaskInput назад
            "q",
        ]
        app, history = self.run_app(keys, solve_fn=slow_solve)
        self.assertEqual(app.exit_code, 0)
        self.assertIn("BusyScreen", history)
        self.assertNotIn("PreviewScreen", history)
        self.assertFalse(list(self.tmp.glob("*.py")), "файл не должен сохраниться после отмены")

    def test_error_during_generation_shows_toast(self):
        """Ошибка генерации возвращает на ввод задачи с уведомлением."""
        def failing(prompt, provider=None, api_key=None, custom_url=None):
            raise RuntimeError("сеть недоступна")

        keys = [
            "enter", "т", "ctrl-enter", "enter", "enter",
            ("pause", 0.35),
            "esc",
            "q",
        ]
        app, history = self.run_app(keys, solve_fn=failing)
        self.assertEqual(app.exit_code, 0)
        self.assertNotIn("PreviewScreen", history)
        self.assertIn("TaskInputScreen", history)

    def test_help_screen(self):
        keys = ["?", "enter", "q"]
        app, history = self.run_app(keys)
        self.assertEqual(app.exit_code, 0)
        self.assertIn("HelpScreen", history)


class TestCoreFunctions(unittest.TestCase):
    def test_clean_keeps_hash_in_strings(self):
        src = "print('#')  # комментарий\n"
        out = run.remove_comments_and_docstrings(src)
        self.assertIn("print('#')", out)
        self.assertNotIn("комментарий", out)

    def test_clean_removes_bare_docstrings_anywhere(self):
        src = 'a = 1\n"""пояснение"""\nb = 2\n'
        out = run.remove_comments_and_docstrings(src)
        self.assertNotIn("пояснение", out)
        self.assertIn("a = 1", out)
        self.assertIn("b = 2", out)

    def test_extract_fenced(self):
        self.assertEqual(run.extract_code("текст\n```python3\nprint(42)\n```\nещё"), "print(42)")
        self.assertEqual(run.extract_code("просто код print(7)"), "просто код print(7)")

    def test_fallback_switches_to_gigachat(self):
        attempts = []

        def fake_solve(prompt, provider=None, api_key=None, custom_url=None):
            attempts.append(provider)
            if provider != "gigachat":
                raise RuntimeError("провайдер упал")
            return "print(9)\n"

        old_gen = run.generate_code_clean
        run.generate_code_clean = fake_solve
        try:
            code, used = run.generate_code_with_fallback("задача", provider="deepseek", err_out=None)
            self.assertEqual(code, "print(9)\n")
            self.assertEqual(used, "gigachat")
            self.assertEqual(attempts, ["deepseek", "gigachat"])
        finally:
            run.generate_code_clean = old_gen

    def test_fallback_disabled_raises(self):
        def fake_solve(prompt, provider=None, api_key=None, custom_url=None):
            raise RuntimeError("провайдер упал")

        old_gen = run.generate_code_clean
        run.generate_code_clean = fake_solve
        try:
            with self.assertRaises(RuntimeError):
                run.generate_code_with_fallback("задача", provider="deepseek", allow_fallback=False)
        finally:
            run.generate_code_clean = old_gen

    def test_fallback_skips_known_dead_provider(self):
        """Провайдер с ошибкой авторизации пропускается без повторного ожидания."""
        run.clear_provider_dead()
        run.mark_provider_dead("gemini", "invalid key", ttl=60)
        attempts = []

        def fake_solve(prompt, provider=None, api_key=None, custom_url=None):
            attempts.append(provider)
            return "print(1)\n"

        old_gen = run.generate_code_clean
        run.generate_code_clean = fake_solve
        try:
            code, used = run.generate_code_with_fallback("задача", provider="gemini", err_out=False)
            self.assertEqual(used, "gigachat")
            self.assertEqual(attempts, ["gigachat"], "мёртвый провайдер не должен вызываться повторно")
        finally:
            run.generate_code_clean = old_gen
            run.clear_provider_dead()

    def test_auth_error_marks_provider_dead(self):
        """Ошибка авторизации помечает провайдера недоступным на время."""
        run.clear_provider_dead()

        def fake_solve(prompt, provider=None, api_key=None, custom_url=None):
            if provider != "gigachat":
                raise RuntimeError("HTTP 401: invalid authentication credentials")
            return "print(2)\n"

        old_gen = run.generate_code_clean
        run.generate_code_clean = fake_solve
        try:
            code, used = run.generate_code_with_fallback("задача", provider="deepseek", err_out=False)
            self.assertEqual(used, "gigachat")
            self.assertIsNotNone(run.provider_dead_reason("deepseek"))
            # повторный вызов уже не трогает мёртвый провайдер
            calls = []
            run.generate_code_clean = lambda prompt, provider=None, **kw: (calls.append(provider), "print(3)\n")[1]
            run.generate_code_with_fallback("задача", provider="deepseek", err_out=False)
            self.assertEqual(calls, ["gigachat"])
        finally:
            run.generate_code_clean = old_gen
            run.clear_provider_dead()

    def test_version_compare(self):
        self.assertGreater(run.parse_version("3.0.0"), run.parse_version("2.1.1"))
        self.assertEqual(run.parse_version("бред"), (0,))

    def test_validate_code(self):
        ok, err = run.validate_code("a = 1\nprint(a)\n")
        self.assertTrue(ok, err)
        bad_ok, bad_err = run.validate_code("for_iin range(3):\n    pass\n")
        self.assertFalse(bad_ok)
        self.assertTrue(bad_err)
        empty_ok, _ = run.validate_code("")
        self.assertFalse(empty_ok)

    def test_retry_on_syntax_error(self):
        """Синтаксически битый ответ модели приводит к повторной генерации."""
        responses = ["for_iin range(3):\n    pass\n", "for i in range(3):\n    print(i)\n"]
        calls = []

        def fake_solve(prompt, provider=None, api_key=None, custom_url=None):
            calls.append(prompt)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        old_gen = run.generate_code_clean
        run.generate_code_clean = fake_solve
        try:
            code, used = run.generate_code_with_fallback("задача", provider="gigachat", err_out=False)
            self.assertEqual(len(calls), 2, "должна быть повторная попытка")
            self.assertIn(run._CORRECTIVE_HINT, calls[1], "повторный запрос должен содержать подсказку")
            ok, err = run.validate_code(code)
            self.assertTrue(ok, f"итоговый код должен быть корректным: {err}")
        finally:
            run.generate_code_clean = old_gen

    def test_panel_widths(self):
        lines = run._panel_lines("Заголовок", ["содержимое"], 40)
        self.assertEqual(len(lines), 3)
        self.assertEqual(run._visible_len(lines[0]), 40)
        self.assertEqual(run._visible_len(lines[1]), 40)
        self.assertEqual(run._visible_len(lines[2]), 40)

    def test_textbuffer_editing(self):
        b = run.TextBuffer("")
        b.insert_text("ab")
        b.move(-1, 0)
        b.insert("X")
        self.assertEqual(b.text(), "aXb")
        b.home()
        b.delete()
        self.assertEqual(b.text(), "Xb")
        b.end()
        b.insert_text("\ncd")
        self.assertEqual(b.lines, ["Xb", "cd"])
        b.cy = 0
        b.end()
        b.delete()
        self.assertEqual(b.text(), "Xbcd")

    def test_fit_and_strip(self):
        self.assertEqual(run.fit("abcdef", 4), "abcd")
        self.assertEqual(run._visible_len(run.UI.c("abc", run.UI.GREEN)), 3)
        self.assertEqual(run.UI.strip_ansi("\033[1;95mfor\033[0m"), "for")


class TestSelftestEmbedded(unittest.TestCase):
    def test_builtin_selftest_passes(self):
        ok = run.run_selftest()
        self.assertTrue(ok, "встроенный --selftest должен проходить")


if __name__ == "__main__":
    unittest.main(verbosity=2)
