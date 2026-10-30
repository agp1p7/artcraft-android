import os
import re
import sys
from pathlib import Path

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
    raw_matches = list(re.finditer(pattern, mask))
    ranges = []
    for m in raw_matches:
        prefix = mask[:m.start()]
        if re.search(r'\b(?:struct|enum|impl|trait|for|let)\s*$', prefix):
            continue
        if re.search(r'->\s*(?:&\s*(?:\x27\w+\s*)?(?:mut\s+)?)?$', prefix):
            continue
        end = m.end()
        if mask[end - 1] == '{':
            depth = 1
            while end < len(mask) and depth:
                depth += (mask[end] == '{') - (mask[end] == '}')
                end += 1
            if depth:
                raise RuntimeError('Full-export phase=services-initializer unbalanced braces')
        ranges.append((m.start(), end))
    outer = [(start, end) for start, end in ranges if not any(a < start and end <= b for a, b in ranges)]
    print(f'Full-export Services scan raw={len(raw_matches)} initializers={len(ranges)} outer={len(outer)}', flush=True)
    if len(outer) != 1:
        details = []
        for m in raw_matches:
            line = text.count('\n', 0, m.start()) + 1
            context = ' '.join(text[max(0, m.start() - 60):m.end() + 80].split())[:180]
            details.append(f'line {line}: {context}')
        raise RuntimeError(f'Full-export phase=services-initializer expected=1 actual={len(outer)} raw={len(raw_matches)} candidates={details}')
    start, end = outer[0]
    return text[:start] + 'lightcraft_export_services(' + text[start:end] + ')' + text[end:]


def replace_one(text, old, new, phase):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Full-export phase={phase} expected=1 actual={count} anchor={old!r}')
    return text.replace(old, new, 1)


def prepare():
    import subprocess
    subprocess.run([sys.executable, str(Path(__file__).with_name('test_lightcraft_export_full.py'))], check=True)
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
    marker = re.sub(r'[^0-9a-zA-Z_-]', '', os.environ.get('GITHUB_SHA', 'local'))[:7]
    return r"""
pub fn local_export_progress_panel(app: &mut crate::LightcraftApp, ui: &mut egui::Ui) {
    let Some(task) = &app.export else { return; };
    let status = task.status();
    let total = task.total;
    let started = status.get("done").and_then(Value::as_u64).unwrap_or(0).min(total as u64);
    let current = status.get("current").and_then(Value::as_str).unwrap_or("");
    let io = local_export_io();
    let width = (ui.ctx().content_rect().width() - 32.0).clamp(160.0, 340.0);
    let position = ui.ctx().content_rect().center() - egui::vec2(width * 0.5, 70.0);
    egui::Window::new("匯出進度")
        .id(egui::Id::new("lightcraft_export_progress_window"))
        .collapsible(false)
        .resizable(false)
        .movable(true)
        .default_width(width)
        .default_pos(position)
        .show(ui.ctx(), |ui| {
            ui.set_max_width(width);
            ui.label(format!("已開始 {} / {} 張（非完成數）", started, total));
            let fraction = if total > 1 { Some((started as f32 / total as f32).min(0.99)) } else { None };
            crate::progress::Progress::new(fraction).widget("progress:localExport").show(ui);
            if !current.is_empty() {
                ui.add(egui::Label::new(format!("目前：{}", current)).truncate());
            }
            ui.label(format!("檔案寫入：成功 {} · 失敗 {}", io.0, io.1));
            ui.small("寫入成功包含目的地提交；照片結果於結束時提示。");
            ui.small("build __BUILD__");
        });
    ui.ctx().request_repaint_after(std::time::Duration::from_millis(100));
}
""".replace('__BUILD__', marker)


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
