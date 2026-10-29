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
    cargo = root / "Cargo.toml"
    source = root / "src/lib.rs"
    replace_checked(cargo,
        'lightcraft-engine = { path = "../../crates/engine" }',
        'lightcraft-engine = { path = "../../crates/engine", features = ["rawnind-model"] }')
    replace_checked(source,
        'Session::new().with_fs()',
        'Session::new().with_fs().with_default_denoise_models()')
    upstream = root.parents[1]
    replace_checked(upstream / 'crates/gpu/src/lib.rs',
        '    depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange',
        '    // Experimental Android workaround: use the reference CPU image pipeline.\n'
        '    // This does not disable the UI compositor or independently configured AI inference.\n'
        '    !cfg!(target_os = "android") && depth == lightcraft_pipeline::OutputDepth::U8 && !device_proof && overlay != lightcraft_pipeline::Overlay::HdrRange')
    replace_checked(upstream / 'crates/codecs/src/encode.rs',
        '    if subsampling != ChromaSubsampling::S422 {',
        '    // Experimental Android workaround: retain requested sampling, use serial jpeg-encoder.\n'
        '    if subsampling != ChromaSubsampling::S422 && !cfg!(target_os = "android") {')
    print('Experimental Android export workaround applied: CPU render and serial JPEG; root cause unconfirmed; device validation required')

if __name__ == "__main__":
    patch(Path(sys.argv[1]))
