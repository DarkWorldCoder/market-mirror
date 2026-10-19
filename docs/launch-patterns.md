# Launch patterns: benchmark priors and real cases

Generated 2026-10 for MarketMirror. Machine-readable twin: `benchmarks/launch_patterns.json`. Every figure and every case below links to the page it was read from; nothing is estimated or invented.

## How to use these priors

- **Treat each number as a vendor sample, not a law.** LocaliQ/WordStream rows are averages across their (mostly US SMB) customer accounts; Superads and Lebesgue rows are medians/averages from DTC-heavy ad accounts; Mailchimp and Benchmark Email rows are SMB-heavy; RevenueCat rows cover 75k subscription apps. The same metric from two sources can differ 2-3x purely because of sample and statistic (mean vs median, link-CTR vs all-clicks CTR). Use the **note** column before comparing.
- **Pick the row that matches your funnel step and objective.** Facebook *traffic* CTR (~1.9%) and *lead* CTR (~2.7%) are different campaigns; TikTok "CTR 1.77%" counts all clicks while the 0.61% median counts link clicks; LinkedIn conversion rate counts lead-form submits.
- **Emerging markets: costs are ~90% lower, response is often lower too.** India/Philippines Facebook CPM and CPC run at roughly a tenth of global medians, Indian email open rates in the Benchmark Email sample are ~11% vs ~26% overall, and RevenueCat's Day-14 revenue per install for India/SEA is $0.06-0.09 vs $0.39 in North America. Cheap reach does not imply cheap conversions.
- **For simulations, use the benchmark as the centre of a wide prior** (e.g. log-normal with sigma ~0.5) and let the matching cases below narrow it. Prefer the `benchmarks` array for defaults; the `benchmarks_extended` rows add per-industry detail from the same reports.
- **Units.** `%` rows are percentages (8.56 means 8.56%). `usd`/`gbp` are per click / per 1,000 impressions / per lead as the metric says. Churn rows from Recurly carry an explicit unit caution (page says "annual", magnitudes look monthly).

## Benchmarks by channel

Core rows are listed first; extended rows (same sources, more industries/regions) follow under each channel.

