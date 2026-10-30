
type V6Samples = Vec<(usize, Vec<f32>)>;
fn gpu_accept_v6_before(cx: &mut Cx<'_>, k: &str, n: usize, src: Option<&Buf>) -> Option<V6Samples> {
    if n < (16 << 20) || !["wb_k", "chroma_k"].contains(&k) || crate::ctx::failed() { return None; }
    let src = src?;
    if n.checked_mul(3).is_none_or(|len| len > src.len) { crate::ctx::fail(crate::ctx::FailKind::Fatal, format!("v6 {k}: invalid input")); return None; }
    let mut points = vec![0, n / 4, n / 2, n * 3 / 4, n - 4];
    for b in [1usize << 20, 16usize << 20] { if b + 4 <= n { points.extend([b - 1, b, b + 1]); } }
    points.sort_unstable(); points.dedup();
    let mut samples = Vec::new();
    for start in points {
        let part = cx.slice(src, start * 3, 12);
        let values: Vec<f32> = cx.read(&part, 12);
        if crate::ctx::failed() { return None; }
        samples.push((start, values));
    }
    Some(samples)
}
fn gpu_accept_v6_after(cx: &mut Cx<'_>, k: &str, n: usize, p: &[u32], dst: &Buf, before: Option<V6Samples>) {
    let Some(before) = before else { return; };
    if crate::ctx::failed() { return; }
    if n.checked_mul(3).is_none_or(|len| len > dst.len) || (k == "wb_k" && p.len() < 11) { crate::ctx::fail(crate::ctx::FailKind::Fatal, format!("v6 {k}: invalid output or params")); return; }
    let mut checked = 0usize; let mut mismatches = 0usize; let mut max_error = 0.0f32;
    for (start, input) in before {
        let part = cx.slice(dst, start * 3, 12);
        let output: Vec<f32> = cx.read(&part, 12);
        if crate::ctx::failed() { log::warn!("gpu-diag: accept-v6 kernel={} passed=false readback_failed=true", k); return; }
        let mut bad = 0usize;
        for (a, b) in input.chunks_exact(3).zip(output.chunks_exact(3)) {
            let mut expected = [a[0], a[1], a[2]];
            if k == "wb_k" {
                if p[1] != 0 { for row in 0..3 { expected[row] = f32::from_bits(p[2 + row * 3]) * a[0] + f32::from_bits(p[3 + row * 3]) * a[1] + f32::from_bits(p[4 + row * 3]) * a[2]; } }
                for v in &mut expected { *v = v.max(0.0); }
            } else {
                let y = (a[0] * 0.2627 + a[1] * 0.6780 + a[2] * 0.0593).max(1e-6);
                for v in &mut expected { *v /= y; }
            }
            for (e, got) in expected.iter().zip(b) {
                let error = (*e - *got).abs();
                bad += usize::from(!e.is_finite() || !got.is_finite() || error > 2e-5 + e.abs() * 1e-4);
                max_error = max_error.max(error); checked += 1;
            }
        }
        mismatches += bad;
        if bad > 0 { log::warn!("gpu-diag: accept-v6 kernel={} start={} mismatch_channels={}", k, start, bad); }
    }
    let passed = checked > 0 && mismatches == 0;
    log::warn!("gpu-diag: accept-v6 kernel={} checked_channels={} mismatch_channels={} max_abs_error={} passed={} sparse_only=true probes_change_timing=true", k, checked, mismatches, max_error, passed);
    if !passed { crate::ctx::fail(crate::ctx::FailKind::Fatal, format!("v6 {k}: CPU-reference mismatch; GPU output rejected")); }
}
