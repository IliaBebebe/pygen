#!/usr/bin/env bash
# ==============================================================================
# PyGen Installer: Полная установка без sudo для Linux
# Устанавливает: CLI (pygen), GUI (pygen -g), расширения для VS Code, IDLE, PyCharm
# ==============================================================================

set -e

GITHUB_RAW="https://raw.githubusercontent.com/IliaBebebe/pygen/main"
REXCORP_RAW="https://rexcorp.space/1581"
LOCAL_BIN="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
VSCODE_EXT_DIR="$HOME/.vscode/extensions/pygen"
IDLE_DIR="$HOME/.idlerc"

# Определение команды python3
PYTHON_BIN="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON_BIN" ]; then
    echo "[!] Ошибка: Python 3 не найден в системе. Установите python3."
    exit 1
fi

echo "=========================================================="
echo "          🚀 Установка PyGen (без root / без sudo)         "
echo "=========================================================="
echo "[*] Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

mkdir -p "$LOCAL_BIN"
mkdir -p "$DESKTOP_DIR"

# Определяем, запущен ли скрипт из клонированного репозитория или через curl | bash
SCRIPT_DIR=""
if [ -n "${BASH_SOURCE[0]}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

fetch_or_copy() {
    local rel_path="$1"
    local dest_path="$2"
    if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/$rel_path" ]; then
        cp "$SCRIPT_DIR/$rel_path" "$dest_path"
    else
        # Пробуем зеркало rexcorp.space, затем GitHub
        if ! curl -fsSL "$REXCORP_RAW/$rel_path" -o "$dest_path" 2>/dev/null || [ ! -s "$dest_path" ]; then
            curl -sL "$GITHUB_RAW/$rel_path" -o "$dest_path"
        fi
    fi
}

# 1. Установка основного исполняемого файла в ~/.local/bin/pygen
echo "[1/5] Установка основного скрипта в $LOCAL_BIN/pygen..."
fetch_or_copy "run.py" "$LOCAL_BIN/pygen"
chmod +x "$LOCAL_BIN/pygen"

# Создание ярлыка для быстрого запуска GUI
cat << 'EOF' > "$LOCAL_BIN/pygen-gui"
#!/usr/bin/env bash
exec "$HOME/.local/bin/pygen" --gui "$@"
EOF
chmod +x "$LOCAL_BIN/pygen-gui"

# 2. Добавление ~/.local/bin в PATH (в .bashrc и .zshrc)
echo "[2/5] Проверка переменной окружения PATH..."
ADD_PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'

for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    if [ -f "$rc" ]; then
        if ! grep -q '\.local/bin' "$rc"; then
            echo "$ADD_PATH_LINE" >> "$rc"
            echo "    -> Добавлен PATH в $rc"
        fi
    fi
done

# 3. Установка Desktop ярлыка для Linux
echo "[3/5] Создание Desktop-ярлыка..."
cat << EOF > "$DESKTOP_DIR/pygen.desktop"
[Desktop Entry]
Name=Заметки
Comment=Скрытный черновик и генератор кода
Exec=$LOCAL_BIN/pygen --gui
Icon=text-editor
Terminal=false
Type=Application
Categories=Utility;Development;
EOF
chmod +x "$DESKTOP_DIR/pygen.desktop"

# 4. Установка расширений для IDE (VS Code, IDLE, PyCharm)
echo "[4/5] Установка расширений для редакторов..."

# --- VS Code ---
mkdir -p "$VSCODE_EXT_DIR"
fetch_or_copy "extensions/vscode/package.json" "$VSCODE_EXT_DIR/package.json"
fetch_or_copy "extensions/vscode/extension.js" "$VSCODE_EXT_DIR/extension.js"
echo "    [✓] VS Code: установлено в ~/.vscode/extensions/pygen (Горячая клавиша: Ctrl+Alt+G)"

# --- IDLE ---
mkdir -p "$IDLE_DIR"
fetch_or_copy "extensions/idle/PyGen.py" "$IDLE_DIR/PyGen.py"
fetch_or_copy "extensions/idle/pygen_idle.py" "$IDLE_DIR/pygen_idle.py"

# Копируем модуль в user site-packages, чтобы IDLE видел модуль без root
USER_SITE="$($PYTHON_BIN -m site --user-site 2>/dev/null || true)"
if [ -n "$USER_SITE" ]; then
    mkdir -p "$USER_SITE"
    cp "$IDLE_DIR/PyGen.py" "$USER_SITE/PyGen.py"
    cp "$IDLE_DIR/pygen_idle.py" "$USER_SITE/pygen_idle.py"
    # Создаем .pth файл на случай нестандартных путей
    echo "$IDLE_DIR" > "$USER_SITE/pygen.pth"
fi

# Настройка конфига IDLE
CFG_EXT="$IDLE_DIR/config-extensions.cfg"
if [ ! -f "$CFG_EXT" ]; then
    cat << 'EOF' > "$CFG_EXT"
[PyGen]
enable=True

[PyGen_cfgBindings]
pygen-solution=<Alt-Key-g>
EOF
else
    if ! grep -q '\[PyGen\]' "$CFG_EXT"; then
        cat << 'EOF' >> "$CFG_EXT"

[PyGen]
enable=True

[PyGen_cfgBindings]
pygen-solution=<Alt-Key-g>
EOF
    fi
fi
echo "    [✓] IDLE: установлено в ~/.idlerc (Горячая клавиша: Alt+G)"

# --- PyCharm / JetBrains ---
JB_DIR="$HOME/.config/JetBrains"
if [ -d "$JB_DIR" ]; then
    for ide in "$JB_DIR"/*; do
        if [ -d "$ide" ]; then
            TOOLS_DIR="$ide/tools"
            mkdir -p "$TOOLS_DIR"
            TARGET_XML="$TOOLS_DIR/External Tools.xml"
            if [ ! -f "$TARGET_XML" ]; then
                fetch_or_copy "extensions/pycharm/External_Tools.xml" "$TARGET_XML"
            else
                if ! grep -q 'PyGen' "$TARGET_XML"; then
                    # Если файл уже есть, добавляем инструмент в существующий набор
                    TMP_TOOL="/tmp/pygen_tool_$$.xml"
                    fetch_or_copy "extensions/pycharm/External_Tools.xml" "$TMP_TOOL"
                    # Извлекаем tool блоки и вставляем перед </toolSet>
                    sed -i '$ d' "$TARGET_XML" # удаляем последнюю строку </toolSet>
                    cat << 'EOF' >> "$TARGET_XML"
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
</toolSet>
EOF
                    rm -f "$TMP_TOOL"
                fi
            fi
            echo "    [✓] PyCharm ($(basename "$ide")): настроены External Tools"
        fi
    done
else
    echo "    [-] JetBrains каталог пока не найден (создастся при первом запуске PyCharm)"
fi

# 5. Тестовая проверка работоспособности
echo "[5/5] Финальная проверка работоспособности..."
export PATH="$HOME/.local/bin:$PATH"

echo "=========================================================="
echo "          🎉 Установка успешно завершена!                 "
echo "=========================================================="
echo ""
echo "📌 Способы использования:"
echo ""
echo "1. В терминале (CLI):"
echo "   pygen \"задание\" -dt        # Сохранить решение на Рабочий стол"
echo "   pygen -c                 # Решить задание ПРЯМО ИЗ БУФЕРА ОБМЕНА"
echo "   pygen                    # Интерактивный режим (поддерживает многострочную вставку)"
echo ""
echo "2. Скрытный компактный GUI:"
echo "   pygen -g                 # Открыть маленький скрытный интерфейс (Заметки)"
echo "   (В GUI: Ctrl+Enter — решить, Esc — мгновенно спрятать)"
echo ""
echo "3. В редакторах кода:"
echo "   - VS Code: выделите условие (или нажмите Ctrl+Alt+G) -> вставит готовый код"
echo "   - IDLE:    выделите условие и нажмите Alt+G -> вставит код"
echo "   - PyCharm: Меню Tools -> External Tools -> PyGen: Решить из буфера"
echo ""
echo "4. ИИ Провайдеры:"
echo "   - По умолчанию: GigaChat (работает в РФ без VPN, 100% бесплатно)"
echo "   - DeepSeek: pygen --deepseek -k ВАШ_КЛЮЧ (или в настройках GUI)"
echo ""
