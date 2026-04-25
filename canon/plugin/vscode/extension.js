// Canon VS Code extension — phase 1D (minimal sideload-ready surface).
//
// Each command shells out to the `canon` CLI. The extension does NOT
// reimplement Canon logic; it's a thin UX wrapper. This keeps the
// VS Code surface aligned with the Claude Code commands and the bare
// CLI — all three call the same canon executable.

const vscode = require('vscode');
const { spawn } = require('child_process');
const path = require('path');

function canonExecutable() {
  const cfg = vscode.workspace.getConfiguration('canon');
  return cfg.get('executable', 'canon');
}

function workspaceCwd() {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return undefined;
  }
  return folders[0].uri.fsPath;
}

function runInTerminal(name, args) {
  const cwd = workspaceCwd();
  if (!cwd) {
    vscode.window.showErrorMessage('Canon: open a workspace folder first.');
    return;
  }
  const term = vscode.window.createTerminal({ name: `Canon: ${name}`, cwd });
  const cmd = [canonExecutable(), name, ...args].map(quoteIfNeeded).join(' ');
  term.show(true);
  term.sendText(cmd);
}

function quoteIfNeeded(s) {
  if (s === undefined || s === null) return '';
  const str = String(s);
  if (/[\s"']/.test(str)) {
    return `"${str.replace(/"/g, '\\"')}"`;
  }
  return str;
}

function captureCanon(args) {
  return new Promise((resolve) => {
    const cwd = workspaceCwd();
    if (!cwd) {
      resolve({ code: -1, stdout: '', stderr: 'No workspace folder open.' });
      return;
    }
    const proc = spawn(canonExecutable(), args, { cwd, shell: false });
    let stdout = '';
    let stderr = '';
    proc.stdout.on('data', (d) => (stdout += d.toString()));
    proc.stderr.on('data', (d) => (stderr += d.toString()));
    proc.on('error', (err) => {
      resolve({ code: -1, stdout, stderr: stderr + String(err) });
    });
    proc.on('close', (code) => resolve({ code, stdout, stderr }));
  });
}

async function cmdSpecify() {
  const slug = await vscode.window.showInputBox({
    prompt: 'Spec slug (e.g. cache-layer)',
    placeHolder: 'kebab-case-slug',
    validateInput: (v) => (v && /^[a-z0-9-]+$/.test(v) ? null : 'Use lowercase, digits, and dashes only.'),
  });
  if (!slug) return;
  const ns = await vscode.window.showInputBox({
    prompt: 'Optional north-star slug to cite (leave blank to pick interactively)',
    placeHolder: 'agent-first-tooling',
  });
  const args = [slug];
  if (ns) args.push('--from-north-star', ns);
  runInTerminal('specify', args);
}

async function cmdPlan() {
  const specId = await vscode.window.showInputBox({
    prompt: 'Spec id (directory under .pedia/specs/, e.g. 001-cache-layer)',
    placeHolder: 'NNN-slug',
  });
  if (!specId) return;
  runInTerminal('plan', [specId]);
}

async function cmdTasks() {
  const specId = await vscode.window.showInputBox({
    prompt: 'Spec id to derive Hopewell tasks from',
    placeHolder: 'NNN-slug',
  });
  if (!specId) return;
  runInTerminal('tasks', [specId]);
}

async function cmdCheck() {
  const channel = vscode.window.createOutputChannel('Canon: check');
  channel.show(true);
  channel.appendLine('$ canon check');
  const result = await captureCanon(['check']);
  if (result.stdout) channel.append(result.stdout);
  if (result.stderr) channel.append(result.stderr);
  channel.appendLine(`\n[exit ${result.code}]`);
  if (result.code !== 0) {
    vscode.window.showWarningMessage(`Canon check exited with code ${result.code}. See output channel.`);
  }
}

async function cmdTrace() {
  const id = await vscode.window.showInputBox({
    prompt: 'Trace from id (spec-id, HW-NNNN, north-star slug, ...)',
    placeHolder: 'HW-0042 or 001-cache-layer or agent-first-tooling',
  });
  if (!id) return;
  const direction = await vscode.window.showQuickPick(
    [
      { label: 'Up (parent citations)', value: '--up' },
      { label: 'Down (children)', value: '--down' },
      { label: 'Both (no flag)', value: '' },
    ],
    { placeHolder: 'Direction' },
  );
  if (!direction) return;

  const args = ['trace', id, '--format', 'markdown'];
  if (direction.value) args.push(direction.value);

  const result = await captureCanon(args);
  if (result.code !== 0) {
    vscode.window.showErrorMessage(`canon trace failed (exit ${result.code}): ${result.stderr.trim() || 'unknown error'}`);
    return;
  }

  // Open the trace as a virtual markdown document and preview it.
  const doc = await vscode.workspace.openTextDocument({
    language: 'markdown',
    content: result.stdout || '_(empty trace)_',
  });
  await vscode.window.showTextDocument(doc, { preview: true });
  // Best-effort: trigger built-in markdown preview side-by-side.
  try {
    await vscode.commands.executeCommand('markdown.showPreviewToSide');
  } catch (_) {
    // markdown preview command may be unavailable; the text doc is enough.
  }
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand('canon.specify', cmdSpecify),
    vscode.commands.registerCommand('canon.plan', cmdPlan),
    vscode.commands.registerCommand('canon.tasks', cmdTasks),
    vscode.commands.registerCommand('canon.check', cmdCheck),
    vscode.commands.registerCommand('canon.trace', cmdTrace),
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
