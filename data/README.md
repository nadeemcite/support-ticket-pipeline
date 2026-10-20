# Data inventory

All personal data in these files is **synthetic**: `example.com/.org` emails (RFC 2606), Ofcom drama-range UK phone numbers, the standard Visa test card `4111 1111 1111 1111`, and the published example IBAN `GB82 WEST 1234 5698 7654 32`.

| Path | Used by | Purpose |
|---|---|---|
| `../tickets.json`, `../kb_articles.json` | pipeline (default inputs) | The PROBLEM.md samples, verbatim. The evaluator may replace them. |
| `eval/tickets.json` | evals (Stages 2–5) | 23 tickets: the 3 samples + 20 cases covering every `issue_type`, 5 languages (en/es/fr/de/pt), PII, prompt injection, no-KB-match, empty/vague tickets, VIP/critical |
| `eval/kb_articles.json` | evals | 11 articles: the 4 samples + 7 more (2FA, app crash, CSV export, cancellation, account takeover, email change, outages) |
| `eval/gold.json` | eval scorers | Expected labels per ticket. Each field is a list of **acceptable** values, preferred first, plus retrieval relevance, required citations, required/forbidden draft phrases, and expected PII types |
| `fixtures/edge_cases/` | pytest (Stage 1) | Duplicate IDs, missing `ticket_id`, missing/blank/regional language, unknown tier, whitespace/control chars, NFC, extra fields, blank content, plus `expected.json` |
| `fixtures/empty_kb/` | pytest (Stages 2, 5) | `{"articles": []}`: every retrieval must be empty and the run must still pass |
| `fixtures/empty_tickets/` | pytest (Stage 5) | `{"tickets": []}`: valid run with empty artifacts |
| `fixtures/malformed/` | pytest (Stage 1) | Wrong top-level key and truncated JSON: must exit 2 (rule I1) |
| `fixtures/replay/` | pytest (Stage 5) | `tickets_v2.json` (1 changed + 1 added ticket) and `expected.json` cache hit/miss expectations |
| `fixtures/pii_cases.json` | pytest (Stage 1) | PII detector/masker cases, including false-positive guards (Luhn-invalid numbers, order IDs, error codes, advice text) |
| `fixtures/safety_cases.json` | pytest (Stage 4) | S1/S2/S3 positive and negative phrases, multilingual, negation-aware |
| `fixtures/grounding_cases.json` | pytest (Stage 4) | Grounding-guard sentences with expected flag and check ID |

Rules: fixtures are **read-only inputs to tests**. Changing one is a reviewed change, noted in the stage's sign-off.
