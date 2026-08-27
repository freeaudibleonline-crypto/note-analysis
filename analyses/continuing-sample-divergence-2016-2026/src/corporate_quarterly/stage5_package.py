"""Deterministic, scoped clean packaging for the 2026Q1 v3.2 release."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable
import zipfile

from .constants import PROJECT_ROOT


ARCHIVE_ROOT = "corporate_quarterly_pipeline"
PACKAGE_FILENAME = "corporate_quarterly_2026Q1_v3_2_clean.zip"
FORBIDDEN_COMPONENTS = frozenset({"__MACOSX", "__pycache__", ".pytest_cache"})
FORBIDDEN_NAMES = frozenset({".DS_Store"})
FORBIDDEN_SUFFIXES = frozenset({".pyc", ".pyo"})
ROOT_FILES = ("README.md", "Makefile", "pyproject.toml", "requirements.lock")
RELEASE_REQUIRED = (
    "article_note.md",
    "article_note_render.md",
    "claims_v3_2.csv",
    "claim_corrections_v3_2.csv",
    "mismatch_heatmap.csv",
    "headline_2x2.csv",
    "deadband_sensitivity.csv",
    "rounding_sensitivity.csv",
    "unit_registry.json",
    "chart_manifest_v3_2.json",
    "expected_value_changes_v3_2.csv",
    "audit_v3_2.md",
    "v3_1_immutability_manifest.json",
    "charts/mismatch_heatmap.png",
    "charts/headline_2x2.png",
    "charts/deadband_sensitivity.png",
)
SOURCE_REQUIRED = (
    "outputs/2026Q1_v3/main_vs_continuing_sample.csv",
    "outputs/2026Q1_v3/continuing_sample_raw_manifest.json",
    "outputs/2026Q1_v3_1/claims_v3_1.csv",
    "outputs/2026Q1_v3_1/mismatch_heatmap.csv",
    "outputs/2026Q1_v3_1/headline_2x2.csv",
    "outputs/2026Q1_v3_1/deadband_sensitivity.csv",
    "outputs/2026Q1_v3_1/rounding_sensitivity.csv",
    "data/raw/2026Q1/data_manifest.json",
    "data/raw/continuing_sample_2026Q1/data_manifest.json",
    "data/raw/historical_2026Q1/data_manifest.json",
    "data/raw/non_operating_2026Q1/data_manifest.json",
)


class Stage5PackageError(RuntimeError):
    """Raised when the v3.2 archive is incomplete or unclean."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_forbidden(relative: Path) -> bool:
    return bool(
        set(relative.parts) & FORBIDDEN_COMPONENTS
        or relative.name in FORBIDDEN_NAMES
        or relative.suffix.lower() in FORBIDDEN_SUFFIXES
    )


def _iter_tree(root: Path, relative_root: Path) -> Iterable[Path]:
    directory = root / relative_root
    if not directory.is_dir():
        raise Stage5PackageError(f"Required package directory is missing: {relative_root}")
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise Stage5PackageError(f"Symlink is forbidden in clean ZIP: {path}")
        if path.is_file() and not _is_forbidden(path.relative_to(root)):
            yield path


