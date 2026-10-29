import subprocess
import sys
from pathlib import Path
from patch_lightcraft_gpu_diagnostics_v2 import replace_checked


def prepare():
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_stage_v4.py')), '--prepare'], check=True)
    template = Path(__file__).resolve().parents[1] / 'templates/android/SafActivity.java'
    replace_checked(template, 'LightCraft GPU diagnostics v4-stage-probe', 'LightCraft GPU diagnostics v5-integrated-7checks')
    replace_checked(template, 'text.length() > 500000', 'text.length() > 2000000')


def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_stage_v4.py')), str(root)], check=True)
    upstream = root.parents[1]
    gpu = upstream / 'crates/gpu/src'
    for target in ['ctx', 'render']:
        (gpu / f'gpu_diag_v5_{target}.rs').write_text(Path(__file__).with_name(f'gpu_diag_v5_{target}.rs').read_text())
        text = (gpu / f'{target}.rs').read_text()
        include = f'\ninclude!("gpu_diag_v5_{target}.rs");\n'
        if include not in text:
            (gpu / f'{target}.rs').write_text(text + include)
    ctx = gpu / 'ctx.rs'
    anchor = '        let mut entries = vec![wgpu::BindGroupEntry { binding: 0, resource: params.as_entire_binding() }];'
    replace_checked(ctx, anchor, '        self.gpu_diag_v5_params(enc, name, p, &params);\n' + anchor)
    render = gpu / 'render.rs'
    anchor = '    cx.run(k, &p, &[ins[0], ins[1], ins[2], Some(out)], groups1(n));'
    replace_checked(render, anchor, '    let diag_v5_before = gpu_diag_v5_before(cx, k, n, &p, ins[0], out);\n' + anchor + '\n    gpu_diag_v5_after(cx, k, n, &p, ins[0], out, diag_v5_before);')
    build = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[1], text=True).strip()
    old = '    log::warn!("gpu-diag: render-v2 w={} h={} adapter={:?} limits={:?}; probes alter synchronization", w, h, gpu.info, gpu.device.limits());'
    new = '    log::warn!("gpu-diag: v5-integrated-7checks build=' + build + ' w={} h={} adapter={:?} limits={:?}; sparse checks; independent controls allocate extra scratch; readbacks change synchronization", w, h, gpu.info, gpu.device.limits());'
    replace_checked(render, old, new)
    print('V5 integrated seven checks installed; Rust compilation and device validation still required')


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
