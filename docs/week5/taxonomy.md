# Week 5 failure taxonomy — 20 random support traces

Sample: 20 traces drawn with seed `20260907` from `traces.jsonl` (sha256 `61f4e963…a133133`).
Coded from the traces alone, before any change to the app. One trace, one mode.
Ranked by count; severity breaks ties.

| # | Failure mode | Count | % of 20 | Severity | Example |
| --- | --- | ---: | ---: | --- | --- |
| 1 | Refuses while the chunk that answers it is ranked first | 3 | 15% | annoys the user | `TR-0055` |
| 2 | Says it does not know and still names a source file | 2 | 10% | embarrasses the client | `TR-0012` |
| 3 | Prints the citation in a bracket style no other answer uses | 2 | 10% | annoys the user | `TR-0045` |
| 4 | Tells a paying legacy subscriber it cannot say whether their plan is valid | 1 | 5% | embarrasses the client | `TR-0112` |
| 5 | Stops mid-word at the length cap and never reaches the last question | 1 | 5% | annoys the user | `TR-0035` |
| — | No defect seen | 11 | 55% | — | `TR-0098` |
| | **Total** | **20** | **100%** | | |

**Severity key.** *embarrasses the client* — a client could quote this back at us in a
meeting. *annoys the user* — the customer gets there, but slower or after a second message.

**Read the residual carefully.** 11 of 20 traces show no defect, and that includes six
correct refusals of questions the corpus genuinely does not answer. A high residual on a
20-trace sample is a real result, not a rounding error, and it is why every mode below is
a small count. It also means the ranking is fragile: one trace is 5 points, so modes 3, 4
and 5 are separated by less than the noise of a single draw.

**Next.** Mode 1 is the prediction target: [`prediction.md`](prediction.md), committed
`b1d5b09` on 2026-09-07, before any fix. It was chosen over mode 2 because it has the most
traces and because mode 2 is a one-clause prompt edit with nothing to learn from it.

Verbatim open coding, the seeded draw, the replay evidence, the demo-set comparison and
the benchmark note: [`notes.md`](notes.md).
