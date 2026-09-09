# Architecture

## Ownership

`g2lex-data` is the source, build, validation, and release repository for distributed G2Lex datasets. It owns source inventory, immutable release inputs, adapters, versioned transforms, deterministic compilation, manifests, provenance, catalogs, and release staging.

LexHint owns managed dictionary acquisition and runtime lookup. `g2lex-data` selects LexHint datasets through the public resolver and never treats an implicit source default as a product decision. Lexphon owns installation and lookup policy. KokoroG2P remains the compatibility baseline for Kokoro-specific assets, but not their migrated source of truth.

## Production pipeline

```text
source catalog and selector
          |
          v
LexHint resolver: explicit source variant, version=None
          |
          v
resolved SQLite identity and runtime metadata
          |
          v
source integrity and parser
          |
          v
versioned pronunciation transform
          |
          v
validated typed G2Lex input
          |
          v
G2Lex asset + exact manifest
          |
          v
immutable release + catalog
```

Direct LexHint records select `variant=dictionary`, an explicit `source_variant`, and the required schema. They omit a dated dataset version. Resolution chooses the newest installed artifact compatible with that schema. If no compatible artifact is installed, the error contains a versionless command with the selected source variant. Native and English source variants cannot cross-resolve.

The current catalog exposes 36 English-Wiktionary-derived physical pairs and 19 native-Wiktionary-derived physical pairs. English-source pairs use the logical name `*:lexhint`; native alternatives use `*:lexhint-native`. English keeps only `en-us:lexhint` and `en-gb:lexhint`, both locale projections of one English source artifact.

The pronunciation transform calls the resolved LexHint API with the configured locale, preserves meaningful pronunciation variants, and records audit counters. Transform IDs are immutable contracts. Semantic changes require a new transform ID and data release.

## Artifact contracts

Every manifest records the stable asset identity, language, kind, encoding, producer and data versions, G2Lex version, source selector, exact resolved dataset metadata, transform inputs and report, asset hash and size, logical hash, and entry counts. For LexHint sources, exact provenance includes dataset version, release tag and publication time, release asset name and digest, SQLite digest and size, source variant, Wiktionary edition, metadata language, schema, locale, and LexHint runtime version.

Build validation checks source identity, transformed-input losslessness, typed and ordered values, deterministic rebuilds, and manifest/file consistency. The catalog exposes immutable asset and manifest URLs, hashes, sizes, logical hashes, release tags, encodings, and provider/license summaries. Releases are versioned independently from Python tooling and existing release directories cannot be overwritten.

## Compatibility boundary

The migration compatibility gate compares historical KokoroG2P mappings with consolidated assets by complete key membership and typed values, including tagged selectors and ordered variants. Historical G2Lex releases and source catalogs remain immutable. New LexHint source resolution affects only future builds and records the selected upstream identity in their manifests.
