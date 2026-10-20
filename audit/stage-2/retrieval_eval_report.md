# Stage 2 — retrieval eval report

- Eval set: `data/eval/tickets.json` (23 tickets) against `data/eval/kb_articles.json` (11 articles); gold = `data/eval/gold.json` `relevant_articles`.
- Primary retriever: **OpenAI `text-embedding-3-small` embeddings** via LiteLLM (decision OD-2). Comparison: offline TF-IDF.
- Metrics are deterministic functions of the rankings. A ticket "hits" when at least one relevant article is among the kept top 3.
- Only PII-masked text is embedded (rule P-EXT; asserted by `test_only_masked_text_reaches_the_embedder`).

## Summary at the configured threshold

| Metric | Embedding (min_score 0.25) | TF-IDF (min_score 0.05) |
|---|---|---|
| Recall@3, English tickets with relevant articles | 16/16 (1.00) | 16/16 (1.00) |
| Recall@3, non-English (E-2004 es, E-2005 fr, E-2006 de, E-2017 pt) | 4/4 (1.00) | 2/4 (0.50) |
| Recall@3, all tickets with relevant articles | 20/20 (1.00) | 18/20 (0.90) |
| Top-1 is a relevant article | 20/20 (1.00) | 16/20 (0.80) |
| No-match tickets (E-2010/11/12) return `[]` | 3/3 (1.00) | 3/3 (1.00) |
| MRR | 1.0 | 0.8417 |

## Embedding stability (fresh re-embedding, empty cache)

- Same top-3 article IDs: **23/23** tickets
- Largest score difference for the same article: **0.0011**; rankings byte-identical: **False**
- Closest kept-range score to the threshold (0.25): **0.0032** away, ~3× the observed drift
- Meaning: the OpenAI embedding API is not bit-for-bit deterministic, but drift is far too small to change any ranking or threshold decision. Pipeline reruns are byte-identical because every vector is cached by content hash (`.cache/embeddings/`). A clean checkout re-embeds and can differ in the 3rd–4th decimal of a score.

## Threshold sweep

Chosen embedding threshold **0.25**: every value in [0.20, 0.35] is perfect on this set; 0.25 sits inside that band with margin both ways (highest no-match top score ≈ 0.21, lowest relevant top-1 ≈ 0.39) and keeps useful secondary evidence such as KB-004 for T-1001.

| Retriever | min_score | Recall@3 en | Recall@3 non-en | Top-1 | MRR | No-match `[]` |
|---|---|---|---|---|---|---|
| embedding | 0.0 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 1/3 (0.33) |
| embedding | 0.15 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 2/3 (0.67) |
| embedding | 0.2 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.22 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.25 ← | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.28 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.3 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.35 | 16/16 (1.00) | 4/4 (1.00) | 20/20 (1.00) | 1.0 | 3/3 (1.00) |
| embedding | 0.4 | 14/16 (0.88) | 3/4 (0.75) | 17/20 (0.85) | 0.85 | 3/3 (1.00) |
| tfidf | 0.0 | 16/16 (1.00) | 2/4 (0.50) | 16/20 (0.80) | 0.8417 | 3/3 (1.00) |
| tfidf | 0.02 | 16/16 (1.00) | 2/4 (0.50) | 16/20 (0.80) | 0.8417 | 3/3 (1.00) |
| tfidf | 0.05 ← | 16/16 (1.00) | 2/4 (0.50) | 16/20 (0.80) | 0.8417 | 3/3 (1.00) |
| tfidf | 0.1 | 15/16 (0.94) | 2/4 (0.50) | 16/20 (0.80) | 0.825 | 3/3 (1.00) |
| tfidf | 0.15 | 15/16 (0.94) | 2/4 (0.50) | 16/20 (0.80) | 0.825 | 3/3 (1.00) |
| tfidf | 0.2 | 15/16 (0.94) | 2/4 (0.50) | 16/20 (0.80) | 0.825 | 3/3 (1.00) |

## Per-ticket rankings (embedding, configured threshold)

Top terms are the lexical (TF-IDF) overlap shown for explainability; non-English tickets often have none, which is exactly why embeddings are used. The snippet is the KB sentence most similar to the ticket.

