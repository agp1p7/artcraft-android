import sys
from pathlib import Path

MODULE = r"""
use crate::LightcraftApp;
use lightcraft_catalog::PhotoId;

#[derive(Clone, Default)]
struct DragState {
    start: Option<egui::Pos2>,
    press: egui::Pos2,
    base: Vec<u64>,
    additive: bool,
    dragging: bool,
    generation: u64,
}

fn key(name: &str) -> egui::Id { egui::Id::new(("lightcraft_box_select", name)) }
fn clear(ctx: &egui::Context) { ctx.data_mut(|d| d.insert_temp(key("drag"), DragState::default())); }

pub fn enabled(ctx: &egui::Context) -> bool {
    crate::local_multiselect::enabled(ctx) && ctx.data(|d| d.get_temp::<bool>(key("enabled"))).unwrap_or(false)
}

pub fn controls(ui: &mut egui::Ui) {
    let mut on = ui.ctx().data(|d| d.get_temp::<bool>(key("enabled"))).unwrap_or(false);
    let mut add = ui.ctx().data(|d| d.get_temp::<bool>(key("additive"))).unwrap_or(false);
    ui.checkbox(&mut on, "框選");
    if on { ui.checkbox(&mut add, "加選"); }
    ui.ctx().data_mut(|d| { d.insert_temp(key("enabled"), on); d.insert_temp(key("additive"), add); });
    if !on { clear(ui.ctx()); }
}

pub fn scroll_source(ctx: &egui::Context) -> egui::containers::scroll_area::ScrollSource {
    use egui::containers::scroll_area::ScrollSource;
    if enabled(ctx) { ScrollSource::SCROLL_BAR + ScrollSource::MOUSE_WHEEL } else { ScrollSource::default() }
}

fn hit_ids(ids: &[PhotoId], cells: &[egui::Rect], selection: egui::Rect) -> Vec<u64> {
    ids.iter().zip(cells).filter_map(|(id, cell)| selection.intersects(*cell).then_some(id.0)).collect()
}

fn merge_ids(base: &[u64], hits: &[u64], additive: bool) -> Vec<u64> {
    let mut result = if additive { base.to_vec() } else { Vec::new() };
    let mut seen: std::collections::HashSet<u64> = result.iter().copied().collect();
    for id in hits { if seen.insert(*id) { result.push(*id); } }
    result
}

pub fn box_selection(app: &mut LightcraftApp, ui: &egui::Ui, ids: &[PhotoId], cells: &[egui::Rect], origin: egui::Pos2, area: egui::Rect, generation: u64) {
    let ctx = ui.ctx();
    let (pressed, down, released, pos, press, command, cancel) = ui.input(|i| (
        i.pointer.primary_pressed(), i.pointer.primary_down(), i.pointer.primary_released(),
        i.pointer.interact_pos().or(i.pointer.latest_pos()), i.pointer.press_origin(),
        i.modifiers.command || i.modifiers.ctrl,
        i.key_pressed(egui::Key::Escape) || i.events.iter().any(|e| matches!(e, egui::Event::Touch { phase: egui::TouchPhase::Cancel, .. }))
    ));
    let visible = area.intersect(ui.clip_rect());
    if !enabled(ctx) || cancel || visible.width() <= 0.0 || visible.height() <= 0.0 { clear(ctx); return; }
    let Some(pos) = pos else { clear(ctx); return; };
    let mut state = ctx.data(|d| d.get_temp::<DragState>(key("drag"))).unwrap_or_default();
    if pressed {
        let press = press.unwrap_or(pos);
        if !visible.contains(press) || !ui.rect_contains_pointer(visible) { clear(ctx); return; }
        state = DragState {
            start: Some(press - origin.to_vec2()), press,
            base: app.session.selection.ids.iter().map(|id| id.0).collect(),
            additive: command || ctx.data(|d| d.get_temp::<bool>(key("additive"))).unwrap_or(false),
            dragging: false, generation,
        };
    }
    let Some(start) = state.start else { return; };
    if state.generation != generation || (!down && !released) { clear(ctx); return; }
    if pos.distance(state.press) >= 6.0 { state.dragging = true; }
    if state.dragging {
        let at = egui::pos2(pos.x.clamp(visible.left(), visible.right()), pos.y.clamp(visible.top(), visible.bottom()));
        let selection = egui::Rect::from_two_pos(start, at - origin.to_vec2());
        let hits = hit_ids(ids, cells, selection);
        let t = crate::theme::Tokens::get(ctx);
        let painter = ui.painter().with_clip_rect(visible);
        for cell in cells.iter().filter(|cell| selection.intersects(**cell)) {
            let screen = cell.translate(origin.to_vec2());
            if screen.intersects(visible) { painter.rect_filled(screen, 2.0, t.accent.gamma_multiply(0.18)); }
        }
        let screen = selection.translate(origin.to_vec2());
        painter.rect_filled(screen, 0.0, t.accent.gamma_multiply(0.10));
        painter.rect_stroke(screen, 0.0, egui::Stroke::new(1.5, t.accent), egui::StrokeKind::Inside);
        painter.text(at + egui::vec2(8.0, 8.0), egui::Align2::LEFT_TOP, format!("框選預覽 {} 張", hits.len()), t.font(12.5), t.text);
        if released {
            let target = merge_ids(&state.base, &hits, state.additive);
            if app.session.selection.ids.iter().map(|id| id.0).ne(target.iter().copied()) {
                let result = if target.is_empty() {
                    app.run("library.selectNone", serde_json::json!({}))
                } else {
                    app.run("library.select", serde_json::json!({"ids": target, "mode": "replace"}))
                };
                if let Err(error) = result { app.toast(ctx, format!("框選失敗：{}", error)); }
            }
            clear(ctx);
            ctx.request_repaint();
            return;
        }
        ctx.request_repaint();
    }
    if released { clear(ctx); } else { ctx.data_mut(|d| d.insert_temp(key("drag"), state)); }
}
"""


