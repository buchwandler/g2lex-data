# Phase E verification evidence

## Automated checks

- `ruff check .` passed in implementation check `check-0016` and again in `check-0014` before the final test pass.
- `pytest -q` passed in implementation check `check-0017`.
- CLI help and Python compilation passed in checks `check-0018` through `check-0021`.
- BuildSession tests recorded exactly one pair generation, one backend construction, one parent build, and one backend close for the covered fixtures.

## Reproducibility

The `de-de:demo` fixture was built twice with data version `phase-e`. Both asset hashes matched:

```text
eb0586cf1390bb422eb978e2fc8780d149ee5ba5c14a3c57bba7e4fb2da6a730
```

This was recorded by implementation check `check-0022`.

## Manual release measurement

A full 42-locale GitHub release workflow was not run from this checkout because it requires the external LexHint datasets and a GitHub Actions release execution. The workflow now exposes the required producer and assembler boundaries. The implementation does not add intra-locale chunking before those measurements are available.
