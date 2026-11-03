"""
Week 10 — the triage squad: an orchestrator plus two narrow workers, raced
against the Week 7 single agent on the same 10 Week-6 eval cases.

  metering.py      one metered client both arms share (tokens, cost, 429 waits)
  workers.py       triage worker and policy-lookup worker (narrow prompts, few tools)
  worker_api.py    the workers as an HTTP service, with 500 injection
  orchestrator.py  decompose -> both workers in parallel -> synthesise
  race.py          the race, the failure run, and the generated reports
"""
