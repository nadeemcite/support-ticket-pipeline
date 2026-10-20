# Stage 4 — grounding flags review

Every G1–G3 flag raised on the eval drafts, with the cited KB text next to it. Flags never block a draft. Mark each **TP** (the draft claims something its cited text doesn't support) or **FP** (heuristic too strict), and note any tuning.

Total flags: **8** across 92 drafts.

### F1 — T-1003 · `deepseek-v4.1-flash` · oracle · G1 (number_or_duration)

- Sentence: “If any of the invoices for the last three months are not showing up under Billing > Documents, please let us know which months are missing and we will escalate the matter to our billing support team for further review.”
- Unsupported: ['three months'] · best overlap with cited text: 0.29
- Cited KB text:

  ```
  [KB-003] Invoice PDFs are available under Billing > Documents. Customers can filter by month and download each invoice as PDF. If invoices are missing, escalate to billing support.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F2 — E-2001 · `deepseek-v4.1-flash` · oracle · G2 (ui_path)

- Sentence: “- Your iOS version (Settings > General > About)”
- Unsupported: ['Settings > General > About'] · best overlap with cited text: 0.25
- Cited KB text:

  ```
  [KB-006] Ask the customer to update the app to the latest version, restart the device, and reinstall the app. Collect the device model, operating system version and app version. If the app still crashes after reinstalling, escalate to general support with the collected details.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F3 — E-2008 · `deepseek-v4.1-flash` · oracle · G3 (commitment)

- Sentence: “For your security, please never share your password or any verification codes with anyone, including our support team — we will never ask for them.”
- Unsupported: ['we will'] · best overlap with cited text: 0.18
- Cited KB text:

  ```
  [KB-002] Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. If the reset succeeded but login still fails, escalate to account support. Never ask the customer to send their password.
  [KB-009] If a customer reports logins they do not recognise or account details they did not change, treat the ticket as critical. Advise them to reset their password immediately and sign out of all sessions under Settings > Security. Escalate to account support immediately.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F4 — E-2013 · `deepseek-v4.1-flash` · oracle · G3 (commitment)

- Sentence: “To keep your account safe, please do not share your password, one-time codes or recovery codes with anyone, including our support staff — we will never ask you for them.”
- Unsupported: ['we will'] · best overlap with cited text: 0.14
- Cited KB text:

  ```
  [KB-005] If a customer has lost access to their two-factor authentication (2FA) device, support agents must not disable 2FA from chat or email. Escalate to account support so the customer's identity can be verified. Never ask the customer for one-time codes or recovery codes.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F5 — T-1002 · `deepseek-v4.1-flash` · e2e · G3 (commitment)

- Sentence: “Double-check that you're entering the most recent password you set (older saved passwords in your browser can be filled in automatically).”
- Unsupported: ['can be'] · best overlap with cited text: 0.17
- Cited KB text:

  ```
  [KB-002] Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. If the reset succeeded but login still fails, escalate to account support. Never ask the customer to send their password.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F6 — T-1003 · `deepseek-v4.1-flash` · e2e · G1 (number_or_duration)

- Sentence: “If any of the invoices for the last three months are not showing up under that section, please let us know which months are missing and we'll escalate the matter to our billing support team to look into it.”
- Unsupported: ['three months'] · best overlap with cited text: 0.31
- Cited KB text:

  ```
  [KB-003] Invoice PDFs are available under Billing > Documents. Customers can filter by month and download each invoice as PDF. If invoices are missing, escalate to billing support.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F7 — E-2006 · `deepseek-v4.1-flash` · e2e · G2 (ui_path)

- Sentence: “Falls Sie zusätzlich Fragen zu Ihren Rechnungen haben: Rechnungs-PDFs finden Sie unter Billing > Documents.”
- Unsupported: ['Billing > Documents'] · best overlap with cited text: 0.07
- Cited KB text:

  ```
  [KB-008] Subscriptions can be cancelled under Billing > Plan > Cancel subscription. Access continues until the end of the current billing period. Cancelling does not trigger an automatic refund for the current period. Requests to change where a refund is paid must be escalated to billing ops.
  [KB-004] Refunds depend on settlement status, product type, and fraud checks. Agents should not guarantee same-day refunds unless policy explicitly allows it.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

### F8 — E-2008 · `deepseek-v4.1-flash` · e2e · G3 (commitment)

- Sentence: “Please never share your password with anyone, including our support team — we will never ask you for it.”
- Unsupported: ['we will'] · best overlap with cited text: 0.25
- Cited KB text:

  ```
  [KB-002] Ask the user to verify they are using the most recent password, clear cached sessions, and retry in an incognito window. If the reset succeeded but login still fails, escalate to account support. Never ask the customer to send their password.
  [KB-009] If a customer reports logins they do not recognise or account details they did not change, treat the ticket as critical. Advise them to reset their password immediately and sign out of all sessions under Settings > Security. Escalate to account support immediately.
  ```

- Human verdict: ☐ TP ☐ FP · Note: ______

