import subprocess
import sys
from pathlib import Path

subprocess.run([sys.executable, '-m', 'py_compile', 'tools/patch_lightcraft_export_full.py', 'tools/patch_lightcraft_multiselect.py', 'tools/test_lightcraft_multiselect.py'], check=True)
subprocess.run([sys.executable, 'tools/test_lightcraft_multiselect.py'], check=True)
subprocess.run([sys.executable, 'tools/patch_lightcraft_gpu_window_v6.py', '--prepare'], check=True)
subprocess.run([sys.executable, 'tools/patch_lightcraft_export_full.py', '--prepare'], check=True)
p = Path('lib/android_project.py')
s = p.read_text()
anchor = '    root, android_dir, app, version = Path(argv[1]), Path(argv[2]), argv[3], argv[4]\n'
hook = '    if app == "lightcraft":\n        import subprocess\n        subprocess.run([sys.executable, str(root / "tools/patch_lightcraft_gpu_window_v6.py"), str(android_dir)], check=True)\n'
for script in ['patch_lightcraft_local_ui.py', 'patch_lightcraft_settings_log.py', 'patch_lightcraft_export_progress.py', 'patch_lightcraft_export_full.py', 'patch_lightcraft_multiselect.py']:
    old = '        subprocess.run([sys.executable, str(root / "tools/' + script + '"), str(android_dir)], check=True)\n'
    s = s.replace(old, '')
for previous in ['tools/patch_lightcraft_gpu_candidate_v3.py', 'tools/patch_lightcraft_gpu_stage_v4.py', 'tools/patch_lightcraft_gpu_stage_v5.py']:
    s = s.replace(previous, 'tools/patch_lightcraft_gpu_window_v6.py')
if s.count(anchor) != 1:
    raise RuntimeError('Android project generator format changed')
if hook not in s:
    s = s.replace(anchor, anchor + hook, 1)
if s.count(hook) != 1:
    raise RuntimeError('Expected exactly one v6 GPU hook')
full_hook = '        subprocess.run([sys.executable, str(root / "tools/patch_lightcraft_export_full.py"), str(android_dir)], check=True)\n'
multi_hook = '        subprocess.run([sys.executable, str(root / "tools/patch_lightcraft_multiselect.py"), str(android_dir)], check=True)\n'
s = s.replace(hook, hook + full_hook + multi_hook, 1)
p.write_text(s)
