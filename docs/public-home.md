# Public product page

The site root `/` serves the public PokerFill product page. It is static
HTML/CSS/JavaScript and makes no API calls or requests for customer data.
The lobby, profile mix and traffic visuals use explicitly labelled example data.

The existing customer app is served at `/backoffice`, rewritten to
`workspace.html`. Microsoft sign-in returns there. API authentication and
customer membership checks are unchanged. Root links with existing workspace
hashes or a `live_request` query redirect to `/backoffice`, retaining the full
query and hash. Existing live table windows therefore keep working.

Page files: `frontend/index.html`, `home.css`, `home.js`. The brand and sign-in
links use relative URLs so the page works on the existing Azure hostname and
on a custom domain once that domain is configured separately.

With `tools/preview.py --port 4298` running, `tools/check_home.py` checks public
access without private API calls, stake selection, FAQs, mobile widths, sign-in
and old workspace links. `tools/check_live_cards.py` verifies live windows
through the root URL redirect. Deploy using the existing `tools/deploy.py`.

## Selected domain

Public brand: **PokerFill**. Selected domain: `pokerfill.com`. Planned demo
mailbox: `hello@pokerfill.com`. Registration, DNS and mailbox provisioning are
still required. Keep the existing platform links until the mailbox can receive
enquiries.

