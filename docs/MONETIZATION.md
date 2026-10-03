# Monetization blueprint: Extractly

## The product in one line

A hosted API that turns unstructured text into schema-validated JSON. Customers are automation builders (Zapier/Make/n8n power users, indie hackers, ops teams) who currently hand-roll LLM glue code for every parse step.

## Pricing tiers

| Tier | Price | Daily quota | Rate limit | Support |
|---|---|---|---|---|
| Free | $0 | 25 extractions/day | 30/min | Community |
| Pro | $29/mo | 2,000 extractions/day | 30/min | Email |
| Team | $99/mo | 20,000 extractions/day | 120/min | Priority email |

Pro is sold as a monthly license through Gumroad. The customer pastes the license key on the dashboard; `/v1/upgrade` verifies it live against Gumroad and flips the key to Pro. No Stripe account, no webhook infrastructure, no PCI scope. Team is manual onboarding for now.

## Unit economics (measured, not modeled)

Inference: NVIDIA Nemotron 3 Nano via Nebius Token Factory.
Published catalog pricing (fetched 2026-10-03 from Token Factory's public
catalog): **$0.06 / 1M input tokens, $0.24 / 1M output tokens**.

Measured per-extraction usage (live, 2026-10-03):

| Case | Prompt tokens | Completion tokens | Cost |
|---|---|---|---|
| Typical (invoice, ~120 chars) | 207 | 151 | **$0.000049** |
| Heavy (8,000 chars + one retry) | ~2,200 | ~600 | **$0.000276** |

Worst-case cost per tier at 100% quota utilization (heavy case):

| Tier | Max extractions/mo | Max inference cost/mo | Revenue/mo |
|---|---|---|---|
| Free | 750 | $0.21 | $0 |
| Pro | 60,000 | $16.56 | $29.00 |
| Team | 600,000 | $165.60 | $99.00 |

Two honest notes:

1. **Team at 100% heavy-case utilization is underwater** ($165.60 cost vs $99 revenue). In practice nobody sustains 20k max-length extractions with retries every day; at typical-case cost ($0.000049) the same tier costs $29.40/mo. The Team tier is positioned for bursty, not saturated, use, and the terms allow a fair-use conversation at sustained saturation. This is disclosed, not hidden.
2. **Free at 100% utilization costs $0.21/mo per user.** That is the customer-acquisition cost, and it is trivially affordable. Abuse is bounded by design: 25/day quota, 10 keys/hour/IP, input caps, kill switch.

Contribution margin at realistic utilization (10% of quota, typical case):

| Tier | Revenue/mo | Inference cost/mo | Gumroad fee | Gross margin |
|---|---|---|---|---|
| Pro | $29.00 | $0.29 | $3.40 (10% + $0.50) | **$25.31 (87%)** |
| Team | $99.00 | $2.94 | n/a (manual) | **$96.06 (97%)** |

Infrastructure: one AWS t3.micro (free tier, $0), SQLite (no managed DB bill), no per-seat costs. Fixed costs are effectively $0 until traffic outgrows a single box.

## Go-to-market

1. **Gumroad audience (now):** Inan already sells a $79 AI product on Gumroad with payouts connected. Extractly Pro launches as a second product to the same buyer pool: builders who buy AI tooling.
2. **Automation communities (week 1-2):** launch posts with a live demo key in Zapier/Make/n8n communities and r/automation. The product demos itself in one curl.
3. **Template directory (month 2):** prebuilt Zapier/Make templates ("email to CRM", "ticket triage to Linear") with Extractly as the parse step. Templates are the distribution.
4. **SEO docs (ongoing):** every docs page is a landing page for "extract JSON from [x]" queries.

## What "profitable" means here

No venture scale needed. 40 Pro customers = $1,160/mo revenue against roughly $12/mo inference and $0 infra. The business is profitable from customer one because marginal cost rounds to zero and fixed cost is zero. The honest risk is distribution, not economics, which is why GTM starts with an audience that already buys.
