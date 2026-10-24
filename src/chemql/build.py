import json
import tarfile
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

JSON_MANIFEST = ROOT / "cqlpackage.json"
TOML_MANIFEST = ROOT / "cqlpackage.toml"

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "dist",
    "build",
}

EXCLUDED_FILES = {
    "build.py",
    ".DS_Store",
}


def load_manifest():
    # JSON takes priority when both manifests exist.
    if JSON_MANIFEST.is_file():
        with JSON_MANIFEST.open("r", encoding="utf-8") as f:
            return json.load(f), JSON_MANIFEST

    if TOML_MANIFEST.is_file():
        if tomllib is None:
            raise RuntimeError(
                "TOML support requires Python 3.11 or newer."
            )

        with TOML_MANIFEST.open("rb") as f:
            return tomllib.load(f), TOML_MANIFEST

    raise FileNotFoundError(
        "Neither cqlpackage.json nor cqlpackage.toml was found."
    )


def main():
    package, manifest_path = load_manifest()

    name = package["name"]
    version = str(package["version"])

    root_name = f"{name}-{version}"
    archive_name = f"{root_name}.tar.gz"

    DIST.mkdir(exist_ok=True)
    archive_path = DIST / archive_name

    included = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(ROOT)

        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue

        if path.name in EXCLUDED_FILES:
            continue

        if path.suffix in {".pyc", ".pyo"}:
            continue

        included.append(path)

    if manifest_path not in included:
        raise RuntimeError("The package manifest was not included.")

    with tarfile.open(archive_path, "w:gz") as archive:
        for path in sorted(included):
            relative = path.relative_to(ROOT)
            archive.add(
                path,
                arcname=f"{root_name}/{relative.as_posix()}",
                recursive=False,
            )

    print(f"Package  : {name}")
    print(f"Version  : {version}")
    print(f"Manifest : {manifest_path.name}")
    print(f"Files    : {len(included)}")
    print(f"Archive  : {archive_path}")
    print("Build successful!")


if __name__ == "__main__":
    main()