| Ticket | Lang | Subject | Kept top 3 (score) | Gold relevant | | Best snippet of #1 | Top terms of #1 |
|---|---|---|---|---|---|---|---|
| T-1001 | en | I was charged twice for one order | KB-001 (0.5553), KB-004 (0.2895), KB-008 (0.2742) | KB-001, KB-004 | ✅ | Escalate to billing ops if two settled charges exist for the same order. | charg, pend, order, card |
| T-1002 | en | Cannot log in after resetting password | KB-002 (0.5529), KB-009 (0.4109), KB-010 (0.322) | KB-002 | ✅ | If the reset succeeded but login still fails, escalate to account support. | password, login, reset |
| T-1003 | en | Where can I download invoice PDFs? | KB-003 (0.7572), KB-007 (0.409), KB-008 (0.2532) | KB-003 | ✅ | Customers can filter by month and download each invoice as PDF. | invoic, download invoic, download, invoic pdf |
| E-2001 | en | App crashes when I open it | KB-006 (0.5259) | KB-006 | ✅ | If the app still crashes after reinstalling, escalate to general support with the collected details. | app, crash, app crash, restart |
| E-2002 | en | Export monthly report as CSV | KB-007 (0.7058), KB-003 (0.3595) | KB-007 | ✅ | Reports can be exported under Reports > Export. | export, csv, report csv, report |
| E-2003 | en | Someone else logged into my account | KB-009 (0.524), KB-005 (0.3671), KB-002 (0.3479) | KB-009 | ✅ | If a customer reports logins they do not recognise or account details they did not change, treat the ticket as critical. | account, chang |
| E-2004 | es | No puedo iniciar sesión después de cambiar mi contraseña | KB-002 (0.4123), KB-009 (0.3262), KB-005 (0.2942) | KB-002 | ✅ | If the reset succeeded but login still fails, escalate to account support. | — |
| E-2005 | fr | Où puis-je télécharger mes factures ? | KB-003 (0.5917), KB-007 (0.4029), KB-008 (0.3025) | KB-003 | ✅ | Invoice PDFs are available under Billing > Documents. | pdf |
| E-2006 | de | Abonnement kündigen | KB-008 (0.5261), KB-003 (0.2999), KB-004 (0.2905) | KB-008, KB-004 | ✅ | Subscriptions can be cancelled under Billing > Plan > Cancel subscription. | — |
| E-2007 | en | Two settled charges for order 88213 | KB-001 (0.5528), KB-004 (0.4034), KB-008 (0.3116) | KB-001, KB-004 | ✅ | Escalate to billing ops if two settled charges exist for the same order. | charg, settl, settl charg, two settl |
| E-2008 | en | Can I just send you my password? | KB-002 (0.4962), KB-009 (0.4093), KB-005 (0.3697) | KB-002 | ✅ | If the reset succeeded but login still fails, escalate to account support. | password, send, send password |
| E-2009 | en | Invoice question | KB-003 (0.4627), KB-004 (0.4508), KB-008 (0.4189) | KB-003 | ✅ | If invoices are missing, escalate to billing support. | invoic, bill |
| E-2010 | en | Do you sponsor football teams? | `[]` | — (none) | ✅ | top score 0.1244 < threshold | — |
| E-2011 | en | ∅ | `[]` | — (none) | ✅ | empty ticket | — |
| E-2012 | en | Help | `[]` | — (none) | ✅ | top score 0.1869 < threshold | — |
| E-2013 | en | Lost my phone with the authenticator app | KB-005 (0.6493), KB-002 (0.3515), KB-006 (0.3146) | KB-005 | ✅ | If a customer has lost access to their two-factor authentication (2FA) device, support agents must not disable 2FA from chat or email. | lost, factor, two factor, two |
| E-2014 | en | Dashboard and reports both failing | KB-011 (0.3992), KB-009 (0.331), KB-003 (0.2912) | KB-011 | ✅ | If the status page shows no incident but several features are failing, escalate to general support. | fail, show |
| E-2015 | en | Change my login email | KB-010 (0.5801), KB-002 (0.3171), KB-009 (0.2934) | KB-010 | ✅ | The account email address can be changed under Settings > Profile > Email. | email, address, chang, email address |
| E-2016 | en | Pending charge still showing | KB-001 (0.5953), KB-004 (0.2568) | KB-001 | ✅ | Customers may see both a completed charge and a temporary pending authorization. | charg, pend, two, complet |
| E-2017 | pt | O aplicativo fecha sozinho | KB-006 (0.3889) | KB-006 | ✅ | Ask the customer to update the app to the latest version, restart the device, and reinstall the app. | app |
| E-2018 | en | Send my refund to my bank account instead | KB-008 (0.415), KB-004 (0.3429), KB-001 (0.2742) | KB-008, KB-004 | ✅ | Requests to change where a refund is paid must be escalated to billing ops. | cancell, subscription, cancell subscription, refund |
| E-2019 | en | March invoice missing | KB-003 (0.5928), KB-001 (0.3056), KB-008 (0.2853) | KB-003 | ✅ | If invoices are missing, escalate to billing support. | invoic, invoic miss, miss, bill |
| E-2020 | en | WHERE IS MY MONEY | KB-001 (0.3657), KB-009 (0.2725), KB-004 (0.2719) | KB-001, KB-004 | ✅ | Escalate to billing ops if two settled charges exist for the same order. | charg |

## Where TF-IDF and embeddings disagree

| Ticket | Lang | TF-IDF kept | Embedding kept | Gold |
|---|---|---|---|---|
| T-1001 | en | KB-001, KB-004 | KB-001, KB-004, KB-008 | KB-001, KB-004 |
| T-1003 | en | KB-003, KB-007 | KB-003, KB-007, KB-008 | KB-003 |
| E-2001 | en | KB-006, KB-009 | KB-006 | KB-006 |
| E-2002 | en | KB-007 | KB-007, KB-003 | KB-007 |
| E-2003 | en | KB-010, KB-009, KB-002 | KB-009, KB-005, KB-002 | KB-009 |
| E-2004 | es | `[]` | KB-002, KB-009, KB-005 | KB-002 |
| E-2005 | fr | KB-003 | KB-003, KB-007, KB-008 | KB-003 |
| E-2006 | de | `[]` | KB-008, KB-003, KB-004 | KB-008, KB-004 |
| E-2007 | en | KB-001, KB-005 | KB-001, KB-004, KB-008 | KB-001, KB-004 |
| E-2008 | en | KB-002, KB-009 | KB-002, KB-009, KB-005 | KB-002 |
| E-2009 | en | KB-003, KB-008, KB-001 | KB-003, KB-004, KB-008 | KB-003 |
| E-2013 | en | KB-005, KB-006 | KB-005, KB-002, KB-006 | KB-005 |
| E-2014 | en | KB-003, KB-007, KB-011 | KB-011, KB-009, KB-003 | KB-011 |
| E-2016 | en | KB-001 | KB-001, KB-004 | KB-001 |
| E-2018 | en | KB-008, KB-002, KB-004 | KB-008, KB-004, KB-001 | KB-008, KB-004 |
| E-2019 | en | KB-003 | KB-003, KB-001, KB-008 | KB-003 |
| E-2020 | en | KB-001 | KB-001, KB-009, KB-004 | KB-001, KB-004 |
