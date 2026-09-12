from __future__ import annotations

import argparse
import json
from pathlib import Path

import g2lex

from g2lex_data.build import _g2lex_version
from g2lex_data.espeak import EspeakBackend
from g2lex_data.inventory import build_word_inventory
from g2lex_data.transforms.espeak import generate_espeak_pair


def _source_id(path: Path) -> str:
    with g2lex.open(path) as lexicon:
        value = lexicon.metadata.get("catalog_id") or lexicon.metadata.get("source_id")
    if not isinstance(value, str) or not value:
        raise ValueError(f"source {path} has no catalog_id/source_id metadata")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate paired eSpeak G2Lex assets")
    parser.add_argument("--locale", required=True)
    parser.add_argument("--source", action="append", type=Path, required=True)
    parser.add_argument("--source-id", action="append")
    parser.add_argument("--voice", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--espeak-git-revision", default="unknown")
    parser.add_argument("--expected-espeak-version")
    parser.add_argument("--piper-version", default="1.8.0")
    args = parser.parse_args(argv)

    source_ids = args.source_id or [_source_id(path) for path in args.source]
    if len(source_ids) != len(args.source):
        parser.error("--source-id must be repeated once per --source")
    source_paths = dict(zip(source_ids, args.source, strict=True))
    inventory = build_word_inventory(source_paths, locale=args.locale)
    with EspeakBackend(
        git_revision=args.espeak_git_revision,
        expected_version=args.expected_espeak_version,
    ) as backend:
        pair = generate_espeak_pair(inventory=inventory, voice=args.voice, backend=backend)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    normal_path = args.output_dir / f"g2lex-{args.locale}-espeak.g2lex"
    piper_path = args.output_dir / f"g2lex-{args.locale}-espeak-piper.g2lex"
    report_path = args.output_dir / f"{args.locale}-espeak-report.json"
    for path, entries, name, encoding in (
        (normal_path, pair.normal_entries, "espeak", "ipa"),
        (piper_path, pair.piper_entries, "espeak-piper", "espeak-ipa3"),
    ):
        source = args.output_dir / f".{path.stem}.json"
        source.write_text(json.dumps(entries, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        g2lex.pack_file(
            source,
            path,
            input_format="json-map",
            source_id=f"{args.locale}:{name}",
            metadata={
                "catalog_id": f"{args.locale}:{name}",
                "language": args.locale,
                "name": name,
                "kind": "pronunciation",
                "phoneme_encoding": encoding,
                "source_ids": list(inventory.source_ids),
                "word_inventory": pair.shared_report["word_inventory"],
                "transform": pair.normal_report if name == "espeak" else pair.piper_report,
                "g2lex_version": _g2lex_version(),
                "piper_version": args.piper_version,
            },
        )
        source.unlink()
    with g2lex.open(normal_path) as normal, g2lex.open(piper_path) as piper:
        if tuple(normal.keys()) != tuple(piper.keys()):
            raise ValueError("generated pair has different key inventories")
    report = {
        **pair.shared_report,
        "normal": pair.normal_report,
        "piper": {**pair.piper_report, "piper_version": args.piper_version},
        "outputs": [normal_path.name, piper_path.name],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(normal_path)
    print(piper_path)
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
