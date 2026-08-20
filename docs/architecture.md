# Architecture

The application has one dependency direction:

```text
CLI → config/tasks → runner → adapters → grading → trace/compare
```

- `config.py` validates one run-config file. Credential values are resolved only inside the live
  adapter and are excluded from representations and persisted values.
- `models.py` validates task cards, fixture boundaries, Gold recomputation, and candidate matrices.
- `runner.py` owns sequential execution, read-only mock tools, version coordinates, grading, and
  failure signatures. Git coordinates are best-effort and nullable for an installed wheel running
  outside a worktree.
- `adapters/` contains the Python adapter boundary, the minimal Bailian protocol boundary, and one
  narrow Node runtime boundary pinned to `pi-agent-core@0.73.1`. The offline pi adapter uses pi's
  real `Agent.prompt()` and sequential tool loop with a deterministic faux transport; it cannot
  access a provider, account, or production write API. The separately gated live pi adapter keeps
  the same Agent and read-only tool boundary, inherits its credential from the environment, rejects
  response-model fallback, disables provider retries, and stops before a third provider turn. Its
  bound preflight uses the minimal direct SSE transport because pi-ai only exposes `responseModel`
  when the provider ID differs; live Agent turns still flag any such divergent ID as fallback.
- `schemas/` contains exactly the current config, task, and trace schemas as wheel package data.
- `trace.py` is the only persistence boundary; `compare.py` reads validated traces.

There are no compatibility layers. Package resources locate the pi bridge; the adapter receives the
working directory only to resolve the checked-in Node lock and dependency installation. Historical
implementations are recoverable from Git and are intentionally absent from the active tree.
