---
status: in-review
route: dispatch
date: 2026-11-20
ticket: 33GOD-33
base: 1043467512828dea4dc2c5a29ff401f9207d36a0
---
# 33GOD-33 — benchmark NDCG normalization

## Intent
<frozen-after-approval>
Correct binary NDCG@k in the standalone CodeGraph Voyage smoke benchmark: missing relevant nodes must lower the score. The denominator is the gain from `min(k, len(relevant))` ideal hits, independent of the number of retrieved hits. Zero/negative cutoffs, empty rankings, and empty relevance sets yield zero. Preserve the benchmark's synthetic fake-vector caveat. Do not change providers, live project databases, README, MCP, hooks, or the unrelated dirty main checkout. Commit/push a candidate branch for independent review, without landing main yet.
</frozen-after-approval>

## Code Map
- `src/codegraph_voyage/tests/benchmark.py:130-138`: old denominator sorted observed relevance, making a partial result appear perfect. Only production change is this metric.
- `src/codegraph_voyage/tests/test_benchmark_ndcg.py`: independent regression test, not the dirty `test_all.py`.
- `src/codegraph_voyage/tests/test_all.py`: inherited tests for CodeGraph document extraction, Voyage payloads, sanitizer, sidecar, ranking, CLI failure and explore. Do not edit.
- `README.md`: inherited setup, environment, architecture, and verification docs; currently dirty in shared checkout, not touched here.

## Acceptance and verification
- AC8: the example `ndcg(['d1'], {'d1','d2'})` equals `0.6131471927654584` (red before repair); test empty/irrelevant, full ideal, cutoff, and nonpositive cutoff; run all three benchmark strategies.
- AC1–7,9: assess inherited functionality against the **clean committed** baseline via focused unit tests, read-only CodeGraph fixture DB checksum, installed CLI `index/search/semantic_candidates/status/explore` on a disposable CodeGraph-generated database. Capture tests' fake HTTP payload evidence rather than calling a provider. Distinguish configured lint/type checkers from compileall.
- AC10: commit only the metric, regression, and this evidence/spec file to a ticket branch; push for review. Compare hashes of all seven pre-existing dirty shared-checkout paths before/after. Do not merge.

## Evidence
- Red: `uv run --no-cache python -m unittest codegraph_voyage.tests.test_benchmark_ndcg -v` before fix → 4 tests, 2 failures (partial hit: 1.0 rather than 0.6131471927654584; cutoff: 0.6309297535714575 rather than 0.38685280723454163).
- Green: `uv run --no-cache python -m unittest discover -s src/codegraph_voyage/tests -p 'test*.py' -v` → 89 tests, OK. Existing suite covers Voyage document/query `input_type`, sanitization of outbound fake HTTP requests, atomic failures, composite key and pruning; fixture regressions separate.
- Smoke: `uv run --no-cache python -m codegraph_voyage.tests.benchmark --verbose` → exit 0, lexical recall/MRR/NDCG 0.8333/1.0000/0.9502, vector 0.5167/0.4333/0.6278, fused 0.6333/1.0000/0.8458. Synthetic fake vectors **do not demonstrate quality improvement**; fused does not dominate lexical.
- Disposable live CodeGraph: `/home/delorenj/.hermes/profiles/33god-pm/cache/scratch/33god33_e2e.py` generated a one-file/two-node real CodeGraph SQLite index. Installed worktree CLI `index --provider fake` → 2 new, rerun → 0 changed; `status` → 2 embeddings; `search` and `semantic_candidates` returned pinned `auth_service`; non-dry-run `explore` → verbatim source for `auth_service`, exit 0. CodeGraph DB SHA256 before/after `f3004676046ea0c9ae9f57bad1b464f7acf5a629a90dff8addd2cf8c7ab269ad`.
- `git diff --check` and `python -m compileall -q src/codegraph_voyage` passed. `pyproject.toml` has no `[tool.*]` lint/type configuration, and neither `ruff` nor `mypy` available; compileall is only syntax validation, not a lint/type pass.
- BMAD render attempt in isolated worktree: `uv run --no-cache <worktree>/_bmad/scripts/render_skill.py ...` exit 2 (script is not tracked in extracted repository); canonical script with worktree project-root exit 1 (`missing config value communication_language`). Canonical owning-project workflow step 01/02 read; the worktree's incomplete BMAD config prevents a proper render. This scoped spec retains review evidence without changing BMAD config or parent.
