import subprocess
import sys
from pathlib import Path
from patch_lightcraft_gpu_diagnostics_v2 import replace_checked

PROBE = r'''
fn gpu_diag_stage_v4(cx: &mut Cx<'_>, b: &Buf, n: usize, nc: usize, stage: &str) {
    if n < (16 << 20) || nc == 0 || nc > 4 || crate::ctx::failed() { return; }
    if n.checked_mul(nc).is_none_or(|len| len > b.len) {
        log::warn!("gpu-diag: stage-v4 invalid-layout stage={} n={} nc={} len={}", stage, n, nc, b.len);
        return;
    }
    let width = n.min(64);
    for center in [0, n / 4, n / 2, n * 3 / 4, n - 1] {
        let start = center.saturating_sub(width / 2).min(n - width);
        let part = cx.slice(b, start * nc, width * nc);
        let values: Vec<f32> = cx.read(&part, width * nc);
        let zeros = values.iter().filter(|v| **v == 0.0).count();
        let nonfinite = values.iter().filter(|v| !v.is_finite()).count();
        let min = values.iter().copied().filter(|v| v.is_finite()).fold(f32::INFINITY, f32::min);
        let max = values.iter().copied().filter(|v| v.is_finite()).fold(f32::NEG_INFINITY, f32::max);
        log::warn!("gpu-diag: stage-v4 stage={} n={} nc={} start={} words={} zero_channels={} nonfinite={} min={} max={}; readback synchronizes", stage, n, nc, start, values.len(), zeros, nonfinite, min, max);
    }
}

'''

def prepare():
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_candidate_v3.py')), '--prepare'], check=True)
    template = Path(__file__).resolve().parents[1] / 'templates/android/SafActivity.java'
    replace_checked(template, 'LightCraft GPU diagnostics v2', 'LightCraft GPU diagnostics v4-stage-probe')

def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_candidate_v3.py')), str(root)], check=True)
    render = root.parents[1] / 'crates/gpu/src/render.rs'
    replace_checked(render, 'pub fn render(', PROBE + 'pub fn render(')
    old = '    cx.run(k, &p, &[ins[0], ins[1], ins[2], Some(out)], groups1(n));'
    replace_checked(render, old, old + '\n    if n > 0 && out.len % n == 0 { gpu_diag_stage_v4(cx, out, n, out.len / n, k); }'.replace('\n', '\n'.encode().decode('unicode_escape')))
    old = '        box_pass(cx, *horizontal, if i == 0 { src } else { prev }, out, (w, h), nc, *r);'
    new = old + '\n        let stage = format!("blur-{}-pass{}-r{}", if *horizontal { "h" } else { "v" }, i, r);\n        gpu_diag_stage_v4(cx, out, w * h, nc, &stage);'
    replace_checked(render, old, new.replace('\n', '\n'.encode().decode('unicode_escape')))
    print('GPU diagnostics v4: per-map and per-blur probes above 16M pixels; preserves v3; probes change synchronization; not a validated fix')

if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
