"""Build Lambda deployment ZIP package.

Installs production + aws dependencies into a staging directory, then
copies the burnwatch source and lambda_handler.py and zips everything.

Run with: python build_lambda.py
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
STAGE = ROOT / "build" / "lambda_stage"
OUT_ZIP = ROOT / "lambda_package.zip"

print("=== BurnWatch Lambda package builder ===")

# 1. Clean staging dir
if STAGE.exists():
    shutil.rmtree(STAGE)
STAGE.mkdir(parents=True)

# 2. Install 3rd-party dependencies only (no local package) using manylinux binaries
print("Installing 3rd-party dependencies into staging directory...")
deps = [
    "pydantic>=2.5,<3",
    "fastapi>=0.109,<1",
    "uvicorn[standard]>=0.27,<1",
    "click>=8.1,<9",
    "python-dotenv>=1.0,<2",
    "pyserial>=3.5,<4",
    "boto3>=1.34,<2",
    "mangum>=0.17,<1",
]
subprocess.run(
    [
        sys.executable, "-m", "pip", "install",
        "--quiet",
        "--target", str(STAGE),
        "--platform", "manylinux2014_x86_64",
        "--python-version", "3.11",
        "--only-binary", ":all:",
        "--upgrade",
        *deps,
    ],
    check=True,
)
print("Dependencies installed.")

# 3. Copy burnwatch source package
print("Copying burnwatch source package...")
src_pkg = ROOT / "src" / "burnwatch"
dest_pkg = STAGE / "burnwatch"
if dest_pkg.exists():
    shutil.rmtree(dest_pkg)
shutil.copytree(src_pkg, dest_pkg)

# 4. Copy lambda_handler.py
shutil.copy(ROOT / "lambda_handler.py", STAGE / "lambda_handler.py")

# 5. Remove pyc caches from staging to keep the package lean
for cache in STAGE.rglob("__pycache__"):
    shutil.rmtree(cache)

# 6. Build ZIP
print(f"Building {OUT_ZIP} ...")
if OUT_ZIP.exists():
    OUT_ZIP.unlink()

with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for file in sorted(STAGE.rglob("*")):
        if file.is_file():
            arcname = file.relative_to(STAGE)
            zf.write(file, arcname)

size_mb = OUT_ZIP.stat().st_size / (1024 * 1024)
print(f"Package ready: {OUT_ZIP} ({size_mb:.1f} MB)")
