
type V5Samples = Vec<(usize, Vec<f32>)>;
fn gpu_diag_v5_points(n: usize) -> Vec<usize> {
    if n < 64 { return vec![]; }
    let mut centers = vec![0, n / 4, n / 2, n * 3 / 4, n - 1];
    for b in ((1 << 20)..n).step_by(1 << 20) {
        centers.extend([b - 1, b, (b + 1).min(n - 1)]);
    }
    for bytes in [64usize << 20, 128usize << 20, 256usize << 20] {
        let b = bytes / 12;
        if b > 0 && b + 1 < n { centers.extend([b - 1, b, b + 1]); }
    }
    let mut starts: Vec<_> = centers.into_iter().map(|i| i.min(n - 4)).collect();
    starts.sort_unstable(); starts.dedup(); starts
}
fn gpu_diag_v5_sample(cx: &mut Cx<'_>, b: &Buf, n: usize, stage: &str) -> V5Samples {
    if crate::ctx::failed() || n.checked_mul(3).is_none_or(|v| v > b.len) { return vec![]; }
    let mut samples = Vec::new();
    for start in gpu_diag_v5_points(n) {
        let part = cx.slice(b, start * 3, 12);
        let values: Vec<f32> = cx.read(&part, 12);
        log::warn!("gpu-diag: matched-v5 stage={} n={} start={} zero={} nonfinite={} failed={}", stage, n, start,
            values.iter().filter(|v| **v == 0.0).count(), values.iter().filter(|v| !v.is_finite()).count(), crate::ctx::failed());
        samples.push((start, values));
        if crate::ctx::failed() { break; }
    }
    samples
}
fn gpu_diag_v5_before(cx: &mut Cx<'_>, k: &str, n: usize, p: &[u32], src: Option<&Buf>, dst: &Buf) -> Option<V5Samples> {
    if n < (16 << 20) || !["wb_k", "chroma_k"].contains(&k) { return None; }
    let input = src?;
    log::warn!("gpu-diag: v5-integrated-7checks kernel={} host_params={:?} input_words={} input_bytes={} input_handle={:?} output_words={} output_bytes={} output_handle={:?}; bindings use entire buffer; probes alter synchronization", k, p, input.len, input.raw().size(), input.raw(), dst.len, dst.raw().size(), dst.raw());
    Some(gpu_diag_v5_sample(cx, input, n, &format!("{}-input", k)))
}
fn gpu_diag_v5_after(cx: &mut Cx<'_>, k: &str, n: usize, p: &[u32], src: Option<&Buf>, dst: &Buf, before: Option<V5Samples>) {
    let Some(before) = before else { return; };
    for (name, host, record) in crate::ctx::gpu_diag_v5_records() {
        let actual: Vec<u32> = cx.read(&record, host.len() + 2);
        let ok = actual.len() == host.len() + 2 && actual[0] as usize == host.len() && actual[1] == *host.last().unwrap_or(&0) && actual[2..] == host[..];
        log::warn!("gpu-diag: parameter-v5 kernel={} host={:?} device={:?} match={} failed={}; separate echo shader, same production parameter buffer", name, host, actual, ok, crate::ctx::failed());
    }
    let after = gpu_diag_v5_sample(cx, dst, n, &format!("{}-output", k));
    for ((start, input), (other, output)) in before.iter().zip(&after) {
        if start != other { continue; }
        let mut mismatch = 0usize;
        let mut max_error = 0.0f32;
        for (a, b) in input.chunks_exact(3).zip(output.chunks_exact(3)) {
            let mut expected = [a[0], a[1], a[2]];
            if k == "wb_k" && p.len() >= 11 {
                if p[1] != 0 {
                    for row in 0..3 { expected[row] = f32::from_bits(p[2 + row * 3]) * a[0] + f32::from_bits(p[3 + row * 3]) * a[1] + f32::from_bits(p[4 + row * 3]) * a[2]; }
                }
                for v in &mut expected { *v = v.max(0.0); }
            } else if k == "chroma_k" {
                let y = (a[0] * 0.2627 + a[1] * 0.6780 + a[2] * 0.0593).max(1e-6);
                for v in &mut expected { *v /= y; }
            } else { continue; }
            for (e, got) in expected.iter().zip(b) {
                let error = (*e - *got).abs();
                mismatch += usize::from(!e.is_finite() || !got.is_finite() || error > 2e-5 + e.abs() * 1e-4);
                max_error = max_error.max(error);
            }
        }
        log::warn!("gpu-diag: reference-v5 kernel={} start={} mismatch_channels={} max_abs_error={} input_first={:?} output_first={:?}", k, start, mismatch, max_error, &input[..input.len().min(3)], &output[..output.len().min(3)]);
    }
    if k == "wb_k" && !crate::ctx::failed() {
        static DONE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
        if !DONE.swap(true, std::sync::atomic::Ordering::Relaxed) {
            if let Some(input) = src { gpu_diag_v5_controls(cx, input, n, &before); }
        }
    }
}
fn gpu_diag_v5_controls(cx: &mut Cx<'_>, src: &Buf, n: usize, reference: &V5Samples) {
    let kernel = cx.gpu.gpu_diag_v5_copy_kernel();
    for (mode, chunk, wait, fresh) in [
        ("fresh-1m-batched", 1usize << 20, false, true),
        ("fresh-256k-batched", 1usize << 18, false, true),
        ("fresh-1m-waited", 1usize << 20, true, true),
        ("pool-eligible-1m-batched", 1usize << 20, false, false),
    ] {
        if crate::ctx::failed() { break; }
        let dst = if fresh { cx.gpu.gpu_diag_v5_fresh(n * 3) } else { cx.gpu.buffer(n * 3) };
        log::warn!("gpu-diag: control-v5 begin mode={} scratch_bytes={} extra_memory=true source_unchanged=true", mode, dst.raw().size());
        for op in [0u32, 1u32] {
            for offset in (0..n).step_by(chunk) {
                let take = (n - offset).min(chunk);
                let enc = cx.enc.get_or_insert_with(|| cx.gpu.encoder());
                cx.gpu.gpu_diag_v5_copy_run(enc, &kernel, src, &dst, [n as u32, offset as u32, take as u32, op]);
                if wait { cx.sync(); }
            }
            if op == 0 {
                let filled = gpu_diag_v5_sample(cx, &dst, n, &format!("{}-sentinel", mode));
                let wrong: usize = filled.iter().map(|(_, v)| v.iter().filter(|x| **x != -12345.0).count()).sum();
                log::warn!("gpu-diag: coverage-v5 mode={} sentinel_fill_wrong_sampled_channels={} not_full_scan=true", mode, wrong);
            }
        }
        let copied = gpu_diag_v5_sample(cx, &dst, n, &format!("{}-copy", mode));
        let mut wrong = 0usize;
        let mut sentinel = 0usize;
        for ((a, input), (b, output)) in reference.iter().zip(&copied) {
            if a != b { continue; }
            wrong += input.iter().zip(output).filter(|(x, y)| x.to_bits() != y.to_bits()).count();
            sentinel += output.iter().filter(|x| **x == -12345.0).count();
        }
        log::warn!("gpu-diag: control-v5 end mode={} copy_mismatch_sampled_channels={} sentinel_remaining_sampled_channels={} failed={} not_full_scan=true pool_reuse_not_guaranteed=true", mode, wrong, sentinel, crate::ctx::failed());
        drop(dst); cx.flush();
    }
}
