# Knowledge system design notes

## Approach

The implementation is a deterministic, offline hybrid of **structured fact extraction** and **source-aware paragraph retrieval**. All answers are generated from the five snapshots passed to `ingest()`. There are no calls to the current website, external services, or paid models. Python 3.11's standard library is sufficient. No API keys are needed.

**Ingest:** For each dated snapshot, the system retains the complete page corpus, extracts Markdown tables from the official rate sheets, builds a lightweight inverted index of paragraph-sized evidence blocks, and preserves the original URL and snapshot ID. It does not overwrite prior crawls. Ingest also keeps supporting context (page title and source class) so a calculator, old news story, or unrelated product does not outrank a current official rate page.

**Answer:** A question with an `as_of` parameter uses the latest snapshot whose date is on or before that request. A current question uses the last snapshot. An explicit "as of Month YYYY" in the question is recognized when `as_of` is absent. For rate questions, product-specific table selectors resolve term, model-year grouping, account subtype, balance amount, APR vs APY, standard vs promotional, loan-amount ceilings, and purchase vs refinance. This avoids matching different tiers as though they were contradictory facts. Responses include original source URLs, snapshot IDs, supporting excerpts, and a conflict explanation where appropriate. Non-rate questions use source-aware retrieval or a limited group of reliable operational passages. If an exact product/rate cannot be verified, the system abstains rather than fabricate a number. Non-rate fee pages missing from a subsequent crawl can retain their last-seen verified value, explicitly tagged with the older snapshot.

**Conflicts:** Rate-table entries are canonicalized into `(product family, qualifying tier, metric)` keys. The system contrasts matching keys across dated snapshots, carries forward their sources, and identifies the most recent official value. APR and APY remain separate; model-year tier comparisons also preserve loan term. It separately checks for certain same-snapshot calculator discrepancies and key/value changes on plain-text source pages. The output includes both competing values and the authority / chronology decision. The engine deliberately avoids treating different balance bands or products as conflicts.

**Performance and reproducibility:** Pre-indexed paragraphs and cached table structures make the query path deterministic and fast. There is no network dependency, no model temperature, and no async task. All dependencies are standard-library modules, and `build()` provides the exact scorer contract.

## Trade-offs and limitations

A fully general semantic parser or knowledge graph could handle more novel entities and paraphrases, but would add runtime cost, variability, and possibly API requirements. The current structured extraction is strong for product rates and operational FAQs, but unusual free-form questions can still return an extractive excerpt or an honest refusal. A useful next iteration would parse all first-party FAQ pairs and track page-level publication timestamps and promotion expiry dates more systematically. An additional improvement would cluster near-duplicate product/metric conflicts across all first-party pages instead of mostly the canonical rate sheets.

## Setup

Use Python 3.11 or newer. `requirements.txt` has no third-party dependencies. With the original private participant snapshot ZIPs placed in `snapshots_zip/`, run from the repository root:

```bash
python3 harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

You may also run unit tests without any private snapshot data:

```bash
python3 -m unittest discover -s tests -v
```

## Public evaluation

On the provided 40-question practice evaluation, the final local test returned `qa_score=0.969`, zero stale traps, zero answer exceptions, repeat consistency 1.0, and p95 answer latency <=0.02s on the development machine. The scorer's published question set does **not** provide conflict-gold labels; the hidden conflict score is therefore unknown. Its separate synthetic harness self-test passed the QA and conflict checks, returning 1.0. These numbers do **not** predict the hidden score.

## Data handling and secrets

The public repository intentionally excludes `snapshots_zip/`, extracted `snapshots/*/` data, credentials, tokens, and secrets. The participant kit contains a private copy of real credit-union website content; please use it only for local testing and never distribute it. No API keys or external requests are required.