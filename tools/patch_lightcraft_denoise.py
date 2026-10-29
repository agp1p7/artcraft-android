import sys
from pathlib import Path

def replace_checked(path, old, new):
    text = path.read_text()
    if new in text:
        return
    if text.count(old) != 1:
        raise RuntimeError(f'Unexpected source format: {path}; refusing to patch')
    path.write_text(text.replace(old, new, 1))

def patch(root):
    replace_checked(root / 'Cargo.toml',
        'lightcraft-engine = { path = "../../crates/engine" }',
        'lightcraft-engine = { path = "../../crates/engine", features = ["rawnind-model"] }')
    replace_checked(root / 'src/lib.rs',
        'Session::new().with_fs()',
        'Session::new().with_fs().with_default_denoise_models()')
    upstream = root.parents[1]
    replace_checked(upstream / 'crates/gpu/src/lib.rs',
        '    depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange',
        '    // Experimental Android workaround: use the reference CPU image pipeline.\n'
        '    // This does not disable the UI compositor or independently configured AI inference.\n'
        '    !cfg!(target_os = "android") && depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange')
    encoder = upstream / 'crates/codecs/src/encode.rs'
    text = encoder.read_text()
    old_workaround = (
        '    // Experimental Android workaround: retain requested sampling, use serial jpeg-encoder.\n'
        '    if subsampling != ChromaSubsampling::S422 && !cfg!(target_os = "android") {')
    if old_workaround in text:
        if text.count(old_workaround) != 1:
            raise RuntimeError('Ambiguous previous JPEG workaround')
        encoder.write_text(text.replace(old_workaround,
            '    if subsampling != ChromaSubsampling::S422 {', 1))
    elif '    if subsampling != ChromaSubsampling::S422 {' not in text:
        raise RuntimeError('Unexpected JPEG encoder; inspect manually')
    print('Android CPU image-render fallback enabled; original JPEG encoder retained; device validation required')

if __name__ == '__main__':
    patch(Path(sys.argv[1]))