### Email

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| email_open_rate | all | global | **35.63%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | Average unique open rate across Mailchimp campaigns with tracking on, sent to >=1,000 subscribers, industry self-reported; data last updated Dec 2023; Apple MPP inflates opens. |
| email_click_rate | all | global | **2.62%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | Average click rate, same sample as open rate; page defines CTR as total clicks / emails delivered. |
| unsubscribe_rate | all | global | **0.22%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | Average unsubscription rate per campaign, same sample. |
| email_open_rate | ecommerce | global | **29.81%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | 'Ecommerce' row; click rate 1.74%, unsubscribe 0.19%. |
| email_click_rate | ecommerce | global | **5.58%** | 2026 | [Klaviyo 2026 Email Marketing Benchmarks by Industry](https://www.klaviyo.com/products/email-marketing/benchmarks) | Click rate for automated FLOWS (e.g. welcome, abandoned cart) across Klaviyo ecommerce customers; flows are 5.3% of sends but ~41% of email revenue. |
| email_click_rate | ecommerce | global | **1.69%** | 2026 | [Klaviyo 2026 Email Marketing Benchmarks by Industry](https://www.klaviyo.com/products/email-marketing/benchmarks) | Click rate for one-off CAMPAIGNS (94.7% of sends); page says flows have ~13x the placed-order rate of campaigns but does not print the rates. |
| email_open_rate | all | global | **25.54%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | Grand-total average across 68,000 Benchmark Email users, 90+ industries, 21 regions; click 1.45%, unsubscribe 0.10%. Data period NOT stated on page (fetched Oct 2026; year here = fetch year). |
| email_open_rate | all | india | **10.74%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | India row of the regional table; click 0.84%, unsubscribe 0.07%. Vendor-specific sample skewed to SMBs; data period not stated. |
| email_open_rate | all | sea | **11.64%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | 'South East Asia' row; click 0.39%, unsubscribe 0.03%. |
| email_open_rate | all | africa | **15.42%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | 'Africa' row; click 0.54%, unsubscribe 0.10%. |
| landing_conversion | all | global | **19.3%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Average landing-page conversion rate for traffic arriving from email (highest channel). |

<details><summary>Extended rows for Email (8)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| email_open_rate | education | global | **35.64%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | 'Education + Training' row of the industry table; click rate 3.02%, unsubscribe 0.18%. |
| email_click_rate | education | global | **3.02%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | 'Education + Training' row of the industry table. |
| email_click_rate | ecommerce | global | **1.74%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | 'Ecommerce' row of the industry table. |
| email_open_rate | finance | global | **31.35%** | 2023 | [Mailchimp Email Marketing Benchmarks](https://mailchimp.com/resources/email-marketing-benchmarks/) | 'Business + Finance' row; click rate 2.78%, unsubscribe 0.15%. |
| email_click_rate | all | india | **0.84%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | India row of the regional table. |
| email_open_rate | all | us | **27.69%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | 'US / Canada' row; click 1.18%, unsubscribe 0.14%. |
| email_open_rate | fitness | global | **19.85%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | 'Health and Fitness' industry row; click 0.95%, unsubscribe 0.09%. |
| email_open_rate | saas | global | **13.86%** | 2026 | [Benchmark Email - Email Marketing Benchmarks by Industry and Region](https://www.benchmarkemail.com/email-marketing-benchmarks/) | 'Computer Software' industry row; click 0.25%. 'Information Technology and Services' row is 28.16% open / 0.61% click. |

</details>

### Landing pages & SaaS trials

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| landing_conversion | all | global | **6.6%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Median conversion rate across all industries; 41K+ landing pages, 464M+ visitors, 57M+ conversions. Industry medians range 3.8%-12.3% (chart only). |
| trial_to_paid | saas | global | **8.0%** | 2026 | [ChartMogul / ProductLed - SaaS Conversion Report (Jan 2026)](https://chartmogul.com/reports/saas-conversion-report-2/) | Median free-to-paid conversion across 200 surveyed B2B software products (typical $1-10M ARR); page notes few products sit at exactly 8%. |
| trial_to_paid | saas | global | **30.0%** | 2026 | [ChartMogul / ProductLed - SaaS Conversion Report (Jan 2026)](https://chartmogul.com/reports/saas-conversion-report-2/) | Free-to-paid for trials that REQUIRE a credit card; described as >5x the rate of no-card trials. 20% of free-trial products require a card; 62% use 14-day trials. |
| trial_to_paid | saas | global | **18.2%** | 2025 | [First Page Sage - SaaS Free Trial Conversion Rate Benchmarks](https://firstpagesage.com/seo-blog/saas-free-trial-conversion-rate-benchmarks/) | Opt-in (no card) trial-to-paid, organic traffic; paid traffic 17.4%. Agency client sample: 86 SaaS companies (71% B2B), Q1 2022-Q3 2025; 'paid' = even one paid month. |
| trial_to_paid | saas | global | **48.8%** | 2025 | [First Page Sage - SaaS Free Trial Conversion Rate Benchmarks](https://firstpagesage.com/seo-blog/saas-free-trial-conversion-rate-benchmarks/) | Opt-out (card required) trial-to-paid, organic traffic; paid traffic 51%. Visitor-to-trial is only 2.5% for opt-out vs 8.5% for opt-in. |

<details><summary>Extended rows for Landing pages & SaaS trials (3)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| freemium_to_paid | saas | global | **2.6%** | 2025 | [First Page Sage - SaaS Free Trial Conversion Rate Benchmarks](https://firstpagesage.com/seo-blog/saas-free-trial-conversion-rate-benchmarks/) | Freemium-to-paid, organic traffic (paid 2.8%); visitor-to-freemium 13.3%. |
| visitor_to_trial | saas | global | **8.5%** | 2025 | [First Page Sage - SaaS Free Trial Conversion Rate Benchmarks](https://firstpagesage.com/seo-blog/saas-free-trial-conversion-rate-benchmarks/) | Website visitor-to-free-trial for opt-in trials, organic traffic. |
| trial_to_paid | education | global | **24.8%** | 2025 | [First Page Sage - SaaS Free Trial Conversion Rate Benchmarks](https://firstpagesage.com/seo-blog/saas-free-trial-conversion-rate-benchmarks/) | 'Education / Edtech' industry row; visitor-to-trial 10.3%. Fintech 19.4% (visitor-to-trial 9.0%); Healthcare/Medtech 21.5%. |

</details>

### Google / Microsoft search ads

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| landing_conversion | all | global | **11.3%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Average landing-page conversion rate for Google paid search traffic; all paid search 10.9%. |
| ctr | all | us | **6.64%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | Average across thousands of LocaliQ customer Google Ads + Microsoft Ads search campaigns (mostly US SMBs); 20+ industries. |
| cpc | all | us | **$5.42** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | Average cost per click, search campaigns, all industries. |
| conversion_rate | all | us | **8.18%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | Average Google Ads conversion rate (conversions / clicks), all industries. |
| cpl | all | us | **$66.69** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | Average cost per lead, search; page says CPL fell for the first time in five years. |
| conversion_rate | education | us | **13.14%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Education & Instruction' row. |
| cpl | saas | us | **$93.69** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Business Services' row (proxy for B2B/SaaS). |

<details><summary>Extended rows for Google / Microsoft search ads (11)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| ctr | education | us | **7.56%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Education & Instruction' row: CPC $4.81, CPL $77.48, CVR 13.14%. |
| cpc | education | us | **$4.81** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Education & Instruction' row. |
| cpl | education | us | **$77.48** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Education & Instruction' row. |
| ctr | fitness | us | **5.81%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Health & Fitness' row: CPC $6.17, CPL $67.36, CVR 6.94%. |
| cpc | fitness | us | **$6.17** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Health & Fitness' row. |
| conversion_rate | fitness | us | **6.94%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Health & Fitness' row. |
| cpl | fitness | us | **$67.36** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Health & Fitness' row. |
| cpc | finance | us | **$3.39** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Finance & Insurance' row: CTR 9.83%, CPL $74.44, CVR 2.64%. |
| conversion_rate | finance | us | **2.64%** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Finance & Insurance' row (lowest CVR in the table). |
| cpc | saas | us | **$5.87** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Business Services' row used as the closest proxy for B2B/SaaS: CTR 6.10%, CPL $93.69, CVR 4.85%. |
| cpc | ecommerce | us | **$4.44** | 2026 | [LocaliQ / WordStream 2026 Search Advertising Benchmarks](https://localiq.com/blog/search-advertising-benchmarks/) | 'Apparel / Fashion & Jewelry' row: CTR 6.64%, CPL $97.51, CVR 4.50%. 'Shopping, Collectibles & Gifts' row: CPC $4.14, CTR 8.28%, CVR 4.01%. |

</details>

### Facebook / Meta ads

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| ctr | all | us | **1.93%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average CTR for TRAFFIC-objective campaigns across LocaliQ/WordStream customer accounts (prior year 1.71%); data period not stated. |
| cpc | all | us | **$0.6** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average CPC for traffic campaigns (prior year $0.70). |
| cpc | all | us | **$1.8** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average CPC for lead campaigns (prior year $1.92). |
| conversion_rate | all | us | **8.54%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average conversion rate (leads / clicks) for lead campaigns (prior year 7.72%). |
| cpl | all | us | **$27.39** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average cost per lead for lead campaigns (prior year $27.66). |
| cpl | education | us | **$26.31** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Education & Instruction' lead-campaign row. |
| cpl | fitness | us | **$27.11** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Health & Fitness' lead-campaign row. |
| cpm | all | global | **$20.59** | 2026 | [Superads Facebook Ads CPM benchmark (global)](https://www.superads.ai/facebook-ads-costs/cpm-cost-per-mille/global) | Mean of monthly MEDIAN campaign CPMs, Jul 2025-Jul 2026, from >$3B spend across thousands of Superads-connected ad accounts (skews to DTC/ecommerce advertisers). Monthly range $16.47-$24.26. |
| cpc | all | india | **$0.1** | 2026 | [Superads Facebook Ads CPC benchmark (India)](https://www.superads.ai/facebook-ads-costs/cpc-cost-per-click/india) | Average of monthly median CPCs (~$0.104), Jul 2025-Jul 2026; monthly range $0.025-$0.209; ~90% below global median. |
| cpm | all | india | **$1.35** | 2026 | [Superads Facebook Ads CPM benchmark (India)](https://www.superads.ai/facebook-ads-costs/cpm-cost-per-mille/india) | Average of monthly median CPMs, Jul 2025-Jul 2026; monthly values from $0.36 (Feb 2026) to $5.02 (Jul 2026); very volatile, small sample. |
| cpm | all | philippines | **$1.39** | 2026 | [Superads Facebook Ads CPM benchmark (Philippines)](https://www.superads.ai/facebook-ads-costs/cpm-cost-per-mille/philippines) | Average of monthly median CPMs, Jul 2025-Jul 2026; monthly range $0.76-$3.39; ~6.8% of global median. |
| cpm | ecommerce | us | **$16.08** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | Ecommerce-brand Facebook CPM by country from Lebesgue's connected-store dataset; collection dates and sample size not stated; article dated Jul 2026. |
| cpm | ecommerce | philippines | **$3.4** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | Philippines row; same dataset caveats. Note the gap vs Superads' $1.39 median: different advertiser mix and statistic. |
| cpm | ecommerce | india | **$1.36** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | India row (lowest of 51 countries listed). |

<details><summary>Extended rows for Facebook / Meta ads (17)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| landing_conversion | all | global | **13.0%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Average landing-page conversion rate for paid Facebook traffic. |
| ctr | all | us | **2.7%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | Average CTR for LEAD-objective campaigns (prior year 2.59%). |
| ctr | education | us | **1.5%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Education & Instruction' traffic-campaign row; CPC $0.70. |
| conversion_rate | education | us | **15.87%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Education & Instruction' lead-campaign row: CTR 1.74%, CPC $1.72, CPL $26.31. |
| ctr | fitness | us | **1.86%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Health & Fitness' traffic-campaign row; CPC $0.64. |
| conversion_rate | fitness | us | **7.98%** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Health & Fitness' lead-campaign row: CTR 3.09%, CPC $1.84, CPL $27.11. |
| cpc | finance | us | **$0.86** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Finance & Insurance' traffic-campaign row (highest CPC); CTR 1.46%. |
| cpc | ecommerce | us | **$0.71** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Apparel / Fashion & Jewelry' traffic-campaign row; CTR 1.51%. 'Shopping, Collectibles & Gifts' row: CTR 1.88%, CPC $0.59. |
| cpc | saas | us | **$0.7** | 2026 | [LocaliQ / WordStream 2026 Facebook Ads Benchmarks](https://localiq.com/blog/facebook-advertising-benchmarks/) | 'Business Services' traffic-campaign row (proxy for B2B/SaaS); CTR 1.64%. |
| cpc | all | global | **$1.05** | 2026 | [Superads Facebook Ads CPC benchmark (global, via India page)](https://www.superads.ai/facebook-ads-costs/cpc-cost-per-click/india) | Global 'all industries' median CPC comparison line shown on the India page; range ~$0.77-$1.29, Jul 2025-Jul 2026; CPC = spend / clicks (click type not specified). |
| cpc | all | philippines | **$0.075** | 2026 | [Superads Facebook Ads CPC benchmark (Philippines)](https://www.superads.ai/facebook-ads-costs/cpc-cost-per-click/philippines) | Average of monthly median CPCs, Jul 2025-Jul 2026; monthly range ~$0.044-$0.149. |
| cpm | ecommerce | brazil | **$2.63** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | Brazil row; Mexico $3.92, Colombia $2.00, Chile $2.44. |
| cpm | ecommerce | south_africa | **$2.99** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | South Africa row; Egypt $1.81. Kenya, Nigeria, Indonesia, Vietnam are NOT in the table. |
| cpm | ecommerce | sea | **$5.39** | 2026 | [Lebesgue - Facebook Ads CPM by Country (2026 ecommerce benchmark)](https://lebesgue.io/facebook-ads/facebook-cpm-by-country) | Malaysia row used as SEA mid-point; Singapore $7.21, Philippines $3.40. |
| cpm | all | global | **$8.17** | 2025 | [Focus Digital - platform comparison tracker (Oct 2025)](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | Meta average CPM in the October-2025 cross-platform tracker on the same page; cost per link click $0.37, link CTR 1.77%. Snapchat CPM $12.84, YouTube $7.61. |
| cpm | ecommerce | global | **$14.19** | 2025 | [Influee - TikTok Ads Benchmarks (Meta 2025 comparison, citing Triple Whale)](https://influee.co/blog/tiktok-ads-benchmarks) | SECONDARY source. Meta 2025 DTC averages listed for comparison: link CTR 2.19%, CPA $38.19, ROAS 1.86. |
| social_engagement_rate | all | global | **0.15%** | 2025 | [Socialinsider Social Media Benchmarks](https://www.socialinsider.io/blog/social-media-benchmarks/) | Average engagement rate by followers ((reactions+comments+shares)/fans), brand posts, 2025; X 0.12%. |

</details>

### Instagram (organic)

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| social_engagement_rate | all | global | **0.4%** | 2026 | [Dash Social 2026 Instagram Benchmark Report](https://www.dashsocial.com/social-media-benchmarks/instagram) | Engagement rate / followers across Dash Social brand sample (sample size not stated); engagement / views = 1.9%. |
| social_engagement_rate | all | global | **2.7%** | 2026 | [Dash Social 2026 Instagram Benchmark Report](https://www.dashsocial.com/social-media-benchmarks/instagram) | Reels engagement rate (denominator not stated on page); carousels 1.4%, static images 1.3%. |

<details><summary>Extended rows for Instagram (organic) (3)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| landing_conversion | all | global | **17.9%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Average landing-page conversion rate for paid Instagram traffic; Facebook paid traffic 13%; YouTube/TikTok/X 6-9%. |
| social_engagement_rate | beauty | global | **0.2%** | 2026 | [Dash Social 2026 Instagram Benchmark Report](https://www.dashsocial.com/social-media-benchmarks/instagram) | Beauty industry engagement / followers; engagement / views 2.1%. Media & Entertainment 0.5% / 2.3%. |
| social_engagement_rate | all | global | **0.48%** | 2025 | [Socialinsider Social Media Benchmarks](https://www.socialinsider.io/blog/social-media-benchmarks/) | Average engagement rate by followers ((likes+comments)/followers), brand posts, 2025; 2024: 0.50%. |

</details>

### Paid social (all)

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| landing_conversion | all | global | **12.0%** | 2024 | [Unbounce 2024 Conversion Benchmark Report](https://unbounce.com/conversion-benchmark-report/) | Average landing-page conversion rate for paid social traffic overall. |

### TikTok (ads & organic)

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| ctr | all | global | **0.61%** | 2026 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | Median CTR, Aug 2025-Jul 2026, 5,900 brands (compiled from Triple Whale / TwoMinuteReports / Gupta Media / Lebesgue datasets); prior 12 months 0.70%. |
| cpm | all | global | **$4.08** | 2026 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | Median CPM, Aug 2025-Jul 2026 (prior 12 months $5.71). Same page's Oct-2025 platform tracker shows TikTok avg CPM $4.67 vs Meta $8.17. |
| conversion_rate | all | global | **1.56%** | 2026 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | Median CVR (purchases / clicks), Aug 2025-Jul 2026; median CPA $17.07; median ROAS 1.51. |
| ctr | education | global | **0.42%** | 2025 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | 'Education and Training' row of the service/B2B industry table, calendar 2025, 2,500 advertisers; median CPC $0.49. |
| cpm | ecommerce | global | **$13.26** | 2025 | [Influee - TikTok Ads Benchmarks (citing Triple Whale, Jan-Dec 2025)](https://influee.co/blog/tiktok-ads-benchmarks) | SECONDARY source: Influee reproduces Triple Whale's 2025 DTC-brand averages (Triple Whale's own page returned 403). 2024 value $11.43. CTR 1.77% (all clicks), CVR 2.01%, CPA $32.74, ROAS 2.21. |
| ctr | ecommerce | global | **1.77%** | 2025 | [Influee - TikTok Ads Benchmarks (citing Triple Whale, Jan-Dec 2025)](https://influee.co/blog/tiktok-ads-benchmarks) | SECONDARY source. Average CTR (all clicks) for DTC brands on Triple Whale; 2024: 1.56%. Industry MEDIAN CTRs on the same page are 0.49%-0.73%. |
| social_engagement_rate | all | global | **3.7%** | 2025 | [Socialinsider Social Media Benchmarks](https://www.socialinsider.io/blog/social-media-benchmarks/) | Average engagement rate by followers ((likes+comments+shares+saves)/followers) for brand TikTok posts, 2025, ~70M posts analyzed; 2024: 2.50%. Page text also says 3.73%. |

<details><summary>Extended rows for TikTok (ads & organic) (6)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| cpa | all | global | **$17.07** | 2026 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | Median cost per acquisition, Aug 2025-Jul 2026 (prior 12 months $24.86); mostly ecommerce advertisers. |
| cpc | education | global | **$0.49** | 2025 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | 'Education and Training' row, calendar 2025. |
| ctr | finance | global | **1.36%** | 2025 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | 'Internet Finance' row (median CPC $0.08); 'Traditional Finance' row CTR 0.35%, CPC $0.49. |
| ctr | ecommerce | global | **0.82%** | 2025 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | 'Retail and E-commerce' row; median CPC $0.26. |
| ctr | health | global | **0.69%** | 2025 | [Focus Digital - Average TikTok Ads CTR and CPM by Industry](https://focus-digital.co/average-tiktok-ads-ctr-and-cpm-by-industry/) | 'Healthcare and Pharmaceutical' row; median CPC $0.30. |
| cpa | health | global | **$16.87** | 2025 | [Influee - TikTok Ads Benchmarks (citing Triple Whale, Jan-Dec 2025)](https://influee.co/blog/tiktok-ads-benchmarks) | SECONDARY source. 'Health & Wellness' median: CPM $5.34, CTR 0.57%, CVR 1.68%, ROAS 0.72. |

</details>

### LinkedIn ads

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| ctr | saas | global | **0.47%** | 2024 | [Huble - LinkedIn Ads benchmarks for 2025 (2024 client data)](https://www.huble.com/blog/linkedin-ads-benchmarks) | Overall sponsored-content CTR (single image + carousel + video) across Huble's B2B clients' 2024 campaigns; agency sample, not LinkedIn-published. |
| cpc | saas | global | **£2.44** | 2024 | [Huble - LinkedIn Ads benchmarks for 2025 (2024 client data)](https://www.huble.com/blog/linkedin-ads-benchmarks) | Overall CPC in GBP; single-image £2.96, carousel £1.69, video £6.39. |

<details><summary>Extended rows for LinkedIn ads (2)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| conversion_rate | saas | global | **15.65%** | 2024 | [Huble - LinkedIn Ads benchmarks for 2025 (2024 client data)](https://www.huble.com/blog/linkedin-ads-benchmarks) | Overall conversion rate (LinkedIn 'conversions' incl. lead-gen form submits / clicks); CPA £29.06. |
| cpl | saas | global | **£29.06** | 2024 | [Huble - LinkedIn Ads benchmarks for 2025 (2024 client data)](https://www.huble.com/blog/linkedin-ads-benchmarks) | Overall CPA (treated as cost per lead); single-image £28.08. |

</details>

### App Store / subscription apps

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| app_store_conversion | all | us | **8.56%** | 2025 | [AppTweak - Average App Conversion Rate per Category (2025)](https://www.apptweak.com/en/aso-blog/average-app-conversion-rate-per-category) | US App Store average CVR = app units / product-page views, 2025; category spread 5.2% (Games-Trivia) to 52.8% (Food & Drink). Page separately and inconsistently mentions 25%. |
| install_to_trial | all | global | **6.2%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Median download-to-trial-start rate across 75,000 subscription apps on RevenueCat; P90 20.3%; high-priced apps 9.8%, low-priced 4.3%. |
| trial_to_paid | fitness | global | **39.9%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Health & Fitness median trial-start-to-paid conversion; top 10% of apps 68.3%. Travel 48.7%, Media & Entertainment 43.8%. |
| install_to_paid | all | global | **12.11%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Median Day-35 download-to-paid for HARD-PAYWALL apps; freemium median 2.18%. Health & Fitness P90 12.1%. |
| revenue_per_install_d14 | all | india_sea | **$0.06** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Median Day-14 revenue per install for India/SEA and Latin America is $0.06-$0.09 vs North America $0.39 (value shown is the low end of the stated range). |
| retention_d30 | fitness | global | **3.9%** | 2026 | [Braze - App retention guide (citing AppsFlyer data via Business of Apps)](https://www.braze.com/resources/articles/mobile-app-retention) | SECONDARY source: Health & Fitness Day-30 retention iOS 3.9% / Android 3.4% as reproduced by Braze; AppsFlyer and Business of Apps pages were blocked/404 for direct fetch. |
| retention_d30 | education | global | **2.7%** | 2026 | [Braze - App retention guide (citing AppsFlyer data via Business of Apps)](https://www.braze.com/resources/articles/mobile-app-retention) | SECONDARY source: Education Day-30 retention iOS 2.7% / Android 2.2% (lowest listed category besides Social). |

<details><summary>Extended rows for App Store / subscription apps (6)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| app_store_install_rate | all | us | **3.8%** | 2025 | [AppTweak - Average App Conversion Rate per Category (2025)](https://www.apptweak.com/en/aso-blog/average-app-conversion-rate-per-category) | US App Store install rate = app units / impressions (search + browse), 2025; 0.6% (Games-Board) to 7.8% (Medical). |
| trial_to_paid | all | latam | **25.0%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Latin America median trial-to-paid; top performers 53.3%. No India/SEA trial-to-paid medians printed on the page. |
| trial_to_paid | all | global | **45.7%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Median trial-to-paid for 17-32 day trials vs 26.8% for shorter trials (per contributor Hannah Parvaz). Low-priced apps 47.8%, high-priced 28.4%. |
| subscription_year1_retention | all | global | **44.1%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Share of YEARLY subscribers still paying after year 1 (prior year 47.1%); monthly plans 17.0%, weekly plans 3.4%. |
| refund_rate | education | global | **4.86%** | 2025 | [RevenueCat State of Subscription Apps 2025](https://www.revenuecat.com/state-of-subscription-apps-2025/) | Education refund rate (highest category); Health & Fitness 4.71%, Travel 1.51%; hard paywall 5.8% vs freemium 3.4%. |
| retention_d30 | finance | global | **6.6%** | 2026 | [Braze - App retention guide (citing AppsFlyer data via Business of Apps)](https://www.braze.com/resources/articles/mobile-app-retention) | SECONDARY source: Finance Day-30 retention iOS 6.6% / Android 3.1%; News highest at 15.3% iOS; Shopping 4.6% / 4.0%. |

</details>

### Google Play

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| app_store_conversion | all | us | **16.15%** | 2025 | [AppTweak - Average App Conversion Rate per Category (2025)](https://www.apptweak.com/en/aso-blog/average-app-conversion-rate-per-category) | US Google Play average CVR (installs / store listing visitors), 2025; spread 6.6% (Games-Strategy) to 62.3% (Auto & Vehicles). |

### Mobile UA (cross-network)

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| cpi | all | global | **$1.8** | 2025 | [Singular Quarterly Trends Report (Q2 2025 data)](https://www.singular.net/quarterly-report-2025-q3/) | Global cost per install across Singular-measured UA spend, Q2 2025 (+15.4% QoQ); CPM $4.16, CTR 5.6%, IPM 2.3. Sample biased to apps actively spending on UA; regional breakdowns Android-only and chart-only. |

<details><summary>Extended rows for Mobile UA (cross-network) (2)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| cpm | all | global | **$4.16** | 2025 | [Singular Quarterly Trends Report (Q2 2025 data)](https://www.singular.net/quarterly-report-2025-q3/) | Global mobile UA CPM, Q2 2025 (+28.4% QoQ); iOS CPM +50.7% QoQ vs Android +9%. |
| install_per_mille | all | global | **2.3 (ratio)** | 2025 | [Singular Quarterly Trends Report (Q2 2025 data)](https://www.singular.net/quarterly-report-2025-q3/) | Installs per 1,000 impressions; Android 2.75 vs iOS 0.979 (Android ~3x). |

</details>

### Subscription churn

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| churn_rate | all | global | **3.6%** | 2026 | [Recurly Research - Churn Rate Benchmarks](https://recurly.com/research/churn-rate-benchmarks/) | Average overall subscriber churn across the Recurly network, July 2026 data; voluntary 2.34%, involuntary 1.25%. UNIT CAUTION: page labels industry figures 'median annual' but Recurly's earlier methodology described monthly churn; magnitudes match monthly. |
| churn_rate | education | global | **4.99%** | 2026 | [Recurly Research - Churn Rate Benchmarks](https://recurly.com/research/churn-rate-benchmarks/) | Education median churn (highest industry); voluntary 3.30%, involuntary 1.69%. |

<details><summary>Extended rows for Subscription churn (3)</summary>

| metric | industry | region | value | year | source | measurement note |
|---|---|---|---|---|---|---|
| churn_rate | saas | global | **3.22%** | 2026 | [Recurly Research - Churn Rate Benchmarks](https://recurly.com/research/churn-rate-benchmarks/) | SaaS median churn (voluntary 2.16%, involuntary 1.06%); lowest industry in the dataset. Same unit caution. |
| churn_rate | ecommerce | global | **4.25%** | 2026 | [Recurly Research - Churn Rate Benchmarks](https://recurly.com/research/churn-rate-benchmarks/) | Ecommerce (subscription boxes / DTC) median churn; voluntary 2.87%, involuntary 1.38%. |
| churn_rate | media | global | **4.14%** | 2026 | [Recurly Research - Churn Rate Benchmarks](https://recurly.com/research/churn-rate-benchmarks/) | Digital media & entertainment median churn; voluntary 2.55%, involuntary 1.59%. |

</details>

## Cases by category

Each case states what was tested, what the source says happened, only the numbers printed in the source, and a one-line lesson. `channel` lists the channels the write-up credits.

### Consumer App (15)

- **Daily Horoscope – localized paywalls by country** (2026) · channels: app_store, paywall_experiment · [source](https://superwall.com/case-studies/daily-horoscope)  
  *Tested:* Country- and language-specific paywall designs and pricing versus one generic global paywall  
  *What happened:* Using Superwall's audience builder to segment by language and country, Daily Horoscope replaced a generic text-intro paywall with localized variants. Trial starts rose 183% versus the generic control; the baseline trial start rate was described as low but not quantified.  
  *Numbers:* trial_start_lift = 183 %  
  *Lesson:* Localizing paywall design and pricing per country nearly tripled trial starts versus a one-size-fits-all paywall.

- **Mojo – removing AI credit packs from the subscription paywall** (2026) · channels: app_store, paywall_experiment · [source](https://superwall.com/case-studies/mojo)  
  *Tested:* A/B test hiding one-off AI credit packs from the initial paywall so only subscriptions were shown  
  *What happened:* In mid-January 2026 Mojo (AI video reels editor) tested subscriptions-only versus subscriptions plus credit packs with identical pricing and copy. New subscription revenue rose 14% from more users choosing subscriptions and higher ARPPU, with no significant increase in paywall drop-off or AI costs; results were clear within a week.  
  *Numbers:* new_subscription_revenue_lift = 14 %  
  *Lesson:* Low-commitment consumable options on the same paywall diverted high-value users; removing them raised subscription revenue 14%.

- **Infinity Technologies Battery Charging Animation app (TikTok)** (2025 · region: indonesia) · channels: tiktok, influencer · [source](https://ads.tiktok.com/business/en/inspiration/infinity-technologies-case-study)  
  *Tested:* Value-based optimisation at launch plus TikTok Creative Challenge creator UGC reused as ads, measured via Adjust  
  *What happened:* The Vietnam-based developer used VBO to target likely purchasers in Indonesia and other SEA markets, sourced creator videos through TikTok Creative Challenge briefs and reused that UGC in ads. TikTok reports ROAS 46% above target, CVR 6.3x benchmark, 8% CTR and a lower (unquantified) CPI.  
  *Numbers:* roas_vs_target = 46 %; cvr_vs_benchmark = 6.3 ratio; ctr = 8 %  
  *Lesson:* Creator-made UGC recycled into value-optimised ads delivered above-target ROAS for a utility app in Indonesia.

- **Solo iOS app – $1,400 in first 90 days** (2025) · channels: app_store, apple_search_ads, reddit, twitter · [source](https://hackernoon.com/lessons-from-my-first-profitable-ios-app-%241400-in-90-days)  
  *Tested:* Pre-launch validation via Google Trends/Reddit/App Store reviews, then ASO on title/keywords, $5/day Apple Search Ads, and sharing insights (not links) on Twitter and Reddit  
  *What happened:* Lin Wang's first iOS app saw almost no downloads in its first weeks. After focusing on App Store Optimization, a $5/day Apple Search Ads budget, and insight-driven posts on Twitter and Reddit, the app reached $1,400 in revenue after 90 days. The author advises planning monetization from day one and favoring subscriptions over ads.  
  *Numbers:* revenue_90_days_usd = 1400 usd; apple_search_ads_daily_budget_usd = 5 usd  
  *Lesson:* For a first indie app, downloads only arrived after deliberate ASO and a tiny Search Ads budget; launch alone produced almost nothing.

- **Adam Lyttle apps – free growth tactics to 30K downloads/month** (2024) · channels: tiktok, reddit, product_hunt, app_store, quora, twitter · [source](https://adamlyttleapps.substack.com/p/free-growth-hacks-to-boost-your-app)  
  *Tested:* Daily self-made short videos (Pokémon card scanner app), Reddit content reposting, ASO on low-competition keywords, Quora answers, build-in-public, App Store feature submissions  
  *What happened:* Indie developer Adam Lyttle reports growing an app from 1,000 to 30,000 downloads a month using only free tactics. He describes TikTok's automatic ~200-viewer reach per video (about 2 downloads per video at a 1% rate), a Reddit GIF-repost approach that reached the front page but risked being found out, Product Hunt results as 'meh', and Quora answers for an intermittent fasting app that generate ongoing search-driven downloads.  
  *Numbers:* downloads_per_month_before = 1000 count; downloads_per_month_after = 30000 count; tiktok_initial_reach_per_video = 200 count  
  *Lesson:* Compounding many small free channels (daily short video, ASO, Q&A content) took an indie app from 1K to 30K monthly downloads; Product Hunt contributed little.

- **Five Minute Journal onboarding redesign (Applica / RevenueCat)** (2024) · channels: onboarding · [source](https://www.revenuecat.com/blog/growth/five-minute-journal-onboarding-redesign-arpu)  
  *Tested:* Rebuilding onboarding around Jobs-to-be-Done segments, benefit-led screens and early testimonials  
  *What happened:* The journaling app's onboarding was redesigned to personalise content per user segment and lead with benefits and social proof. ARPU rose about 20% (p = 0.04), trial starts rose about 10% and trial conversions about 14%.  
  *Numbers:* arpu_lift = 20 %; trial_start_lift = 10 %; trial_conversion_lift = 14 %  
  *Lesson:* Segment-aware, benefit-focused onboarding lifted monetisation, not just activation.

- **Goibibo multi-event bidding App campaign (Google)** (2024 · region: india) · channels: google_ads · [source](https://business.google.com/in/think/marketing-strategies/india-app-marketing-strategy/)  
  *Tested:* Google App campaign optimised for three funnel events simultaneously to reach customers spending over Rs 3,500  
  *What happened:* Goibibo moved from single-event to multi-event bidding across the funnel. Google's Nov 2024 article reports the campaign scaled and outperformed legacy campaigns within two weeks, with CPI down almost 50% and cost per customer improved 34%.  
  *Numbers:* cpi_change = -50 %; cost_per_customer_improvement = 34 %; high_value_customer_threshold_inr = 3500 inr  
  *Lesson:* Bidding on several funnel events at once lowered both CPI and cost per paying customer for an Indian travel app (platform-reported).

- **HabitKit – indie habit tracker 2024 year in review** (2024) · channels: youtube, app_store, podcast, billboard, threads · [source](https://sebastianroehl.substack.com/p/2024-my-indie-app-business-year-in)  
  *Tested:* Pricing experiments; a Times Square billboard (RevenueCat contest); earned feature on MKBHD's The Studio channel; building in public  
  *What happened:* Sebastian Röhl's HabitKit and sibling apps reached $10,000 MRR in 2024, with MRR flat mid-year and recovering in H2. The June Times Square billboard was described as not a big success for downloads or revenue, while an unsolicited December MKBHD feature produced a large download/revenue spike and his best month ever. A companion RevenueCat write-up notes the launch earned roughly $150 on day one and the big growth came months later when the app began ranking for 'habit tracker' in several App Store regions.  
  *Numbers:* mrr_usd = 10000 usd; launch_day_revenue_usd = 150 usd; social_followers = 14000 count; newsletter_subscribers = 400 count  
  *Lesson:* For an indie habit app, an earned YouTube creator feature outperformed a Times Square billboard, and App Store keyword ranking mattered more than launch day.

- **PhonePe Indus Appstore launch** (2024 · region: india) · channels: offline, app_store, partnership · [source](https://www.outlookbusiness.com/news/phonepes-indus-appstore-crosses-1-million-installations-within-a-month)  
  *Tested:* Launching a localised Android app store with OEM pre-installs, zero commission on in-app billing and short-video app discovery  
  *What happened:* Indus Appstore launched in Feb 2024 with pre-install deals with Nokia and Lava and a target of 250-300M pre-installed devices by year-end. Outlook Business reported over 1M installs within a month, with 45% of users from Tier 2 cities, and 200,000+ apps across 45 categories.  
  *Numbers:* installs_first_month = 1000000 count; share_users_tier2_cities = 45 %; apps_listed = 200000 count; preinstall_target_devices = 250000000 count  
  *Lesson:* OEM pre-installation plus local-language positioning pulled a large Tier-2 share in the first month of an Indian app-store launch.

- **1000 Pound Club Hacker News launch (failed)** (2023) · channels: hacker_news · [source](https://www.indiehackers.com/post/results-from-launching-on-hackernews-71f8a450fe)  
  *Tested:* Following the advice to have 5 friends upvote within the first hour of an HN post, some using newly created accounts  
  *What happened:* The post never ranked despite more upvotes than neighbors; a friend's comment was removed by a moderator and the founder believes it was flagged as a voting ring. About 5 people viewed the landing page, 0 signed up, and Hotjar showed ~1-second visits.  
  *Numbers:* visitors = 5 count; signups = 0 count  
  *Lesson:* Coordinated upvotes from new accounts appear to get HN posts flagged, producing worse results than no upvotes at all.

- **Rootd, FitnessAI and Mojo paywall placement and pricing-frame tests (RevenueCat)** (2023) · channels: paywall, onboarding · [source](https://www.revenuecat.com/blog/growth/paywall-tests-grow-app-revenue)  
  *Tested:* FitnessAI moved the paywall before onboarding and added a video; Rootd moved its paywall to the start of onboarding; Mojo defaulted to the yearly plan and framed annual price as monthly  
  *What happened:* FitnessAI's change raised paywall views 50% and doubled install-to-trial conversions with unchanged trial-to-paid, doubling revenue. Rootd (panic-attack app, 2020) moved its paywall to the start of onboarding and reported 5x revenue with almost no negative feedback. Mojo's yearly-default and monthly-framing test raised yearly subscription take-up 15-20% with a minor rise in cancellations.  
  *Numbers:* paywall_views_lift_fitnessai = 50 %; install_to_trial_multiple_fitnessai = 2 x; revenue_multiple_rootd = 5 x; yearly_plan_takeup_lift_mojo_low = 15 %; yearly_plan_takeup_lift_mojo_high = 20 %  
  *Lesson:* Showing the paywall earlier and defaulting to annual with monthly-equivalent framing increased trials and annual take-up.

- **Apna deep linking and attribution (Branch)** (2022 · region: india) · channels: instagram, facebook, youtube, twitter, push, referral, web_to_app · [source](https://www.branch.io/resources/case-study/apna-drives-73-increase-in-new-users-using-branch/)  
  *Tested:* Deep-linking organic social, push and in-app referrals to in-app content, plus MMP attribution and affiliate fraud rules  
  *What happened:* Apna (26M users, 70+ cities) routed users from Instagram, Facebook, YouTube Community, Twitter, push and referrals straight to relevant jobs whether or not the app was installed, and used Branch for paid attribution and fraud blocking. Branch reports a 73% increase in new users and 4.7x growth in app engagement rate comparing Q1-Q3 2022 with Q1-Q3 2021.  
  *Numbers:* new_users_uplift_yoy = 73 %; engagement_rate_growth = 4.7 ratio; users = 26000000 count; monthly_job_applications = 9000000 count  
  *Lesson:* Removing friction between social/referral links and in-app content was credited with a large YoY new-user gain for a jobs app (vendor-reported).

- **ProjectionLab Product Hunt launch** (2022) · channels: product_hunt · [source](https://projectionlab.com/blog/product-hunt-launch)  
  *Tested:* Indie financial-planning simulator launching on Product Hunt  
  *What happened:* Won #1 Product of the Day with 375 upvotes, which produced 1,202 page visits and 33 new subscribers according to the founder's after-action report.  
  *Numbers:* upvotes = 375 count; visitors = 1202 count; new_subscribers = 33 count  
  *Lesson:* A #1 of the day finish translated into only ~1,200 visits and 33 subscribers for a niche consumer product.

- **Moonly – trial on annual plan only** (2021) · channels: app_store, paid_ads, push, paywall_experiment · [source](https://adapty.io/case-studies/moonly/)  
  *Tested:* Weekly experimentation program (ad creatives, channels, screenshots, onboarding, paywalls, push timing); adding a free trial only to the annual plan on the post-onboarding paywall  
  *What happened:* Moonly, a lifestyle/lunar app launched March 2020 and self-funded by the founder selling her apartment, integrated Adapty shortly after launch and reached $2.45M ARR in 2021. Its post-onboarding paywall drives about 80% of subscriptions; raising prices lowered conversion, but adding a trial to the annual plan only raised paywall conversion 39%, ARPPU 5%, and revenue per 100 installs 47%.  
  *Numbers:* arr_usd = 2450000 usd; paywall_conversion_lift = 39 %; arppu_lift = 5 %; revenue_per_100_installs_lift = 47 %; share_of_subs_from_first_paywall = 80 %  
  *Lesson:* Attaching a trial to the annual plan alone shifted mix toward annual and lifted revenue per install 47%, whereas raising prices hurt conversion.

- **ALTBalaji install-to-first-view journey (WebEngage)** (2018 · region: india) · channels: push, email · [source](https://webengage.com/?p=9747)  
  *Tested:* Time-delayed push (then email fallback) after app install/upgrade promoting the flagship show, measured against a control group  
  *What happened:* ALTBalaji built a WebEngage Journey that waited minutes to hours after install or upgrade for a video play, then pushed the flagship show and fell back to email after a day if push was unreachable. Compared with January, the February journey showed D1 retention up 30%, D3 up 51%, D6 up 77%, D7 up 75% (month over month) and a 9.51% uplift in video plays versus control.  
  *Numbers:* retention_d7_improvement_mom = 75 %; retention_d1_improvement_mom = 30 %; retention_d3_improvement_mom = 51 %; conversion_uplift_vs_control = 9.51 %  
  *Lesson:* A single well-timed post-install push with email fallback moved early retention for an Indian OTT app.

### Saas (14)

- **Adyogi WhatsApp marketing messages placement (Meta)** (2026 · region: india) · channels: whatsapp, facebook_ads, instagram · [source](https://whatsappbusiness.com/resources/success-stories/adyogi/)  
  *Tested:* Adding WhatsApp marketing messages (via Ads Manager, Advantage+ placements) as a placement alongside Facebook/Instagram ads for opted-in D2C customer bases  
  *What happened:* The Indian agency built a repeatable onboarding process so its 250+ retail/D2C clients could message opted-in WhatsApp audiences from the same campaigns. Meta reports advertisers sending WhatsApp marketing messages grew 3x over six months, the feature rolled out across 55 accounts, and one ethnic-apparel client saw higher cost efficiency at comparable ROAS (self-reported).  
  *Numbers:* advertisers_using_whatsapp_growth_6m = 3 ratio; advertiser_accounts_launched = 55 count; agency_clients = 250 count  
  *Lesson:* Treating WhatsApp as an ad placement to reach opted-in buyers gave D2C brands an alternative to saturated retargeting (platform-reported).

- **BrandingStudio.ai Product Hunt launch** (2026) · channels: product_hunt, paid_social · [source](https://www.indiehackers.com/post/400-signups-from-product-hunt-1-paying-customer-what-4-days-taught-me-about-launch-vs-traction-7c0aacf745)  
  *Tested:* Solo founder with no PH network launching a $237 one-time AI branding product on Product Hunt, plus $140 LinkedIn ads  
  *What happened:* Peaked #3 and ended #6 of the day with 168 upvotes. Four days later: 400+ signups, 360 brands created, 98% activation, but a single paying customer ($237), a 0.25% conversion rate. Serving 400 free users cost about $20 in AI API spend.  
  *Numbers:* upvotes = 168 count; signups = 400 count; activation_rate = 98 %; paying_customers = 1 count; revenue_usd = 237 usd; conversion_rate = 0.25 %; ai_cost_usd = 20 usd; linkedin_ad_spend_usd = 140 usd  
  *Lesson:* PH traffic activated heavily but did not pay for a higher-ticket product; the founder attributes it to curious rather than buying visitors.

- **Supademo first 100 customers from Reddit** (2026) · channels: reddit, community, product_hunt · [source](https://supademo.com/blog/reddit-first-100-customers)  
  *Tested:* Value-first Reddit offer posts (free interactive demos built for commenters' products) in r/SaaS, r/startups, r/Entrepreneur and r/indiehackers after karma warm-up, with results posted publicly in-thread  
  *What happened:* The founder reports the first 100 customers came from Reddit at no cost, one post drew 11,000+ views in a day and hundreds of signups, and the same offer worked on Indie Hackers and Product Hunt. He credits these early users for reaching ~$1M ARR in 11 months. Self-reported.  
  *Numbers:* post_views_one_day = 11000 count; customers_from_reddit = 100 count; arr_usd = 1000000 usd  
  *Lesson:* Offering free work in-thread and posting results publicly (never in DMs) converted lurkers; links were withheld until asked to avoid bans.

- **Newsletter sponsorship program ($2,000 across 20+ newsletters)** (2024) · channels: email · [source](https://www.indiehackers.com/post/ive-spent-2-000-sponsoring-newsletters-and-here-s-what-i-ve-learned-so-far-085a751fc4)  
  *Tested:* Buying 20+ newsletter ad placements over 3 months, selecting on clicks per ad slot rather than subscriber counts, negotiating prices and tracking with UTMs  
  *What happened:* The founder reports 40+ paid customers from the program; best placement delivered 150 clicks at $0.52 per click. 60% of partnerships were negotiated down 30-50%, and one good sponsorship led to 2-3 free features in other newsletters.  
  *Numbers:* spend_usd = 2000 usd; sponsorships = 20 count; paid_customers = 40 count; best_cpc_usd = 0.52 usd; best_clicks = 150 count  
  *Lesson:* Clicks on the specific ad slot, not subscriber counts, predicted results; negotiating and multi-issue packages cut costs by up to half.

- **PostHog onboarding email flow iterations** (2024) · channels: email · [source](https://posthog.com/blog/how-we-built-email-onboarding)  
  *Tested:* Seven versions of an onboarding email sequence: role-based personalisation, founder-sent emails, hedgehog art vs screenshots, ICP filtering, product-intent paths  
  *What happened:* PostHog published per-version metrics: v3.0 had 56% open / 7.4% CTR / 3% conversion; a personalised role email hit 68% open and 16% CTR; later simplified versions ran 50-52% open, 2.4-4% CTR, with unsubscribes falling to 0.3% when about half the emails came from a founder's address. Subject-line and body copy tests showed no noticeable impact, and a founder-targeted startup email was removed for cannibalising revenue.  
  *Numbers:* open_rate_personalized_role_email = 68 %; ctr_personalized_role_email = 16 %; open_rate_v3 = 56 %; ctr_v3 = 7.4 %; unsubscribe_rate_v6 = 0.3 %  
  *Lesson:* Role-based personalisation and personal-sender emails moved engagement; copy and subject-line tweaks did not.

- **Quicklist.ing Indie Hackers newsletter sponsorship** (2024) · channels: email · [source](https://www.indiehackers.com/post/i-tried-sponsoring-the-indie-hacker-newsletter-did-it-pay-off-0ef4eda9df)  
  *Tested:* Paying $1,000 for a slot in the Indie Hackers newsletter (70,000 subscribers, 35% open rate, 1% click rate) one week after launching, needing ~5 sales to break even  
  *What happened:* The ad ran on a Saturday and produced only 2 sales and about 30-40 signups by Monday, against a site baseline of 12-15% visitor-to-signup and ~5% signup-to-paid. The founder noted weekend timing and a possible delayed tail.  
  *Numbers:* spend_usd = 1000 usd; sales = 2 count; signups = 40 count; newsletter_subscribers = 70000 count; first_week_revenue_usd = 3000 usd  
  *Lesson:* A large general-audience newsletter slot did not break even; weekend send timing was blamed and the founder shifted to other channels.

- **Saner.ai Product Hunt launch** (2024) · channels: product_hunt · [source](https://www.indiehackers.com/post/so-i-guess-the-product-hunt-launch-is-still-worth-it-heres-why-and-how-b4757a04ab)  
  *Tested:* First-time founder launching a productivity app on Product Hunt after ~3 weeks of part-time prep and early outreach to supporters  
  *What happened:* Won Product of the Day. Traffic reached 5k unique visitors and the launch generated more than 1,000 signups. The founder credits fit with PH's indie-hacker/founder audience.  
  *Numbers:* visitors = 5000 count; signups = 1000 count  
  *Lesson:* Product Hunt still produces large signup volumes when the product serves the founder/indie audience that dominates the platform.

- **SlotSwap Reddit waitlist launch** (2024) · channels: reddit, twitter · [source](https://www.indiehackers.com/post/how-i-launched-on-reddit-and-got-over-50-signups-65875db3c6)  
  *Tested:* Launching a newsletter-swap platform waitlist in r/substack with an off-the-cuff post leaning on the founder's own newsletter credibility, followed by a thank-you post  
  *What happened:* After ~30 signups from Twitter DMs, the first Reddit post produced 17 comments and ~35 waitlist signups in 24 hours; a follow-up post days later added ~15 more, for 50+ signups from about 20 minutes of writing with no community backlash.  
  *Numbers:* waitlist_signups = 50 count; signups_first_24h = 35 count; comments = 17 count  
  *Lesson:* Picking a tightly related, engaged subreddit and writing unpolished posts yielded cheap waitlist signups; a follow-up update post captured a second wave.

- **MySignature AppSumo Select lifetime deal** (2023) · channels: marketplace, facebook, reddit, paid_search, email · [source](https://mysignature.io/blog/appsumo-launch/)  
  *Tested:* 6-week AppSumo Select lifetime deal (plus a 1-week phase 2 six months later) with a public roadmap, review automation and Google Ads to defend brand searches  
  *What happened:* Ranked #3 product of the week, sold 2,622 deals for $138,000 gross, of which MySignature kept $46,026 (~30%). Generated 93 reviews (avg 4.08), 1,280+ support tickets and 240+ questions. Unclear tier descriptions caused negative reviews and an estimated 20-30% lost sales; the AppSumo page also outranked the brand for its own keywords.  
  *Numbers:* sales = 2622 count; gross_revenue_usd = 138000 usd; net_revenue_usd = 46026 usd; reviews = 93 count; avg_rating = 4.08 stars; support_tickets = 1280 count  
  *Lesson:* Lifetime-deal volume came at a ~70% platform cut, heavy support load and brand-search cannibalization; unclear plan tiers were the costliest mistake.

- **Tally 2.0 Product Hunt launch** (2023) · channels: product_hunt, twitter, email · [source](https://blog.tally.so/product-hunt-launch-results/)  
  *Tested:* Relaunching a mature form builder (Tally 2.0 redesign) on Product Hunt, promoted via newsletter and social, using a reusable launch checklist  
  *What happened:* Launched Sept 19, 2023 on a day where three products each passed 1,000 upvotes; Tally finished #1 Product of the Day, Week and Month and later won a Golden Kitty (best bootstrapped). Launch day brought 9.8K homepage visitors and 766 new free users; the next day set a record of 785 new users. Weekly signups rose from ~2,300 to ~4,400 in the two weeks after launch.  
  *Numbers:* visitors_launch_day = 9800 count; signups_launch_day = 766 count; signups_day_after = 785 count; product_hunt_referral_uniques = 3900 count; weekly_signups_before = 2300 count; weekly_signups_after = 4400 count  
  *Lesson:* A well-prepared relaunch of an established product can roughly double weekly signups for weeks, with most PH-referred traffic concentrated on launch day.

- **Stagetimer programmatic SEO** (2022) · channels: seo · [source](https://www.embarque.io/case-studies/significantly-growing-the-organic-traffic-of-a-saas-from-scratch)  
  *Tested:* Founder-built programmatic timer pages (up to ~3,000 indexable pages) plus agency-written landing pages and blog posts for a countdown-timer SaaS  
  *What happened:* Starting early 2022 from 40-50 monthly visitors, organic traffic rose to ~2,700/month by Sept-Oct 2022 and over 8,838/month by February 2023; programmatic pages began ranking between July and September 2022, taking about 3 months each on average. Revenue and signup gains are described but not quantified. Agency-authored case study.  
  *Numbers:* monthly_visitors_before = 50 count; monthly_visitors_after = 8838 count; programmatic_pages = 3000 count; months_to_rank = 3 months  
  *Lesson:* Programmatic pages around a keyword template took ~3 months to rank but moved a near-zero-traffic SaaS to thousands of monthly organic visitors.

- **Vidds Product Hunt launch** (2021) · channels: product_hunt, email, linkedin, twitter · [source](https://www.indiehackers.com/post/how-we-got-150-signups-on-our-web-app-and-our-first-100-of-revenue-67692b2c37)  
  *Tested:* Two-person video tool team launching on a competitive Tuesday with a personal talk-to-camera video, mockups, a 50% PH coupon, an email drip and ~25 confirmed early supporters  
  *What happened:* Finished #4 Product of the Day, which led to 150 signups over the following week and 2 subscription purchases totalling $127.80 against a goal of 100 upvotes and a handful of signups.  
  *Numbers:* product_hunt_rank = 4 rank; signups = 150 count; paying_customers = 2 count; revenue_usd = 127.8 usd  
  *Lesson:* Heavy preparation got a top-4 finish, but it converted to ~150 signups and two paying users, roughly a 1.3% signup-to-paid rate.

- **Plausible Analytics HN-driven growth (July 2020)** (2020) · channels: hacker_news, seo, twitter · [source](https://plausible.io/blog/july-2020-recap)  
  *Tested:* Content marketing where a co-founder's article reached the Hacker News front page, rather than a product post  
  *What happened:* July 2020 saw 69k visitors (+151%) with a record 35,665-visitor day, 617 new trial signups (+59% vs June, beating the prior best of 515) and MRR of $2,750 (+46%) with 400+ paying subscribers. The GitHub repo hit 2,000 stars.  
  *Numbers:* visitors = 69000 count; trial_signups = 617 count; mrr_usd = 2750 usd; paying_subscribers = 400 count; github_stars = 2000 count  
  *Lesson:* Article-driven HN traffic converted to record trials; referrer quality differed sharply (Reddit 79% bounce vs Google 39%).

- **You Need A Wiki Product Hunt launch** (2019) · channels: product_hunt, twitter · [source](https://www.indiehackers.com/post/0370ba5360)  
  *Tested:* Saturday launch of a Google Docs wiki tool, hunted the day before, with friends' upvotes and a tweet to @producthunt  
  *What happened:* Won Product of the Day with 1,087 upvotes and 969 signups. Sessions were 3,030 on launch day and 8,934 over 7 days; page views 5,553 and 22,350 respectively, plus 116 Drift chat messages. All users were in trial at posting time.  
  *Numbers:* upvotes = 1087 count; signups = 969 count; sessions_launch_day = 3030 count; sessions_7_days = 8934 count; page_views_7_days = 22350 count  
  *Lesson:* A weekend launch with pre-seeded votes reached #1 and nearly 1,000 signups; paid conversion was not yet known.

### Devtool (11)

- **Open SaaS (Wasp) Product Hunt launch** (2025) · channels: product_hunt, hacker_news, reddit, community · [source](https://docs.opensaas.sh/blog/2025-05-07-you-should-still-launch-your-product-on-ph/)  
  *Tested:* Sixth PH launch by the Wasp team, this time for a free open-source SaaS starter, cross-posted to HN, Reddit and dev.to  
  *What happened:* Finished #7 of the day with about 400 upvotes after ~100 in the hidden first four hours; PH's 500K-subscriber newsletter added only ~20 upvotes. Hacker News front page for about half a day sent more than 3x PH's traffic, and the repo trended globally on GitHub with over 2.5k stars a week after launch.  
  *Numbers:* upvotes = 400 count; product_hunt_rank = 7 rank; github_stars_week_1 = 2500 count; hn_vs_ph_traffic_multiple = 3 x  
  *Lesson:* For a developer product, Hacker News and GitHub trending outperformed Product Hunt; PH's main value was a dated excuse to promote everywhere at once.

- **Corbado Product Hunt launch** (2024) · channels: product_hunt, linkedin, twitter, community · [source](https://www.corbado.com/blog/launch-developer-tool-product-hunt)  
  *Tested:* Passkey dev tool launched on a Thursday with an established hunter, a non-technical explainer video and ~4 weeks of prep tracked in Notion  
  *What happened:* Launched Jan 25, 2024; finished #4 Product of the Day and #1 Developer Tool of the Week. Website traffic was 2x normal and daily signups 4x usual on launch day and the days after. Homepage listing was delayed ~2 hours by PH review; feedback was mostly supportive rather than deep.  
  *Numbers:* product_hunt_rank = 4 rank; traffic_multiple = 2 x; daily_signups_multiple = 4 x  
  *Lesson:* Most PH users spend minutes on a product, too little for a dev tool, so the page had to serve a non-technical majority and developer minority at once.

- **Glasskube Launch Week #2** (2024) · channels: hacker_news, twitter, linkedin, community · [source](https://dev.to/glasskube/glasskube-launch-week-2-the-wrap-up-39gp)  
  *Tested:* Five-day themed launch week (GitOps readiness) combining daily social posts, a Show HN, a DevHunt listing and an in-person SF meetup  
  *What happened:* Placed 3rd on DevHunt and stayed on the Show HN page for two days. Website views grew over 100%, real user installations rose over 10%, and the week produced 20+ cloud signups, 2 new contributors and 100+ meetup signups.  
  *Numbers:* website_views_growth = 100 %; installs_growth = 10 %; cloud_signups = 20 count; new_contributors = 2 count; devhunt_impressions = 2400 count; meetup_signups = 100 count  
  *Lesson:* Smaller developer-focused launch platforms gave fewer upvotes but users closer to the target persona.

- **Onlook Studio Hacker News launch** (2024) · channels: hacker_news · [source](https://onlook.substack.com/p/july-2024-update)  
  *Tested:* Two-person team pivoting from a designer Chrome extension to an open-source developer desktop app and launching on Hacker News  
  *What happened:* Reached #1 on Hacker News with 300+ upvotes and 90+ comments, driving over 50,000 visits to launch assets. The repo reached 1.4k+ stars, 60 forks and 200+ clones; almost all users came from external channels.  
  *Numbers:* hn_upvotes = 300 count; hn_comments = 90 count; visits = 50000 count; github_stars = 1400 count; forks = 60 count  
  *Lesson:* Open-sourcing and an HN launch generated strong developer inbound, but minimal analytics at launch left the team unable to measure retention.

- **Permit.io Product Hunt launch** (2023) · channels: product_hunt, twitter, youtube, instagram, community · [source](https://permit.io/blog/producthunt-howto)  
  *Tested:* Launch built around a developer-advocate-narrated video, a supporter launch kit, a dedicated landing page and an $800 paid push (Twitter Space, Instagram, YouTube) timed in two waves across time zones  
  *What happened:* #1 Product of the Day on Sept 13, 2023 with 300+ upvotes in the first two hours and ~4x the votes of prior competitor launches. Launch video passed 100K YouTube views, the landing page got 1.3K hits in 24 hours, signups spiked 500% (about double a normal feature launch) and seven sales meetings were booked within 24 hours versus ~1 usually.  
  *Numbers:* upvotes_first_2h = 300 count; video_views = 100000 count; landing_page_hits_24h = 1300 count; signup_spike = 500 %; sales_meetings_24h = 7 count; spend_usd = 800 usd  
  *Lesson:* The first two hours decided ranking; warm outreach to people who already knew the product worked while cold outreach performed poorly.

- **Developer micro-SaaS paid ads test ($100 per channel)** (2022) · channels: paid_search, reddit, facebook, quora, bing · [source](https://www.indiehackers.com/post/i-tried-every-possible-paid-advertising-method-for-a-business-d4cfd278f4)  
  *Tested:* Spending ~$100 each on Google, Bing, Reddit, Meta and Quora ads for an unnamed developer micro-SaaS targeting US/EU, to compare signup yield  
  *What happened:* Google Ads: 174 clicks, ~28 signups. Bing: ~$75 spent, 96 clicks, 21 signups. Reddit: 208 clicks, 39 signups but mostly low-CPC countries. Meta: 240 clicks, 44 signups. Quora: 149 clicks, 23 signups. All users were still in 30-day trials; dev ad-blockers limited tracking.  
  *Numbers:* budget_per_channel_usd = 100 usd; google_clicks = 174 count; google_signups = 28 count; reddit_clicks = 208 count; reddit_signups = 39 count; meta_clicks = 240 count; meta_signups = 44 count; quora_clicks = 149 count; quora_signups = 23 count; bing_clicks = 96 count; bing_signups = 21 count  
  *Lesson:* Small budgets bought 20-45 trial signups per channel, but Reddit's cheap clicks skewed to low-value geographies and paid conversion was unknown at posting.

- **Infisical open-source launch (3,000 stars in 2 months)** (2022) · channels: reddit, hacker_news, email, twitter, community · [source](https://infisical.com/blog/how-we-got-3000-github-stars-in-2-months)  
  *Tested:* Multi-platform organic launch of an open-source secrets manager: same-day Reddit posts, newsletters, Show HN and international forums, all pointing traffic at GitHub  
  *What happened:* Open-sourced Nov 21, 2022 from a ~90-star repo. Reddit posts in r/opensource, r/github and r/node landed well (helped by a co-founder's 2,000+ karma); TLDR and Console.dev newsletters picked it up; a Show HN reached #3 and was still producing activity 3+ weeks later; a Vercel CEO tweet and a Korean forum added waves. Roughly 3,000 stars within two months, with no cold outreach.  
  *Numbers:* github_stars_2_months = 3000 count; hn_rank = 3 rank; starting_stars = 90 count  
  *Lesson:* Launching everywhere at once and routing to GitHub compounded via newsletters and word of mouth; pre-built platform karma was cited as a prerequisite.

- **Wasp Beta launch week** (2022) · channels: hacker_news, product_hunt, reddit, twitter, community · [source](https://wasp.sh/blog/2023/01/31/wasp-beta-launch-review)  
  *Tested:* Supabase-style launch week (one feature per day plus a closing hackathon) for an open-source web framework, with a 20-day Twitter countdown beforehand  
  *What happened:* Launched Nov 27, 2022 over Thanksgiving weekend. Last day of the week added 190 GitHub stars, 108 new projects and 83 new users; Hacker News brought the most traffic by far and Product Hunt gave #5 of the day with ~250 upvotes. Weekly active users roughly doubled from ~10 to ~20 after the launch.  
  *Numbers:* github_stars_added = 190 count; new_projects = 108 count; new_users = 83 count; product_hunt_upvotes = 250 count; product_hunt_rank = 5 rank  
  *Lesson:* Launching over a holiday weekend depressed traffic and moderator attention; a public launch date still made the team far more productive.

- **PostHog Hacker News launch** (2020) · channels: hacker_news, community · [source](https://posthog.com/blog/after-the-hn-launch)  
  *Tested:* Open-source product analytics launch on Hacker News with ~$1K spent to seed early GitHub stars, targeting 500/700/1,000 star goals  
  *What happened:* Five days after posting, the repo passed 800 stars and over 200 people had signed up, with several businesses integrating it into daily work. The HN showing pushed the repo onto GitHub trending, bringing more users.  
  *Numbers:* github_stars_day_5 = 800 count; signups = 200 count; marketing_spend_usd = 1000 usd  
  *Lesson:* Early publicity is a temporary spike; accurate repo tagging mattered for trending, and the real test is retention of launch-day users.

- **Supabase alpha launch** (2020) · channels: hacker_news, community · [source](https://supabase.com/blog/alpha-launch-postmortem)  
  *Tested:* Alpha launch of an open-source Firebase alternative via Hacker News on a single docker-compose server  
  *What happened:* Hit the top of HN on May 27, 2020 and stayed on the front page over 24 hours. About 30,000 new visitors in the week (peak ~15,000 day one), 1,400+ signups in 7 days (~600 on day one), and the main repo jumped from ~300 to 1,300 stars overnight. Hit DigitalOcean's 400-server and Cloudflare's 1,000-subdomain limits, causing ~3 hours of downtime.  
  *Numbers:* visitors_week = 30000 count; signups_week = 1400 count; github_stars_after = 1300 count; downtime_hours = 3 hours  
  *Lesson:* A front-page HN launch doubles as a load test; vendor resource limits and single-admin accounts caused the only outages.

- **Streamlit open-source launch** (2019) · channels: community, twitter, hacker_news · [source](https://discuss.streamlit.io/t/open-source-launch-recap/750)  
  *Tested:* Launching an open-source Python framework with a long-form post on Towards Data Science plus community forum and GitHub  
  *What happened:* In the first three weeks the launch post had 127,000+ views and 9,000+ claps; 11,000+ users created 20,000+ apps, the repo passed 3,285 stars and was #1 trending on GitHub for two days. The team received 496 questions/bugs/feature requests and 14 pull requests and admitted falling behind on replies.  
  *Numbers:* launch_post_views = 127000 count; users = 11000 count; apps_created = 20000 count; github_stars = 3285 count; pull_requests = 14 count  
  *Lesson:* Demand outran support capacity; the team had to rebuild its response process for forum and GitHub issues after launch.

### Edtech (11)

- **IMSE email segmentation and automation (Mailchimp)** (2026) · channels: email · [source](https://mailchimp.com/case-studies/imse-segmentation-strategy/)  
  *Tested:* List cleaning, segmentation by course completion/job title/location, first-name personalisation, automation flows for two flagship curricula  
  *What happened:* The Institute for Multi-Sensory Education, a literacy training organisation with 505,000 educator contacts, ran a re-engagement campaign, removed unresponsive contacts and built automated post-training flows. Open rates peaked at 42.8% (1.7x improvement, above a 35.64% education benchmark), click-through rates grew 3x to a 6.9% peak, and delivery rate reached 99.6%.  
  *Numbers:* open_rate = 42.8 %; open_rate_lift_multiple = 1.7 x; click_through_rate = 6.9 %; ctr_lift_multiple = 3 x; list_size = 505000 count  
  *Lesson:* Cleaning a large educator list and segmenting by role and training completion tripled clicks.

- **Preu AI (Chile) – annual plan anchoring** (2026 · region: latam) · channels: app_store, paywall_experiment · [source](https://superwall.com/case-studies/preu-ai)  
  *Tested:* Adding a heavily discounted annual plan (priced at 60% of monthly) next to the existing single monthly plan  
  *What happened:* Chilean exam-prep app Preu AI tested a control with one monthly subscription and a 'Try Free' button against a variant adding an annual plan priced at 60% of the monthly rate. Proceeds per user increased 80% and trial conversion rate increased 22%.  
  *Numbers:* proceeds_per_user_lift = 80 %; trial_conversion_lift = 22 %  
  *Lesson:* Anchoring a monthly plan against a discounted annual plan raised both trial conversion and proceeds per user.

- **TimesPro (India) mobile course landing page redesigns (via ConvertPolo)** (2026 · region: india) · channels: landing_page · [source](https://wingify.com/success-stories/timespro-convertpolo-apply-now-cta-clicks/)  
  *Tested:* Three mobile A/B tests on IIM/IIT program pages surfacing key program details and accreditation earlier, with sticky navigation  
  *What happened:* ConvertPolo ran three mobile landing page experiments for TimesPro (Times of India Group) using VWO. Experiment 1 raised Apply Now clicks 144.95% and brochure downloads 239%; experiment 3 raised form submissions 34.87%. The case study reports overall Apply Now clicks up 180% and brochure downloads up 301%; test durations are not stated.  
  *Numbers:* apply_now_cta_clicks_lift = 180 %; brochure_download_clicks_lift = 301 %; form_submissions_lift_exp3 = 34.87 %; page_engagement_lift = 142 %  
  *Lesson:* On mobile program pages, moving credibility signals and key details above the fold produced large CTA and form lifts.

- **Driver's-license exam-prep app paywall redesign (RevenueCat case studies)** (2025) · channels: paywall · [source](https://www.revenuecat.com/blog/growth/paywall-redesigns-case-studies)  
  *Tested:* Replacing a long-form onboarding paywall with a short version adding a trial toggle, real App Store reviews and the weekly plan on the main screen  
  *What happened:* In a RevenueCat roundup of four unnamed apps, an exam-prep app's shorter paywall lifted ARPU 17.02%. Sibling cases in the same post: a crypto tracker's redesign raised paywall conversion from 2.7% to 3.24%, a party game's short paywall lifted install-to-trial 31% and revenue 64%, and a diet app's lifted install-to-trial 72%. The post notes Apple began rejecting trial toggles in February 2026.  
  *Numbers:* arpu_lift = 17.02 %; paywall_conversion_before_crypto_app = 2.7 %; paywall_conversion_after_crypto_app = 3.24 %  
  *Lesson:* Shorter paywalls with social proof and a visible trial option beat long-form paywalls across categories including exam prep.

- **UNext / Online Manipal (India) online-degree page first-fold test** (2025 · region: india) · channels: landing_page · [source](https://wingify.com/success-stories/unext/)  
  *Tested:* 12-day mobile A/B test adding a new hero image, highlighted grade, rearranged form fields, finance/scholarship options and closing date  
  *What happened:* UNext (Bengaluru), handling marketing for Online Manipal, ran the test in VWO. Enroll Now clicks rose 11.68% and successful form submissions rose 9.34%. The page notes users were interested in enrolling but overlooked finance options and the closing date.  
  *Numbers:* cta_clicks_lift = 11.68 %; form_submissions_lift = 9.34 %; test_duration = 12 days  
  *Lesson:* Surfacing financing options and a deadline in the first fold lifted both clicks and completed enquiries.

- **Duolingo leaderboards, streaks and push-notification growth program** (2023) · channels: product, push_notifications, referral · [source](https://www.lennysnewsletter.com/p/how-duolingo-reignited-user-growth)  
  *Tested:* A series of product bets (gamified moves counter, Uber-style referral, leagues leaderboards, streak-saver notifications) prioritised via a retention-driven growth model  
  *What happened:* Former CPO Jorge Mazal describes how DAU was growing single digits YoY in mid-2018; a growth model showed current-user retention had ~5x the DAU impact of the next lever. A moves-counter test was neutral and a referral offering a free month of Plus lifted new users only 3%, while leaderboards lifted learning time 17% and tripled highly engaged learners. Streak-saver notifications and later streak features contributed to DAU growing 4.5x over four years.  
  *Numbers:* dau_growth_multiple = 4.5 x; learning_time_lift = 17 %; new_users_lift_referral = 3 %; current_user_retention_lift = 21 %; best_user_daily_churn_reduction = 40 %  
  *Lesson:* Retention of current users moved DAU far more than referral or acquisition tweaks; competitive social features and streak protection drove the big wins.

- **Codecademy pricing, checkout and trial-model testing program** (2020) · channels: pricing_page, checkout, free_trial · [source](https://speero.com/post/how-codecademy-saw-5x-growth-with-strategic-testing)  
  *Tested:* Widening monthly/annual price gap by country, reordering checkout plan cards with dollar savings, staged free-trial models including credit-card-upfront  
  *What happened:* Daniel Layfield describes Codecademy's growth testing: reordering plan cards, highlighting savings and showing annual savings in dollars rather than percentages produced a 28% lift in annual Pro plans plus a small overall conversion gain. A credit-card-upfront trial for new users missed targets after two months, but a later variant with a different paywall beat control (no figure given).  
  *Numbers:* annual_plan_lift = 28 %  
  *Lesson:* Presenting annual savings as dollar amounts and leading with the preferred plan lifted annual subscriptions; trial models needed several iterations before winning.

- **Penn Foster dedicated paid-search landing page** (2020) · channels: landing_page, paid_search · [source](https://wingify.com/success-stories/penn-foster/)  
  *Tested:* Sending brand paid-search traffic to a consolidated, fast mobile landing page with two CTAs instead of the homepage  
  *What happened:* Penn Foster, a for-profit online college, tested a lighter dedicated page with a high mobile speed score against the homepage. Over 24 days and roughly 35,000 visitors split evenly, the variation produced a 202% jump in click-to-lead conversion rate.  
  *Numbers:* conversion_rate_lift = 202 %; test_duration = 24 days; visitors = 35000 count  
  *Lesson:* Routing branded paid traffic to a focused, fast landing page rather than the homepage tripled lead conversion.

- **UTS Open postgraduate online learning marketplace launch (Optimizely)** (2020) · channels: website, ecommerce · [source](https://www.optimizely.com/field-notes/customer-stories/university-of-technology-sydney/)  
  *Tested:* Launching a commerce-driven course marketplace with Optimizely Commerce as source of truth for products and pricing  
  *What happened:* University of Technology Sydney launched UTS Open in December 2019. The case study reports a 45% fall in drop-off rate, and that in January 2020 returning visitors and associated revenue were up 400% versus the launch month. No experiment design is described (vendor write-up).  
  *Numbers:* drop_off_rate_reduction = 45 %; returning_visitors_and_revenue_lift_vs_launch_month = 400 %  
  *Lesson:* Treating short courses as ecommerce products with a unified catalogue reduced drop-off and drove repeat purchase, per the vendor write-up.

- **AssessmentDay co-branded landing page content removal test** (2019) · channels: landing_page · [source](https://wingify.com/success-stories/assessmentday/)  
  *Tested:* Split-URL test removing the FAQ section, the screenshots section, or both from a practice-aptitude-test sales page  
  *What happened:* UK test-prep provider AssessmentDay tested three variations against the original. Removing FAQs lifted sales 62%, removing screenshots lifted them 56%, but removing both dropped sales 3%. Test duration is not stated; the page's screenshots are from 2019.  
  *Numbers:* sales_lift_remove_faq = 62 %; sales_lift_remove_screenshots = 56 %; sales_change_remove_both = -3 %  
  *Lesson:* Trimming one distracting section helped, but stripping too much content hurt; test removals individually.

- **Compare Courses (Australia) Bachelor of Accounting enquiry page** (2019) · channels: landing_page · [source](https://wingify.com/success-stories/compare-courses/)  
  *Tested:* Split-URL test redesigning the enquiry form, moving it above the fold and adding a testimonial  
  *What happened:* Australian course search site Compare Courses moved the Send Enquiry form above the fold with social proof. The Ask an Expert CTA lead rate rose 159.52% and Request Brochure rose 13.3%, but the redesigned Send Enquiry form itself performed slightly worse (9.71% original vs 9.52% variation).  
  *Numbers:* ask_expert_lead_rate_lift = 159.52 %; brochure_request_lift = 13.3 %; send_enquiry_conversion_original = 9.71 %; send_enquiry_conversion_variation = 9.52 %  
  *Lesson:* A layout change can lift secondary CTAs while hurting the primary one; track every conversion goal on the page.

### Fintech (8)

- **Groww weighted multi-event bidding (Google)** (2024 · region: india) · channels: google_ads · [source](https://business.google.com/in/think/marketing-strategies/india-app-marketing-strategy/)  
  *Tested:* Full-funnel event optimisation with different weightings per event and bids tuned toward highest-LTV customers  
  *What happened:* Groww optimised for all events from sign-up to first investment, weighted near-conversion events higher and bid toward high-LTV users. Google reports 55% more transacting shoppers and acquisition/sign-up costs cut 14%.  
  *Numbers:* transacting_users_uplift = 55 %; acquisition_cost_change = -14 %  
  *Lesson:* Weighting deeper events in App campaigns grew transacting investors in a saturated Indian finance category (platform-reported).

- **easypaisa Smart+ vs manual campaigns (TikTok)** (2024 · region: pakistan) · channels: tiktok · [source](https://ads.tiktok.com/business/en/inspiration/easypaisa_smart+_app_campaign)  
  *Tested:* Head-to-head test of TikTok's automated Smart+ app campaigns against manually managed campaigns at identical bids and budgets, optimising for wallet activations  
  *What happened:* easypaisa ran Smart+ and manual campaigns in parallel with the same bid and budget. TikTok reports the Smart+ arm delivered 50% more conversions, 30% lower cost per conversion, 24% more impressions and 15% lower CPM. Test duration and sample size are not stated.  
  *Numbers:* conversions_uplift = 50 %; cost_per_conversion_change = -30 %; impressions_uplift = 24 %; cpm_change = -15 %  
  *Lesson:* Automated campaign setup beat manual management on both volume and cost for a Pakistani mobile-wallet activation objective.

- **Lucky One Card cashback launch (Egypt)** (2022 · region: egypt) · channels: offline, partnership, in_app · [source](https://ventureburn.com/2022/11/egypts-lucky-fintech-strikes-it-lucky-with-10m-users/)  
  *Tested:* Launching a cashback card (up to 5%) on top of a credit/offers platform with a 40,000-merchant network  
  *What happened:* Lucky launched the Lucky One Card in June with up to 5% cashback and expanded merchant partnerships. The company announced passing 10M registered users, with 1M new customers onboarded in September alone, alongside a $25M Series A and expansion into Morocco. Marketing channels are not described.  
  *Numbers:* registered_users = 10000000 count; new_users_single_month = 1000000 count; merchants = 40000 count; cashback_max = 5 %; funding_usd = 25000000 usd  
  *Lesson:* A high-cashback card attached to an existing merchant network coincided with Lucky's fastest monthly user growth (company-reported).

- **Ualá full-funnel TikTok campaign (Winclap)** (2022 · region: latam) · channels: tiktok, influencer · [source](https://ads.tiktok.com/business/en-US/inspiration/uala-708)  
  *Tested:* Reach & Frequency In-Feed branding in new territories plus performance campaigns optimised to install, registration and first deposit, with creator-led creatives  
  *What happened:* Winclap analysed TikTok trends and creators, produced multiple creator videos and ran broad/lookalike audiences in Argentina and Mexico. TikTok reports installs up 62% in the quarter, registrations up 57%, CAC cut 50% in Argentina and 4x in Mexico in the first three weeks, with 2.7M reached by the R&F campaign.  
  *Numbers:* installs_uplift_quarter = 62 %; registrations_uplift = 57 %; cac_reduction_argentina = 50 %; cac_reduction_mexico = 4 ratio; reach = 2700000 count  
  *Lesson:* Pairing awareness buys in new markets with deep-funnel (first-deposit) optimisation cut fintech CAC sharply in LATAM.

- **Yalla Card & Super App launch (PaySky, Egypt)** (2022 · region: egypt) · channels: offline, partnership, in_app · [source](https://www.zawya.com/en/press-release/companies-news/yalla-card-and-super-app-reaches-a-new-milestone-in-a-record-breaking-time-djtib8zo)  
  *Tested:* Launching a Visa-backed card plus super app with card pickup at Egypt Post branches and bundled money-transfer/bill-pay features  
  *What happened:* PaySky launched Yalla in Feb 2022 with card access through the app or Egypt Post offices in partnership with Visa and ENPO. The company's press release says it passed 1M users in under eight months with 1.5M+ transactions worth over EGP 2B; Cairo was about 30% of users. Marketing tactics are not described.  
  *Numbers:* users_under_8_months = 1000000 count; transactions = 1500000 count; transaction_value_egp = 2000000000 egp; share_users_cairo = 30 %  
  *Lesson:* Physical distribution through a national post network supported a fintech reaching 1M users in under a year in Egypt (company press release).

- **Leading Indian private-sector bank app engagement (CleverTap)** (2021 · region: india) · channels: in_app, push, app_store · [source](https://clevertap.com/case-study/bank-boosted-business-10-engagement-analytics/)  
  *Tested:* In-app interstitial/footer notifications, a Next-Best-Offer model and multi-day drop-off journeys inside the bank's revamped mobile app  
  *What happened:* After a one-year POC the bank (unnamed in body text) ran 49 Journey campaigns, 22 drop-off campaigns and an NBO model promoting 22 products to 7M+ users. CleverTap reports a 10-12% increase in business, in-app campaigns growing from 1% to 25% of app/web traffic, and 4x more users creating a fixed deposit from a 15-min/day-3/day-7 drop-off sequence.  
  *Numbers:* business_uplift = 10 %; in_app_traffic_uplift = 2400 %; in_app_share_of_traffic_after = 25 %; fixed_deposit_creators_uplift = 4 ratio; users_reached = 7000000 count; journey_campaigns = 49 count  
  *Lesson:* Timed drop-off nudges (15 min, day 3, day 7) and product recommendations inside the app out-performed generic push for a bank's cross-sell.

- **Nubank member-get-member growth** (2021 · region: latam) · channels: referral, community · [source](https://www.aakashg.com/nubank-story/)  
  *Tested:* Mobile-first referral engine built into the app at launch instead of paid marketing, paired with a no-fee credit card  
  *What happened:* Nubank launched its beta a month after a $15M Series A (Aug 2014) and reportedly did not spend that round on marketing; in-app referrals are credited with 80-90% of clients arriving organically. It had 350,000 card clients 16 months after launch, a blended CAC under $5, and grew from 3.7M to 48.1M customers over three years per the article (secondary analysis by Aakash Gupta).  
  *Numbers:* cac_usd = 5 usd; customers_16_months = 350000 count; customers_latest = 48100000 count; customer_cagr_3y = 100 %; payback_months = 11 count  
  *Lesson:* A product with an obvious price advantage (no annual fee) plus an in-app referral loop kept CAC under $5 in Brazil.

- **Bibit registration optimisation (TikTok)** (2020 · region: indonesia) · channels: tiktok · [source](https://ads.tiktok.com/business/en-US/inspiration/bibit-69)  
  *Tested:* One month of CPI-optimised install ads followed by a switch to Registration Optimization bidding for a mutual-fund app  
  *What happened:* Bibit targeted Gen Z and millennial retail investors, tested CPI campaigns for about a month, then moved to registration-optimised ads over a three-month campaign. TikTok reports registrations up 414% as budget was scaled 460%, with cost per registration down 10.51%.  
  *Numbers:* registrations_uplift = 414 %; budget_increase = 460 %; cost_per_registration_change = -10.51 %  
  *Lesson:* Optimising to the down-funnel registration event rather than installs let an Indonesian investing app scale spend 4.6x while cutting cost per registration.

### Ecommerce (7)

- **DigiHaat (ONDC) lifecycle journeys (CleverTap)** (2026 · region: india) · channels: push, in_app, whatsapp, email, referral · [source](https://clevertap.com/?p=131054)  
  *Tested:* Segmented multi-step journeys (abandoned cart, onboarding, membership renewal) with channel fallback, geo/time personalisation and A/B tests  
  *What happened:* DigiHaat grouped users by purchases, ONDC category codes and intent, then ran ~1,500 campaigns a quarter (1,559 in Q1 2026) across push, in-app, WhatsApp and email with automated fallback. CleverTap reports 47% conversion from abandoned-cart journeys, 25% first-purchase conversion from onboarding, 24% renewal from expiry journeys and a 33% improvement in M3 retention.  
  *Numbers:* abandoned_cart_journey_conversion = 47 %; onboarding_first_purchase_conversion = 25 %; membership_renewal_conversion = 24 %; m3_retention_improvement = 33 %; campaigns_q1_2026 = 1559 count; reachable_users = 460000 count; daily_app_launches = 41800 count  
  *Lesson:* High campaign cadence with channel fallback and intent-based segmentation produced strong journey-level conversion on a government-backed marketplace app (vendor-reported).

- **Kilimall in-app purchase growth (TikTok Kenya)** (2026 · region: kenya) · channels: tiktok · [source](https://expression.africa/tiktok-for-business-turns-one-in-kenya-as-creators-earn-kes-47m/)  
  *Tested:* Smart+ automation, Branded Spark Ads and full-funnel measurement to grow in-app purchases  
  *What happened:* In TikTok for Business's first-year Kenya recap (Feb 2026), Kilimall is reported to have generated more than 152,000 purchases and a 6x increase in sales compared with Q2 after adopting Smart+ automation, Branded Spark Ads and full-funnel measurement. Time period and spend are not given.  
  *Numbers:* purchases = 152000 count; sales_uplift_vs_q2 = 6 ratio  
  *Lesson:* Automated buying plus Spark Ads was credited with a step change in in-app purchases for a Kenyan marketplace (platform-reported).

- **Canifa app conversion programme (CleverTap)** (2024 · region: vietnam) · channels: push, in_app, sms, email · [source](https://clevertap.com/news/press-release/leading-fashion-brand-canifa-achieves-54-higher-app-conversion-rate-with-clevertap/)  
  *Tested:* Unifying customer data and running personalised push/in-app/SMS/email journeys for a Vietnamese fashion retailer with 100+ stores  
  *What happened:* Canifa consolidated siloed data into CleverTap profiles and used push and in-app as the primary channels for timely offers. The Feb 2024 press release reports a 54% higher app conversion rate, 50% MoM conversion growth, and 7% lifts in revenue per user and retention over 60 days.  
  *Numbers:* app_conversion_rate_uplift = 54 %; conversion_rate_uplift_mom = 50 %; revenue_per_user_uplift_60d = 7 %; retention_uplift_60d = 7 %  
  *Lesson:* For an omnichannel fashion brand, push and in-app personalisation drove the conversion lift once data silos were unified (vendor press release).

- **KFC Mexico always-on app sales (TikTok)** (2024 · region: latam) · channels: tiktok · [source](https://ads.tiktok.com/business/es/inspiration/kfc-app-growth)  
  *Tested:* May-Dec 2024 always-on In-Feed, Spark Ads and Interactive Add-Ons with humour creative, interest targeting and retargeting of high-intent users to drive in-app delivery orders  
  *What happened:* KFC Mexico assigned each format a funnel role, targeted food/humour/delivery audiences and continuously reallocated budget. Client internal data reported by TikTok shows a 20% increase in app channel sales, 3x campaign revenue vs prior benchmarks and 4x campaign transactions.  
  *Numbers:* app_sales_uplift = 20 %; campaign_revenue_vs_benchmark = 3 ratio; campaign_transactions_vs_benchmark = 4 ratio  
  *Lesson:* Culturally local, humorous creative in an always-on structure with retargeting lifted app-order revenue for a QSR in Mexico.

- **AB Clothing (Philippines, Shopify) – TikTok Pixel for Shopify campaign** (2021 · region: philippines) · channels: tiktok_ads · [source](https://ads.tiktok.com/business/tr/inspiration/ab-clothing)  
  *Tested:* Installing TikTok Pixel for Shopify (June 2021) and running Conversions-objective ads optimized for Complete Payment with before/after makeover creative  
  *What happened:* AB Clothing swapped the standard pixel for the TikTok Pixel for Shopify to track more funnel events, used Developer Mode and ROAS reports to make fewer but better bid adjustments, and ran makeover-style video ads. TikTok reports the campaign reached 1.1M users with a 2.5x ROAS and a 56% 2-second view rate.  
  *Numbers:* reach = 1100000 count; roas = 2.5 ratio; two_second_view_rate = 56 %  
  *Lesson:* Richer event tracking via the Shopify-specific pixel let a small apparel store optimize to purchases and hit 2.5x ROAS on TikTok.

- **Daraz 11.11 'Gyara Gyara' sale 2020 (Pakistan)** (2020 · region: pakistan) · channels: app_store, offline, partnership, in_app · [source](https://www.dawn.com/news/1592130)  
  *Tested:* Flash mechanics (mystery box, 'jhatka' deals), 12 digital-payment partners and brand tie-ups to drive app-led sale traffic  
  *What happened:* Daraz discounted 15M+ products with Rs50 crore of discounts and limited-time deals; the mystery box sold out in 5 seconds and jhatka deals in 11 seconds. Sponsored coverage in Dawn reports 2.5M+ active users in the first 24 hours, 2B+ page views over 7 days, roughly 50% of spend via digital payments and new digital-payment customer acquisition nearly doubling versus the prior 11.11.  
  *Numbers:* active_users_first_24h = 2500000 count; page_views_7_days = 2000000000 count; share_spend_digital_payments = 50 %; payment_partners = 12 count  
  *Lesson:* Scarcity mechanics and payment-partner incentives concentrated demand into the app during a tentpole sale (company-reported, sponsored coverage).

- **Jumia Target CPA Smart Bidding (Google Ads)** (2019 · region: africa) · channels: google_ads · [source](https://group.jumia.com/news/jumia-harnesses-machine-learning-to-optimise-bids-while-boosting-conversions)  
  *Tested:* Switching many-account manual bidding to Target CPA Smart Bidding across the pan-African marketplace  
  *What happened:* Jumia moved its Google Ads accounts to Target CPA so bids were automated to a cost target, with the first four to six weeks described as rocky. The Nov 2019 case reports conversion rate up 48%, conversions up 52%, CPA down 2.4% and search impression share up 33% YoY.  
  *Numbers:* conversion_rate_uplift = 48 %; conversions_uplift = 52 %; cpa_change = -2.4 %; search_impression_share_uplift_yoy = 33 %  
  *Lesson:* Automated bidding scaled conversions across many African country accounts at roughly flat CPA after a learning period.

### Health App (6)

- **Ahead (emotional-intelligence app) – paid 30-day trial extension** (2026) · channels: app_store, paywall_experiment · [source](https://superwall.com/case-studies/ahead-app)  
  *Tested:* Secondary prompt offering a 30-day trial for a small fee versus the standard free 7-day trial  
  *What happened:* Ahead found users considered 7 days too short to commit to a personalized plan. In a Superwall multi-page test, the variant that let users extend to a 30-day trial for a small extra cost produced a 7% increase in conversion to trial, while proceeds per user remained strong, indicating the extension did not cannibalize paid subscriptions.  
  *Numbers:* trial_conversion_lift = 7 %; control_trial_days = 7 days; variant_trial_days = 30 days  
  *Lesson:* Letting users opt into a longer, paid trial raised trial starts 7% without lowering proceeds per user.

- **Cal AI – 123 paywall experiments in 18 months** (2026) · channels: app_store, paywall_experiment, web_checkout, push, email · [source](https://superwall.com/case-studies/cal-ai)  
  *Tested:* High-volume paywall experimentation across 46 trigger points: onboarding, exit-intent, feature gates, win-back, upsells, pricing matrix, Stripe web checkout  
  *What happened:* Cal AI joined Superwall in March 2024 just before launch. It reports $28K revenue in month 1, $115K in month 2, $1M MRR within 6 months, and 15M+ downloads with roughly $40M annual revenue within 18 months. It ran 123 iOS A/B experiments (424 variants, ~5 per month, 61 on the onboarding paywall); monthly revenue grew 3x+ in 10 months and trial-to-paid improved 31% relative over 12 months. 87% of new users see a paywall, 57% of viewers start a transaction and 63% of those complete.  
  *Numbers:* month1_revenue_usd = 28000 usd; month2_revenue_usd = 115000 usd; ab_experiments = 123 count; variants_tested = 424 count; monthly_revenue_multiple_10mo = 3 ratio; trial_to_paid_relative_lift = 31 %; users_seeing_paywall = 87 %; paywall_view_to_transaction_start = 57 %; transaction_completion = 63 %; downloads = 15000000 count  
  *Lesson:* Roughly five paywall experiments a month across many trigger points compounded into a 3x monthly revenue increase and a 31% trial-to-paid gain (vendor case study).

- **Cal AI – influencer retainer machine (TikTok/Instagram)** (2025) · channels: tiktok, instagram, influencer · [source](https://getlatka.com/interviews/cal-ai-zach-yadegari-2025)  
  *Tested:* Scaling organic-style influencer marketing with ~250 creators on monthly retainers posting on TikTok and Instagram  
  *What happened:* Cal AI, a photo calorie-counting app launched May 2024 by teenage founders, hit its first $1M in sales by September 4, 2024. By May 2025 the founder reported 20,000-30,000 new downloads per day, 20-25% of users starting a paid plan or 3-day trial in their first session, mid-six-figure monthly influencer spend across ~250 retained creators, and a run rate above $35M. TechCrunch (March 2025) reported founder claims of 5M+ downloads in eight months, which it could not verify.  
  *Numbers:* influencers_on_retainer = 250 count; daily_downloads_low = 20000 count; daily_downloads_high = 30000 count; first_session_trial_or_paid_rate_low = 20 %; first_session_trial_or_paid_rate_high = 25 %; annual_run_rate_usd = 35000000 usd; annual_plan_price_usd = 29 usd  
  *Lesson:* A bootstrapped app scaled to a $35M run rate in a year primarily by paying hundreds of creators monthly retainers for TikTok/Instagram posts (founder-reported figures).

- **Philips Pregnancy+ – high-cadence paywall experimentation** (2025) · channels: app_store, paywall_experiment, seasonal_promo · [source](https://adapty.io/case-studies/pregnancy-plus/)  
  *Tested:* Raising paywall test cadence from ~1 per quarter to 3+ per month (42 variants in 12 months); free trial vs discounted intro price; trial-timeline visual; day-5 promo; seasonal campaigns  
  *What happened:* Pregnancy+ (80M downloads, freemium, 10+ localized markets) adopted Adapty in November 2024. Over 12 months weekly subscription revenue grew 300% and premium conversion rose from 0.4% to about 2% in top markets. A free-trial variant beat a discounted intro price by 140% revenue, a transparent trial timeline added 27%, and a day-5 promotion added 17%; BFCM campaign revenue rose 113% vs prior period.  
  *Numbers:* weekly_subscription_revenue_growth = 300 %; premium_conversion_before = 0.4 %; premium_conversion_after = 2 %; paywall_variants_tested = 42 count; free_trial_vs_discount_revenue_lift = 140 %; trial_timeline_revenue_lift = 27 %; day5_promo_revenue_lift = 17 %; bfcm_revenue_lift = 113 %; retention_second_renewal = 65 %  
  *Lesson:* Moving from quarterly to multi-weekly paywall tests compounded into a 5x conversion rate and 300% weekly revenue growth; free trials outperformed intro discounts.

- **Deep Sleep Sounds (Slumber Group) – agency-run subscription experiments** (2023) · channels: app_store, paywall_experiment · [source](https://www.revenuecat.com/blog/company/applica-revenuecat-case-study)  
  *Tested:* Continuous A/B experimentation on subscription funnel run by growth agency Applica on top of RevenueCat analytics  
  *What happened:* Sleep app Deep Sleep Sounds added RevenueCat alongside its in-house subscription handling to get normalized data and easier experimentation. Applica's experiment program lifted the app's ARPU by 52%, and Slumber estimates over 300 hours saved across analytics and product teams. Applica says some clients run up to five experiments per month.  
  *Numbers:* arpu_lift = 52 %; hours_saved = 300 hours  
  *Lesson:* Making subscription data measurable enabled a steady experiment cadence that raised ARPU 52% for a sleep app.

- **FoodNoms 2 – major relaunch with press, beta and Product Hunt** (2023) · channels: pr, app_store, product_hunt, beta, social · [source](https://foodnoms.com/blog/foodnoms-2-launch-retrospective)  
  *Tested:* Free major update launched with 100+ beta testers, press kit and PR consultant, Apple feature request, Product Hunt and social posts; measuring first-30-day funnel vs original launch  
  *What happened:* Indie nutrition tracker FoodNoms 2 launched January 2023 after ~2.5 years of work. The paid PR consultant approach flopped, but MacStories and 9to5Mac coverage plus App Store features outside the US drove results: 11,799 new users in 30 days vs 5,658 for v1, activation 48.9% vs 36.5%, day-1 retention 21% vs 12.7%, +841 net new active subscribers, $19,915 new-subscriber revenue before Apple's 15% fee, and MRR +$1,864. The app passed 3K subscribers and $80K ARR; the author called the financial return poor relative to the time invested.  
  *Numbers:* new_users_30d = 11799 count; new_users_30d_v1 = 5658 count; activation_rate = 48.9 %; day1_retention = 21 %; net_new_subscribers_30d = 841 count; new_subscriber_revenue_30d_usd = 19915 usd; mrr_change_usd = 1864 usd; arr_usd = 80000 usd  
  *Lesson:* Enthusiast-press reviews and App Store features doubled 30-day new users and improved activation and retention, while a paid PR consultant delivered nothing.

### Course (5)

- **Impromptu Speakers Academy cohort 3 launch (Preston Chin)** (2025) · channels: email, tiktok, instagram, community · [source](https://prestonchin.substack.com/p/my-failed-cohort-launch-made-7773)  
  *Tested:* Five-week waitlist, 14-day free preview course, 2-3 emails/day open cart, 53 personalised videos, welcome event for early buyers  
  *What happened:* A live 5-week impromptu-speaking cohort priced $797-$997 targeted 30 students and enrolled 9, generating $7,773 revenue and $5,023 net profit on 80 hours of work. The 442-person waitlist converted at 2%; general-list open rate fell to 28% (usually 40%) with ~30 unsubscribes per email during the heavy send cadence, and 53 personalised videos produced about 3 sales.  
  *Numbers:* revenue_usd = 7773 usd; students = 9 count; waitlist_signups = 442 count; waitlist_conversion_rate = 2 %; net_profit_usd = 5023 usd; general_list_open_rate_during_launch = 28 %  
  *Lesson:* Over-emailing the general list and automated waitlist inflation hurt more than price; reaching the right people mattered more than the offer.

- **Colin and Samir creator-business cohort course (Kajabi)** (2024) · channels: youtube, community · [source](https://digiday.com/future-of-tv/future-of-tv-briefing-a-qa-with-colin-and-samirs-samir-chaudry-on-the-state-of-the-creator-economy/)  
  *Tested:* YouTube creators launching a four-week cohort course for creators who already run a business, after 18 months of curriculum development  
  *What happened:* Per a Digiday Q&A two weeks into the first cohort (January 2024), 70 people signed up and the cohort brought in just shy of $100,000. The creators said they had not yet broken even on the investment, which included a dedicated hire and an outside agency.  
  *Numbers:* students = 70 count; development_time = 18 months  
  *Lesson:* Even a large YouTube audience did not make a first cohort immediately profitable once production and staffing costs were counted.

- **Flutter Animations Masterclass launch (Code With Andrea)** (2021) · channels: email, reddit, twitter, youtube, landing_page · [source](https://codewithandrea.com/meta/flutter-animations-course-retro/)  
  *Tested:* Validation via Reddit post and subscriber survey, waitlist landing page, tiered pre-sale pricing ($30/$35/$45/$59) staggered over weeks  
  *What happened:* Andrea Bizzotto validated with a 1,158-response survey (92.5% interested), built a 1,200-person waitlist, and ran a staggered pre-sale on Teachable. The course earned $13,371 from May to July 2021; 8% of the waitlist bought in the first 24 hours and about 90% of sales came from email. Only 0.2% of site visitors reached a checkout page, and the author calculated ~$36/hour against 355 hours invested.  
  *Numbers:* revenue_usd = 13371 usd; waitlist_size = 1200 count; waitlist_conversion_first_24h = 8 %; email_share_of_sales = 90 %; site_visitor_to_checkout_rate = 0.2 %; hours_invested = 355 hours  
  *Lesson:* Email drove nearly all sales while Twitter/YouTube built audience but converted poorly; spreading the launch across pricing tiers kept momentum.

- **WAIM Unlimited fall enrollment (Wandering Aimfully)** (2021) · channels: podcast, email, affiliate · [source](https://podcast.wanderingaimfully.com/episodes/106-recapping-our-best-launch-yet-214-000-in-total-revenue)  
  *Tested:* Podcast-promoted enrollment window for a coaching/membership program with affiliate partners  
  *What happened:* The hosts recapped their fall 2021 enrollment period for WAIM Unlimited, which brought in about $214,000 and 107 new members, with what they describe as minimal costs. They say it hit a revenue target they had chased for three years.  
  *Numbers:* revenue_usd = 214000 usd; new_members = 107 count  
  *Lesson:* A recurring enrollment window promoted through an owned podcast and affiliates produced the creators' largest launch.

- **Blogging for Devs email course and paid community launch (Monica Lent)** (2020) · channels: twitter, email, community · [source](https://kit.com/resources/blog/blogging-for-devs-case-study)  
  *Tested:* Free 7-day email course launched with a tweet, then a free beta for 100 engaged subscribers, application waitlist, and a build-in-public Twitter thread before public paid-community launch  
  *What happened:* The email course drew 2,300+ landing page visitors and 1,048 subscribers in two weeks (44% conversion) from a ~9,000-follower Twitter audience, with 70%+ open rates on early emails. The paid community launched publicly in November 2020 and made about $5,000 in its first week and ~$10,000 in six weeks, with $1,300 MRR at launch; up to 72.5% of new paid members were already newsletter subscribers.  
  *Numbers:* signups_first_two_weeks = 1048 count; landing_page_conversion_rate = 44 %; first_week_revenue_usd = 5000 usd; six_week_revenue_usd = 10000 usd; mrr_at_launch_usd = 1300 usd; email_open_rate_first_emails = 70 %  
  *Lesson:* A free email course warmed an audience that then supplied most paid community members; beta-then-waitlist staging de-risked the paid launch.

### Fitness App (5)

- **Stompers (walking app) – single-page vs multi-page paywall** (2026) · channels: app_store, paywall_experiment · [source](https://superwall.com/case-studies/stompers)  
  *Tested:* A/B test of a single-page paywall (value + annual/monthly prices on one screen) against a multi-screen flow with trial reminder before pricing  
  *What happened:* Gamified walking app Stompers compared $9.99/mo against $79.99/yr and $49.99/yr options in two layouts. The single-page paywall increased overall conversion rate by over 16% and drove more annual free trials, raising ARPU; the multi-page version skewed users toward monthly trials.  
  *Numbers:* conversion_rate_lift = 16 %; monthly_price_usd = 9.99 usd; annual_price_usd = 79.99 usd  
  *Lesson:* A single-screen paywall showing all plans beat a multi-step flow on conversion and shifted mix toward annual trials.

- **Zumba app – 7-day vs 14-day trial test and app-to-web checkout** (2024) · channels: app_store, web_checkout, paywall_experiment · [source](https://www.revenuecat.com/customers/stepping-up-growth-how-zumba-boosted-conversion-by-8-with-revenuecat)  
  *Tested:* A/B test shortening free trial from 14 to 7 days; routing iOS users to hosted web checkout via RevenueCat Web Purchase Button after Apple's May 2024 rule change  
  *What happened:* Zumba launched its fitness app in 2024 and ran trial-length experiments through RevenueCat. The 7-day trial produced an 8% lift in install-to-paid conversion, and web-originated subscribers showed higher retention and roughly 15% better LTV than expected, driven by lower store fees and higher trial-to-paid on annual web plans. Regional pricing/messaging was used for India and Latin America.  
  *Numbers:* install_to_paid_lift = 8 %; ltv_lift_web_checkout = 15 %; trial_length_before = 14 days; trial_length_after = 7 days  
  *Lesson:* A shorter trial raised install-to-paid conversion, and web checkout improved LTV despite the expected dip in upfront conversion.

- **Runna – from PDF plans to App Store, 30x subscription growth** (2023) · channels: app_store, apple_search_ads, push, email · [source](https://revenuecat.com/customers/how-revenuecat-helped-runna-hit-the-ground-running-to-reach-30x-year-over-year-growth/)  
  *Tested:* MVP as emailed PDF plans, then in-app purchases via RevenueCat after App Store rejection; Apple Search Ads keyword optimization; calendar-connection retention KPI  
  *What happened:* Runna's first app linked to web payments and was rejected by Apple; switching to RevenueCat IAP got approval within a week and the app launched March 2022. Subscriptions grew 30x between December 2022 and December 2023. Cutting spend in high-cost markets lowered CAC 8%, optimizing Apple Search Ads on top-converting keywords raised US trial conversion 56%, and retention analysis around calendar connections contributed a 5.7% trial-conversion lift.  
  *Numbers:* subscription_growth_multiple_dec22_dec23 = 30 ratio; cac_reduction = 8 %; us_trial_conversion_lift_asa = 56 %; trial_conversion_lift_retention_work = 5.7 %; funding_gbp = 8000000 gbp  
  *Lesson:* Native IAP unblocked the App Store launch, and keyword-level Search Ads optimization plus retention-driven onboarding tweaks lifted trial conversion materially.

- **Sweatcoin – micro-creator Spark Ads for installs (UK/US)** (2022) · channels: tiktok_ads, influencer · [source](https://ads.tiktok.com/business/zh/inspiration/sweatcoin-994)  
  *Tested:* Boosting micro-creator native-style videos as Spark Ads with an app-install objective via agency Kurve, then expanding globally  
  *What happened:* Step-rewards app Sweatcoin ran creator-made Spark Ads on TikTok targeting UK and US installs across iOS and Android. TikTok reports CPI down 53% (agency cites ~70% in some cases), click-to-conversion up 26% comparing January vs June 2022, more than half a million downloads, and 31M+ reach.  
  *Numbers:* cpi_reduction = 53 %; click_to_conversion_lift = 26 %; downloads = 500000 count; reach = 31000000 count  
  *Lesson:* Native-looking micro-creator videos run as Spark Ads cut CPI by half for a fitness app's install campaigns.

- **Slopes – App of the Day featuring numbers** (2018) · channels: app_store · [source](https://blog.curtisherbert.com/slopes-diaries-23-featuring-numbers/)  
  *Tested:* Impact of two App Store Today-tab features (a winter sports list, then App of the Day on Jan 6, 2018) on a ski/snowboard tracking app  
  *What happened:* Curtis Herbert published download data: the list feature produced about 2.8k downloads on day one with ~50% daily drop-off versus a ~2k/day seasonal baseline, and also ranked the story first for ski/snowboard searches. App of the Day brought about 19k downloads on day one (#3 in Sports), an estimated 35k extra downloads over the week, roughly a 25% boost on the prior season's 120k. Only ~5.5k of the 19k day-one installs launched the app, and revenue was expected to lag until users reached a resort.  
  *Numbers:* app_of_the_day_day1_downloads = 19000 count; estimated_extra_downloads_week = 35000 count; list_feature_day1_downloads = 2800 count; day1_installs_that_opened_app = 5500 count; prior_season_downloads = 120000 count  
  *Lesson:* App of the Day drove ~10x a normal day's installs but under a third of day-one installers opened the app, so featuring spikes convert poorly to immediate revenue.

### Newsletter (5)

- **Escape the Cubicle Substack growth to 10,000** (2025) · channels: substack_notes, seo, community · [source](https://escapethecubicle.substack.com/p/10000-subscribers-in-less-than-a)  
  *Tested:* Daily Substack Notes activity, engaging other writers for recommendations, and SEO-oriented problem-solving posts instead of LinkedIn/Medium/TikTok  
  *What happened:* Wes Pearce grew from zero to 10,000 subscribers in under a year. He reports 30-50% of subscribers came from inside Substack, Notes bringing 10-20 subscribers a day, and the newsletter ranking for 1,200+ keywords, while his 100K+ LinkedIn following contributed little.  
  *Numbers:* subscribers = 10000 count; share_from_substack_internal_low = 30 %; share_from_substack_internal_high = 50 %; daily_subscribers_from_notes_low = 10 count; ranking_keywords = 1200 count  
  *Lesson:* In-platform discovery (Notes, recommendations) outperformed a large external social following for newsletter growth.

- **How to Write for a Living (David McIlroy) 48 to 20,000 subscribers** (2025) · channels: substack_notes, community, email · [source](https://thedavidmcilroy.substack.com/p/how-i-grew-from-48-to-20000-substack)  
  *Tested:* Consistent weekly posting, Substack Notes, networking with other writers, repurposing Medium articles, interviews with fellow writers, a rebrand  
  *What happened:* Starting with 48 imported subscribers in June 2023 and publishing 35 posts by early December, the newsletter reached 500 subscribers after about six months and crossed 20,000 in March 2025 (646 days). Paid subscriber and revenue figures are behind the paywall.  
  *Numbers:* subscribers_start = 48 count; subscribers = 20000 count; days_to_20k = 646 days; posts_first_six_months = 35 count  
  *Lesson:* Growth was slow for six months then compounded; the author attributes it to routine publishing and in-platform networking rather than a single tactic.

- **Changing the Channel (Kirsten Powers) Substack growth** (2024) · channels: substack_recommendations, email, instagram, word_of_mouth · [source](https://kirstenpowers.substack.com/p/what-i-learned-growing-from-zero)  
  *Tested:* Relaunch with Substack recommendations as main driver, long-form essays, free-for-a-week paywall model, explicit 'tap the heart' asks  
  *What happened:* Launched November 2022 with zero subscribers; by April 2023 ~3,000 free and 216 paid; after a September 2023 relaunch, over 10,000 subscribers and 480 paid by about April 2024 (~5% conversion). One viral essay emailed to 3,200 people drew 80,000+ page views and ~2,500 free and 58 paid subscribers. The author says Twitter (~300K) and Instagram (~37K) contributed little.  
  *Numbers:* subscribers = 10000 count; paid_subscribers = 480 count; free_to_paid_conversion = 5 %; viral_essay_page_views = 80000 count; viral_essay_new_free_subscribers = 2500 count  
  *Lesson:* Recommendations from other Substacks and shareable long-form essays beat large legacy social followings as growth channels.

- **ICYMI by Lia Haberman growth to 10K** (2023) · channels: substack_recommendations, press, linkedin, email · [source](https://liahaberman.substack.com/p/how-i-grew-my-newsletter-to-10k-subscribers)  
  *Tested:* Substack recommendations network, breaking-news subject lines, press/podcast appearances, LinkedIn newsletter edition  
  *What happened:* ICYMI grew from 137 subscribers (Jan 2021) to 1,070 (Jan 2022), 4,045 (Jan 2023) and 10,000+ by July 2023. Recommendations from 38 other Substacks produced about 3,000 subscribers (~45% of total from other Substack newsletters); a single recommendation added 329 net subscribers in a day, a breaking-news subject line added ~800 overnight, and a Buffer listing brought 548. A collab newsletter produced no noticeable growth.  
  *Numbers:* subscribers = 10000 count; subscribers_from_recommendations = 3000 count; share_from_other_substacks = 45 %; recommending_newsletters = 38 count; subscribers_from_breaking_news_email = 800 count  
  *Lesson:* Substack recommendations and timely newsy subject lines were the measurable growth drivers; cross-promo collabs and giveaways were not.

- **Lenny's Newsletter paid launch** (2020) · channels: twitter, email, guest_posts · [source](https://on.substack.com/p/how-lenny-rachitsky-earned-65000)  
  *Tested:* Converting a free Substack to paid at $15/month with a 48-hour 33% launch discount, pre-seeded with influential followers  
  *What happened:* Per Substack's write-up of Lenny Rachitsky's talk, he grew to ~15,000 free subscribers via Twitter, guest posts and a mix of weekly posts and one large series (two posts drove ~50% of growth). The paid launch brought ~200 paid subscribers in the first couple of days and ~250 after a reminder, reaching ~500 paid and ~$65K/year before fees.  
  *Numbers:* free_subscribers = 15000 count; paid_subscribers = 500 count; annual_revenue_usd = 65000 usd; price_monthly_usd = 15 usd; launch_discount = 33 %  
  *Lesson:* Roughly half of launch-period paid subscribers came in the first week; discounts, seeding with influencers and a reminder email drove the spike.

### D2C (4)

- **Godrej Aer Pocket brand launch (TikTok Kenya)** (2026 · region: kenya) · channels: tiktok, influencer · [source](https://expression.africa/tiktok-for-business-turns-one-in-kenya-as-creators-earn-kes-47m/)  
  *Tested:* TikTok-first creative with targeted creator collaborations for a consumer-goods launch  
  *What happened:* The same Kenya recap reports Godrej Aer drove more than 10M video views, doubled monthly sales month-on-month and held a 33% market share for Aer Pocket for three months. Figures are TikTok-reported.  
  *Numbers:* video_views = 10000000 count; monthly_sales_growth_mom = 2 ratio; market_share = 33 %  
  *Lesson:* Creator-led TikTok-native creative was tied to sales doubling for a CPG launch in Kenya (platform-reported).

- **Woolah Tea Advantage+ Shopping Campaigns (Meta)** (2026 · region: india) · channels: facebook_ads, instagram · [source](https://indiantelevision.com/mam/meta-showcases-northeast-msmes-using-ai-and-whatsapp-to-fuel-business-growth/)  
  *Tested:* Switching a Northeast-India D2C tea brand's Meta spend to Advantage+ Shopping Campaigns  
  *What happened:* At Meta's World MSME Day event in Guwahati (June 2026), Woolah Tea's founder said the move to Advantage+ Shopping Campaigns produced a more than 600% increase in orders within six months. This is a founder statement reported by the press, with no spend or baseline given.  
  *Numbers:* orders_uplift_6_months = 600 %  
  *Lesson:* A small D2C brand attributed a large order jump to Meta's automated shopping campaigns (founder-reported, no baseline).

- **Tanishq app engagement flows (MoEngage)** (2023 · region: india) · channels: whatsapp, push, in_app, email, onsite_messaging · [source](https://www.moengage.com/casestudy/tanishq-increases-app-retention-rates-using-moengage/)  
  *Tested:* Cross-channel engagement Flows plus on-site messaging lead-gen and AI personalisation during the Akshaya Tritiya sale  
  *What happened:* Tanishq ran MoEngage Flows across WhatsApp, push, in-app and email to lift app stickiness, and used on-site messaging on web/app for lead generation. The vendor page reports a 25% uplift in weekly retention, a 107% rise in click-to-conversion during the Akshaya Tritiya week, and roughly 5,000 leads a month from OSM campaigns.  
  *Numbers:* weekly_retention_uplift = 25 %; click_to_conversion_uplift_sale_week = 107 %; cart_abandonment_campaign_conversion_rate = 3.37 %; osm_leads_per_month = 5000 count; osm_ctr = 7.2 %; osm_form_fill_rate = 5 %  
  *Lesson:* Multi-channel lifecycle flows (WhatsApp+push+in-app+email) moved weekly retention for a jewellery retailer whose app users mirror offline shoppers (vendor-reported).

- **Country Delight lockdown engagement flows (MoEngage)** (2020 · region: india) · channels: push, sms · [source](https://www.moengage.com/casestudy/country-delight-engagement-case-study/)  
  *Tested:* Event-tracked install-to-subscription journeys with push on delivery slots, signup nudges and next-purchase offers during the pandemic surge  
  *What happened:* Country Delight used MoEngage Flows to engage surge traffic at each funnel stage, mainly via push (71% delivery rate) with SMS as backup. The vendor page reports a 2.5x increase in DAU, MAU rising by 5 lakh month-on-month, a 20% conversion-rate improvement and retention of 50% of the existing base. The page is undated; it refers to the pandemic lockdown.  
  *Numbers:* dau_uplift = 2.5 ratio; mau_increase_mom = 500000 count; conversion_rate_uplift = 20 %; existing_customers_retained = 50 %; push_delivery_rate = 71 %  
  *Lesson:* Stage-specific push flows converted a demand spike into subscriptions for a milk-delivery app (vendor-reported, undated page; year inferred from lockdown reference).

### Dtc (4)

- **The Beauty Crop – SMS-led flows and segmentation** (2025) · channels: email, sms, loyalty · [source](https://www.klaviyo.com/uk/customers/case-studies/the-beauty-crop)  
  *Tested:* Consolidating SMS into Klaviyo, making SMS lead in key flows, 14 master segments by skin type/loyalty/discount, and skin-type question in sign-up pop-ups  
  *What happened:* London beauty brand The Beauty Crop had been blasting identical emails and running SMS and loyalty on separate platforms. After moving SMS into Klaviyo, integrating LoyaltyLion, and building nested segments, it reported an 84x YoY increase in flow-generated revenue in Q2 2025, 112% YoY growth in Klaviyo-attributed revenue, with SMS at 44% of Klaviyo revenue and 36% of total revenue.  
  *Numbers:* flow_revenue_yoy_multiple = 84 ratio; klaviyo_attributed_revenue_yoy_growth = 112 %; sms_share_of_klaviyo_revenue = 44 %; sms_share_of_total_revenue = 36 %; master_segments = 14 count  
  *Lesson:* Letting SMS lead in coordinated flows and segmenting by skin type turned flows into a major revenue line within a year.

- **Dermalogica – 82 flows and first SMS program** (2024) · channels: email, sms · [source](https://www.klaviyo.com/sg/customers/case-studies/dermalogica-email-sms)  
  *Tested:* Re-platforming from Mailchimp (one flow) to Klaviyo in 3 months with 82 automated flows, skin-concern education pathways, and launching SMS for product drops and skincare tips  
  *What happened:* Dermalogica switched to Klaviyo in 2020 alongside a Demandware-to-Shopify move. It built 82 live flows (abandoned cart/browse, SKU-specific post-purchase, AI face-mapping) with Recharge and Yotpo integrations, runs consistent A/B tests, and uses SMS for releases and education. It reports an 84.1% increase in SMS revenue per recipient in H1 2024 and a flow unsubscribe rate of 0.27%.  
  *Numbers:* sms_revenue_per_recipient_increase_h1_2024 = 84.1 %; live_flows = 82 count; flow_unsubscribe_rate = 0.27 %  
  *Lesson:* Dozens of concern-specific flows plus educational SMS raised SMS revenue per recipient 84% while keeping unsubscribes under 0.3%.

- **LifeStraw – building email flows from zero on Klaviyo** (2024) · channels: email, sms · [source](https://www.klaviyo.com/customers/case-studies/lifestraw)  
  *Tested:* Migrating from ActiveCampaign (no automations, ~3% of revenue from email) to Klaviyo with welcome, abandonment, post-purchase replacement-filter and back-in-stock flows  
  *What happened:* LifeStraw, a Shopify water-filter brand, had email driving about 3% of ecommerce revenue in 2020 with no automations at all. After migrating to Klaviyo (with a slow sending-domain warm-up) and having an agency build core flows, it beat its 2022 email revenue goal by more than 2x in its first flows quarter (Q4 2022). In H1 2024, 33% of ecommerce revenue was attributed to Klaviyo with a reported 69x ROI.  
  *Numbers:* email_share_of_revenue_before = 3 %; klaviyo_attributed_revenue_share_h1_2024 = 33 %; roi = 69 ratio  
  *Lesson:* Basic lifecycle flows (welcome, abandonment, replenishment) took email from 3% to 33% of ecommerce revenue for a brand that previously sent one email a month.

- **Living Proof – personalized hair-quiz flows** (2019) · channels: email, quiz, social_sampling · [source](https://www.klaviyo.com/customers/case-studies/living-proof-case-study)  
  *Tested:* Replacing mass email blasts with a 9-hair-type quiz, persona segmentation, and behavior-triggered welcome and abandoned-cart flows on Klaviyo (integrated with Salesforce Commerce Cloud)  
  *What happened:* Unilever-owned Living Proof wanted to grow DTC in 2019 but its stack only supported mass blasts. It launched a hair care quiz delivering automated recommendations for 9 hair types, used sample programs and product-launch early access to collect subscriber data, and added triggered flows. In under a year it reported a 514% YoY increase in Q3 owned revenue from email, 21% higher revenue per recipient, and 29% list growth in under two quarters.  
  *Numbers:* q3_email_revenue_yoy_increase = 514 %; revenue_per_recipient_increase = 21 %; list_growth = 29 %  
  *Lesson:* A quiz-based segmentation model plus triggered flows multiplied email revenue roughly 6x within a year.

### Subscription App (3)

- **Unnamed AI photo generator app – automated refund handling** (2024) · channels: app_store · [source](https://adapty.io/case-studies/ai-photo-generator/)  
  *Tested:* Enabling Adapty Refund Saver to auto-submit consumption data to Apple within the 12-hour refund window  
  *What happened:* A leading AI photo generator app was losing significant revenue to App Store refunds handled manually. Within two weeks of enabling Refund Saver its refund rate fell 40%, daily revenue rose by more than $2,500 with no increase in installs, and it reports saving over $75,000 per month.  
  *Numbers:* refund_rate_reduction = 40 %; daily_revenue_increase_usd = 2500 usd; monthly_savings_usd = 75000 usd  
  *Lesson:* Responding to Apple refund requests automatically recovered meaningful revenue without any acquisition change.

- **Wave AI Note Taker – solo founder, always-on paywall tests + Meta ads** (2024) · channels: facebook_ads, app_store, paywall_experiment · [source](https://adapty.io/case-studies/wave/)  
  *Tested:* Continuous paywall A/B testing (always one live test) combined with heavy Meta paid acquisition for a one-person app  
  *What happened:* Josh Mohrer built Wave, an AI audio note-taker, alone; the first concept was coded in one day with ChatGPT help in 2023. Using Adapty's paywall builder and A/B testing with Meta ads for acquisition, the app reached $4M ARR within 8 months and over 55k downloads. The case names paywall A/B testing as the main growth factor.  
  *Numbers:* arr_usd = 4000000 usd; months_to_4m_arr = 8 months; downloads = 55000 count; team_size = 1 count  
  *Lesson:* A solo developer paired paid Meta acquisition with a permanently running paywall test to reach $4M ARR in eight months.

- **Impulse brain training – early SKAN subscription-optimized campaigns** (2021) · channels: tiktok_ads · [source](https://ads.tiktok.com/business/en-US/inspiration/impulse---brain-training-659)  
  *Tested:* Launching SKAdNetwork campaigns on TikTok (from August 2021) with Lowest Cost bidding optimized for subscription events using In-Feed Ads in US/EU  
  *What happened:* Impulse adopted TikTok's SKAN solution at release and optimized toward users likely to subscribe. From August to October 2021 installs rose 741% with CPI down 21%, in-app subscriptions rose 735% with CPA down 21%, install-to-subscription CVR doubled (June-September), and TikTok's share of install traffic grew 60%.  
  *Numbers:* installs_increase = 741 %; cpi_decrease = 21 %; subscriptions_increase = 735 %; cpa_decrease = 21 %; install_to_subscription_cvr_multiple = 2 ratio  
  *Lesson:* Optimizing SKAN campaigns to the subscription event rather than installs scaled volume ~8x while lowering unit costs.

### B2B (2)

- **Aidlab Show HN (second attempt)** (2025) · channels: hacker_news · [source](https://www.indiehackers.com/post/front-page-of-hn-the-full-postmortem-traffic-lessons-surprises-cbe9e0a7f6)  
  *Tested:* Re-doing a failed Show HN five years later with a personal founder story, SDK code examples, a tech narrative and a free-dataset call to action  
  *What happened:* Reached the HN front page. Launch day brought ~468 active users (350 from HN/GitHub), then 100-150/day for three days and a long tail; ~6k page views total, 500+ unique visitors from HN, 2+ minute sessions and ~20% bounce rate. 170+ visitors reached the shop but there were no direct conversions; side effects were 4 inbound inquiries and 8 LinkedIn invites (3 from VCs).  
  *Numbers:* active_users_launch_day = 468 count; page_views = 6000 count; hn_unique_visitors = 500 count; bounce_rate = 20 %; direct_conversions = 0 count; inbound_inquiries = 4 count  
  *Lesson:* A story-plus-code framing got a hardware/SDK company to the HN front page, yielding engaged traffic and B2B inquiries but zero direct sales.

- **Cloutly cold email partnership campaign** (2020) · channels: cold_outreach · [source](https://www.indiehackers.com/post/94-opens-42-replies-how-i-used-cold-email-to-land-20-b2b-partnerships-in-3-months-with-my-exact-templates-e4505f9c89)  
  *Tested:* A four-step personalized cold email sequence to 122 targeted B2B leads for a review-management SaaS  
  *What happened:* The campaign recorded 94% opens and a 42% reply rate over 122 leads, booked 30+ B2B meetings and landed over 20 deals in 3 months; the founder says cold email was the company's most profitable channel since launch.  
  *Numbers:* leads = 122 count; open_rate = 94 %; reply_rate = 42 %; meetings = 30 count; deals = 20 count  
  *Lesson:* A small, hand-personalized list with four touches outperformed scattergun volume; the author recommends partnership framing when LTV is low.

### Gaming (1)

- **VNG Revelation MMORPG SEA launch (TikTok)** (2023 · region: sea) · channels: tiktok, influencer, app_store · [source](https://ads.tiktok.com/business/en/inspiration/vng-revelation)  
  *Tested:* Pre-launch organic TikTok account, App Pre-Registration ads, then CBO install campaigns with local creators per market  
  *What happened:* VNG opened a TikTok account two months before the Feb 2023 launch, ran pre-registration campaigns starting in one market then expanding, and launched with Campaign Budget Optimization using creatives featuring game characters and local creators across six SEA markets. TikTok reports CPI 54% below target and installs 313% above target in Vietnam, and 1.8x the install KPI in Thailand, Philippines and Indonesia.  
  *Numbers:* cpi_vs_target_vietnam = -54 %; installs_vs_target_vietnam = 313 %; installs_vs_kpi_th_ph_id = 1.8 ratio  
  *Lesson:* Seeding an organic account and pre-registration ahead of launch, then scaling with CBO and market-local creators, beat install targets across SEA.

## What is missing (gaps we could not source)

Benchmarks we looked for and could not read from a primary page in Oct 2026:

- **WordStream's own benchmark pages** (`wordstream.com/blog/facebook-ads-benchmarks`, `/google-ads-benchmarks`) returned HTTP 403; the same data was read from the LocaliQ (parent company) pages instead.
- **AppsFlyer** app-marketing / app-install-cost report pages returned 404/429 and **Adjust**'s mobile app trends ebook page returned 404; **Business of Apps** retention page returned 403. Day-30 retention by category is therefore included only as a SECONDARY row (Braze reproducing AppsFlyer-via-Business-of-Apps numbers). No primary Day-1 / Day-7 retention benchmark is included.
- **Triple Whale**'s Facebook and TikTok benchmark pages returned 403; its 2025 TikTok/Meta DTC averages are included only via Influee's reproduction (marked SECONDARY).
- **Rival IQ 2025 Social Media Industry Benchmark Report**: the HTML page gives only year-over-year changes and the PDF exceeded the fetch size limit, so no Rival IQ engagement medians are included.
- **Klaviyo**: open rate, placed-order rate and per-industry values did not render on the benchmarks page (charts only); only flow vs campaign click rates are included.
- **Unbounce** per-industry landing-page medians (3.8%-12.3%) exist only as a chart image, so only the overall median and per-channel averages are included.
- **LinkedIn**: no LinkedIn-published benchmark found; the rows come from one agency's (Huble) 2024 client data in GBP.
- **Country-level Facebook CPM for Kenya, Nigeria and Indonesia**: the Superads country pages exist but their values load as a live widget (not in page text); Lebesgue's 51-country table omits all three. Only India, Philippines, Brazil, South Africa, Egypt and Malaysia have cited values.
- **Email benchmarks by country** come from a single SMB-heavy vendor (Benchmark Email) with no stated data period; no Mailchimp/Klaviyo regional split was available.
- **Trial-to-paid and install-to-paid medians for India / Indonesia / Philippines / Kenya / Nigeria** are not printed on RevenueCat's 2025 report page (only "IN/SEA" revenue-per-install and a Latin America trial-to-paid median).
- **Google Ads / search benchmarks for non-US regions**, **YouTube ad benchmarks**, **WhatsApp marketing benchmarks**, **SMS benchmarks** and **influencer-campaign cost/engagement benchmarks** were not sourced.
- **Instagram / TikTok ad (paid) CTR by region** outside the Superads/Lebesgue Facebook pages was not sourced.

Case-study gaps:

- Fewer post-mortems with hard numbers exist for **Kenya, Nigeria, Indonesia and the Philippines** than for the US/EU; most emerging-market write-ups are vendor case studies (Meta/Google/TikTok for Business, CleverTap, MoEngage) that state lift percentages but rarely absolute spend, CPI or revenue.
- Very few sources publish **failed** launches with numbers; the case list over-represents successes. Treat the "lesson" lines as survivorship-biased.
- Many consumer-app retrospectives (Reddit, Indie Hackers) state downloads and revenue but not spend, so CAC/ROAS cannot be derived from them.

Case sources tried and not usable (blocked, paywalled, 404, or no verifiable year/numbers), so nothing from them is included:

- **Blocked (403/429/500):** beehiiv.com case studies (Half Baked, The Brink, World Builders), peerlist.io launch write-up, thegrowthcenterletter.beehiiv.com cold-email pipeline post, saas-accelerator.beehiiv.com, Medium's Morning Brew referral-program post, growthclassics.beehiiv.com Duolingo landing-page post, propakistani.pk Daraz/Careem posts, Indie Hackers via plain HTTP (read through the browser pane instead), archive.org availability API (rate-limited), TikTok for Business Dolls Kill page (500).
- **404 / redirected to index:** flow-ai.com, save.day, markup.io, hockeystack.com AppSumo post, customer.io Musora/Monarch/Olivia stories, gannonmeyer.substack.com cohort launch, growthtldr.libsyn.com, Branch Tokopedia/Bukalapak stories, MoEngage Lifestyle story, TikTok JD.ID / CoLearn / Steppen / Petit Bambou / Glow Recipe pages (index or undated), Think with Google Gojek page, newsroom.tiktok.com Philippines TikTok Shop post.
- **Paywalled:** WARC case pages for Maya and GCash (Philippines).
- **Fetched but excluded for missing year or missing numbers:** RevenueCat Pixelcut and MyMood AI; Adapty SocialKit, Pepapp, Prosto; Klaviyo Club L London and a beauty-startup story; Shopify immi and Snocks; AppsFlyer Future and ABI Game Studio; Appcues Yotpo and ProfitWell stories; Unbounce Webistry (empty body); Wingify Powtoon (2017); TikTok Bibit conversion-lift study (undated, no country); Moniepoint referral post (no outcomes); Google YouTube Works SEA 2023 PDF (image-only, Maya case unreadable).

