from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from .build import build
from .catalog import build_catalog
from .download import download_source, validate_sources
from .parity import compare_german
from .release import prepare_release
from .validate import validate_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="g2lex-data", description="Build and publish G2Lex data assets"
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build")
    p_build.add_argument("--id", action="append", dest="ids")

    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--catalog", action="store_true")

    p_catalog = sub.add_parser("catalog")
    p_catalog.add_argument("--data-version", required=True)
    p_catalog.add_argument("--base-url")

    p_release = sub.add_parser("release")
    p_release.add_argument("--data-version", required=True)

    p_download = sub.add_parser("download-source")
    p_download.add_argument("id")

    sub.add_parser("sources")

    p_parity = sub.add_parser("parity")
    p_parity.add_argument("--baseline", type=Path)
    p_parity.add_argument("--baseline-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build":
        manifests = build(args.ids)
        for manifest in manifests:
            print(f"built {manifest['id']}")
    elif args.command == "validate":
        validate_all(catalog=args.catalog)
        print("validation OK")
    elif args.command == "catalog":
        catalog = build_catalog(args.data_version, base_url=args.base_url)
        print(f"catalog artifacts: {len(catalog['artifacts'])}")
    elif args.command == "release":
        print(prepare_release(args.data_version))
    elif args.command == "download-source":
        download_source(args.id)
    elif args.command == "sources":
        validate_sources()
        print("sources OK")
    elif args.command == "parity":
        result = (
            compare_german(args.baseline, baseline_dir=args.baseline_dir)
            if args.baseline
            else compare_german(baseline_dir=args.baseline_dir)
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if not result["ok"]:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
