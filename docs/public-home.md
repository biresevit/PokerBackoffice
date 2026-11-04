# Public product page

The site root `/` serves the public PokerFill product page. It is static
HTML/CSS/JavaScript and makes no API calls or requests for live customer data.
The hero lobby, profile charts and traffic visuals use labelled example data.
The platform gallery uses the actual screenshots supplied for publication.

The existing customer app is served at `/backoffice`, rewritten to
`workspace.html`. Microsoft sign-in returns there. API authentication and
customer membership checks are unchanged. Root links with existing workspace
hashes or a `live_request` query redirect to `/backoffice`, retaining the full
query and hash. Existing live table windows therefore keep working.

Page files: `frontend/index.html`, `home.css`, `home.js`. The brand and sign-in
links use relative URLs so the page works on the existing Azure hostname and
on a custom domain once that domain is configured separately.

`home-showcase.css` and `home-showcase.js` provide the profile and MTT sections.
The eight profile cards reproduce the supplied example VPIP/PFR/3-bet/C-bet
values as responsive vector charts in the site's palette. The MTT illustration
uses 20 human entries plus either 100 or 200 operator-funded entries, each
contributing $10 to the pool, excluding fees. It displays the operator's funding
separately from the total; this is an illustration, not a guaranteed payout.

`home-screens.css` and `home-screens.js` provide the screenshot gallery. Eight
original PNGs were selected from `images/` and copied unchanged to
`frontend/product-shots/`: overview, player settings, weekly schedule, live
lobby, manual control on, chat, account distributions and hand replay. Each
view has a description, full-size dialog, previous/next controls and a zoom
toggle. Native lazy loading and on-selection loading avoid downloading every
screenshot at initial page load. The remaining original captures stay in the
source folder for later use.

With `tools/preview.py --port 4298` running, `tools/check_home.py` checks public
access without private API calls, profile/MTT examples, all screenshot loads,
dialog zoom and keyboard navigation, mobile widths, sign-in and old workspace
links. `tools/check_live_cards.py` verifies live windows
through the root URL redirect. Deploy using the existing `tools/deploy.py`.

## Selected domain

Public brand: **PokerFill**. Selected domain: `pokerfill.com`. Planned demo
mailbox: `hello@pokerfill.com`. Registration, DNS and mailbox provisioning are
still required. Keep the existing platform links until the mailbox can receive
enquiries.
