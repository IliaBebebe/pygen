const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');
const os = require('os');
const fs = require('fs');

function findPyGenCommand() {
    const candidates = [
        path.join(os.homedir(), '.local', 'bin', 'pygen'),
        path.join(os.homedir(), 'pygen', 'run.py'),
        'pygen'
    ];
    for (const c of candidates) {
        if (fs.existsSync(c)) {
            return c;
        }
    }
    return 'pygen';
}

function activate(context) {
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
                    child = spawn('python3', [pyCmd, '--stdout'], { stdio: ['pipe', 'pipe', 'pipe'] });
                } else {
                    child = spawn(pyCmd, ['--stdout'], { stdio: ['pipe', 'pipe', 'pipe'] });
                }

                let stdoutData = '';
                let stderrData = '';

                child.stdout.on('data', chunk => { stdoutData += chunk.toString(); });
                child.stderr.on('data', chunk => { stderrData += chunk.toString(); });

                child.on('error', err => {
                    vscode.window.showErrorMessage('PyGen не найден. Запустите скрипт установки install.sh');
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
                                    editBuilder.insert(editor.selection.active, stdoutData + '\n');
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
            spawn('python3', [pyCmd, '--gui'], { detached: true, stdio: 'ignore' }).unref();
        } else {
            spawn(pyCmd, ['--gui'], { detached: true, stdio: 'ignore' }).unref();
        }
    });

    context.subscriptions.push(genCommand, guiCommand);
}

function deactivate() {}

module.exports = { activate, deactivate };
