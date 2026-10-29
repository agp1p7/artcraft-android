import subprocess
import sys
from pathlib import Path

def replace_checked(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected diagnostic source format: {path}')
    path.write_text(text.replace(old, new, 1))

def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_denoise.py')), str(root)], check=True)
    upstream = root.parents[1]
    replace_checked(upstream / 'crates/gpu/src/lib.rs',
        '    // Experimental Android workaround: use the reference CPU image pipeline.\n'
        '    // This does not disable the UI compositor or independently configured AI inference.\n'
        '    !cfg!(target_os = "android") && depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange',
        '    // Diagnostic build: allow GPU rendering; retain upstream failure handling.\n'
        '    depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange')
    ctx = upstream / 'crates/gpu/src/ctx.rs'
    replace_checked(ctx, '        let info = adapter.get_info();',
        '        let info = adapter.get_info();\n'
        '        log::warn!("gpu-diag: adapter={:?}; limits={:?}", info, adapter.limits());')
    replace_checked(ctx, '        assert_eq!(bufs.len(), k.nbuf, "{name}: binding count");',
        '        assert_eq!(bufs.len(), k.nbuf, "{name}: binding count");\n'
        '        log::warn!("gpu-diag: kernel={} groups={:?} parameter_words={} buffers={:?}", name, groups, p.len(), bufs.iter().map(|b| b.map(|b| (b.len, b.raw().size()))).collect::<Vec<_>>());')
    replace_checked(ctx, '        let size = (len * 4) as u64;\n        let staging = self.device.create_buffer',
        '        let diag_started = std::time::Instant::now();\n'
        '        log::warn!("gpu-diag: readback begin words={} buffer_bytes={} element_bytes={}", len, src.raw().size(), std::mem::size_of::<T>());\n'
        '        let size = (len * 4) as u64;\n        let staging = self.device.create_buffer')
    replace_checked(ctx, '        let out: Vec<T> = bytemuck::cast_slice(&data).to_vec();',
        '        log::warn!("gpu-diag: readback complete bytes={} zero_bytes={} elapsed_ms={}", data.len(), data.iter().filter(|v| **v == 0).count(), diag_started.elapsed().as_millis());\n'
        '        let out: Vec<T> = bytemuck::cast_slice(&data).to_vec();')
    print('GPU DIAGNOSTIC BUILD: Android GPU allowed; metadata-only runtime diagnostics added; not a validated fix')

if __name__ == '__main__':
    patch(Path(sys.argv[1]))