def once(text, old, new, phase):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'Box-select phase={phase} expected=1 actual={count} anchor={old!r}')
    return text.replace(old, new, 1)


def patch_grid(text):
    old = '.id_salt("grid-scroll").auto_shrink([false, false])'
    new = '.id_salt("grid-scroll").scroll_source(crate::local_boxselect::scroll_source(ui.ctx())).auto_shrink([false, false])'
    text = once(text, old, new, 'scroll-conflict')
    old = '    });\n    app.caches.grid_stats.cells_visited += visited;'
    new = '        crate::local_boxselect::box_selection(app, ui, &ids, &lay.cells, origin, area, generation);\n    });\n    app.caches.grid_stats.cells_visited += visited;'
    return once(text, old, new, 'viewport-handler')


def patch(root):
    ui = root.resolve().parents[1] / 'crates/ui-egui/src'
    module = ui / 'local_boxselect.rs'
    if module.exists():
        raise RuntimeError('Box-select already applied; use fresh sources')
    lib, grid, multi = ui / 'lib.rs', ui / 'panels/grid.rs', ui / 'local_multiselect.rs'
    lib_text = once(lib.read_text(), 'pub mod local_multiselect;\n', 'pub mod local_multiselect;\npub mod local_boxselect;\n', 'module')
    grid_text = patch_grid(grid.read_text())
    old = '        if active {\n            ui.label(format!("已選 {} 張", app.session.selection.ids.len()));'
    new = '        if active {\n            crate::local_boxselect::controls(ui);\n            ui.label(format!("已選 {} 張", app.session.selection.ids.len()));'
    multi_text = once(multi.read_text(), old, new, 'toolbar-controls')
    multi_text = once(multi_text, '        ui.small("點縮圖勾選／取消；選好後按「完成」再匯出。");', '        ui.small(if crate::local_boxselect::enabled(ui.ctx()) { "按住左鍵拖曳框選，放開完成；加選可保留原選取。" } else { "點縮圖勾選／取消；選好後按「完成」再匯出。" });', 'toolbar-help')
    for path, value in [(module, MODULE), (lib, lib_text), (grid, grid_text), (multi, multi_text)]:
        path.write_text(value)
    print('Box-select installed: preview then commit on release, additive selection, content coordinates, generation cancellation; no automatic edge scrolling; APK/device validation required', flush=True)


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
