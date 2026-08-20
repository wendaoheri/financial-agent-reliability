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
- `adapters/` contains the mock adapter and the minimal Bailian protocol boundary. No provider may
  write to production systems or expose credential values.
- `schemas/` contains exactly the current config, task, and trace schemas as wheel package data.
- `trace.py` is the only persistence boundary; `compare.py` reads validated traces.

There are no compatibility layers or repository-root assumptions. Historical implementations are
recoverable from Git and are intentionally absent from the active tree.
