from __future__ import annotations

import argparse
import subprocess

from g2lex_data.config import AssetConfig, load_config
from g2lex_data.sources import lexhint_download_args


def _required_input(record: AssetConfig, key: str) -> str:
    value = (record.transform_inputs or {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{record.id} requires transform input {key}")
    return value.strip()


def _selector(record: AssetConfig) -> tuple[str, str, str, str | None]:
    inputs = record.transform_inputs or {}
    dataset_version = inputs.get("lexhint_dataset_version")
    if dataset_version is not None and not isinstance(dataset_version, str):
        raise ValueError(f"{record.id} transform input lexhint_dataset_version must be a string")
    return (
        _required_input(record, "lexhint_language"),
        _required_input(record, "lexhint_source_variant"),
        _required_input(record, "lexhint_variant"),
        dataset_version,
    )


def download_locales(locales: list[str]) -> None:
    config = load_config()
    commands: dict[tuple[str, str, str, str | None], tuple[str, ...]] = {}
    for locale in locales:
        record = config.asset(f"{locale}:espeak")
        if record.source_provider != "g2lex-assets":
            raise ValueError(f"{record.id} is not a generated eSpeak asset")
        for source_id in record.source_ids:
            parent = config.asset(source_id)
            if parent.source_provider != "lexhint":
                raise ValueError(f"{record.id} source {source_id} is not a LexHint asset")
            selector = _selector(parent)
            commands.setdefault(selector, lexhint_download_args(parent, version=selector[3]))
    for args in commands.values():
        subprocess.run(args, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download LexHint sources needed by eSpeak shards")
    parser.add_argument("--locale", action="append", required=True)
    args = parser.parse_args(argv)
    download_locales(args.locale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
