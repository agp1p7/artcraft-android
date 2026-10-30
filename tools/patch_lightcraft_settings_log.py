import re
import sys
from pathlib import Path
from local_ui_parts import BRIDGE, SETTINGS

LAUNCH = r"""
static LIGHTCRAFT_SETTINGS_APP: std::sync::OnceLock<android_activity::AndroidApp> = std::sync::OnceLock::new();
fn lightcraft_settings_log_export() -> Result<(), String> {
    let app = LIGHTCRAFT_SETTINGS_APP.get().ok_or("Android activity not ready")?;
    saf::Bridge::new(app).export_gpu_log()
}
"""


def patch(root):
    root = root.resolve()
    ui = root.parents[1] / 'crates/ui-egui/src'
    if 'LIGHTCRAFT_SETTINGS_APP' in (root / 'src/lib.rs').read_text():
        raise RuntimeError('Settings-log phase=preflight already applied; use a fresh generated launcher')
    pending = {}

    def read(path):
        return pending[path] if path in pending else path.read_text()

    def once(path, old, new, phase):
        text = read(path)
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f'Settings-log phase={phase} file={path} expected=1 actual={count} anchor={old!r}')
        pending[path] = text.replace(old, new, 1)
        print(f'Settings-log validated phase={phase} file={path}', flush=True)

    once(ui / 'lib.rs', '    pub picker: Option<pick::Picker>,',
         '    #[cfg(target_os = "android")]\n    pub gpu_log_export: Option<Box<dyn FnMut() -> Result<(), String>>>,\n    pub picker: Option<pick::Picker>,', 'services-field')
    anchor = 'fn general_tab(app: &mut LightcraftApp, ui: &mut egui::Ui, t: &Tokens) {'
    once(ui / 'panels/settings.rs', anchor, anchor + '\n' + SETTINGS, 'settings-button')
    bridge_anchor = '        pub fn request_open(&self, id: u64, multiple: bool)'
    bridges = [p for p in (root / 'src').rglob('*.rs') if bridge_anchor in read(p)]
    if len(bridges) != 1:
        raise RuntimeError(f'Settings-log phase=jni-location expected=1 actual={len(bridges)} files={bridges}')
    once(bridges[0], bridge_anchor, BRIDGE + '\n' + bridge_anchor, 'jni-method')
    launcher = root / 'src/lib.rs'
    text = read(launcher)
    pattern = r'\bfn\s+android_main\s*\(\s*(?:mut\s+)?(\w+)\s*:\s*(?:\w+::)*AndroidApp\s*,?\s*\)\s*\{'
    mains = list(re.finditer(pattern, text))
    if len(mains) != 1:
        raise RuntimeError(f'Settings-log phase=android-main file={launcher} expected=1 actual={len(mains)}')
    m = mains[0]
    text = text[:m.end()] + '\n    let _ = LIGHTCRAFT_SETTINGS_APP.set(' + m.group(1) + '.clone());' + text[m.end():]
    constructors = list(re.finditer(r'\bServices\s*\{', text))
    if len(constructors) != 1:
        raise RuntimeError(f'Settings-log phase=services-constructor file={launcher} expected=1 actual={len(constructors)}')
    m = constructors[0]
    text = text[:m.end()] + '\n        gpu_log_export: Some(Box::new(lightcraft_settings_log_export)),' + text[m.end():]
    pending[launcher] = text + '\n' + LAUNCH
    for path, text in pending.items():
        path.write_text(text)
    print('Settings-log patch applied; export engine, export tasks, bottom bar and shared writer untouched; APK compilation and device validation still required', flush=True)


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        from patch_lightcraft_local_ui import prepare
        prepare()
    else:
        patch(Path(sys.argv[1]))
