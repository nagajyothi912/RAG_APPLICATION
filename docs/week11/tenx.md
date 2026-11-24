# tenx.md — what breaks first at 10× ticket volume

**At 10× volume the Groq rate limit breaks first, not cost or latency: the peak minute goes from 4 to 40 requests, ~44,000 tokens/min against a measured cap of 8,000 (5.5× over), and the cap is already hit at 1.8× today's volume, while the whole day costs about $1.23.**

## The numbers

| input | value | source |
|---|---|---|
| Tokens per request | ~1,100 | measured, 70 live v2 requests (1,076 FAQ, 1,122 organic) |
| Cost per request | ~$0.000275 | measured, same requests |
| Groq limit, tokens per minute | **8,000** | `x-ratelimit-limit-tokens` response header on the app's key, read 2026-11-04 |
| Groq limit, requests per day | **1,000** | `x-ratelimit-limit-requests` header, same call |
| Today's volume | 448 req/day busiest day, **4 req in the busiest minute** | the drill log (3,000 requests over 7 days) |

| | today | 10× | cap | 10× vs cap |
|---|---:|---:|---:|---:|
| peak minute tokens | ~4,400 | ~44,000 | 8,000 | **5.5×** |
| requests / day | 448 | 4,480 | 1,000 | 4.5× |
| cost / day | $0.12 | $1.23 | – | not a problem |
| p50 latency | ~1.1–1.7 s generation, unthrottled | **5.7–7.4 s measured** when run at ~2× the TPM cap | – | degrades (see below) |

- **Order of failure:** peak-minute tokens hit the cap at 8,000 / 4,400 = **1.8× today's volume**; the daily request cap at 1,000 / 448 = **2.2×**. Both are rate limits and both come long before cost matters.
- **Latency is the symptom, not the cause.** In the cost experiment the sequence ran at roughly 2× the TPM cap, and the p50 per-request time rose from about 1.1–1.7 s (unthrottled single requests; the drill trace's generation span is 1.7 s) to 5.7 s and 7.4 s, because the OpenAI client silently retries 429s with back-off. The user sees slowness; the log shows `llm_api_ms` growing.
- **Cost:** $1.23 a day at 10×. Irrelevant next to the above.

## Caveats, stated plainly

- "Today's volume" is the **synthetic** drill baseline (3,000 requests over 7 days, a daytime-weighted draw), not production traffic. Replace the 448/day and 4/minute with your real ones; the method is `cost_report.py` for tokens per request plus a per-minute count from the index.
- The 8,000 TPM / 1,000 RPD limits are what this key reported today. A paid Groq tier moves the cap; it does not change which of the three hits first at this token size.
- Not in the plan, but the numbers imply it: shrink tokens per request (the 400-token output cap is already truncating 36% of organic answers, so *raising* it makes this worse), cache repeats ([cost_by_stage.md](cost_by_stage.md)), and queue or shed load at the app rather than letting the client retry blindly.
