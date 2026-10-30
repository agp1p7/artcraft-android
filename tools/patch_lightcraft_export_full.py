import os
import re
import sys
from pathlib import Path
from patch_lightcraft_export_progress import PANEL as BASE_PANEL

HOST = r"""
static LIGHTCRAFT_EXPORT_APP: std::sync::Mutex<Option<android_activity::AndroidApp>> = std::sync::Mutex::new(None);
fn lightcraft_export_services(mut services: lightcraft_ui_egui::Services) -> lightcraft_ui_egui::Services {
    services.write_shared = Some(std::sync::Arc::new(|path, bytes| {
        let result = (|| -> Result<(), String> {
            let app = LIGHTCRAFT_EXPORT_APP.lock().unwrap_or_else(|e| e.into_inner()).clone().ok_or("Android activity not ready")?;
            lightcraft_engine::export::write_file(path, bytes)?;
            let receipt = saf::Bridge::new(&app).commit(path)?;
            match receipt.as_str() {
                "OK" | "NONE" => Ok(()),
                _ => Err(format!("Android destination commit failed: {}", receipt)),
            }
        })();
        lightcraft_ui_egui::export_task::local_export_note_io(result.is_ok());
        result
    }));
    services
}
"""
IO_STATE = r"""
static LOCAL_EXPORT_IO: std::sync::Mutex<(u64, u64)> = std::sync::Mutex::new((0, 0));
pub fn local_export_note_io(ok: bool) {
    let mut io = LOCAL_EXPORT_IO.lock().unwrap_or_else(|e| e.into_inner());
    if ok { io.0 += 1; } else { io.1 += 1; }
}
fn local_export_reset_io() {
    *LOCAL_EXPORT_IO.lock().unwrap_or_else(|e| e.into_inner()) = (0, 0);
}
fn local_export_io() -> (u64, u64) {
    *LOCAL_EXPORT_IO.lock().unwrap_or_else(|e| e.into_inner())
}
"""
RAW = re.compile(r'(?:br|cr|r)(#*)"')
CHAR = re.compile(r"'(?:\\u\{[0-9a-fA-F_]+\}|\\x[0-9a-fA-F]{2}|\\.|[^'\\\n])'")


