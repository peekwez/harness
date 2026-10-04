# Verify

Write one statement for each behavior that a test must prove.
Write one statement per line, in the form `V-<feature>-<n>: <statement>`.
A test links to a statement with a comment: `verifies: V-<feature>-<n>  kills: <the bug it catches>`.

Example. Harness does not read text inside a fenced block.

```
- V-orders-1: A paid order writes exactly one event row.
- V-orders-2: A failed payment writes no event row.
```
