# Temporal Knowledge Engine

A deterministic, offline knowledge system for the interface.ai **Staff Platform & Reliability Engineer** build assignment.

The implementation ingests dated credit-union website snapshots, answers current and historical questions with citations, resolves rate and source conflicts, and declines to guess when information is missing. It uses **Python 3.11+ standard library only**; no external API, paid model, live website calls, or credentials.

## Submission

- `submission/solution.py` — `build()` factory returning a system with `ingest(snapshot)`, `answer(question, as_of=None)`, and `conflicts()`.
- `submission/requirements.txt` — no third-party dependencies.
- `submission/NOTES.md` — architecture, temporal/source-authority rules, limitations, and evaluation.
- `harness/contract.py` — supplied interface definitions for local unit tests.
- `tests/test_contract.py` — synthetic tests; no protected website snapshots.

## Run unit tests

```bash
python3 -m unittest discover -s tests -v
```

## Run the official public evaluation

The actual **website snapshot archives are deliberately not in this repository**. To reproduce the public scoring locally, obtain the original participant kit from interface.ai, then copy its `harness/run_eval.py`, `harness/scoring.py`, `eval/public_eval.jsonl`, and `snapshots_zip/` to the corresponding paths beside this README. The harness extracts the snapshots as part of evaluation.

```bash
python3 harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

The implementation was evaluated locally against the provided 40-question practice set: **0.969 QA score**, zero exceptions and zero stale-trap hits; p95 response latency about 0.01 seconds on that run. The hidden set is not available and these results are not a guarantee of a hidden score.

## Design overview

Ingestion preserves snapshot history and builds an inverted evidence index and normalized rate-table facts. The answer method selects the most recent crawl on or before the requested date (or the newest crawl by default), matches product/tier/metric qualifiers, ranks official rate pages above calculators and stale posts, and returns original source links. The conflict method identifies competing values with context-aware fact keys and explains how each discrepancy was resolved. Unverifiable answers are declined.

For details, see [submission/NOTES.md](submission/NOTES.md).

## Data safety

Do **not** commit the participant ZIP, private `snapshots_zip/`, extracted `snapshots/*/` website pages, `.env` files, or API credentials. Website data supplied for this hiring exercise must not be redistributed.
