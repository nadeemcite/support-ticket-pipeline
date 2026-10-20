# Stage 1 — PII masking report

> All PII below is **synthetic** test data (see `data/README.md`). The original text is shown so the reviewer can confirm nothing was missed; it exists only in the input files, never in pipeline artifacts.

## Summary

- Eval tickets whose detected PII types equal `gold.pii_expected`: **23/23**
- `pii_cases.json` fixtures passing (types + exact masked text): **14/14**
- Raw PII values found in `normalised_tickets.json` / `run_manifest.json` across all fixture runs: **0**

## Eval tickets with PII (original vs masked)

| Ticket | Original | Masked (what every later stage and API sees) | Detected | Expected | |
|---|---|---|---|---|---|
| E-2007 | Both charges for order 88213 are now settled on my statement, not pending. My card is 4111 1111 1111 1111 and my email is jane.doe@example.com. Please refund one of them. | Both charges for order 88213 are now settled on my statement, not pending. My card is [CARD_NUMBER_1] and my email is [EMAIL_1]. Please refund one of them. | card_number, email | card_number, email | ✅ |
| E-2008 | I'm locked out after resetting. My password is Summer2026! - can you log in for me and check what is wrong? | I'm locked out after resetting. My password is [CREDENTIAL_1] - can you log in for me and check what is wrong? | credential | credential | ✅ |
| E-2013 | I got a new phone and can no longer get my two-factor codes. Can you turn off 2FA for me? You can reach me on +44 20 7946 0958. | I got a new phone and can no longer get my two-factor codes. Can you turn off 2FA for me? You can reach me on [PHONE_1]. | phone | phone | ✅ |
| E-2015 | I'm moving to a new company email. How can I update the email address on my account? The new one will be sam.lee@example.org. | I'm moving to a new company email. How can I update the email address on my account? The new one will be [EMAIL_1]. | email | email | ✅ |
| E-2018 | I cancelled my subscription. Please send any refund to IBAN GB82 WEST 1234 5698 7654 32 instead of my card. | I cancelled my subscription. Please send any refund to IBAN [IBAN_1] instead of my card. | iban | iban | ✅ |

## Eval tickets without PII (must be unchanged by masking)

| Ticket | Detected | Expected | Text unchanged | |
|---|---|---|---|---|
| T-1001 | — | — | yes | ✅ |
| T-1002 | — | — | yes | ✅ |
| T-1003 | — | — | yes | ✅ |
| E-2001 | — | — | yes | ✅ |
| E-2002 | — | — | yes | ✅ |
| E-2003 | — | — | yes | ✅ |
| E-2004 | — | — | yes | ✅ |
| E-2005 | — | — | yes | ✅ |
| E-2006 | — | — | yes | ✅ |
| E-2009 | — | — | yes | ✅ |
| E-2010 | — | — | yes | ✅ |
| E-2011 | — | — | yes | ✅ |
| E-2012 | — | — | yes | ✅ |
| E-2014 | — | — | yes | ✅ |
| E-2016 | — | — | yes | ✅ |
| E-2017 | — | — | yes | ✅ |
| E-2019 | — | — | yes | ✅ |
| E-2020 | — | — | yes | ✅ |

## Detector fixtures (`data/fixtures/pii_cases.json`)

Cases with an empty expected list are **false-positive guards** (order IDs, dates, amounts, error codes, Luhn-invalid numbers, advice text).

| ID | Input | Masked output | Detected | Expected | |
|---|---|---|---|---|---|
| P01 | My email is jane.doe@example.com, please reply there. | My email is [EMAIL_1], please reply there. | email | email | ✅ |
| P02 | Call me on +44 20 7946 0958 after 5pm. | Call me on [PHONE_1] after 5pm. | phone | phone | ✅ |
| P03 | My card is 4111 1111 1111 1111 and it was charged twice. | My card is [CARD_NUMBER_1] and it was charged twice. | card_number | card_number | ✅ |
| P04 | Card 4111-1111-1111-1111 expired. | Card [CARD_NUMBER_1] expired. | card_number | card_number | ✅ |
| P05 | Reference number 1234 5678 9012 3456 from the bank. | Reference number 1234 5678 9012 3456 from the bank. | — | — (guard) | ✅ |
| P06 | Send it to IBAN GB82 WEST 1234 5698 7654 32 please. | Send it to IBAN [IBAN_1] please. | iban | iban | ✅ |
| P07 | My password is Summer2026! - can you log in for me? | My password is [CREDENTIAL_1] - can you log in for me? | credential | credential | ✅ |
| P08 | the code is 482913, I just got it by SMS | the code is [CREDENTIAL_1], I just got it by SMS | credential | credential | ✅ |
| P09 | I changed my password this morning but login fails. | I changed my password this morning but login fails. | — | — (guard) | ✅ |
| P10 | Order 88213 was charged on 2026-05-20 for $49.99. | Order 88213 was charged on 2026-05-20 for $49.99. | — | — (guard) | ✅ |
| P11 | Old: sam.lee@example.org, new: s.lee@example.com | Old: [EMAIL_1], new: [EMAIL_2] | email, email | email, email | ✅ |
| P12 | Error 503 since 09:00 UTC on the dashboard. | Error 503 since 09:00 UTC on the dashboard. | — | — (guard) | ✅ |
| P13 | Mi correo es ana.garcia@example.com y mi contraseña es Clave#123 | Mi correo es [EMAIL_1] y mi contraseña es [CREDENTIAL_1] | email, credential | email, credential | ✅ |
| P14 | Please never share your password with anyone. | Please never share your password with anyone. | — | — (guard) | ✅ |

## How placeholders and hashes appear in the artifact

`normalised_tickets.json` stores only masked text plus a `pii_summary` (type, placeholder, count, `sha256(PII_HASH_SALT + value)`). Example for E-2007:

```json
[
  {
    "type": "card_number",
    "placeholder": "[CARD_NUMBER_1]",
    "count": 1,
    "hash": "sha256:6986c79c7a9b672ccf8483a33cdb13f129f261adfe04981905bb1974430923b8"
  },
  {
    "type": "email",
    "placeholder": "[EMAIL_1]",
    "count": 1,
    "hash": "sha256:cd06e9f1add4f33adf5802b7b8f589f79d21e70c4c045798be2c3fc61765ddd4"
  }
]
```
