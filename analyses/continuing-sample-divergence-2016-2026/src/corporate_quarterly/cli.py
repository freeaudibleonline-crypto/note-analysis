from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .constants import PROJECT_ROOT, load_release
from .estat import fetch_release
from .pipeline import build_release, write_failure_stubs
from .stage2_pipeline import (
    build_stage2,
    fetch_stage2_sources,
    write_stage2_failure_stubs,
)
from .stage3_pipeline import (
    build_stage3,
    fetch_stage3_sources,
    write_stage3_failure_stubs,
)
from .stage4_pipeline import build_stage4, write_stage4_failure_stub
from .stage5_pipeline import build_stage5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corporate-quarterly",
        description="法人企業統計・四半期別調査の再現可能分析パイプライン",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in (
        "fetch",
        "build",
        "run",
        "fetch-stage2",
        "build-stage2",
        "run-stage2",
        "fetch-stage3",
        "build-stage3",
        "run-stage3",
        "build-stage4",
        "build-stage5",
    ):
        sub = subparsers.add_parser(command)
        sub.add_argument("--release", default="2026Q1")
        if command in {
            "build",
            "build-stage2",
            "build-stage3",
            "build-stage4",
            "build-stage5",
        }:
            sub.add_argument(
                "--offline",
                action="store_true",
                help="保存済みrawだけを使い、ネットワーク取得を禁止する",
            )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = Path(PROJECT_ROOT)
    try:
        if args.command == "build-stage5":
            if args.release != "2026Q1":
                raise ValueError("Stage 5 is registered for release 2026Q1")
            output_dir, status, test_count = build_stage5(
                project_root=project_root,
                offline=args.offline,
            )
            print(f"STAGE5 BUILD {status}: {output_dir} (tests={test_count})")
            return 0 if status == "PASS" else 1
        if args.command == "build-stage4":
            if args.release != "2026Q1":
                raise ValueError("Stage 4 is registered for release 2026Q1")
            output_dir, status = build_stage4(
                project_root=project_root,
                offline=args.offline,
            )
            print(f"STAGE4 BUILD {status}: {output_dir}")
            return 0 if status == "PASS" else 1
        if args.command == "fetch-stage3":
            if args.release != "2026Q1":
                raise ValueError("Stage 3 is registered for release 2026Q1")
            result = fetch_stage3_sources(project_root)
            print(
                "STAGE3 FETCH PASS: "
                f"continuing_sources={len(result['continuing_sample_manifest'].get('sources', []))}, "
                f"nonoperating_sources={len(result['nonoperating_manifest'].get('sources', []))}"
            )
            return 0
        if args.command in {"build-stage3", "run-stage3"}:
            if args.release != "2026Q1":
                raise ValueError("Stage 3 is registered for release 2026Q1")
            if args.command == "run-stage3":
                fetch_stage3_sources(project_root)
            output_dir, status = build_stage3(
                project_root=project_root,
                offline=(args.command == "build-stage3" and args.offline),
            )
            print(f"STAGE3 BUILD {status}: {output_dir}")
            return 0 if status == "PASS" else 1
        if args.command == "fetch-stage2":
            if args.release != "2026Q1":
                raise ValueError("Stage 2 is registered for release 2026Q1")
            result = fetch_stage2_sources(project_root)
            print(
                "STAGE2 FETCH PASS: "
                f"historical_sources={len(result['historical_manifest'].get('sources', []))}, "
                f"external_activated={result['external_manifest'] is not None}"
            )
            return 0
        if args.command in {"build-stage2", "run-stage2"}:
            if args.release != "2026Q1":
                raise ValueError("Stage 2 is registered for release 2026Q1")
            if args.command == "run-stage2":
                fetch_stage2_sources(project_root)
            output_dir, status = build_stage2(
                project_root=project_root,
                offline=(args.command == "build-stage2" and args.offline),
            )
            print(f"STAGE2 BUILD {status}: {output_dir}")
            return 0 if status == "PASS" else 1
        if args.command == "fetch":
            manifest = fetch_release(load_release(args.release), project_root)
            print(
                f"FETCH PASS: {args.release} ({len(manifest.get('sources', []))} sources)"
            )
            return 0
        if args.command == "run":
            fetch_release(load_release(args.release), project_root)
            output_dir, status = build_release(
                args.release, project_root=project_root, offline=True
            )
        else:
            output_dir, status = build_release(
                args.release, project_root=project_root, offline=args.offline
            )
        print(f"BUILD {status}: {output_dir}")
        return 0 if status == "PASS" else 1
    except Exception as exc:
        # Stage 5 owns its atomic staging/failure policy.  In particular, the
        # CLI must never append a FAIL marker to an already completed v3.2.
        if args.command == "build-stage4":
            try:
                write_stage4_failure_stub(
                    project_root / "outputs" / "2026Q1_v3_1",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        if args.command in {"build-stage3", "run-stage3"}:
            try:
                write_stage3_failure_stubs(
                    project_root / "outputs" / "2026Q1_v3",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        if args.command in {"build-stage2", "run-stage2"}:
            try:
                write_stage2_failure_stubs(
                    project_root / "outputs" / "2026Q1_v2",
                    reason=f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        if args.command in {"build", "run"}:
            try:
                release = load_release(args.release)
                write_failure_stubs(
                    project_root / "outputs" / release.release_id,
                    release,
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
        print(f"PIPELINE FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