def code_mask(text):
    out = list(text)
    i = 0
    while i < len(text):
        start = i
        if text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end
        elif text.startswith('/*', i):
            depth = 1
            i += 2
            while i < len(text) and depth:
                if text.startswith('/*', i):
                    depth += 1
                    i += 2
                elif text.startswith('*/', i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth:
                raise RuntimeError('Unterminated block comment')
        else:
            raw = RAW.match(text, i)
            char = CHAR.match(text, i)
            if raw:
                end = text.find('"' + raw.group(1), raw.end())
                if end < 0:
                    raise RuntimeError('Unterminated raw string')
                i = end + 1 + len(raw.group(1))
            elif text[i] == '"':
                i += 1
                while i < len(text):
                    if text[i] == '\\':
                        i += 2
                    elif text[i] == '"':
                        i += 1
                        break
                    else:
                        i += 1
                else:
                    raise RuntimeError('Unterminated string')
            elif char:
                i = char.end()
            else:
                i += 1
                continue
        out[start:i] = ['\n' if c == '\n' else ' ' for c in text[start:i]]
    return ''.join(out)


def wrap_services(text):
    mask = code_mask(text)
    pattern = r'(?<![\w:])(?:\w+::)*Services\s*(?:::default\s*\(\s*\)|\{)'
    matches = [m for m in re.finditer(pattern, mask) if not re.search(r'\b(?:struct|enum|impl|trait)\s*$', mask[:m.start()])]
    if len(matches) != 1:
        raise RuntimeError(f'Full-export phase=services-initializer expected=1 actual={len(matches)}')
    m = matches[0]
    end = m.end()
    if mask[end - 1] == '{':
        depth = 1
        while end < len(mask) and depth:
            depth += (mask[end] == '{') - (mask[end] == '}')
            end += 1
        if depth:
            raise RuntimeError('Full-export phase=services-initializer unbalanced braces')
    return text[:m.start()] + 'lightcraft_export_services(' + text[m.start():end] + ')' + text[end:]


def replace_one(text, old, new, phase):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Full-export phase={phase} expected=1 actual={count} anchor={old!r}')
    return text.replace(old, new, 1)


def prepare():
    from patch_lightcraft_gpu_diagnostics_v2 import JAVA
    path = Path(__file__).resolve().parents[1] / 'templates/android/SafActivity.java'
    block = JAVA.replace('LightCraft GPU diagnostics v2', 'LightCraft GPU candidate v6-windowed-checked')
    block = block.replace('button.setText("匯出 GPU 日誌");', 'button.setText("匯出 GPU 日誌 v6");')
    text = replace_one(path.read_text(), block, '', 'remove-java-log-export')
    text = replace_one(text, '        installGpuDiagExport();\n', '', 'remove-log-startup-call')
    if any(marker in text for marker in ['installGpuDiagExport', 'exportGpuLog', 'gpuDiagSaving', 'gpu-diag-export']):
        raise RuntimeError('Full-export phase=remove-java-log-export residual entry point')
    path.write_text(text)
    print('Full-export: Java log export implementation and floating button removed', flush=True)


def panel():
    text = replace_one(BASE_PANEL, '    if app.export.is_none() && app.last_export_result.is_none() { return; }\n', '', 'always-visible-panel')
    text = replace_one(text, '.exact_size(112.0)', '.exact_size(148.0)', 'panel-height')
    marker = re.sub(r'[^0-9a-zA-Z_-]', '', os.environ.get('GITHUB_SHA', 'local'))[:7]
    text = replace_one(text, '        .show(ui, |ui| {\n', '        .show(ui, |ui| {\n            ui.label("匯出進度 · build ' + marker + '");\n', 'build-marker')
    text = replace_one(text, '                    let total = task.total;\n', '                    let total = task.total;\n                    let io = local_export_io();\n', 'io-snapshot')
    text = replace_one(text, '                    ui.label("等待寫入完成；成功與失敗數將於結束後顯示。");', '                    ui.label(format!("檔案寫入：成功 {} · 失敗 {}（成功含目的地提交）", io.0, io.1));\n                    ui.label("照片成功／失敗／跳過數，以結束後結果為準。");', 'io-label')
    text = replace_one(text, '                }\n            });', '                } else {\n                    ui.label(if app.services.write_shared.is_some() { "背景匯出已連接，等待開始匯出。" } else { "背景匯出未連接：此版本未完成整合。" });\n                }\n            });', 'idle-state')
    return text


def patch(root):
    root = root.resolve()
    launcher = root / 'src/lib.rs'
    source = launcher.read_text()
    if 'LIGHTCRAFT_EXPORT_APP' in source:
        raise RuntimeError('Full-export already applied; use fresh generated sources')
    mask = code_mask(source)
    pattern = r'\bfn\s+android_main\s*\(\s*(?:mut\s+)?(\w+)\s*:\s*(?:\w+::)*AndroidApp\s*,?\s*\)\s*\{'
    mains = list(re.finditer(pattern, mask))
    if len(mains) != 1:
        raise RuntimeError(f'Full-export phase=android-main expected=1 actual={len(mains)}')
    m = mains[0]
    source = source[:m.end()] + '\n    *LIGHTCRAFT_EXPORT_APP.lock().unwrap_or_else(|e| e.into_inner()) = Some(' + m.group(1) + '.clone());' + source[m.end():]
    source = wrap_services(source) + '\n' + HOST
    ui = root.parents[1] / 'crates/ui-egui/src'
    task = ui / 'export_task.rs'
    bottom = ui / 'panels/bottombar.rs'
    pending = {launcher: source}
    anchor = 'pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) {'
    pending[bottom] = replace_one(bottom.read_text(), anchor, anchor + '\n    crate::export_task::local_export_progress_panel(app, ui);', 'bottom-panel')
    text = task.read_text()
    busy = '    if app.export.is_some() {\n        return Err("an export is already running".into());\n    }\n'
    if text.count(busy) != 3:
        raise RuntimeError(f'Full-export phase=task-start expected=3 actual={text.count(busy)}')
    text = text.replace(busy, busy + '    app.last_export_result = None;\n    local_export_reset_io();\n')
    text = replace_one(text, '                Err(e) => e,', '                Err(e) => { app.last_export_result = Some(json!({"error": e.clone()})); e },', 'worker-error')
    text = replace_one(text, '            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));', '            app.last_export_result = Some(json!({"error": "匯出意外中止"}));\n            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));', 'worker-disconnected')
    pending[task] = text + '\n' + IO_STATE + '\n' + panel()
    for path, value in pending.items():
        path.write_text(value)
    print('Full-export installed: background writer plus SAF commit, live file receipts, persistent results, visible build marker; APK and device validation required', flush=True)


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
