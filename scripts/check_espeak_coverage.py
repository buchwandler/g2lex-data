from __future__ import annotations

import argparse
import json
from collections import defaultdict

from g2lex_data.config import load_config
from g2lex_data.espeak import EspeakBackend


def coverage() -> dict[str, object]:
    config = load_config()
    groups: dict[str, list[str]] = defaultdict(list)
    for record in config.assets:
        if record.name in {"lexhint", "lexhint-native"}:
            groups[record.id.split(":", 1)[0]].append(record.id)
    generation = config.espeak_generation or {}
    unsupported = generation.get("unsupported", {})
    if not isinstance(unsupported, dict):
        unsupported = {}
    backend = None
    backend_error = None
    try:
        backend = EspeakBackend(
            git_revision=str(generation.get("espeak_git_revision", "unknown")),
            expected_version=(
                str(generation["expected_espeak_version"])
                if generation.get("expected_espeak_version")
                else None
            ),
        )
    except (OSError, RuntimeError) as exc:
        backend_error = str(exc)
    rows: list[dict[str, object]] = []
    try:
        for locale, source_ids in sorted(groups.items()):
            normal_id = f"{locale}:espeak"
            piper_id = f"{locale}:espeak-piper"
            if locale in unsupported:
                rows.append(
                    {
                        "locale": locale,
                        "sources": sorted(source_ids),
                        "voice": None,
                        "normal": False,
                        "piper": False,
                        "reason": unsupported[locale],
                    }
                )
                continue
            normal = next((record for record in config.assets if record.id == normal_id), None)
            piper = next((record for record in config.assets if record.id == piper_id), None)
            voice = (normal.transform_inputs or {}).get("voice") if normal else None
            available = False
            reason = None
            if backend_error:
                reason = backend_error
            elif backend is not None and isinstance(voice, str):
                try:
                    backend.set_voice(voice)
                    available = True
                except ValueError as exc:
                    reason = str(exc)
            rows.append(
                {
                    "locale": locale,
                    "sources": sorted(source_ids),
                    "voice": voice,
                    "normal": bool(normal and available),
                    "piper": bool(piper and available),
                    "reason": reason,
                }
            )
    finally:
        if backend is not None:
            backend.close()
    return {"generator": generation, "locales": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check generated eSpeak locale coverage")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = coverage()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    print("locale  sources  voice  normal  piper")
    for row in result["locales"]:
        sources = ",".join(row["sources"])
        print(
            f"{row['locale']}  {sources}  {row['voice'] or '-'}  {'yes' if row['normal'] else 'no'}  {'yes' if row['piper'] else 'no'}"
        )
        if row["reason"]:
            print(f"  reason: {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