def collect_stage5_package_files(
    project_root: Path = PROJECT_ROOT,
    *,
    release_dir: Path | None = None,
    destination: Path | None = None,
) -> list[Path]:
    """Collect only reproducibility inputs and v3.2 public outputs."""
    root = Path(project_root).resolve()
    release = Path(release_dir or root / "outputs" / "2026Q1_v3_2").resolve()
    if release != root / "outputs" / "2026Q1_v3_2":
        raise Stage5PackageError(f"Unexpected v3.2 release directory: {release}")
    files: list[Path] = []
    for name in ROOT_FILES:
        path = root / name
        if not path.is_file():
            raise Stage5PackageError(f"Required root file is missing: {name}")
        files.append(path)
    for relative in (Path("config"), Path("src"), Path("tests")):
        files.extend(_iter_tree(root, relative))
    for relative in SOURCE_REQUIRED:
        path = root / relative
        if not path.is_file():
            raise Stage5PackageError(f"Required canonical source is missing: {relative}")
        files.append(path)
    for relative in RELEASE_REQUIRED:
        path = release / relative
        if not path.is_file():
            raise Stage5PackageError(f"Required v3.2 artifact is missing: {relative}")
        files.append(path)
    excluded = Path(destination).resolve() if destination is not None else None
    unique = {
        path.resolve(): path
        for path in files
        if path.resolve() != excluded and not _is_forbidden(path.relative_to(root))
    }
    return sorted(unique.values(), key=lambda path: path.relative_to(root).as_posix())


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def create_stage5_clean_zip(
    destination: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create the deterministic v3.2 clean ZIP after an audit PASS."""
    root = Path(project_root).resolve()
    release = root / "outputs" / "2026Q1_v3_2"
    destination = Path(destination).resolve()
    if destination != release / PACKAGE_FILENAME:
        raise Stage5PackageError(f"Unexpected v3.2 archive destination: {destination}")
    audit_path = release / "audit_v3_2.md"
    if not audit_path.is_file():
        raise Stage5PackageError("audit_v3_2.md is missing")
    audit_text = audit_path.read_text(encoding="utf-8")
    if "**STATUS: PASS**" not in audit_text or "| FAIL |" in audit_text:
        raise Stage5PackageError("v3.2 audit is not PASS")
    if (release / "FINAL_RELEASE_FAIL.md").exists() or (
        release / "IMMUTABILITY_FAIL.md"
    ).exists():
        raise Stage5PackageError("A v3.2 failure marker exists")
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing archive: {destination}")
    files = collect_stage5_package_files(
        root, release_dir=release, destination=destination
    )
    member_inventory = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    inventory_payload = (
        json.dumps(
            {
                "schema_version": 1,
                "release": "2026Q1_v3_2",
                "hash_algorithm": "SHA-256",
                "members": member_inventory,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="corporate_quarterly_v3_2_",
            suffix=".zip.tmp",
            dir=destination.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in files:
                relative = path.relative_to(root).as_posix()
                archive.writestr(
                    _zip_info(f"{ARCHIVE_ROOT}/{relative}"), path.read_bytes()
                )
            archive.writestr(
                _zip_info(f"{ARCHIVE_ROOT}/v3_2_package_manifest.json"),
                inventory_payload,
            )
        verification = verify_stage5_clean_zip(temporary_path)
        if verification["status"] != "PASS":
            raise Stage5PackageError(
                "Clean ZIP verification failed: "
                + json.dumps(verification, ensure_ascii=False, sort_keys=True)
            )
        temporary_path.replace(destination)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return {
        "status": "PASS",
        "path": str(destination),
        "sha256": sha256_file(destination),
        "bytes": destination.stat().st_size,
        "member_count": len(files) + 1,
    }


def verify_stage5_clean_zip(path: Path) -> dict[str, Any]:
    """Verify CRC, hygiene, required members, manifest hashes, and render form."""
    archive_path = Path(path)
    issues: list[str] = []
    if not archive_path.is_file():
        return {"status": "FAIL", "issues": ["ARCHIVE_MISSING"]}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad_crc = archive.testzip()
            if bad_crc:
                issues.append(f"CRC_FAILURE:{bad_crc}")
            names = archive.namelist()
            if len(names) != len(set(names)):
                issues.append("DUPLICATE_MEMBERS")
            for name in names:
                member = Path(name)
                if member.is_absolute() or ".." in member.parts:
                    issues.append(f"UNSAFE_PATH:{name}")
                if _is_forbidden(member):
                    issues.append(f"FORBIDDEN_JUNK:{name}")
            required = [
                *(f"{ARCHIVE_ROOT}/{name}" for name in ROOT_FILES),
                *(f"{ARCHIVE_ROOT}/outputs/2026Q1_v3_2/{name}" for name in RELEASE_REQUIRED),
                *(f"{ARCHIVE_ROOT}/{name}" for name in SOURCE_REQUIRED),
                f"{ARCHIVE_ROOT}/v3_2_package_manifest.json",
            ]
            for name in required:
                if name not in names:
                    issues.append(f"REQUIRED_MEMBER_MISSING:{name}")
            manifest_name = f"{ARCHIVE_ROOT}/v3_2_package_manifest.json"
            if manifest_name in names:
                manifest = json.loads(archive.read(manifest_name))
                for row in manifest.get("members", []):
                    member_name = f"{ARCHIVE_ROOT}/{row['path']}"
                    if member_name not in names:
                        issues.append(f"MANIFEST_MEMBER_MISSING:{row['path']}")
                        continue
                    payload = archive.read(member_name)
                    if len(payload) != int(row["bytes"]):
                        issues.append(f"MANIFEST_SIZE_MISMATCH:{row['path']}")
                    if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                        issues.append(f"MANIFEST_HASH_MISMATCH:{row['path']}")
            render_name = (
                f"{ARCHIVE_ROOT}/outputs/2026Q1_v3_2/article_note_render.md"
            )
            if render_name in names:
                render = archive.read(render_name).decode("utf-8")
                if re.search(r"<!--.*?-->", render, flags=re.DOTALL):
                    issues.append("RENDER_HAS_HTML_COMMENT")
                if re.search(r"!\[[^]]*\]\((?!https?://|/)[^)]+\)", render):
                    issues.append("RENDER_HAS_RELATIVE_IMAGE_LINK")
                for index in (1, 2, 3):
                    if render.count(f"【図{index}：") != 1:
                        issues.append(f"RENDER_FIGURE_MARKER_COUNT:{index}")
    except (OSError, zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
        issues.append(f"ARCHIVE_READ_FAILURE:{type(exc).__name__}:{exc}")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "path": str(archive_path),
    }
