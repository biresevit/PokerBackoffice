# Public product page

The site root `/` serves the public PokerFill product page. It is static
HTML/CSS/JavaScript and makes no requests for live customer data. Only submitting
the public quote form calls `/api/contact`.
The hero lobby, profile charts and traffic visuals use labelled example data.
The platform gallery uses the actual screenshots supplied for publication.

The page positions PokerFill as a complete B2B poker bot and liquidity solution:
strategies, scheduling and operational tools are included; supported platforms
require no customer-developed API integration; bots can run on customer Windows
machines or PokerFill machines. Search metadata, structured data, robots and
sitemap configuration and the next indexing steps are in `search-visibility.md`.

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

## Quotes, trial and onboarding

Software pricing is quoted individually after reviewing the customer's platform,
bot count, games, stakes and traffic requirements. There is no public software
price list. The existing MTT amounts illustrate a prize pool, not software fees.

The enquiry form requires only an email address, bot count and game formats.
It does not ask for a name, company, platform or stakes. Poker site and preferred
testing start date/time are optional. The browser displays its IANA time zone
and submits it with the local date/time, so enquiries and fallback email drafts
identify the intended time zone. A preferred date is a request, not a booking.

The game-support section explains: NLH uses a live postflop solver and supports
cash games, SNG and MTT; PLO4 uses saved solver ranges for cash games; PLO5 has
the least advanced strategy of the three and supports cash games. SNG/MTT are
NLH only. Straddle, ante and run it twice are supported; double-board games are not.
The same section lists EvenBet (`https://evenbeter.com/`) and Run Your Own Poker
Site (`https://runyourownpokersite.com/`) as supported platforms, linking to their
sites. Additional platform and custom-site integrations are offered following
an interface review and agreement on scope and timing.

The approved offer is one month free after compatibility review. The operator
provides the bot accounts and funds their balances; trial scope and start date
are agreed before launch. Onboarding explains account preparation, importing
usernames, configuring profiles and schedules, and evaluating the setup.
`frontend/bot-account-template.csv` matches the real backoffice CSV importer:
usernames and optional profile names, with no balance-transfer functionality.

`home-contact.js` posts enquiries to the anonymous `/api/contact` endpoint.
The API validates fields and sends through Namecheap SMTP over verified TLS,
using a fixed From/To `support@pokerfill.com` and the visitor's address as Reply-To.
The only required secret is the Azure application setting
`POKERFILL_SMTP_PASSWORD`. `tools/configure_contact_email.py` prompts locally
with a masked field, verifies SMTP authentication and saves the secret directly
to Azure without writing or printing it. No password is embedded in the website.

Success is shown only after SMTP accepts the message. On errors/timeouts,
the entered fields remain and an email draft link provides a fallback.
There are no automatic retries or confirmation emails to arbitrary recipients.
Same-origin JSON/custom-header checks, field limits and a honeypot reduce spam.
Migration `sql/014_contact_rate_limit.sql` adds shared transaction-locked counters:
five attempts per source IP/hour (IPv6 /64) and 100 total/day. It stores only
hashed buckets, timestamps and counts, cleans after two days, and holds no
enquiry contents. Enquiries are retained in the support mailbox only.
`tools/check_home_quote.py` checks UI delivery, errors, validation, trial
selection, CSV compatibility and mobile layout using mocked mail responses.

## Selected domain

Public brand: **PokerFill**. Selected domain: `pokerfill.com`. Quote/contact
mailbox: `support@pokerfill.com`. The operator activated this mailbox and
confirmed successful login and a test email on November 4, 2026.
