# Manual control at a live table

Open Live tables, choose a table and a hero, and open its live window. Manual control is off by default. Switch it on for that hero at that table. After the controller acknowledges it, legal Fold, Check/Call and Bet/Raise controls appear on hero's turn. Bet input is a total for the current betting round (raise-to), with server-provided minimum/maximum bounds. Pot shortcuts use the pot after calling; 1/3, 2/3, 3/4 and pot amounts are bounded by the table's limits. Plus/minus adjusts by one big blind. Chip amounts use two decimal places.

While enabled, the worker bypasses automatic decision requests for that hero/table. A takeover also cancels submission of an automatic decision still being calculated. An action already committed before takeover cannot be undone. Turn claims serialize automatic and manual sends; each turn is submitted at most once, even after a reconnect. Ambiguous sends are reported as unconfirmed and never retried.

Only operators can take control, and only from their own customer-scoped live request. A second window cannot steal a live control lease. The browser renews its 45-second lease through live polling. Switching off resumes automatic play immediately; closing/disconnecting lets the lease expire and resumes automatic play. A controller epoch change invalidates the old lease and requires taking control again. Stale snapshots and changed turns disable/reject action submission.

PokerController 0.1.0+manual1 is required. Older workers remain view-only and show an update message. The release for normal fleet updates is 2026.10.29.9. The MSI worker-only repair retains its identical existing PDecision executable; other machines receive the normal paired release through Backoffice Updates.

Verification: controller action/concurrency tests, customer and role checks, minor-unit/betting-limit validation, SQL claim/lease smoke checks, and a Playwright browser fixture that submits to a mock API. The browser tests do not submit poker actions to a live table.
