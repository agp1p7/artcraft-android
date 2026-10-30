UI = r'''
#[derive(Default)]
pub struct LocalExportStatus { pub processed: usize, pub success: usize, pub failed: usize, pub skipped: usize }
pub fn local_export_panel(app: &mut crate::LightcraftApp, ui: &mut egui::Ui) {
    let active = app.export.is_some();
    if !active && app.last_export_result.is_none() { return; }
    let mut dismiss = false;
    egui::Panel::bottom("lightcraft_local_export_status").exact_size(78.0)
        .frame(egui::Frame::NONE.fill(crate::theme::Tokens::get(ui.ctx()).chrome).inner_margin(egui::Margin::symmetric(12, 6)))
        .show(ui, |ui| {
            if let Some(task) = &app.export {
                let s = task.local_status.lock().unwrap_or_else(|e| e.into_inner());
                let current = task.progress.lock().map(|g| g.1.clone()).unwrap_or_default();
                let total = task.total;
                ui.label(format!("正在匯出照片…  已處理 {} / {} 張", s.processed.min(total), total));
                let fraction = if total > 1 { Some((s.processed as f32 / total as f32).min(0.99)) } else { None };
                crate::progress::Progress::new(fraction).widget("progress:localExport").show(ui);
                ui.horizontal_wrapped(|ui| {
                    ui.label(format!("成功 {} · 失敗 {} · 跳過 {}", s.success, s.failed, s.skipped));
                    if !current.is_empty() { ui.label(format!("目前：{}", current)); }
                });
                ui.ctx().request_repaint_after(std::time::Duration::from_millis(100));
            } else if let Some(result) = &app.last_export_result {
                let files = result.get("files").and_then(serde_json::Value::as_array);
                let success = files.map_or(0, |v| v.iter().filter(|f| f.get("path").is_some() && f.get("error").is_none()).count());
                let failed = files.map_or(0, |v| v.iter().filter(|f| f.get("error").is_some()).count());
                let skipped = files.map_or(0, |v| v.iter().filter(|f| f.get("skipped").is_some()).count());
                let cancelled = result.get("cancelled").and_then(serde_json::Value::as_bool) == Some(true);
                let error = result.get("error").and_then(serde_json::Value::as_str);
                let title = if cancelled { "匯出已取消" } else if error.is_some() || (failed > 0 && success == 0) { "匯出失敗" } else if failed > 0 { "匯出結束（部分失敗）" } else { "匯出完成" };
                ui.horizontal(|ui| { ui.label(title); dismiss = ui.button("關閉").clicked(); });
                ui.label(format!("成功 {} · 失敗 {} · 跳過 {}", success, failed, skipped));
                if let Some(e) = error { ui.label(e); }
                else if let Some(v) = files {
                    if let Some(e) = v.iter().find_map(|f| f.get("error").and_then(serde_json::Value::as_str)) { ui.label(e); }
                    else if let Some(path) = v.iter().find_map(|f| f.get("path").and_then(serde_json::Value::as_str)) { ui.label(format!("已儲存：{}", path)); }
                }
            }
        });
    if dismiss { app.last_export_result = None; }
}
'''

ENGINE = r'''
thread_local! {
    static LOCAL_EXPORT_OBSERVER: std::cell::RefCell<Option<Box<dyn FnMut(&serde_json::Value)>>> = const { std::cell::RefCell::new(None) };
}
pub fn local_set_export_observer(f: Option<Box<dyn FnMut(&serde_json::Value)>>) { LOCAL_EXPORT_OBSERVER.with(|o| *o.borrow_mut() = f); }
fn local_observe_export(value: serde_json::Value) -> serde_json::Value {
    LOCAL_EXPORT_OBSERVER.with(|o| { if let Some(f) = o.borrow_mut().as_mut() { f(&value); } }); value
}
'''

LAUNCH = r'''
static LIGHTCRAFT_LOCAL_APP: std::sync::OnceLock<android_activity::AndroidApp> = std::sync::OnceLock::new();
fn lightcraft_local_log_export() -> Result<(), String> {
    let app = LIGHTCRAFT_LOCAL_APP.get().ok_or("Android activity not ready")?;
    saf::Bridge::new(app).export_gpu_log()
}
fn lightcraft_local_write(path: &str, data: &[u8]) -> Result<(), String> {
    lightcraft_engine::export::write_file(path, data)?;
    let app = LIGHTCRAFT_LOCAL_APP.get().ok_or("Android activity not ready")?;
    let result = saf::Bridge::new(app).commit(path)?;
    if result.starts_with("ERROR:") { return Err(result); }
    Ok(())
}
'''

BRIDGE = r'''
        pub fn export_gpu_log(&self) -> Result<(), String> {
            self.vm.attach_current_thread(|env| -> jni::errors::Result<()> {
                let raw = self.app.activity_as_ptr() as jni::sys::jobject;
                let activity = unsafe { env.as_cast_raw::<JObject>(&raw)? };
                env.call_method(&*activity, jni_str!("exportGpuLog"), jni_sig!("()V"), &[])?;
                Ok(())
            }).map_err(|e| e.to_string())
        }
'''

SETTINGS = r'''
    #[cfg(target_os = "android")]
    {
        ui.separator();
        ui.label("診斷");
        let button = ui.add_enabled(app.services.gpu_log_export.is_some(), egui::Button::new("匯出 GPU 日誌"));
        register(ui.ctx(), "button:exportGpuLog", button.rect);
        if button.clicked() {
            let result = app.services.gpu_log_export.as_mut().map(|f| f());
            if let Some(Err(e)) = result { app.toast_for(ui.ctx(), format!("日誌匯出失敗：{}", e), 10.0); }
        }
    }
'''
