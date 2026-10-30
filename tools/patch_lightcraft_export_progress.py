import sys
from pathlib import Path

PANEL = r"""
pub fn local_export_progress_panel(app: &mut crate::LightcraftApp, ui: &mut egui::Ui) {
    if app.export.is_none() && app.last_export_result.is_none() { return; }
    let mut dismiss = false;
    egui::Panel::bottom("lightcraft_export_progress").exact_size(112.0)
        .frame(egui::Frame::NONE.fill(crate::theme::Tokens::get(ui.ctx()).chrome).inner_margin(egui::Margin::symmetric(12, 6)))
        .show(ui, |ui| {
            egui::ScrollArea::vertical().id_salt("export_progress_scroll").max_height(88.0).show(ui, |ui| {
                if let Some(task) = &app.export {
                    let status = task.status();
                    let total = task.total;
                    let started = status.get("done").and_then(Value::as_u64).unwrap_or(0).min(total as u64);
                    let current = status.get("current").and_then(Value::as_str).unwrap_or("");
                    ui.label(format!("正在匯出：已開始 {} / {} 張（非完成數）", started, total));
                    let fraction = if total > 1 { Some((started as f32 / total as f32).min(0.99)) } else { None };
                    crate::progress::Progress::new(fraction).widget("progress:localExport").show(ui);
                    if !current.is_empty() { ui.label(format!("目前：{}", current)); }
                    ui.label("等待寫入完成；成功與失敗數將於結束後顯示。");
                    ui.ctx().request_repaint_after(std::time::Duration::from_millis(100));
                } else if let Some(result) = &app.last_export_result {
                    let files = result.get("files").and_then(Value::as_array);
                    let success = files.map_or(0, |v| v.iter().filter(|f| f.get("path").is_some() && f.get("error").is_none() && f.get("skipped").is_none()).count());
                    let failed = files.map_or(0, |v| v.iter().filter(|f| f.get("error").is_some()).count());
                    let skipped = files.map_or(0, |v| v.iter().filter(|f| f.get("skipped").is_some() && f.get("error").is_none()).count());
                    let cancelled = result.get("cancelled").and_then(Value::as_bool) == Some(true);
                    let error = result.get("error").and_then(Value::as_str);
                    let title = if cancelled { "匯出已取消" } else if error.is_some() || (failed > 0 && success == 0) { "匯出失敗" } else if failed > 0 { "匯出結束（部分失敗）" } else { "匯出結束" };
                    ui.horizontal(|ui| { ui.label(title); dismiss = ui.button("關閉").clicked(); });
                    ui.label(format!("成功 {} · 失敗 {} · 跳過 {}", success, failed, skipped));
                    if let Some(e) = error { ui.label(e); }
                    else if let Some(v) = files {
                        if let Some(e) = v.iter().find_map(|f| f.get("error").and_then(Value::as_str)) { ui.label(e); }
                        else if let Some(path) = v.iter().find_map(|f| f.get("path").and_then(Value::as_str)) { ui.label(format!("輸出：{}", path)); }
                    }
                }
            });
        });
    if dismiss { app.last_export_result = None; }
}
"""


def patch(root):
    ui = root.resolve().parents[1] / 'crates/ui-egui/src'
    task = ui / 'export_task.rs'
    if 'pub fn local_export_progress_panel(' in task.read_text():
        raise RuntimeError('Export-progress already applied; use fresh generated sources')
    pending = {}

    def once(path, old, new, phase):
        text = pending[path] if path in pending else path.read_text()
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f'Export-progress phase={phase} file={path} expected=1 actual={count} anchor={old!r}')
        pending[path] = text.replace(old, new, 1)
        print(f'Export-progress validated phase={phase} file={path}', flush=True)

    anchor = 'pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) {'
    once(ui / 'panels/bottombar.rs', anchor, anchor + '\n    crate::export_task::local_export_progress_panel(app, ui);', 'bottom-panel')
    once(task, '    let total = items.len();', '    let total = items.len();\n    app.last_export_result = None;', 'reset-result')
    once(task, '                Err(e) => e,', '                Err(e) => { app.last_export_result = Some(json!({"error": e.clone()})); e },', 'worker-error')
    once(task, '            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));', '            app.last_export_result = Some(json!({"error": "匯出意外中止"}));\n            app.toast(ctx, crate::i18n::tr("Export stopped unexpectedly"));', 'worker-disconnected')
    pending[task] += '\n' + PANEL
    for path, text in pending.items():
        path.write_text(text)
    print('Export-progress UI installed; no settings button, JNI, Services or engine changes; live updates require an existing background export task; APK and device validation required', flush=True)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
