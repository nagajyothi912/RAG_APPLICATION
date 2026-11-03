# Verdict

**Sunk-cost check, out loud:** I built the squad this week and want it to win, so a win needs stronger evidence than a loss. I counted it against the squad that one squad-only bug forced a full re-run of both arms (see README).
Squad vs single agent, same 10 Week-6 cases and the same judge: **tokens 32,874 vs 53,462** (multiplier 0.6x as counted, ~0.8x with the 10 rejected calls estimated), **cost $0.000875 vs $0.001191 per ticket**, **p99 7.5 s vs 18.4 s**, pass rate 8/10 vs 7/10.
The pass-rate edge is one case in ten and within noise. The token, cost and p99 gaps are not: the single agent re-sends its growing conversation on every loop turn (90% of its tokens), while the narrow workers start from short, separate contexts that run in parallel.
**Verdict: KEEP the squad over the Week 7 single agent, conditionally.** This race does not show the squad beating Week 7's fixed workflow, which used about 5k tokens on these tickets.
Conditions before it ships: fix the 300-token reply cap that truncated 2 race replies and the failure-case reply; pass structured account facts instead of worker prose (₹ became $); and pause for a human when a worker fails rather than sending a partial reply.
If those fixes make the squad lose its lead, the verdict flips to kill, and that is an acceptable result.
