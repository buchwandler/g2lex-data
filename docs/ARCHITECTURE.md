# Architecture

## Ownership

`g2lex-data` is the authoritative producer for generic lexicon data. It owns source
inventory and acquisition, immutable revisions and hashes, source adapters, versioned
semantic transforms, deterministic G2Lex compilation, source-to-transformed-input
verification, manifests, provenance, releases, and catalog publication.

Lexphon owns installation, caching, lookup policy, and phonemization. KokoroG2P owns
Kokoro-specific IPA conversion, ratings, runtime precedence, and fallback behavior.
Those responsibilities are not duplicated here.

## Production pipeline

```text
pinned source + provenance
          |
          v
source integrity and parser
          |
          v
versioned transform registry
          |
          v
validated generic G2Lex input
          |
          v
G2Lex asset + manifest
          |
          v
immutable release + catalog v1
          |

LexHint-managed sources resolve through the public `Lexicon` API from explicitly installed, pinned artifacts for all 19 physical base languages. The pronunciation transform calls `iter_pronunciations(include_neutral=True)` with the configured locale, collapses only meaningful POS distinctions, and records source identity, locale derivation, and audit counters in the manifest. English derives the `en-US` and `en-GB` outputs; other languages remain base-language assets without regional claims.
          v
Lexphon installation
```

Transform IDs are immutable contracts. Unknown IDs fail, and semantic changes require a
new ID and data release. Crane uses the documented LexHint entry/POS/pronunciation
interface only while building. CSTR German sources use the `cstr-de-ipa-v1` adapter,
which removes one outer delimiter pair, skips only the documented header, preserves
internal slashes and variant order, and ignores only optional source annotations.

## Artifact contracts

Every manifest records the schema and contract versions, stable ID, language, name, kind,
encoding, data and producer versions, G2Lex version, source identity and provenance,
transform inputs and report hash, actual asset hash and size, logical hash, and entry
counts. Build validation checks source integrity, transformed-input losslessness, typed and
ordered values, deterministic rebuilds, and manifest/file consistency.

The v1 catalog contains one current artifact per ID and exposes immutable asset and
manifest URLs, hashes, sizes, logical hash, release tag, encoding, and provider/license
summary. Releases are data-versioned independently from Python tooling and existing
versions cannot be overwritten.

## Compatibility boundary

The current German Kokoro assets are frozen in `baseline/kokoro-german.json`. A parity
command can compare a supplied KokoroG2P checkout by logical hash and, when needed, by
complete key membership and values including tagged selectors and ordered variants. This
is a migration gate only. No KokoroG2P runtime asset or behavior is changed by this
repository.
