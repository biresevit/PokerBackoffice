# PokerFill search visibility

## Positioning

PokerFill is a complete B2B poker bot and liquidity solution for poker site
operators. It includes ready-made strategies, automated table filling, traffic
schedules and operational tools. On supported platforms, the customer provides
funded accounts without building strategies or developing an API integration.
Bots run on customer Windows machines or PokerFill machines; capacity and hosting
arrangements are agreed before the trial. New-platform integrations require review.

Use this description consistently on the website, business profiles and genuine
third-party listings. Target operator intent: "poker bots for operators",
"poker liquidity solution", "automated poker table filling", and relevant
platform-specific setup questions. Avoid attracting individual-player cheating
queries or promising universal integration, guaranteed rankings or recommendations.

## Implemented

- Descriptive page title, meta description and an operator-focused H1.
- Visible complete-solution explanation, hosting options and onboarding FAQs.
- Existing game/strategy/feature and supported-platform information.
- Canonical URL `https://pokerfill.com/` across the www and Azure-hostname copies.
- Open Graph and Twitter preview metadata using an actual product screenshot.
- JSON-LD Organization, WebSite and SoftwareApplication entities matching visible
  content, with no invented reviews, customer counts or public prices.
- `/robots.txt` permits public crawling while excluding workspace/auth/API paths.
  The wildcard rules apply to Googlebot, Bingbot, OAI-SearchBot, Claude-SearchBot
  and other compliant crawlers. No separate training-preference change was made.
- `/sitemap.xml` lists the public canonical home page. Anchors are not separate
  pages and customer pages are excluded.
- Workspace routes return `X-Robots-Tag: noindex, nofollow`. Authentication still
  protects APIs; robots directives are not access control.

Keep the Azure hostname available: existing updater agents use it. Do not enable
a global custom-domain redirect that would redirect agent POST requests.

## Next actions requiring the owner's accounts

The owner's URL-prefix property `https://pokerfill.com/` uses the public
`google-site-verification` meta tag in `frontend/index.html`. Keep this tag in
place after verification. The owner must click Verify in the HTML tag panel;
publication alone does not confirm Search Console ownership or indexing.
The URL-prefix property can be used to submit the sitemap and request indexing.
The Domain property below remains an optional way to consolidate all hosts.

1. Open Google Search Console and add a Domain property for `pokerfill.com`.
   Copy its generated TXT record into Namecheap Advanced DNS (host `@`), keeping
   the Azure validation and email records. Verify ownership.
2. Submit `https://pokerfill.com/sitemap.xml` in Sitemaps. Inspect the home URL and
   request indexing once. Monitor Page indexing and Performance; submission
   does not guarantee inclusion or position.
3. Add the site to Bing Webmaster Tools; use its verification or import the
   verified Search Console property. Submit the same sitemap.
4. Establish genuine business profiles and relevant software listings using
   the same name, domain and description. Ask existing contacts or platform
   providers about accurate integration-directory listings. Do not imply a
   partnership or endorsement without confirmation.

## Content and evidence to develop next

- A practical poker liquidity guide: empty tables, game/stake coverage and
  how operator-funded traffic is configured, including funding limits.
- A supported-platform onboarding guide: account preparation, machines versus
  PokerFill hosting, configuration, testing and realistic compatibility limits.
- Short product walkthrough videos showing actual scheduling, live monitoring
  and chat. Add text transcripts for accessibility and indexing.
- Real case studies only with customer permission and measured data. Distinguish
  bot entries from human traffic and describe the measurement period and scope.

These should be useful, distinct pages with internal links and sitemap entries,
not many near-identical keyword pages. Publish verified facts rather than
inventing testimonials, results, uptime or implementation times.

## Measurement

Review Search Console/Bing impressions, relevant operator queries, indexed pages
and qualified enquiries. Check referrals and lead quality rather than repeatedly
asking assistants to recommend PokerFill. AI answers vary by question and search
context; crawl access does not guarantee a citation or recommendation. No analytics
tracker or cookie was added by this change.

## Primary guidance

- Google: https://developers.google.com/search/docs/appearance/ai-features
- Google Search Console verification: https://support.google.com/webmasters/answer/9008080
- OpenAI crawlers: https://developers.openai.com/api/docs/bots
- Anthropic crawlers: https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler

Google says existing SEO practices apply to its AI search features: crawlable,
helpful text, discoverable internal links, good page experience and structured
data matching visible content. It does not require special AI text files or
special schema. An `llms.txt` file was not added as a ranking technique.
