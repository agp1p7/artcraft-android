from pathlib import Path
p = Path('lib/android_project.py')
s = p.read_text()
anchor = '    root, android_dir, app, version = Path(argv[1]), Path(argv[2]), argv[3], argv[4]\n'
hook = '    if app == "lightcraft":\n        import subprocess\n        subprocess.run([sys.executable, str(root / "tools/patch_lightcraft_denoise.py"), str(android_dir)], check=True)\n'
if s.count(anchor) != 1:
    raise RuntimeError('Android project generator format changed')
if hook not in s:
    p.write_text(s.replace(anchor, anchor + hook))
