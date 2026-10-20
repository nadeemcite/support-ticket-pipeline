# Stage 1 — normalisation report

Source: `data/fixtures/edge_cases/tickets.json` (expectations in `expected.json`).

## Rejected and duplicate records (from `run_manifest.json`)

| Input index | ticket_id | Outcome | Rule | Reason |
|---|---|---|---|---|
| 2 | — | rejected | I3 | missing ticket_id |
| 1 | X-001 | dropped (duplicate; first occurrence kept) | I4 | repeated ticket_id |

## Before → after (accepted tickets)

| Input index | ticket_id | Field | Before | After |
|---|---|---|---|---|
| 3 | X-002 | language | `""` | `"en"` |
| 3 | X-002 | notes | — | language defaulted to 'en' (missing or blank) |
| 4 | X-003 | language | `"\u2205 (missing)"` | `"en"` |
| 4 | X-003 | notes | — | language defaulted to 'en' (missing or blank) |
| 5 | X-004 | language | `"en-GB"` | `"en"` |
| 6 | X-005 | language | `"EN"` | `"en"` |
| 6 | X-005 | customer_tier | `"GOLD"` | `"gold"` |
| 6 | X-005 | notes | — | unknown customer_tier 'gold' |
| 7 | X-006 | subject | `"   Lots   of\twhitespace\n\n  "` | `"Lots of whitespace"` |
| 7 | X-006 | message | `"  Double   spaces,\ttabs and\u0007 a control character\u0000 must be cleaned.  "` | `"Double spaces, tabs and a control character must be cleaned."` |
| 8 | X-007 | message | `"Cafe\u0301 vs Caf\u00e9 must normalise to the same NFC form."` | `"Café vs Café must normalise to the same NFC form."` |
| 9 | X-008 | extra (I2) | top-level unknown fields | `{"account_id": "ACC-99812", "channel": "email", "tags": ["priority", "beta"]}` |
| 10 | X-009 | message | `"   "` | `""` |
| 10 | X-009 | insufficient_content | — | `true` (rule I6) |

Unchanged tickets/fields are omitted. Idempotency (`normalise(normalise(x)) == normalise(x)`) and byte-identical reruns are asserted in `test_normalise.py` and `test_manifest.py`.
