# Architecture

The application has one dependency direction:

```text
CLI → config/tasks → runner → adapters → grading → trace/compare
                  ↘ eval pack → shared protocol/grading → trace/aggregate
```

- `config.py` validates one run-config file. Credential values are resolved only inside the live
  adapter and are excluded from representations and persisted values.
- `models.py` validates task cards, fixture boundaries, Gold recomputation, and candidate matrices.
- `eval_pack.py` validates frozen PER-420 assets from an explicitly supplied directory and emits
  deterministic zero-network controls. It reuses the central candidate-output validator, grading
  boundary, outcome classifier, and failure-signature policy; it has no provider adapter or
  standalone CLI.
- `runner.py` owns sequential execution, read-only mock tools, experiment coordinates, grading, and
  failure signatures. Its trace coordinates cover evaluation assets, candidate configuration, the
  trace schema, and experiment protocol only; framework Git and dependency coordinates are absent.
- `adapters/` contains the Python adapter boundary, the minimal Bailian protocol boundary, and one
  narrow Node runtime boundary pinned to `pi-agent-core@0.73.1`. The offline pi adapter uses pi's
  real `Agent.prompt()` and sequential tool loop with a deterministic faux transport; it cannot
  access a provider, account, or production write API. The separately gated live pi adapter keeps
  the same Agent and read-only tool boundary, inherits its credential from the environment, rejects
  response-model fallback, disables provider retries, and stops before a third provider turn. Its
  bound preflight uses the minimal direct SSE transport because pi-ai only exposes `responseModel`
  when the provider ID differs; live Agent turns still flag any such divergent ID as fallback.
  The live pi boundary supports only output contract 3.0.0. It fixes the shared reason-code ontology,
  persists only invalid-output class, character count, content hash, and block types—never raw
  invalid provider text—and makes `answer.value` a non-null scalar while requiring null
  for `abstain`/`refuse`. On the final provider turn only, the pi payload adds Bailian's
  `response_format={"type":"json_object"}` and disables further tool selection; the first turn
  remains an unconstrained read-only tool call. Trace observability records which output transport
  was applied. A passed full preflight may bind a filtered subset of the same config, enabling
  safety-isolated per-model runs. Older live output-contract implementations are available only
  through Git history.
- `schemas/` contains the current config, task, trace, and differential-task schemas as wheel
  package data.
- `differential_oracle.py` and `differential_oracle_reference.py` independently recompute PER-420
  Gold. The task, fixture, scoring, candidate-coordinate, and historical harness assets live
  together under `tasks/per420/`; the last two are provenance only and are not active run configs.
- `trace.py` is the normal matrix persistence boundary; `compare.py` reads validated traces. The
  eval-pack path writes its own closed, hashed offline-control bundle.

There are no compatibility layers. Package resources locate the pi bridge; the adapter receives the
working directory only to resolve the checked-in Node lock and dependency installation. Historical
implementations are recoverable from Git and are intentionally absent from the active tree.
