import tempfile
import unittest
from pathlib import Path
from patch_lightcraft_boxselect import MODULE, patch, patch_grid

GRID = r"""fn show_inner(app: &mut LightcraftApp, ui: &mut egui::Ui) {
    egui::ScrollArea::vertical().id_salt("grid-scroll").auto_shrink([false, false]).show_viewport(ui, |ui, viewport| {
        let origin = area.min;
        draw_photos();
    });
    app.caches.grid_stats.cells_visited += visited;
}
"""
MULTI = r"""fn toolbar() {
        if active {
            ui.label(format!("已選 {} 張", app.session.selection.ids.len()));
        }
        ui.small("點縮圖勾選／取消；選好後按「完成」再匯出。");
}
"""


def hit_model(cells, start, end, origin=(0, 0)):
    ax, ay = start[0] - origin[0], start[1] - origin[1]
    bx, by = end[0] - origin[0], end[1] - origin[1]
    x0, x1 = sorted((ax, bx))
    y0, y1 = sorted((ay, by))
    return [i for i, (l, t, r, b) in enumerate(cells, 1) if x0 <= r and l <= x1 and y0 <= b and t <= y1]


class BoxSelectTests(unittest.TestCase):
    def test_viewport_handler_and_scroll_source(self):
        source = patch_grid(GRID)
        call = 'crate::local_boxselect::box_selection(app, ui, &ids, &lay.cells, origin, area, generation);'
        self.assertEqual(source.count(call), 1)
        self.assertLess(source.index(call), source.index('    });'))
        self.assertIn('.scroll_source(crate::local_boxselect::scroll_source(ui.ctx()))', source)

    def test_missing_scroll_anchor_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'phase=scroll-conflict'):
            patch_grid(GRID.replace('grid-scroll', 'other-scroll'))

    def test_missing_viewport_anchor_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'phase=viewport-handler'):
            patch_grid(GRID.replace('cells_visited += visited', 'cells_visited += count'))

    def test_mode_controls_and_wheel(self):
        self.assertIn('"框選"', MODULE)
        self.assertIn('"加選"', MODULE)
        self.assertIn('ScrollSource::SCROLL_BAR + ScrollSource::MOUSE_WHEEL', MODULE)
        self.assertIn('crate::local_multiselect::enabled(ctx)', MODULE)

    def test_release_commit_and_cancellation(self):
        self.assertLess(MODULE.index('if released {'), MODULE.index('app.run("library.select"'))
        self.assertIn('state.generation != generation', MODULE)
        self.assertIn('egui::Key::Escape', MODULE)
        self.assertIn('egui::TouchPhase::Cancel', MODULE)
        self.assertIn('(!down && !released)', MODULE)

    def test_geometry_model_both_directions(self):
        cells = [(0, 0, 90, 90), (100, 0, 190, 90), (0, 100, 90, 190), (100, 100, 190, 190)]
        self.assertEqual(hit_model(cells, (105, 5), (185, 185)), [2, 4])
        self.assertEqual(hit_model(cells, (185, 185), (105, 5)), [2, 4])
        self.assertIn('Rect::from_two_pos', MODULE)
        self.assertIn('selection.intersects(*cell)', MODULE)

    def test_geometry_model_after_scrolling(self):
        cells = [(0, 0, 90, 90), (100, 0, 190, 90), (0, 100, 90, 190), (100, 100, 190, 190)]
        self.assertEqual(hit_model(cells, (25, 25), (205, 105), (20, -80)), [3, 4])
        self.assertIn('press - origin.to_vec2()', MODULE)
        self.assertIn('at - origin.to_vec2()', MODULE)

    def test_additive_model_has_no_duplicates(self):
        base, hits = [1, 3], [3, 4]
        self.assertEqual(list(dict.fromkeys(base + hits)), [1, 3, 4])
        self.assertEqual(list(dict.fromkeys(hits)), [3, 4])
        self.assertIn('if seen.insert(*id)', MODULE)

    def test_disk_patch_validates_before_writing(self):
        for broken in [False, True]:
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as tmp:
                upstream = Path(tmp) / 'source/lightcraft'
                root = upstream / 'apps/lightcraft-android'
                root.mkdir(parents=True)
                ui = upstream / 'crates/ui-egui/src'
                (ui / 'panels').mkdir(parents=True)
                lib, grid, multi = ui / 'lib.rs', ui / 'panels/grid.rs', ui / 'local_multiselect.rs'
                lib.write_text('pub mod local_multiselect;\n')
                grid.write_text(GRID)
                multi.write_text(MULTI.replace('if active {', 'if enabled {') if broken else MULTI)
                before = {p: p.read_bytes() for p in (lib, grid, multi)}
                if broken:
                    with self.assertRaisesRegex(RuntimeError, 'phase=toolbar-controls'):
                        patch(root)
                    self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
                    self.assertFalse((ui / 'local_boxselect.rs').exists())
                else:
                    patch(root)
                    self.assertTrue((ui / 'local_boxselect.rs').exists())
                    self.assertIn('crate::local_boxselect::controls(ui);', multi.read_text())
                    with self.assertRaisesRegex(RuntimeError, 'already applied'):
                        patch(root)


if __name__ == '__main__':
    unittest.main()
