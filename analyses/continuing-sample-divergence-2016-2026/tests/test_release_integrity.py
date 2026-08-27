from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from corporate_quarterly import release_integrity
from corporate_quarterly.release_integrity import (
    ARCHIVE_ROOT,
    CLEAN_EXCLUDED_COMPONENTS,
    CLEAN_EXCLUDED_NAMES,
    CodeDataFailure,
    DependencyFailure,
    INVENTORY_ARCHIVE_NAME,
    LEGACY_ARCHIVE_NAMES,
    REPOSITORY_REQUIRED_PATHS,
    V1_CHART_FILENAMES,
    V1_REQUIRED_OUTPUTS,
    V2_CHART_FILENAMES,
    V2_REQUIRED_OUTPUTS,
    build_release_inventory,
    build_repository_top_level_inventory,
    check_runtime_dependencies,
    classify_failure,
    create_clean_release_zip,
    inspect_archive_structure,
    validate_release_structure,
    verify_clean_release_zip,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_hashes(project_root: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for relative in (Path("outputs/2026Q1"), Path("outputs/2026Q1_v2")):
        for path in (project_root / relative).rglob("*"):
            if path.is_file():
                rows[path.relative_to(project_root).as_posix()] = _sha256(path)
    return rows


def _write_required_fake_release(root: Path) -> None:
    for relative, kind in REPOSITORY_REQUIRED_PATHS.items():
        path = root / relative
        if kind == "directory":
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
    (root / "config" / "release.json").write_text("{}\n", encoding="utf-8")
    (root / "data" / "raw" / "source.bin").write_bytes(b"raw")
    (root / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "tests" / "test_module.py").write_text(
        "def test_value(): assert True\n", encoding="utf-8"
    )
    for name in V1_REQUIRED_OUTPUTS:
        path = root / "outputs" / "2026Q1" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "STATUS: PASS\n" if name == "audit_report.md" else f"{name}\n"
        path.write_text(content, encoding="utf-8")
    for name in V1_CHART_FILENAMES:
        path = root / "outputs" / "2026Q1" / "charts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
    for name in V2_REQUIRED_OUTPUTS:
        path = root / "outputs" / "2026Q1_v2" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == "audit_v2.md":
            content = "**STATUS: PASS**\n"
        elif name == "decision.md":
            content = "ARCHIVE_NO_STABLE_HEADLINE\n"
        else:
            content = f"{name}\n"
        path.write_text(content, encoding="utf-8")
    for name in V2_CHART_FILENAMES:
        path = root / "outputs" / "2026Q1_v2" / "charts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")


def test_actual_v1_v2_inventory_covers_every_file_and_preserves_hashes(
    project_root: Path,
) -> None:
    before = _frozen_hashes(project_root)
    inventory = build_release_inventory(project_root)
    after = _frozen_hashes(project_root)
    assert after == before
    inventoried = {
        row["path"]: row["sha256"]
        for release in inventory["releases"].values()
        for row in release["files"]
    }
    assert inventoried == before
    assert inventory["combined_file_count"] == len(before)
    assert len(inventory["combined_inventory_sha256"]) == 64
    assert inventory["outputs_mutated"] is False


def test_actual_required_repository_and_release_structure_passes(
    project_root: Path,
) -> None:
    top_level = build_repository_top_level_inventory(project_root)
    assert len(top_level) == len(REPOSITORY_REQUIRED_PATHS)
    assert all(row["status"] == "PASS" for row in top_level)
    report = validate_release_structure(project_root)
    assert report.passed, report.to_dict()
    assert report.v1_file_count > 0
    assert report.v2_file_count > 0


def test_missing_repository_paths_are_separate_structure_failures(tmp_path: Path) -> None:
    report = validate_release_structure(tmp_path)
    assert not report.passed
    repository_issues = [issue for issue in report.issues if issue.release == "repository"]
    output_issues = [issue for issue in report.issues if issue.release in {"v1", "v2"}]
    assert repository_issues
    assert output_issues
    assert {issue.path for issue in repository_issues} == set(
        REPOSITORY_REQUIRED_PATHS
    )


def test_clean_zip_is_self_contained_and_excludes_all_junk_and_nested_archives(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _write_required_fake_release(root)
    (root / ".DS_Store").write_bytes(b"junk")
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "module.pyc").write_bytes(b"junk")
    (root / "tests" / ".pytest_cache").mkdir()
    (root / "tests" / ".pytest_cache" / "state").write_bytes(b"junk")
    (root / "outputs" / "__MACOSX").mkdir()
    (root / "outputs" / "__MACOSX" / "metadata").write_bytes(b"junk")
    (root / "outputs" / "アーカイブ.zip").write_bytes(b"old zip")
    destination = root / "outputs" / "clean_release.zip"

    result = create_clean_release_zip(destination, project_root=root)
    assert result["status"] == "PASS"
    assert destination.is_file()
    verification = verify_clean_release_zip(destination)
    assert verification["status"] == "PASS", verification
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert f"{ARCHIVE_ROOT}/{INVENTORY_ARCHIVE_NAME}" in names
        assert f"{ARCHIVE_ROOT}/README.md" in names
        assert any(name.startswith(f"{ARCHIVE_ROOT}/data/raw/") for name in names)
        assert not any(set(Path(name).parts) & CLEAN_EXCLUDED_COMPONENTS for name in names)
        assert not any(Path(name).name in CLEAN_EXCLUDED_NAMES for name in names)
        assert not any(Path(name).name in LEGACY_ARCHIVE_NAMES for name in names)
        assert not any(Path(name).name == destination.name for name in names)
        inventory = json.loads(
            archive.read(f"{ARCHIVE_ROOT}/{INVENTORY_ARCHIVE_NAME}")
        )
        assert inventory["releases"]["v1"]["file_count"] == (
            len(V1_REQUIRED_OUTPUTS) + len(V1_CHART_FILENAMES)
        )
        assert inventory["releases"]["v2"]["file_count"] == (
            len(V2_REQUIRED_OUTPUTS) + len(V2_CHART_FILENAMES)
        )


def test_archive_missing_paths_and_junk_are_reported_separately(tmp_path: Path) -> None:
    archive_path = tmp_path / "legacy.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("legacy/README.md", "readme")
        archive.writestr("legacy/__MACOSX/._README.md", "junk")
        archive.writestr("legacy/.DS_Store", "junk")
    report = inspect_archive_structure(archive_path)
    assert report["required_structure_status"] == "FAIL"
    assert report["hygiene_status"] == "FAIL"
    assert "config" in report["missing_required_paths"]
    assert report["junk_members"]


def test_archive_junk_sidecar_does_not_create_false_required_path_missing(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "complete_with_macos_junk.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for relative, kind in REPOSITORY_REQUIRED_PATHS.items():
            member = (
                f"project/{relative}"
                if kind == "file"
                else f"project/{relative}/placeholder"
            )
            archive.writestr(member, "present")
        archive.writestr("__MACOSX/project/._README.md", "junk")
    report = inspect_archive_structure(archive_path)
    assert report["required_structure_status"] == "PASS"
    assert report["missing_required_paths"] == []
    assert report["hygiene_status"] == "FAIL"
    assert report["junk_members"] == ["__MACOSX/project/._README.md"]


def test_package_destination_cannot_be_inside_frozen_outputs(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_required_fake_release(root)
    with pytest.raises(CodeDataFailure, match="cannot mutate frozen output root"):
        create_clean_release_zip(
            root / "outputs" / "2026Q1_v2" / "nested.zip",
            project_root=root,
        )


def test_legacy_user_archive_name_is_never_an_output_destination(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    _write_required_fake_release(root)
    legacy = root / "アーカイブ.zip"
    original = b"user-owned-original"
    legacy.write_bytes(original)
    with pytest.raises(CodeDataFailure, match="user-owned archive names are protected"):
        create_clean_release_zip(
            legacy,
            project_root=root,
            overwrite=True,
        )
    assert legacy.read_bytes() == original


def test_dependency_and_code_data_failures_have_distinct_contracts() -> None:
    dependency = classify_failure(ModuleNotFoundError("pyarrow"))
    assert dependency.failure_class == "DEPENDENCY_FAILURE"
    assert dependency.exit_code == 3
    data = classify_failure(CodeDataFailure("hash mismatch"))
    assert data.failure_class == "CODE_OR_DATA_FAILURE"
    assert data.exit_code == 4
    nested = RuntimeError("wrapper")
    nested.__cause__ = DependencyFailure("missing library")
    assert classify_failure(nested).failure_class == "DEPENDENCY_FAILURE"


def test_dependency_doctor_lists_missing_packages_without_data_failure() -> None:
    with pytest.raises(DependencyFailure, match="missing-package"):
        check_runtime_dependencies(
            {"missing-package": "missing_module"}, find_spec=lambda _name: None
        )


def test_release_integrity_cli_exit_codes_are_distinct(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        release_integrity,
        "check_runtime_dependencies",
        lambda: (_ for _ in ()).throw(DependencyFailure("missing dependency")),
    )
    assert release_integrity.main(["doctor"]) == 3
    dependency_stderr = capsys.readouterr().err
    assert "DEPENDENCY_FAILURE" in dependency_stderr

    assert release_integrity.main(
        ["--project-root", str(tmp_path), "verify"]
    ) == 4
    data_stderr = capsys.readouterr().err
    assert "CODE_OR_DATA_FAILURE" in data_stderr
