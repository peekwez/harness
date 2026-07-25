---
name: contract-first
description: OpenAPI contracts as the FE/BE seam. Use when building or changing API endpoints, routes, handlers, fetch calls, API clients, Next.js API routes, BFF layers, request/response types, "add an endpoint", "call the backend", or coordinating frontend and backend work.
---

# Contract first

`contracts/*.yaml` (OpenAPI) is the single source of truth for the FE/BE
seam. Backend validators and frontend typed clients both generate from it;
CI fails on drift. Parallel agent teams coordinate through this file instead
of through each other.

Rules — stated explicitly because this is exactly the ambiguity agents
resolve differently per feature:

- **Contract before code.** A new endpoint starts as a contract diff, gets
  human eyes (it's authored), then generates both sides. Never let a handler
  define the shape and back-fill the contract.
- **Codegen in both directions.** Backend: request/response validation from
  the contract. Frontend: typed client from the contract. Neither side
  hand-writes types the contract already defines.
- **BFF-only rule for Next API routes.** Next.js API routes exist solely as
  a backend-for-frontend: auth token exchange, response shaping for a
  specific view. Business logic in a Next route is a defect — it belongs
  behind the contract in the backend service.
- Changing a contract is interface drift by definition — expect G6 to demand
  acknowledgment, and treat any breaking change as an ADR-worthy decision.
