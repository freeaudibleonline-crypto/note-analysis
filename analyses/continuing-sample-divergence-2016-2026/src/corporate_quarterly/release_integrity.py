"""Release integrity inventory, fail classification, and clean packaging.

This module is deliberately read-only with respect to ``outputs/2026Q1`` and
``outputs/2026Q1_v2``.  Inventory files and ZIP archives are written only to an
explicit caller-supplied destination.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Iterable, Sequence
import zipfile

from .constants import PROJECT_ROOT


V1_OUTPUT_ROOT = Path("outputs/2026Q1")
V2_OUTPUT_ROOT = Path("outputs/2026Q1_v2")
V1_REQUIRED_OUTPUTS = (
    "data_manifest.json",
    "processed_quarterly.parquet",
    "industry_contributions.csv",
    "capital_size_contributions.csv",
    "claims.csv",
    "audit_report.md",
    "article.md",
    "industry_concentration.csv",
    "data_quality_log.json",
)
V1_CHART_FILENAMES = (
    "operating_profit_industry_contribution.png",
    "operating_profit_capital_contribution.png",
    "profit_margin_and_gap.png",
    "capex_software_bridge.png",
    "allocation_growth.png",
)
V2_REQUIRED_OUTPUTS = (
    "phase0_reproduction.md",
    "industry_leaf_contributions.csv",
    "industry_x_capital_contributions.csv",
    "capital_margin_bridge.csv",
    "ordinary_operating_gap.csv",
    "software_capex_decomposition.csv",
    "historical_quarterly.parquet",
    "historical_robustness.csv",
    "pattern_decisions.csv",
    "external_evidence_ledger.csv",
    "claims_v2.csv",
    "audit_v2.md",
    "decision.md",
    "candidate_headlines.md",
    "industry_major_contributions.csv",
    "cell_margin_bridge.csv",
    "phase1_additivity_checks.csv",
    "historical_candidate_series.parquet",
    "data_manifest_v2.json",
)
V2_CHART_FILENAMES = (
    "ordinary_profit_industry_x_capital_waterfall.png",
    "operating_margin_change_by_capital.png",
    "historical_candidate_position.png",
    "software_capex_industry_x_capital.png",
    "ordinary_operating_gap_decomposition.png",
)
CLEAN_EXCLUDED_COMPONENTS = frozenset(
    {"__MACOSX", "__pycache__", ".pytest_cache"}
)
CLEAN_EXCLUDED_NAMES = frozenset({".DS_Store"})
PACKAGE_ENTRIES = (
    "README.md",
    "Makefile",
    "pyproject.toml",
    "requirements.lock",
    "config",
    "data",
    "outputs",
    "src",
    "tests",
)
ARCHIVE_ROOT = "corporate_quarterly_pipeline"
INVENTORY_ARCHIVE_NAME = "release_sha256_inventory.json"
LEGACY_ARCHIVE_NAMES = frozenset({"アーカイブ.zip"})
REPOSITORY_REQUIRED_PATHS: dict[str, str] = {
    "config": "directory",
    "data/raw": "directory",
    "outputs/2026Q1": "directory",
    "outputs/2026Q1_v2": "directory",
    "src": "directory",
    "tests": "directory",
    "README.md": "file",
    "pyproject.toml": "file",
    "requirements.lock": "file",
}

DEPENDENCY_MODULES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "pyarrow": "pyarrow",
    "requests": "requests",
    "matplotlib": "matplotlib",
    "openpyxl": "openpyxl",
    "beautifulsoup4": "bs4",
    "lxml": "lxml",
}


class DependencyFailure(RuntimeError):
    """Environment/setup failure distinct from analysis code or data."""


class CodeDataFailure(RuntimeError):
    """A code contract, data contract, or release integrity failure."""


@dataclass(frozen=True)
class StructureIssue:
    release: str
    code: str
    path: str
    detail: str


@dataclass(frozen=True)
class StructureReport:
    status: str
    v1_file_count: int
    v2_file_count: int
    issues: tuple[StructureIssue, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["issues"] = [asdict(issue) for issue in self.issues]
        return value


@dataclass(frozen=True)
class FailureClassification:
    failure_class: str
    exception_type: str
    detail: str
    exit_code: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_files(project_root: Path, relative_root: Path) -> list[Path]:
    root = project_root / relative_root
    return sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(project_root).as_posix(),
    ) if root.is_dir() else []


def _file_inventory(project_root: Path, files: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in files:
        if path.is_symlink():
            raise CodeDataFailure(f"Symlink is not allowed in release inventory: {path}")
        rows.append(
            {
                "path": path.relative_to(project_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return rows


def _inventory_digest(rows: Sequence[dict[str, Any]]) -> str:
    canonical = json.dumps(
        list(rows), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_release_inventory(project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Inventory every file under the immutable v1 and v2 output roots."""
    root = Path(project_root).resolve()
    releases: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    for release_name, relative_root in (
        ("v1", V1_OUTPUT_ROOT),
        ("v2", V2_OUTPUT_ROOT),
    ):
        rows = _file_inventory(root, _release_files(root, relative_root))
        releases[release_name] = {
            "root": relative_root.as_posix(),
            "file_count": len(rows),
            "total_bytes": sum(int(row["bytes"]) for row in rows),
            "inventory_sha256": _inventory_digest(rows),
            "files": rows,
        }
        all_rows.extend(rows)
    return {
        "schema_version": 1,
        "scope": "ALL_FILES_UNDER_FROZEN_V1_AND_V2_OUTPUT_ROOTS",
        "hash_algorithm": "SHA-256",
        "path_base": "project_root",
        "outputs_mutated": False,
        "releases": releases,
        "combined_file_count": len(all_rows),
        "combined_inventory_sha256": _inventory_digest(all_rows),
        "repository_required_structure": build_repository_top_level_inventory(root),
    }


