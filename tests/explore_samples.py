"""Shared explore fixtures: one valid card file and one statement file."""

CARD = """## D-E1: Where do orders live?

**Why now:** The toy needs a store before the second feature.
**Evidence:** explore/bench.sh wrote 10,000 orders in 2 s on SQLite.
**Domain:** storage

### Option A: SQLite file (recommended)
- Solves: One file holds all orders. No server runs.
- Example: The toy wrote 10,000 orders in 2 s.
- Trade-off: One writer at a time.
- 1st order: No database server to run.
- 2nd order: Tests use a temp file.
- 3rd order: A second writer needs a move to Postgres.
- Undo cost: medium, the SQL is portable but the file path is everywhere.

### Option B: Postgres
- Solves: Many writers.
- Example: Two workers write orders at once.
- Trade-off: A server to run in dev and CI.
- 1st order: Docker in dev.
- 2nd order: CI needs a service container.
- 3rd order: Ops owns backups.
- Undo cost: low, the toy has no Postgres code yet.

**Would change it:** Two processes that write orders at once.
**Chosen:** A
**Reason:** We have one writer for a year.
"""

PARKED_CARD = """## D-E2: Which queue do we use?

**Why now:** Jobs pile up in the toy.
**Evidence:** no evidence: the toy has no background jobs yet.

### Option A: Cron (recommended)
- Solves: Runs jobs on a clock.
- Example: A nightly report.
- Trade-off: Jobs wait for the next tick.
- 1st order: No new service.
- 2nd order: Slow jobs overlap.
- 3rd order: A queue comes later anyway.
- Undo cost: low, one cron file.

### Option B: Queue
- Solves: Runs jobs as they arrive.
- Example: A paid order sends a mail at once.
- Trade-off: A broker to run.
- 1st order: A new service in dev.
- 2nd order: CI needs the broker.
- 3rd order: Ops owns the broker.
- Undo cost: medium, workers depend on the client.

**Would change it:** More than 1,000 jobs a minute.
**Chosen:** parked
**Reason:** We do not know the job volume yet.
"""

DECISIONS = "# Decisions\n\n" + CARD + "\n" + PARKED_CARD

VERIFY = ("# Verify\n\n"
          "- V-orders-1: A paid order writes exactly one event row.\n"
          "- V-orders-2: A failed payment writes no event row.\n")

OPEN = ("# Open questions\n\n"
        "## D-E2: Which queue do we use?\n"
        "- Owner: kwesi\n"
        "- Trigger: more than 1,000 jobs a minute\n")
