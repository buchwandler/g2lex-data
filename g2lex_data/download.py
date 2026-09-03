from __future__ import annotations

import os
import tempfile
import urllib.request
from urllib.parse import urlparse, urlunparse

from .common import sha256_file
from .config import AssetConfig, load_config


def _download_url(record: AssetConfig) -> str:
    """Resolve a human-facing Hugging Face blob URL to its immutable file URL."""
    if not record.source_url:
        raise ValueError(f"{record.id} has no source_url; it is repository-owned")
    parsed = urlparse(record.source_url)
    parts = parsed.path.split("/")
    if parsed.netloc == "huggingface.co" and "blob" in parts:
        index = parts.index("blob")
        parts[index] = "resolve"
        return urlunparse(parsed._replace(path="/".join(parts)))
    return record.source_url


def validate_source_file(record: AssetConfig, path=None) -> None:
    source_path = path or record.source_path
    if not source_path.is_file():
        raise FileNotFoundError(f"missing source for {record.id}: {source_path}")
    if source_path.stat().st_size != record.source_size:
        raise ValueError(f"source size mismatch for {record.id}")
    if sha256_file(source_path) != record.source_sha256:
        raise ValueError(f"source SHA-256 mismatch for {record.id}")


def source_statuses() -> tuple[dict[str, object], ...]:
    statuses: list[dict[str, object]] = []
    for record in load_config().assets:
        if record.source_provider == "lexhint":
            from .sources import resolve_source

            resolved = resolve_source(record)
            inputs = record.transform_inputs or {}
            statuses.append(
                {
                    "id": record.id,
                    "provider": "lexhint",
                    "base_language": inputs.get("lexhint_language"),
                    "variant": inputs.get("lexhint_variant"),
                    "dataset_version": inputs.get("lexhint_dataset_version"),
                    "locale": inputs.get("lexhint_locale"),
                    "path": str(resolved.path),
                    "installed": True,
                    "sha256": "ok",
                }
            )
        else:
            validate_source_file(record)
            statuses.append(
                {
                    "id": record.id,
                    "provider": "file",
                    "path": str(record.source_path),
                    "installed": True,
                    "sha256": "ok",
                }
            )
    return tuple(statuses)


def validate_sources() -> None:
    source_statuses()


def download_source(identifier: str) -> None:
    record = load_config().asset(identifier)
    if record.source_provider == "lexhint":
        raise ValueError(
            f"{identifier} is managed by LexHint; install it explicitly with "
            f"lexhint dataset download {record.transform_inputs['lexhint_language']} --variant {record.transform_inputs['lexhint_variant']} --version {record.transform_inputs['lexhint_dataset_version']}"
        )
    url = _download_url(record)
    record.source_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=record.source_path.name + ".", dir=record.source_path.parent
    )
    os.close(fd)
    temp = record.source_path.with_name(os.path.basename(temp_name))
    try:
        urllib.request.urlretrieve(url, temp)
        validate_source_file(record, temp)
        os.replace(temp, record.source_path)
    finally:
        temp.unlink(missing_ok=True)
