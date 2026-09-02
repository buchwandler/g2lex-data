from __future__ import annotations

import os
import tempfile
import urllib.request

from .common import sha256_file
from .config import load_config


def download_source(identifier: str) -> None:
    record = load_config().asset(identifier)
    if not record.source_url:
        raise ValueError(f"{identifier} has no source_url; it is expected to be repository-owned")
    record.source_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=record.source_path.name + ".", dir=record.source_path.parent)
    os.close(fd)
    try:
        temp = record.source_path.with_name(temp_name.split(os.sep)[-1])
        urllib.request.urlretrieve(record.source_url, temp)  # noqa: S310 - configured source URL
        if temp.stat().st_size != record.source_size or sha256_file(temp) != record.source_sha256:
            raise ValueError(f"downloaded source does not match pinned metadata for {identifier}")
        os.replace(temp, record.source_path)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
