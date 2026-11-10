# Explaining the build assignment in a leadership interview

## 60-second explanation

"I built an offline temporal knowledge engine that keeps every historical crawl, treats the credit union's rate sheets as structured data, and resolves questions against the right snapshot and product tier. Instead of blending pages into one answer, it distinguishes a current authoritative source from an outdated calculator or news article. It also reports contradictions with competing values and source references. The implementation uses the Python standard library, so it is deterministic, fast, and has no API dependencies. On the 40 public practice questions it scored 0.969, with zero stale-trap hits and repeat consistency of 1.0. The hidden evaluation is separate, and I have not seen those results."

## Questions to be ready for

**How do you decide which information is true?**
The primary dimensions are snapshot chronology, source authority, product identity, metric (APR or APY), and tier (term, balance, model year, or mortgage size). A more recent calculator does not automatically outrank a published rate table. I preserve earlier snapshots for an `as_of` query.

**How do you detect a real contradiction versus valid rate tiers?**
I extract rows into canonical keys `(product, qualifying tier, metric)`. Different balance bands and APR versus APY are not contradictions. If the exact key changes between crawls, the conflict record includes all observed values, a chosen current value, and citations. The same-snapshot calculator check is separate.

**Why not use an LLM for every answer?**
The requirements heavily reward speed, consistency, and correct source attribution. A deterministic table parser avoids hallucinations and cost, responds in milliseconds, and is easier to audit. I kept BM25-style retrieval for broader explanatory questions. A production system could add a bounded LLM step only when extraction and retrieval cannot resolve the query.

**What happens when the website does not say?**
The system explicitly abstains for unsupported rate products and unsupported terms; it does not infer a number from another product. This is important when replying to members about financial rates.

**What would you improve next?**
Extend extraction to structured FAQs, branch-hours records, fees and effective-date metadata; track promotions with start/end validity; cluster conflicts across all website pages, not only the main rates pages; add regression tests with paraphrases and calibration for refusal decisions. Also add monitoring for ingestion changes and traceability/observability in production.

**What does the public score prove, and not prove?**
It shows correctness on public practice examples, deterministic repeatability, and low query latency in this environment. It does not validate the hidden set or real-data conflict precision: the public scorer does not include real-data gold conflict labels.

## Live demo prompts

- `What is the APR for a 60-month auto loan on a 2025 model-year vehicle?`
- `What was the 10-month fixed jumbo certificate special APY as of May 2026?`
- `What is the highest Share Savings APY?`
- `What is the rate on a 7/1 adjustable-rate mortgage?`
- `How do you know your published rate differs from a calculator?`

The above are sample question types from the public practice exercise; explain how the code reaches each answer rather than memorizing a result.