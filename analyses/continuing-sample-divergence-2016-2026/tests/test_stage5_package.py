from __future__ import annotations

import json
from pathlib import Path
import zipfile

from corporate_quarterly.stage5_package import (
    ARCHIVE_ROOT,
    PACKAGE_FILENAME,
    RELEASE_REQUIRED,
    ROOT_FILES,
    SOURCE_REQUIRED,
    create_stage5_clean_zip,
    verify_stage5_clean_zip,
)


def _minimal_project(root: Path) -> Path:
    for name in ROOT_FILES:
        (root / name).write_text(f"{name}\n", encoding="utf-8")
    for directory in ("config", "src", "tests"):
        path = root / directory
        path.mkdir(parents=True)
        (path / "kept.txt").write_text("kept\n", encoding="utf-8")
        (path / "__pycache__").mkdir()
        (path / "__pycache__" / "ignored.pyc").write_bytes(b"junk")
    for relative in SOURCE_REQUIRED:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".json" else "x\n", encoding="utf-8")
    release = root / "outputs" / "2026Q1_v3_2"
    for relative in RELEASE_REQUIRED:
        path = release / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == "audit_v3_2.md":
            path.write_text("**STATUS: PASS**\n", encoding="utf-8")
        elif relative == "article_note_render.md":
            path.write_text(
                "【図1：資本金階層・指標別の方向不一致率】\n"
                "【図2：複合見出しの2×2表】\n"
                "【図3：deadband感応度】\n",
                encoding="utf-8",
            )
        elif path.suffix == ".json":
            path.write_text(json.dumps({}) + "\n", encoding="utf-8")
        elif path.suffix == ".png":
            path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        else:
            path.write_text("fixture\n", encoding="utf-8")
    (release / ".DS_Store").write_bytes(b"junk")
    return release


def test_stage5_clean_zip_is_scoped_hygienic_and_verified(tmp_path: Path) -> None:
    release = _minimal_project(tmp_path)
    destination = release / PACKAGE_FILENAME
    result = create_stage5_clean_zip(destination, project_root=tmp_path)
    assert result["status"] == "PASS"
    assert verify_stage5_clean_zip(destination)["status"] == "PASS"
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
    assert not any("__pycache__" in name for name in names)
    assert not any(name.endswith((".pyc", ".DS_Store")) for name in names)
    assert f"{ARCHIVE_ROOT}/outputs/2026Q1_v3_1/アーカイブ.zip" not in names
    assert f"{ARCHIVE_ROOT}/outputs/2026Q1_v3_2/audit_v3_2.md" in names


def test_stage5_archive_requires_pass_audit(tmp_path: Path) -> None:
    release = _minimal_project(tmp_path)
    (release / "audit_v3_2.md").write_text("**STATUS: FAIL**\n", encoding="utf-8")
    destination = release / PACKAGE_FILENAME
    try:
        create_stage5_clean_zip(destination, project_root=tmp_path)
    except Exception as exc:
        assert "audit" in str(exc)
    else:  # pragma: no cover - the fail-closed rule must never be bypassed
        raise AssertionError("archive was created from a failed audit")
    assert not destination.exists()

