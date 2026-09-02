# Architecture

## Ownership

`g2lex-data` owns producer-side concerns: source acquisition, pinned revisions and hashes, source adapters, deterministic compilation, source-to-G2Lex parity checks, provenance, licenses, manifests, releases, and catalog publication.

It does not own tokenization, pronunciation lookup policy, fallback engines, POS tagging, IPA conversion for a speech model, or application-specific lexicon priority.

## Release rule

A data release is immutable. Updating an upstream source creates a new data version; old catalog records must continue to resolve to the historical release assets.

## Catalog consumer

The catalog is deliberately generic. Runtime policy belongs to Lexphon or another consumer. In particular, it must not encode Kokoro ratings, model vocabulary rules, or fallback decisions.
