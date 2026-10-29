import subprocess
import sys
from pathlib import Path
from patch_lightcraft_gpu_diagnostics_v2 import replace_checked

HEADER = '    pub fn run(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], bufs: &[Option<&Buf>], groups: [u32; 3]) {'
WRAPPER = r"""    pub fn run(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], bufs: &[Option<&Buf>], groups: [u32; 3]) {
        const MAP_KERNELS: &[&str] = &[
            "log_lum_k", "dark_k", "guided_pre", "guided_ab", "guided_apply",
            "wb_k", "nr_lum", "chroma_k", "nr_col", "subsample", "redeye_k",
            "xguided_pre", "xguided_ab", "xguided_apply",
        ];
        if !MAP_KERNELS.contains(&name) {
            self.run_inner(enc, name, p, bufs, groups);
            return;
        }
        let Some(&count) = p.first() else {
            fail(FailKind::Fatal, format!("map kernel {name} has no element count"));
            return;
        };
        const CHUNK: u32 = 1 << 20;
        let mut offset = 0u32;
        let mut params = p.to_vec();
        params.push(0);
        let last = params.len() - 1;
        while offset < count {
            let take = (count - offset).min(CHUNK);
            params[last] = offset;
            let one_row = [take.div_ceil(256), 1, 1];
            log::warn!("gpu-diag: candidate-v3 kernel={} offset={} count={} total={} groups={:?}", name, offset, take, count, one_row);
            self.run_inner(enc, name, &params, bufs, one_row);
            offset += take;
        }
    }

    fn run_inner(&self, enc: &mut wgpu::CommandEncoder, name: &str, p: &[u32], bufs: &[Option<&Buf>], groups: [u32; 3]) {"""


def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_diagnostics_v2.py')), str(root)], check=True)
    upstream = root.parents[1]
    shader = upstream / 'crates/gpu/src/wgsl/map.wgsl'
    old = '    let i = lin_index(g, nw);'
    new = '    let i = g.x + pu(arrayLength(&P) - 1u); // candidate-v3: explicit chunk offset'
    text = shader.read_text()
    if new not in text:
        if text.count(old) != 14:
            raise RuntimeError('Expected exactly 14 map kernel index expressions')
        shader.write_text(text.replace(old, new))
    elif text.count(new) != 14 or old in text:
        raise RuntimeError('Incomplete v3 map shader patch')
    replace_checked(upstream / 'crates/gpu/src/ctx.rs', HEADER, WRAPPER)
    print('GPU candidate v3: single-row 1M-element map dispatches with explicit offsets; original resolution retained; device validation required')


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_diagnostics_v2.py')), '--prepare'], check=True)
    else:
        patch(Path(sys.argv[1]))
