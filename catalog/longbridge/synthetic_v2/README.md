# PER-29 clean-room synthetic v2

This directory replaces the Stage 3 input role of the retired Longbridge v1
bundle without changing the 15 FTW families, three variants per family,
24 Gold / 21 Silver allocation, or the Financial Tool Workflow 50% weight.

The v2 values, asset identifiers, market, currency, ledgers, actions, and states
are project-authored synthetic fixtures. The generator reads only
`source_spec.v2.json` and family ordinals; it neither reads nor transforms the
isolated v1 quote files. The v2 fixture source is declared CC0-1.0 and is
eligible for model-endpoint transmission only after independent Stage 2 audit.

The v1 bundle remains byte-for-byte unchanged at
`catalog/longbridge/frozen_manifest.v1.json`; its raw and canonical market data
remain forbidden from model endpoints and attachment delivery.

```text
uv run python pipelines/longbridge/build_synthetic_v2.py build
uv run python pipelines/longbridge/build_synthetic_v2.py check
uv run python -m unittest tests.test_longbridge_synthetic_v2 -v
```
