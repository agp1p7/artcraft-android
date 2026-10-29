import subprocess
import sys
from pathlib import Path


def replace_checked(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected v2 source format: {path}: {old[:60]}')
    path.write_text(text.replace(old, new, 1))


JAVA = r"""
    private final java.util.concurrent.atomic.AtomicBoolean gpuDiagSaving = new java.util.concurrent.atomic.AtomicBoolean(false);

    private void installGpuDiagExport() {
        android.widget.Button button = new android.widget.Button(this);
        button.setText("匯出 GPU 日誌");
        android.widget.FrameLayout.LayoutParams lp = new android.widget.FrameLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.WRAP_CONTENT, android.view.ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = android.view.Gravity.TOP | android.view.Gravity.END;
        lp.topMargin = (int) (64 * getResources().getDisplayMetrics().density);
        addContentView(button, lp);
        button.setOnClickListener(v -> {
            if (!gpuDiagSaving.compareAndSet(false, true)) return;
            new Thread(() -> {
                android.net.Uri uri = null;
                Process process = null;
                try {
                    if (android.os.Build.VERSION.SDK_INT < 29) throw new java.io.IOException("Requires Android 10+");
                    StringBuilder text = new StringBuilder("LightCraft GPU diagnostics v2\nModel: ")
                            .append(android.os.Build.MODEL).append("\nAndroid: ")
                            .append(android.os.Build.VERSION.RELEASE)
                            .append("\nRecent own-process log snapshot; may be incomplete. Probe reads change timing.\n");
                    process = new ProcessBuilder("logcat", "-d", "-v", "threadtime",
                            "--pid=" + android.os.Process.myPid(), "-t", "10000").redirectErrorStream(true).start();
                    try (java.io.BufferedReader reader = new java.io.BufferedReader(
                            new java.io.InputStreamReader(process.getInputStream(), java.nio.charset.StandardCharsets.UTF_8))) {
                        String line;
                        int hits = 0;
                        while ((line = reader.readLine()) != null) {
                            if (line.contains("gpu-diag:") || line.contains("gpu:")) {
                                text.append(line).append('\n');
                                hits++;
                                if (text.length() > 500000) {
                                    text.append("OUTPUT TRUNCATED\n");
                                    break;
                                }
                            }
                        }
                        if (hits == 0) text.append("No matching GPU messages; log access or retention may be limited.\n");
                    }
                    process.destroy();
                    String name = "lightcraft-gpu-" + System.currentTimeMillis() + ".txt";
                    android.content.ContentValues values = new android.content.ContentValues();
                    values.put(android.provider.MediaStore.MediaColumns.DISPLAY_NAME, name);
                    values.put(android.provider.MediaStore.MediaColumns.MIME_TYPE, "text/plain");
                    values.put(android.provider.MediaStore.MediaColumns.RELATIVE_PATH, android.os.Environment.DIRECTORY_DOWNLOADS);
                    values.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 1);
                    uri = getContentResolver().insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, values);
                    if (uri == null) throw new java.io.IOException("Could not create diagnostic file");
                    try (java.io.OutputStream out = getContentResolver().openOutputStream(uri)) {
                        if (out == null) throw new java.io.IOException("Could not open diagnostic file");
                        out.write(text.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
                    }
                    android.content.ContentValues ready = new android.content.ContentValues();
                    ready.put(android.provider.MediaStore.MediaColumns.IS_PENDING, 0);
                    getContentResolver().update(uri, ready, null, null);
                    final android.net.Uri saved = uri;
                    runOnUiThread(() -> {
                        android.widget.Toast.makeText(this, "已儲存至下載資料夾：" + name, android.widget.Toast.LENGTH_LONG).show();
                        android.content.Intent share = new android.content.Intent(android.content.Intent.ACTION_SEND);
                        share.setType("text/plain");
                        share.putExtra(android.content.Intent.EXTRA_STREAM, saved);
                        share.setClipData(android.content.ClipData.newRawUri("GPU diagnostics", saved));
                        share.addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        try { startActivity(android.content.Intent.createChooser(share, "分享 GPU 診斷日誌")); }
                        catch (Exception e) { android.util.Log.w(TAG, "Diagnostic file saved, share unavailable", e); }
                    });
                } catch (Exception e) {
                    if (uri != null) getContentResolver().delete(uri, null, null);
                    final String message = e.toString();
                    runOnUiThread(() -> android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show());
                } finally {
                    if (process != null) process.destroy();
                    gpuDiagSaving.set(false);
                }
            }, "gpu-diag-export").start();
        });
    }
"""

PROBE = r"""
fn gpu_diag_probe(cx: &mut Cx<'_>, b: &Buf, w: usize, h: usize, stage: &str) {
    if w == 0 || h == 0 || crate::ctx::failed() { return; }
    let width = w.min(64);
    let x = (w - width) / 2;
    for y in [0, h / 4, h / 2, h * 3 / 4, h - 1] {
        let part = cx.slice(b, (y * w + x) * 3, width * 3);
        let values: Vec<f32> = cx.read(&part, width * 3);
        let nonfinite = values.iter().filter(|v| !v.is_finite()).count();
        let zeros = values.iter().filter(|v| **v == 0.0).count();
        let min = values.iter().copied().filter(|v| v.is_finite()).fold(f32::INFINITY, f32::min);
        let max = values.iter().copied().filter(|v| v.is_finite()).fold(f32::NEG_INFINITY, f32::max);
        log::warn!("gpu-diag: probe stage={} w={} h={} x={} y={} pixels={} zero_channels={} nonfinite={} min={} max={}", stage, w, h, x, y, width, zeros, nonfinite, min, max);
    }
}

"""

REGIONS = r"""
        if let Some((w, h)) = GPU_DIAG_DIMS.with(|d| d.take()) {
            if w > 0 && h > 0 && w.checked_mul(h).and_then(|n| n.checked_mul(4)) == Some(data.len()) {
                let rows = h.div_ceil(16);
                for y0 in (0..h).step_by(rows) {
                    let y1 = (y0 + rows).min(h);
                    let region = &data[y0 * w * 4..y1 * w * 4];
                    let mut black = 0usize;
                    let mut alpha_zero = 0usize;
                    let mut alpha_other = 0usize;
                    for px in region.chunks_exact(4) {
                        black += usize::from(px[0] == 0 && px[1] == 0 && px[2] == 0);
                        alpha_zero += usize::from(px[3] == 0);
                        alpha_other += usize::from(px[3] != 0 && px[3] != 255);
                    }
                    log::warn!("gpu-diag: output-region w={} h={} y0={} y1={} pixels={} rgb_black={} alpha_zero={} alpha_other={}", w, h, y0, y1, region.len() / 4, black, alpha_zero, alpha_other);
                }
            }
        }
"""


def prepare():
    template = Path(__file__).resolve().parents[1] / 'templates/android/SafActivity.java'
    replace_checked(template, '    private static final String TAG = "__TAG__";',
                    '    private static final String TAG = "__TAG__";\n' + JAVA)
    replace_checked(template, '        handleIncomingFiles(getIntent());',
                    '        handleIncomingFiles(getIntent());\n        installGpuDiagExport();')


def patch(root):
    subprocess.run([sys.executable, str(Path(__file__).with_name('patch_lightcraft_gpu_diagnostics.py')), str(root)], check=True)
    upstream = root.parents[1]
    ctx = upstream / 'crates/gpu/src/ctx.rs'
    replace_checked(ctx, 'impl Gpu {',
        'thread_local! { static GPU_DIAG_DIMS: std::cell::Cell<Option<(usize, usize)>> = const { std::cell::Cell::new(None) }; }\n\nimpl Gpu {')
    replace_checked(ctx, '        assert_eq!(bufs.len(), k.nbuf, "{name}: binding count");',
        '        assert_eq!(bufs.len(), k.nbuf, "{name}: binding count");\n'
        '        if name == "main" {\n'
        '            let field = |n| crate::params::index(n).and_then(|i| p.get(i)).copied().unwrap_or(0);\n'
        '            let (w, h, y0) = (field("W"), field("H"), field("Y0"));\n'
        '            GPU_DIAG_DIMS.with(|d| d.set(Some((w as usize, h as usize))));\n'
        '            log::warn!("gpu-diag: finish-band w={} h={} y0={} covered_rows={} groups={:?}", w, h, y0, (groups[1] as u64 * 16).min(h.saturating_sub(y0) as u64), groups);\n'
        '        }')
    replace_checked(ctx, '        let out: Vec<T> = bytemuck::cast_slice(&data).to_vec();',
                    REGIONS + '        let out: Vec<T> = bytemuck::cast_slice(&data).to_vec();')
    render = upstream / 'crates/gpu/src/render.rs'
    replace_checked(render, 'pub fn render(', PROBE + 'pub fn render(')
    replace_checked(render, '    let n = w * h;\n    let _limit = match fault {',
        '    let n = w * h;\n'
        '    log::warn!("gpu-diag: render-v2 w={} h={} adapter={:?} limits={:?}; probes alter synchronization", w, h, gpu.info, gpu.device.limits());\n'
        '    let _limit = match fault {')
    replace_checked(render, '    lap("sample", &mut t, &mut cx);',
        '    lap("sample", &mut t, &mut cx);\n    gpu_diag_probe(&mut cx, &sampled, w, h, "sample");')
    replace_checked(render, '    lap("wb/nr", &mut t, &mut cx);',
        '    lap("wb/nr", &mut t, &mut cx);\n    gpu_diag_probe(&mut cx, &lin, w, h, "linear");')
    print('GPU diagnostics v2 installed: sparse intermediate probes, final spatial statistics and band metadata; not a validated fix')


if __name__ == '__main__':
    if sys.argv[1] == '--prepare':
        prepare()
    else:
        patch(Path(sys.argv[1]))
