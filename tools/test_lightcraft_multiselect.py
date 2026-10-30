import tempfile
import unittest
from pathlib import Path
from patch_lightcraft_multiselect import MODULE, patch, patch_grid

FIXTURE = r"""pub fn show(app: &mut LightcraftApp, ui: &mut egui::Ui) { show_inner(app, ui); }
fn cell(app: &mut LightcraftApp, ui: &mut egui::Ui, id: PhotoId, r: Rect, square: bool, onscreen: bool, ppp: f32) {
    let note = r#"a } brace in a string"#;
    // interaction
    if let Some(k) = app.ui.keyword_painter.clone() {
        if resp.clicked() { paint_keyword(k); }
        return;
    }
    if resp.clicked() {
        let m = ui.input(|i| i.modifiers);
        let mode = if m.shift {
            "range"
        } else if m.command {
            "toggle"
        } else {
            "replace"
        };
        let _ = app.run("library.select", json!({"ids": [id.0], "mode": mode}));
    }
    if resp.double_clicked() {
        let _ = app.run("view.detail", json!({}));
    }
    if resp.drag_started() { start_drag(); }
}
fn untouched() { unrelated(); }
"""


class MultiSelectTests(unittest.TestCase):
    def test_additive_mode_and_toolbar(self):
        source = patch_grid(FIXTURE)
        self.assertIn('m.command || crate::local_multiselect::enabled(ui.ctx())', source)
        self.assertEqual(source.count('crate::local_multiselect::toolbar(app, ui);'), 1)

    def test_keyboard_range_is_preserved(self):
        self.assertIn('if m.shift {\n            "range"', patch_grid(FIXTURE))

    def test_double_click_and_drag_are_gated(self):
        source = patch_grid(FIXTURE)
        self.assertIn('resp.double_clicked() && !crate::local_multiselect::enabled', source)
        self.assertIn('resp.drag_started() && !crate::local_multiselect::enabled', source)
        self.assertIn('&& !(crate::local_multiselect::enabled(ui.ctx()) && resp.double_clicked())', source)

    def test_marks_and_unrelated_code(self):
        source = patch_grid(FIXTURE)
        self.assertIn('crate::local_multiselect::mark(ui, r, app.session.selection.contains(id));', source)
        self.assertIn('fn untouched() { unrelated(); }', source)
        self.assertIn('if resp.clicked() { paint_keyword(k); }', source)
        self.assertIn('let note = r#"a } brace in a string"#;', source)

    def test_missing_anchor_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'phase=additive-selection'):
            patch_grid(FIXTURE.replace('} else if m.command {', '} else if modifiers.command {'))

    def test_duplicate_application_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'already applied'):
            patch_grid(patch_grid(FIXTURE))

    def test_toolbar_commands_and_finish(self):
        self.assertIn('library.selectAll', MODULE)
        self.assertIn('library.selectNone', MODULE)
        self.assertIn('ui.button("完成").clicked() { active = false; }', MODULE)
        self.assertIn('app.ui.keyword_painter = None;', MODULE)

    def test_disk_patch_and_no_partial_writes(self):
        for broken in [False, True]:
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as tmp:
                upstream = Path(tmp) / 'source/lightcraft'
                root = upstream / 'apps/lightcraft-android'
                root.mkdir(parents=True)
                ui = upstream / 'crates/ui-egui/src'
                (ui / 'panels').mkdir(parents=True)
                lib = ui / 'lib.rs'
                grid = ui / 'panels/grid.rs'
                lib.write_text('pub mod export_task;\n')
                grid.write_text(FIXTURE.replace('} else if m.command {', '} else if other.command {') if broken else FIXTURE)
                before = (lib.read_bytes(), grid.read_bytes())
                if broken:
                    with self.assertRaises(RuntimeError):
                        patch(root)
                    self.assertEqual(before, (lib.read_bytes(), grid.read_bytes()))
                    self.assertFalse((ui / 'local_multiselect.rs').exists())
                else:
                    patch(root)
                    self.assertTrue((ui / 'local_multiselect.rs').exists())
                    self.assertEqual(lib.read_text().count('pub mod local_multiselect;'), 1)


if __name__ == '__main__':
    unittest.main()
