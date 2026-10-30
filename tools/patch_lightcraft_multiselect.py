import re
import sys
from pathlib import Path
from patch_lightcraft_export_full import code_mask

MODULE = r"""
use crate::LightcraftApp;

fn key() -> egui::Id { egui::Id::new("lightcraft_multi_select_mode") }

pub fn enabled(ctx: &egui::Context) -> bool {
    ctx.data(|data| data.get_temp::<bool>(key())).unwrap_or(false)
}

pub fn toolbar(app: &mut LightcraftApp, ui: &mut egui::Ui) {
    let mut active = enabled(ui.ctx());
    ui.horizontal_wrapped(|ui| {
        let toggle = ui.selectable_label(active, "多選");
        crate::widgets::register(ui.ctx(), "button:localMultiSelect", toggle.rect);
        if toggle.clicked() {
            active = !active;
            if active { app.ui.keyword_painter = None; }
        }
        if active {
            ui.label(format!("已選 {} 張", app.session.selection.ids.len()));
            if ui.button("全選").clicked() { let _ = app.run("library.selectAll", serde_json::json!({})); }
            if ui.button("清除").clicked() { let _ = app.run("library.selectNone", serde_json::json!({})); }
            if ui.button("完成").clicked() { active = false; }
        }
    });
    ui.ctx().data_mut(|data| data.insert_temp(key(), active));
    if active {
        ui.small("點縮圖勾選／取消；選好後按「完成」再匯出。");
    }
}

pub fn mark(ui: &egui::Ui, rect: egui::Rect, selected: bool) {
    let t = crate::theme::Tokens::get(ui.ctx());
    let r = egui::Rect::from_min_size(rect.left_top() + egui::vec2(6.0, 6.0), egui::vec2(24.0, 24.0));
    let painter = ui.painter();
    painter.rect_filled(r, 4.0, if selected { t.accent } else { t.canvas });
    painter.rect_stroke(r, 4.0, egui::Stroke::new(1.0, t.text_dim), egui::StrokeKind::Inside);
    if selected {
        let a = r.left_top() + egui::vec2(5.0, 12.0);
        let b = r.left_top() + egui::vec2(10.0, 17.0);
        let c = r.left_top() + egui::vec2(19.0, 7.0);
        let stroke = egui::Stroke::new(2.5, egui::Color32::WHITE);
        painter.line_segment([a, b], stroke);
        painter.line_segment([b, c], stroke);
    }
}
"""


def once(text, old, new, phase):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Multi-select phase={phase} expected=1 actual={count} anchor={old!r}')
    return text.replace(old, new, 1)


def patch_grid(text):
    if 'crate::local_multiselect::' in text:
        raise RuntimeError('Multi-select already applied; use fresh sources')
    mask = code_mask(text)
    cells = list(re.finditer(r'\bfn\s+cell\s*\(', mask))
    if len(cells) != 1:
        raise RuntimeError(f'Multi-select phase=cell-function expected=1 actual={len(cells)}')
    start = mask.find('{', cells[0].end())
    if start < 0:
        raise RuntimeError('Multi-select phase=cell-function missing body')
    signature = mask[cells[0].start():start]
    if not re.search(r'\bid\s*:\s*PhotoId\b', signature) or not re.search(r'\br\s*:\s*Rect\b', signature):
        raise RuntimeError(f'Multi-select phase=cell-signature unsupported={signature!r}')
    depth, end = 1, start + 1
    while end < len(mask) and depth:
        depth += (mask[end] == '{') - (mask[end] == '}')
        end += 1
    if depth:
        raise RuntimeError('Multi-select phase=cell-function unbalanced body')
    body = text[start + 1:end - 1]
    body = once(body, '    // interaction\n', '    if crate::local_multiselect::enabled(ui.ctx()) {\n        crate::local_multiselect::mark(ui, r, app.session.selection.contains(id));\n    }\n    // interaction\n', 'selection-marks')
    body = once(body, '    if resp.clicked() {\n        let m = ui.input(|i| i.modifiers);', '    if resp.clicked() && !(crate::local_multiselect::enabled(ui.ctx()) && resp.double_clicked()) {\n        let m = ui.input(|i| i.modifiers);', 'single-toggle')
    body = once(body, '        } else if m.command {', '        } else if m.command || crate::local_multiselect::enabled(ui.ctx()) {', 'additive-selection')
    body = once(body, '        let _ = app.run("library.select", json!({"ids": [id.0], "mode": mode}));', '        let _ = app.run("library.select", json!({"ids": [id.0], "mode": mode}));\n        ui.ctx().request_repaint();', 'selection-repaint')
    body = once(body, '    if resp.double_clicked() {', '    if resp.double_clicked() && !crate::local_multiselect::enabled(ui.ctx()) {', 'no-open-in-multi-mode')
    body = once(body, '    if resp.drag_started() {', '    if resp.drag_started() && !crate::local_multiselect::enabled(ui.ctx()) {', 'no-photo-drag-in-multi-mode')
    text = text[:start + 1] + body + text[end - 1:]
    anchor = 'pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) {'
    return once(text, anchor, anchor + '\n    crate::local_multiselect::toolbar(app, ui);', 'toolbar')


def patch(root):
    ui = root.resolve().parents[1] / 'crates/ui-egui/src'
    module = ui / 'local_multiselect.rs'
    if module.exists():
        raise RuntimeError('Multi-select module already exists; use fresh sources')
    lib = ui / 'lib.rs'
    grid = ui / 'panels/grid.rs'
    lib_text = once(lib.read_text(), 'pub mod export_task;\n', 'pub mod export_task;\npub mod local_multiselect;\n', 'module')
    grid_text = patch_grid(grid.read_text())
    for path, content in [(module, MODULE), (lib, lib_text), (grid, grid_text)]:
        path.write_text(content)
    print('Multi-select installed: mouse/touch toggle mode, selected markers, select-all, clear and finish; no drag-box selection; APK/device validation required', flush=True)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
