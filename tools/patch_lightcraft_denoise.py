import sys
from pathlib import Path

def patch(root):
    cargo = root / "Cargo.toml"
    source = root / "src/lib.rs"
    c, s = cargo.read_text(), source.read_text()
    old_dep = 'lightcraft-engine = { path = "../../crates/engine" }'
    new_dep = 'lightcraft-engine = { path = "../../crates/engine", features = ["rawnind-model"] }'
    old_init = 'Session::new().with_fs()'
    new_init = 'Session::new().with_fs().with_default_denoise_models()'
    for text, old, new in [(c, old_dep, new_dep), (s, old_init, new_init)]:
        if new not in text and text.count(old) != 1:
            raise RuntimeError("Unexpected launcher format; refusing to patch")
    cargo.write_text(c.replace(old_dep, new_dep))
    source.write_text(s if new_init in s else s.replace(old_init, new_init))
    print("Experimental denoise runtime, model catalogue and directory enabled; device test required")

if __name__ == "__main__":
    patch(Path(sys.argv[1]))
