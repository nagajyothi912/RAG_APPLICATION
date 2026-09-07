## Replay of `TR-0023`

Picked by seeded draw from the sampled 20: `random.Random("20260907:replay").choice(sorted(sample['random']))`.

**Question.** 'Is GST included in the 1199 price or added on top?'

**Recorded at.** 2026-09-07T16:57:35.688Z · ticket `T023` · pool `random`

### What the trace carried

| field | value |
| --- | --- |
| mode | `week4` |
| top_k | `3` |
| filters | `{}` |
| chunking | `heading/1000/100` |
| embed model | `all-MiniLM-L6-v2` |
| corpus fingerprint | `6011b16fe1358dd4` |
| model | `openai/gpt-oss-120b` |
| params | `{"temperature": 0.0, "max_tokens": 400}` |
| prompt id | `v1-cfc04156c4e7` |
| score threshold | `0.15` |

### Retrieval: original vs replayed

| rank | original chunk | dense | rerank | replayed chunk | dense | rerank | |
| ---: | --- | ---: | ---: | --- | ---: | ---: | --- |
| 1 | `help_centre/airfiber_legacy_plans.md#3` | 0.3387 | -1.3780 | `help_centre/airfiber_legacy_plans.md#3` | 0.3387 | -1.3780 | match |
| 2 | `help_centre/airfiber_plans.md#1` | 0.3129 | -1.7025 | `help_centre/airfiber_plans.md#1` | 0.3129 | -1.7025 | match |
| 3 | `help_centre/airfiber_plans.md#3` | 0.3401 | -2.2322 | `help_centre/airfiber_plans.md#3` | 0.3401 | -2.2322 | match |

Gate score: original `0.3401`, replayed `0.3401` — match. Refused: original `False`, replayed `False`.

### Replay from the trace's source list alone

Not possible. The trace stores a 180-character preview per chunk and 3 of 3 retrieved chunks are longer than their preview, so the prompt cannot be rebuilt from the source list. The full prompt is recorded separately, which is why the generation replay below works; re-deriving the chunk text from the corpus and checking it against each recorded `text_sha256` is the fallback.

Re-derived chunk text matches every recorded sha256: **True**.

### Generation: original vs replayed

Re-sent the recorded prompt verbatim (1788 characters of context) to `openai/gpt-oss-120b` at temperature `0.0`.

**Original answer**

```
I don't know based on the provided documents.
```

**Replayed answer**

```
I don't know based on the provided documents.
```

### Verdict

| field | result |
| --- | --- |
| corpus fingerprint | match |
| retrieval ranking and scores | match |
| gate score | match |
| chunk text sha256 re-derived from corpus | match |
| raw model output | match |

