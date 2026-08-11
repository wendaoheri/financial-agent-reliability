# PER-28 public benchmark seed bundle

This bundle materializes the 15 public-origin families frozen by PER-26. Public
benchmarks supply task structure only. The factual layer is re-authored from
frozen World Development Indicators API v2 responses licensed CC-BY-4.0; no
benchmark answer, executable program, context row, or candidate output is used
as an oracle.

`seed_catalog.v1.json` records source revision, license evidence, conservative
availability time, raw/snapshot hashes, four deduplication keys, quality state,
and applicability limits. `frozen_manifest.v1.json` seals source responses,
snapshots, case cards, transformation code, and both oracle implementations.

The 15 families and 45 cases are fixed. FKW-09 remains Silver because the WDI
response does not expose immutable observation-level revision history; inventing
one would violate the source-revision case contract. FKW-13 through FKW-15 are
the three PER-26 Silver-only public families. All missing/anomalous variants are
Silver and expect abstention.

`preregistration_variant_protocol.v2.json` is the machine-readable variant-only
amendment consumed by PER-30. It explicitly retires the unmappable v1
`single_factor_control` identifier and introduces
`missing_or_anomalous_diagnostic`; it does not change weights, case count,
family allocation, repeats, exclusions, or statistics.

The generated catalog intentionally keeps `candidate_runs_allowed=false` until
the frozen PER-26 two-person source/license/time review is recorded. Automated
contract validation and independent-oracle agreement do not impersonate that
human sign-off.

Rebuild without network access after the raw responses are present:

```text
uv run python cases/public/build_public_cases.py build
```

The fetch command refuses to overwrite raw responses unless `--overwrite` is
given; overwriting a frozen response requires a new catalog version and review:

```text
uv run python cases/public/build_public_cases.py fetch
```
