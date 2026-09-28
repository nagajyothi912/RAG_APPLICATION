# Week 5 demo script — Error Analysis

**One sentence:** "The account manager said it sometimes gives wrong answers about
billing. That is not a bug report, so I made the app record everything it does,
read twenty answers at random by hand, and turned that into a ranked list with a
dated prediction I can be wrong about."

Total time: 12-15 minutes. Have two things open: the app at `#analysis`, and
`docs/week5/taxonomy.md`.

---

## Act 1 — The problem (2 min)

Say this, do not show anything yet:

- The complaint was "it sometimes gives wrong answers about billing."
- Unfalsifiable. No frequency, no example, no definition of wrong.
- Worse: the app persisted **nothing**. Logging went to stderr and vanished. There
  was no request id, so a user could not even tell us *which* answer was wrong.
- So Week 5 is not a fixing week. It is a *measuring* week.

**The trap I had to avoid:** deciding the categories first and then reading traces
into them. You will find exactly the problems you expected and nothing else.

---

## Act 2 — The method (4 min)

Walk the order, because the order **is** the method:

1. **Instrument first.** Every request now records the question, the index
   configuration, every retrieved chunk with each stage's score, the exact prompt
   sent, the model and its parameters, and the raw output. Enough to replay it
   offline. Off by default.
2. **Write the questions blind.** 120 support tickets authored from each article's
   *heading list*, never the body text. Writing a question after reading the
   sentence that answers it produces a question that flatters retrieval.
3. **Prove it was blind.** Show `git log --oneline`. The ticket bank is commit
   `38ab685`, committed *before* the tracing module existed. At that commit the app
   could not physically produce a trace. The fixture also has four keys and cannot
   hold a label, and a test enforces that.
4. **Run 148 traces.** Real Groq key, real corpus, 17 minutes, zero dropped.
5. **Draw the sample before reading anything.** Seed 20260907. Sorted before
   sampling so a resumed run cannot move it, each pool on its own stream, pinned to
   the trace file's sha256.

**The line that lands:** "I fixed the sample before I read a single answer, so the
frequencies are a property of the draw, not of what I happened to notice."

---

## Act 3 — The findings (4 min)

Open the app at `#analysis`. The taxonomy is on screen.

| # | Mode | Count | % | Severity |
|---|---|---:|---:|---|
| 1 | Refuses while the chunk that answers it is ranked first | 3 | 15% | annoys the user |
| 2 | Says it does not know and still names a source file | 2 | 10% | embarrasses the client |
| 3 | Prints the citation in a bracket style no other answer uses | 2 | 10% | annoys the user |
| 4 | Tells a paying legacy subscriber it cannot say if their plan is valid | 1 | 5% | embarrasses the client |
| 5 | Stops mid-word at the length cap | 1 | 5% | annoys the user |
| — | No defect seen | 11 | 55% | — |

**Then click `TR-0055`.** This is the whole week in one screen. Point at, in order:

- The question: **"how much is that?"** A real follow-up with no prior turn.
- The open coding sentence, written before any category existed.
- **Gate 0.1414 against a threshold of 0.15.** Refused.
- The Prompt tab: *"The model was never called."*
- Back to Retrieval, rank 1, dense score in red: the installation-timelines chunk,
  which contains the ₹500 charge.

**Say:** "The answer was retrieved, ranked first, and then thrown away by a number,
before the model ever saw it. That is not a retrieval problem. Retrieval worked."

**On naming, if asked:** "retrieval issue" is a diagnosis smuggled in as an
observation, and it tells a manager nothing about what to do. Every name here says
what a reader of the answer would actually see.

**Be honest about the residual.** 11 of 20 show no defect, six being correct
refusals. The app is in better shape than the complaint implied. And with 20
traces one trace is 5 points, so modes 3, 4 and 5 are within the noise of a single
draw. Say that out loud before someone else does.

---

## Act 4 — The prediction (2 min)

Show `docs/week5/prediction.md`, then `git show --stat 4f78158`.

- Target: **mode 1**, 3/20.
- One change: skip the numeric gate for queries under four tokens and let the
  system prompt refuse instead.
- Expected: mode 1 drops to **≤1/20**, a **−10 point** move.
- **Three guardrails that must NOT move:** a new "answers something uncovered" mode
  stays at 0/20, "no defect seen" holds at ≥10/20, and hit-rate@3 on the Week 4
  golden set stays at 11/12.

**The line:** "Naming what must not move is what makes this falsifiable. Otherwise
I can 'fix' the refusals next week by letting it invent answers and call that a
win."

Show that the commit contains only that file, and that nothing in app, script or
frontend source changed after it.

---

## Act 5 — The bonus (2 min)

"The demo set we show clients: how often does the top mode appear there?"

**3/20 in the random sample. 0/10 in the demo set.**

"My first guess was that the UI props the demo up, because it scopes each golden
question to its own document. So I ran all 14 again with the scoping removed. It
made no difference. Every one still answered correctly."

**The real reason, and the point of the whole week:** the demo questions were
written from the articles, by us, with the answer in view. Mode 1 needs a query
whose phrasing does not resemble its own answer, like "how much is that?" or
"500". Nobody puts a question like that in a demo.

**Closing line:** "The number that should worry us is not 15 versus 0. It is that
the 15% was invisible until somebody drew twenty traces at random and read them,
and nothing in our week ever would have."

---

## Questions you will get

**"Is 20 enough?"**
No, and the taxonomy says so. One trace is 5 points. Twenty is what the brief
asks for and it is enough to rank the top mode, not to separate modes 3, 4 and 5.

**"How do you know a trace's answer was correct?"**
You do not, from the trace alone. The trace records what the system *did*, not
whether it was right. `TR-0023` refused and was correct; `TR-0112` refused and was
wrong. They look identical. Correctness lives in the open coding, which is why 30
traces carry a verdict and 118 do not. That is the honest limit of this week.

**"Why not fix mode 2 first? It embarrasses the client."**
It is a one-clause prompt edit with nothing to learn from it. Mode 1 has the most
traces and needs an actual decision.

**"Could you have used a benchmark?"**
No, and this is the three-sentence answer in the notes. MMLU scores knowledge the
model already has. Mode 1 is not a knowledge failure at all: the answer was
retrieved and then discarded by a gate before the model was called, so a benchmark
scoring the final string would record a refusal and could not tell it apart from a
question we genuinely cannot answer.

**"Are these real traces or did you make them up?"**
The questions are synthetic and I say so. The traces are real: 148 actual runs of
the shipped pipeline against the real corpus with a real key. What I could not
have is real user traffic.

**"Can you prove you did not fix things while reading?"**
`git show --stat 2b6b858`. The open-coding commit touches one markdown file. A
test re-runs that check.

---

## Numbers to have ready

| | |
|---|---|
| Traces collected | 148 (120 tickets, 14 demo, 14 control) |
| Collection time | 16.8 min, zero failures |
| Sampled and read | 20 random + 10 demo |
| Failure modes | 5, plus an 11-trace residual |
| Top mode | 3/20 = 15% |
| Sample seed | 20260907 |
| Prediction commit | `4f78158`, tagged `week5-prediction` |
| Tests | 182 passing |
| Replay | every field matched, byte-identical output |

## The one thing to admit before being asked

Byte-exact replay only works because the collection run pinned temperature to 0.
The shipped app sends none, so Groq uses its default and the same prompt returns
different wording each call. **A genuine production trace is not byte-replayable.**
That is recorded as a finding in the notes, not quietly patched. It is the most
interesting thing tracing taught me, and volunteering it is stronger than being
caught by it.