def build_repository_top_level_inventory(
    project_root: Path = PROJECT_ROOT,
) -> list[dict[str, Any]]:
    """Inventory required repository/package roots separately from output files."""
    root = Path(project_root).resolve()
    rows: list[dict[str, Any]] = []
    for relative, required_kind in REPOSITORY_REQUIRED_PATHS.items():
        path = root / relative
        observed_kind = (
            "file" if path.is_file() else "directory" if path.is_dir() else "missing"
        )
        rows.append(
            {
                "path": relative,
                "required_kind": required_kind,
                "observed_kind": observed_kind,
                "status": "PASS" if observed_kind == required_kind else "FAIL",
            }
        )
    return rows


def _required_paths() -> dict[str, tuple[Path, ...]]:
    v1 = tuple(V1_OUTPUT_ROOT / name for name in V1_REQUIRED_OUTPUTS)
    v1 += tuple(V1_OUTPUT_ROOT / "charts" / name for name in V1_CHART_FILENAMES)
    v2 = tuple(V2_OUTPUT_ROOT / name for name in V2_REQUIRED_OUTPUTS)
    v2 += tuple(V2_OUTPUT_ROOT / "charts" / name for name in V2_CHART_FILENAMES)
    return {"v1": v1, "v2": v2}


def _status_passes(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return "STATUS: PASS" in text and "| FAIL |" not in text


def validate_release_structure(project_root: Path = PROJECT_ROOT) -> StructureReport:
    """Validate required v1/v2 files and conditional public-article semantics."""
    root = Path(project_root).resolve()
    issues: list[StructureIssue] = []
    for row in build_repository_top_level_inventory(root):
        if row["status"] != "PASS":
            issues.append(
                StructureIssue(
                    "repository",
                    "MISSING_OR_WRONG_TOP_LEVEL_PATH",
                    str(row["path"]),
                    f"required={row['required_kind']}; observed={row['observed_kind']}",
                )
            )
    for release, paths in _required_paths().items():
        for relative in paths:
            path = root / relative
            if not path.is_file():
                issues.append(
                    StructureIssue(
                        release,
                        "MISSING_REQUIRED_FILE",
                        relative.as_posix(),
                        "required regular file is absent",
                    )
                )
            elif path.stat().st_size == 0:
                issues.append(
                    StructureIssue(
                        release,
                        "EMPTY_REQUIRED_FILE",
                        relative.as_posix(),
                        "required file has zero bytes",
                    )
                )

    for release, relative in (
        ("v1", V1_OUTPUT_ROOT / "audit_report.md"),
        ("v2", V2_OUTPUT_ROOT / "audit_v2.md"),
    ):
        path = root / relative
        if path.is_file() and not _status_passes(path):
            issues.append(
                StructureIssue(
                    release,
                    "AUDIT_NOT_PASS",
                    relative.as_posix(),
                    "release audit is absent, contains FAIL, or is not PASS",
                )
            )

    decisions = root / V2_OUTPUT_ROOT / "decision.md"
    public_article = root / V2_OUTPUT_ROOT / "article_public.md"
    if decisions.is_file():
        publish_required = "PUBLISH_LONGITUDINAL_ARTICLE" in decisions.read_text(
            encoding="utf-8"
        )
        if publish_required and not public_article.is_file():
            issues.append(
                StructureIssue(
                    "v2",
                    "MISSING_CONDITIONAL_PUBLIC_ARTICLE",
                    public_article.relative_to(root).as_posix(),
                    "decision requires a longitudinal public article",
                )
            )
        if not publish_required and public_article.exists():
            issues.append(
                StructureIssue(
                    "v2",
                    "FORBIDDEN_STALE_PUBLIC_ARTICLE",
                    public_article.relative_to(root).as_posix(),
                    "no publish decision exists, so article_public.md must be absent",
                )
            )

    return StructureReport(
        status="PASS" if not issues else "FAIL",
        v1_file_count=len(_release_files(root, V1_OUTPUT_ROOT)),
        v2_file_count=len(_release_files(root, V2_OUTPUT_ROOT)),
        issues=tuple(issues),
    )


def require_release_structure(project_root: Path = PROJECT_ROOT) -> StructureReport:
    report = validate_release_structure(project_root)
    if not report.passed:
        raise CodeDataFailure(
            "Required release structure failed: "
            + json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
        )
    return report


def _excluded(relative: Path) -> bool:
    return bool(
        set(relative.parts) & CLEAN_EXCLUDED_COMPONENTS
        or relative.name in CLEAN_EXCLUDED_NAMES
        or relative.name in LEGACY_ARCHIVE_NAMES
    )


def _package_files(
    project_root: Path, *, excluded_paths: Iterable[Path] = ()
) -> list[Path]:
    excluded = {path.resolve() for path in excluded_paths}
    files: list[Path] = []
    for entry in PACKAGE_ENTRIES:
        path = project_root / entry
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = [candidate for candidate in path.rglob("*") if candidate.is_file()]
        else:
            continue
        for candidate in candidates:
            if candidate.resolve() in excluded:
                continue
            relative = candidate.relative_to(project_root)
            if _excluded(relative):
                continue
            if candidate.is_symlink():
                raise CodeDataFailure(f"Symlink is not allowed in clean package: {relative}")
            files.append(candidate)
    return sorted(set(files), key=lambda path: path.relative_to(project_root).as_posix())


def _zip_info(archive_name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def _refuse_frozen_output_destination(project_root: Path, destination: Path) -> None:
    if destination.name in LEGACY_ARCHIVE_NAMES:
        raise CodeDataFailure(
            "Legacy/user-owned archive names are protected and cannot be package "
            f"destinations: {destination}"
        )
    for relative in (V1_OUTPUT_ROOT, V2_OUTPUT_ROOT):
        frozen_root = (project_root / relative).resolve()
        if destination == frozen_root or frozen_root in destination.parents:
            raise CodeDataFailure(
                f"Inventory/package destination cannot mutate frozen output root: {destination}"
            )


def create_clean_release_zip(
    destination: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create a deterministic, verified ZIP without mutating frozen outputs."""
    root = Path(project_root).resolve()
    destination = Path(destination).resolve()
    _refuse_frozen_output_destination(root, destination)
    require_release_structure(root)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing archive: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    inventory = build_release_inventory(root)
    inventory_bytes = (
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    files = _package_files(root, excluded_paths=(destination,))
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="corporate_quarterly_",
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
                _zip_info(f"{ARCHIVE_ROOT}/{INVENTORY_ARCHIVE_NAME}"),
                inventory_bytes,
            )
        verification = verify_clean_release_zip(temporary_path)
        if verification["status"] != "PASS":
            raise CodeDataFailure(
                "Clean ZIP verification failed: "
                + json.dumps(verification, ensure_ascii=False, sort_keys=True)
            )
        # ``replace`` is atomic on the destination filesystem.  There is no
        # separate delete window, and legacy/user-owned archive names are
        # rejected above even when ``overwrite=True``.
        temporary_path.replace(destination)
        temporary_path = None
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return {
        "status": "PASS",
        "archive_path": str(destination),
        "archive_sha256": _sha256(destination),
        "archive_bytes": destination.stat().st_size,
        "member_count": len(files) + 1,
        "inventory_sha256": inventory["combined_inventory_sha256"],
        "excluded_components": sorted(CLEAN_EXCLUDED_COMPONENTS),
        "excluded_names": sorted(CLEAN_EXCLUDED_NAMES),
    }


def verify_clean_release_zip(path: Path) -> dict[str, Any]:
    """Verify exclusions and every frozen v1/v2 member against inventory."""
    archive_path = Path(path)
    issues: list[str] = []
    archive_structure = inspect_archive_structure(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            issues.append("DUPLICATE_ARCHIVE_MEMBERS")
        for name in names:
            member = Path(name)
            if member.is_absolute() or ".." in member.parts:
                issues.append(f"UNSAFE_ARCHIVE_PATH:{name}")
            relative_parts = member.parts[1:] if member.parts else ()
            if set(relative_parts) & CLEAN_EXCLUDED_COMPONENTS:
                issues.append(f"FORBIDDEN_COMPONENT:{name}")
            if member.name in CLEAN_EXCLUDED_NAMES:
                issues.append(f"FORBIDDEN_NAME:{name}")
        inventory_name = f"{ARCHIVE_ROOT}/{INVENTORY_ARCHIVE_NAME}"
        if inventory_name not in names:
            issues.append("MISSING_SHA256_INVENTORY")
            inventory: dict[str, Any] = {}
        else:
            inventory = json.loads(archive.read(inventory_name))
        for release in inventory.get("releases", {}).values():
            for row in release.get("files", []):
                member_name = f"{ARCHIVE_ROOT}/{row['path']}"
                if member_name not in names:
                    issues.append(f"INVENTORIED_MEMBER_MISSING:{row['path']}")
                    continue
                payload = archive.read(member_name)
                if len(payload) != int(row["bytes"]):
                    issues.append(f"INVENTORIED_SIZE_MISMATCH:{row['path']}")
                if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                    issues.append(f"INVENTORIED_HASH_MISMATCH:{row['path']}")
    return {
        "status": (
            "PASS"
            if not issues and archive_structure["status"] == "PASS"
            else "FAIL"
        ),
        "issues": issues,
        "required_structure_status": archive_structure["required_structure_status"],
        "hygiene_status": archive_structure["hygiene_status"],
        "missing_required_paths": archive_structure["missing_required_paths"],
        "junk_members": archive_structure["junk_members"],
        "archive_path": str(archive_path),
    }


def _required_archive_path_count(names: Sequence[str]) -> int:
    name_set = set(names)
    count = 0
    for relative, required_kind in REPOSITORY_REQUIRED_PATHS.items():
        if required_kind == "file":
            present = relative in name_set
        else:
            prefix = relative.rstrip("/") + "/"
            present = any(name.startswith(prefix) for name in names)
        count += int(present)
    return count


def _strip_common_archive_root(names: Sequence[str]) -> list[str]:
    """Choose the root with most required paths; ignore sidecar junk roots."""
    files = [name.rstrip("/") for name in names if name and not name.endswith("/")]
    parts = [Path(name).parts for name in files]
    candidates: list[tuple[str | None, list[str]]] = [
        (None, [Path(name).as_posix() for name in files])
    ]
    for root_name in sorted({value[0] for value in parts if len(value) > 1}):
        stripped = [
            Path(*value[1:]).as_posix()
            for value in parts
            if len(value) > 1 and value[0] == root_name
        ]
        candidates.append((root_name, stripped))
    _, best = max(
        candidates,
        key=lambda item: (_required_archive_path_count(item[1]), item[0] is not None),
    )
    return best


def inspect_archive_structure(path: Path) -> dict[str, Any]:
    """Report archive completeness and junk hygiene as separate results."""
    archive_path = Path(path)
    with zipfile.ZipFile(archive_path) as archive:
        original_names = archive.namelist()
    relative_names = _strip_common_archive_root(original_names)
    name_set = set(relative_names)
    missing: list[str] = []
    for relative, required_kind in REPOSITORY_REQUIRED_PATHS.items():
        if required_kind == "file":
            present = relative in name_set
        else:
            prefix = relative.rstrip("/") + "/"
            present = any(name.startswith(prefix) for name in relative_names)
        if not present:
            missing.append(relative)
    junk: list[str] = []
    for original in [
        name for name in original_names if name and not name.endswith("/")
    ]:
        member = Path(original)
        if (
            set(member.parts) & CLEAN_EXCLUDED_COMPONENTS
            or member.name in CLEAN_EXCLUDED_NAMES
            or member.name in LEGACY_ARCHIVE_NAMES
        ):
            junk.append(original)
    required_status = "PASS" if not missing else "FAIL"
    hygiene_status = "PASS" if not junk else "FAIL"
    return {
        "status": "PASS" if not missing and not junk else "FAIL",
        "required_structure_status": required_status,
        "hygiene_status": hygiene_status,
        "missing_required_paths": missing,
        "junk_members": junk,
        "archive_path": str(archive_path),
    }


def write_release_inventory(
    destination: Path, *, project_root: Path = PROJECT_ROOT, overwrite: bool = False
) -> dict[str, Any]:
    require_release_structure(project_root)
    destination = Path(destination).resolve()
    _refuse_frozen_output_destination(Path(project_root).resolve(), destination)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing inventory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    inventory = build_release_inventory(project_root)
    destination.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return inventory


def check_runtime_dependencies(
    dependencies: Mapping[str, str] | None = None,
    *,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
) -> dict[str, Any]:
    """Fail distinctly when an installed runtime dependency is unavailable."""
    requested = dict(dependencies or DEPENDENCY_MODULES)
    missing = [package for package, module in requested.items() if find_spec(module) is None]
    if sys.version_info < (3, 11):
        missing.insert(0, "python>=3.11")
    if missing:
        raise DependencyFailure("Missing runtime dependencies: " + ", ".join(missing))
    return {
        "status": "PASS",
        "python": ".".join(map(str, sys.version_info[:3])),
        "dependencies": sorted(requested),
    }


def classify_failure(exc: BaseException) -> FailureClassification:
    """Map an exception to the public dependency vs code/data contract."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    dependency = any(
        isinstance(item, (DependencyFailure, ModuleNotFoundError, ImportError))
        for item in chain
    )
    return FailureClassification(
        failure_class=("DEPENDENCY_FAILURE" if dependency else "CODE_OR_DATA_FAILURE"),
        exception_type=type(exc).__name__,
        detail=str(exc),
        exit_code=3 if dependency else 4,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="corporate-quarterly-release-integrity")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    subparsers.add_parser("doctor")
    inventory = subparsers.add_parser("inventory")
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--overwrite", action="store_true")
    package = subparsers.add_parser("package")
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result = check_runtime_dependencies()
        elif args.command == "verify":
            result = require_release_structure(args.project_root).to_dict()
        elif args.command == "inventory":
            inventory = write_release_inventory(
                args.output,
                project_root=args.project_root,
                overwrite=args.overwrite,
            )
            result = {
                "status": "PASS",
                "output": str(args.output),
                "combined_file_count": inventory["combined_file_count"],
                "combined_inventory_sha256": inventory[
                    "combined_inventory_sha256"
                ],
            }
        else:
            result = create_clean_release_zip(
                args.output,
                project_root=args.project_root,
                overwrite=args.overwrite,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        failure = classify_failure(exc)
        print(
            json.dumps(asdict(failure), ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )
        return failure.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
