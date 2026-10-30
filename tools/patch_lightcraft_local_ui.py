from local_ui_parts import UI, ENGINE, LAUNCH, BRIDGE, SETTINGS
import re
import sys
from pathlib import Path

def once(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected source anchor: {path}: {old[:70]}')
    path.write_text(text.replace(old, new, 1))

def close_paren(text, start):
    depth = 1
    i = start
    while i < len(text):
        if text.startswith('//', i):
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        if text[i] == '"':
            i += 1
            while i < len(text):
                if text[i] == "\\":
                    i += 2
                elif text[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise RuntimeError('Unbalanced export result expression')

def prepare():
    p = Path('templates/android/SafActivity.java')
    text = p.read_text()
    prefix = r'    private void installGpuDiagExport\(\) \{.*?        button\.setOnClickListener\(v -> \{'
    text, count = re.subn(prefix, '    public void exportGpuLog() {', text, flags=re.S)
    if count != 1:
        raise RuntimeError('Expected one GPU log button method')
    ending = '            }, "gpu-diag-export").start();\n        });\n    }'
    if text.count(ending) != 1:
        raise RuntimeError('Unexpected log export ending')
    text = text.replace(ending, '            }, "gpu-diag-export").start();\n    }', 1)
    call = '        installGpuDiagExport();\n'
    if text.count(call) != 1:
        raise RuntimeError('Unexpected floating button call')
    p.write_text(text.replace(call, '', 1))

def patch(root):
    upstream = root.parents[1]
    ui = upstream / 'crates/ui-egui/src'
    engine = upstream / 'crates/engine/src/export.rs'
    once(ui / 'lib.rs', '    pub picker: Option<pick::Picker>,', '    #[cfg(target_os = "android")]\n    pub gpu_log_export: Option<Box<dyn FnMut() -> Result<(), String>>>,\n    pub picker: Option<pick::Picker>,')
    settings = ui / 'panels/settings.rs'
    once(settings, 'fn general_tab(app: &mut LightcraftApp, ui: &mut egui::Ui, t: &Tokens) {', 'fn general_tab(app: &mut LightcraftApp, ui: &mut egui::Ui, t: &Tokens) {\n' + SETTINGS)
    once(ui / 'panels/bottombar.rs', 'pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) {', 'pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) {\n    crate::export_task::local_export_panel(app, ui);')
    text = engine.read_text()
    matches = list(re.finditer(r'self\.out\.push\(', text))
    if not matches:
        raise RuntimeError('Export result queue not found; inspect v0.14.0 placement code')
    for m in reversed(matches):
        end = close_paren(text, m.end())
        text = text[:m.end()] + 'local_observe_export(' + text[m.end():end] + ')' + text[end:]
    engine.write_text(text + '\n' + ENGINE)
    task = ui / 'export_task.rs'
    once(task, '    pub total: usize,', '    pub total: usize,\n    pub local_status: Arc<Mutex<LocalExportStatus>>,')
    once(task, '    let total = items.len();', '    let total = items.len();\n    app.last_export_result = None;\n    let local_status = Arc::new(Mutex::new(LocalExportStatus::default()));')
    text = task.read_text()
    anchor = '    let work = move || {'
    if anchor not in text:
        raise RuntimeError('Missing background export worker')
    worker = '    let local_worker = local_status.clone();\n' + anchor + '\n        lightcraft_engine::export::local_set_export_observer(Some(Box::new(move |v| {\n            let mut s = local_worker.lock().unwrap_or_else(|e| e.into_inner());\n            s.processed += 1;\n            if v.get("error").is_some() { s.failed += 1; }\n            else if v.get("skipped").is_some() { s.skipped += 1; }\n            else if v.get("path").is_some() { s.success += 1; }\n            else { s.failed += 1; }\n        })));'
    task.write_text(text.replace(anchor, worker, 1))
    once(task, '    app.export = Some(ExportTask { total, progress, cancel, rx, guard });', '    app.export = Some(ExportTask { total, progress, cancel, rx, guard, local_status });')
    text = task.read_text()
    old = 'ExportTask { total, progress, cancel, rx, guard: row }'
    if text.count(old) != 2:
        raise RuntimeError('Unexpected PDF task constructors')
    task.write_text(text.replace(old, 'ExportTask { total, progress, cancel, rx, guard: row, local_status: Arc::new(Mutex::new(LocalExportStatus::default())) }'))
    once(task, '                Err(e) => e,', '                Err(e) => { app.last_export_result = Some(json!({"error": e.clone()})); e },')
    once(task, '            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));', '            app.last_export_result = Some(json!({"error": "匯出意外中止"}));\n            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));')
    task.write_text(task.read_text() + '\n' + UI)
    bridge_files = [p for p in (root / 'src').rglob('*.rs') if 'pub fn request_open(&self, id: u64, multiple: bool)' in p.read_text()]
    if len(bridge_files) != 1:
        raise RuntimeError('Cannot uniquely locate JNI bridge')
    p = bridge_files[0]
    once(p, '        pub fn request_open(&self, id: u64, multiple: bool)', BRIDGE + '\n        pub fn request_open(&self, id: u64, multiple: bool)')
    launcher = root / 'src/lib.rs'
    text = launcher.read_text()
    main = list(re.finditer(r'fn android_main\(\s*(?:mut\s+)?(\w+)\s*:\s*(?:\w+::)*AndroidApp\s*\)\s*\{', text))
    if len(main) != 1:
        raise RuntimeError('Cannot locate android_main activity')
    m = main[0]
    text = text[:m.end()] + '\n    let _ = LIGHTCRAFT_LOCAL_APP.set(' + m.group(1) + '.clone());' + text[m.end():]
    constructors = list(re.finditer(r'\bServices\s*\{', text))
    if len(constructors) != 1:
        raise RuntimeError('Cannot uniquely locate Android Services constructor')
    m = constructors[0]
    fields = '\n        gpu_log_export: Some(Box::new(lightcraft_local_log_export)),'
    if not re.search(r'\bwrite_shared\s*:', text):
        fields += '\n        write_shared: Some(std::sync::Arc::new(lightcraft_local_write)),'
    text = text[:m.end()] + fields + text[m.end():]
    launcher.write_text(text + '\n' + LAUNCH)
    print('Light craft local UI installed: Settings log export, persistent export panel, per-result accounting; GPU files unchanged; native compilation and device validation required')

if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
