import subprocess
import sys
from pathlib import Path
from patch_lightcraft_gpu_diagnostics_v2 import replace_checked


def prepare():
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_candidate_v3.py')), '--prepare'], check=True)
    p = Path(__file__).resolve().parents[1] / 'templates/android/SafActivity.java'
    replace_checked(p, 'LightCraft GPU diagnostics v2', 'LightCraft GPU candidate v6-windowed-checked')
    replace_checked(p, 'button.setText("匯出 GPU 日誌");', 'button.setText("匯出 GPU 日誌 v6");')


def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_candidate_v3.py')), str(root)], check=True)
    gpu = root.parents[1] / 'crates/gpu/src'
    shader = gpu / 'wgsl/map.wgsl'
    old = '    let i = g.x + pu(arrayLength(&P) - 1u); // candidate-v3: explicit chunk offset'
    new = '    let i = g.x; // candidate-v6: binding-relative local index'
    text = shader.read_text()
    if text.count(old) != 14:
        raise RuntimeError('Expected 14 v3 map indices on a fresh source checkout')
    shader.write_text(text.replace(old, new))
    replace_checked(shader, '    let x = f32(i % w) + 0.5;', '    let x = f32((i + pu(arrayLength(&P) - 1u)) % w) + 0.5;')
    replace_checked(shader, '    let y = f32(i / w) + 0.5;', '    let y = f32((i + pu(arrayLength(&P) - 1u)) / w) + 0.5;')
    for target, helper in [('ctx', 'gpu_window_v6'), ('render', 'gpu_accept_v6')]:
        (gpu / (helper + '.rs')).write_text(Path(__file__).with_name(helper + '.rs').read_text())
        p = gpu / (target + '.rs')
        p.write_text(p.read_text() + '\ninclude!("' + helper + '.rs");\n')
    ctx = gpu / 'ctx.rs'
    header = '    pub fn run(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], bufs: &[Option<&Buf>], groups: [u32; 3]) {'
    replace_checked(ctx, header, header + '\n        if self.gpu_window_v6(enc, name, p, bufs) { return; }')
    render = gpu / 'render.rs'
    anchor = '    cx.run(k, &p, &[ins[0], ins[1], ins[2], Some(out)], groups1(n));'
    replace_checked(render, anchor, '    let v6_before = gpu_accept_v6_before(cx, k, n, ins[0]);\n' + anchor + '\n    gpu_accept_v6_after(cx, k, n, &p, out, v6_before);')
    build = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    old = '    log::warn!("gpu-diag: render-v2 w={} h={} adapter={:?} limits={:?}; probes alter synchronization", w, h, gpu.info, gpu.device.limits());'
    new = '    log::warn!("gpu-diag: v6-windowed-checked build=' + build + ' w={} h={} adapter={:?} limits={:?}; sparse checks change timing; device validation required", w, h, gpu.info, gpu.device.limits());'
    replace_checked(render, old, new)
    lib = gpu / 'lib.rs'
    replace_checked(lib, 'fn record_fallback(reason: String) {', 'fn record_fallback(reason: String) {\n    log::warn!("gpu-diag: result-v6 path=cpu-fallback reason={}", reason);')
    replace_checked(lib, '            (Ok(Some(r)), None) => return Ok(r),', '            (Ok(Some(r)), None) => {\n                log::warn!("gpu-diag: result-v6 path=gpu width={} height={} upstream_checks_passed=true not_full_numerical_proof=true", r.image.width, r.image.height);\n                return Ok(r);\n            },')
    replace_checked(lib, '        let gpu = device().ok_or(Fallback::NotTried)?;', '        let gpu = match device() {\n            Some(g) => g,\n            None => { log::warn!("gpu-diag: result-v6 path=not-tried reason={:?}", unavailable_reason()); return Err(Fallback::NotTried); }\n        };')
    replace_checked(lib, '        if !enabled() || !handles(req.depth, device_proof, req.overlay) {\n            return Err(Fallback::NotTried);', '        if !enabled() || !handles(req.depth, device_proof, req.overlay) {\n            log::warn!("gpu-diag: result-v6 path=not-tried enabled={} handles={} reason={:?}", enabled(), handles(req.depth, device_proof, req.overlay), unavailable_reason());\n            return Err(Fallback::NotTried);')
    if shader.read_text().count('candidate-v6: binding-relative local index') != 14:
        raise RuntimeError('Incomplete v6 shader patch')
    print('V6 windowed GPU candidate plus sparse acceptance installed; v5 stress tests omitted; compilation and device validation required')


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
