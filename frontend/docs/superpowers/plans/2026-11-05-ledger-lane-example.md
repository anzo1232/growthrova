# Ledger Lane Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the invented Northstar content with the verified Ledger Lane campaign while keeping the hero and bento interaction intact.

**Architecture:** A server-only adapter reads the exported Growthrova campaign receipt and original asset, validates the fixed campaign ID and SHA-256, and returns a small public DTO. Same-origin API routes expose only that DTO and the verified image bytes; the bento fetches the DTO and renders only saved channels.

**Tech Stack:** Next.js 16 Pages Router API routes, React 19, TypeScript, Tailwind CSS, Vitest/Testing Library.

**Spec:** User request in the active conversation.

## Global Constraints

- Do not change the finished hero.
- Use campaign `8c9cf54e5728446ca7706e9b813db893` and final selected asset SHA-256 `f26f2322940c9d8c6430628a5dc495aabd47b32d9d93ad2d65caa492ecb4f317`.
- Do not expose backend credentials, organisation IDs, operation IDs, costs, review internals, or draft controls.
- Omit channels without saved output; do not invent email or additional social assets.
- Preserve the cursor spotlight, asymmetrical grid, mobile legibility, and reduced-motion behavior.

## Review Focus

- A tampered or wrong asset must fail closed rather than render.
- A different campaign record must fail closed rather than leak tenant data.
- The public DTO must not contain private backend fields at any nesting depth.
- Missing channels must reflow without blank cards.
- Loading and error states must remain readable on mobile.

---

### Task 1: Server-only Ledger Lane adapter

**Files:**
- Create: `server/ledger-lane-example.ts`
- Create: `server/ledger-lane-example.test.ts`

**Interfaces:**
- Produces: `loadLedgerLaneExample(): Promise<LedgerLaneExample>` and `loadLedgerLaneAsset(): Promise<Buffer>`.

- [ ] Write tests for exact campaign provenance, public field allowlisting, missing email, wrong campaign rejection, and asset hash rejection.
- [ ] Run the focused test and confirm it fails because the adapter does not exist.
- [ ] Implement the adapter with server-only filesystem reads and exact ID/hash checks.
- [ ] Run the focused test and confirm it passes.

### Task 2: Narrow read-only API

**Files:**
- Create: `pages/api/examples/ledger-lane/index.ts`
- Create: `pages/api/examples/ledger-lane/creative.ts`
- Create: `pages/api/examples/ledger-lane/api.test.ts`

**Interfaces:**
- Consumes: Task 1 loader functions.
- Produces: same-origin GET-only JSON and JPEG endpoints.

- [ ] Write handler tests for GET success, non-GET rejection, cache headers, and private-field absence.
- [ ] Run the focused tests and confirm they fail because routes do not exist.
- [ ] Implement GET-only handlers and fail-closed errors.
- [ ] Run the focused tests and confirm they pass.

### Task 3: Data-driven bento

**Files:**
- Modify: `components/ui/campaign-bento.tsx`
- Create: `components/ui/campaign-bento.test.tsx`

**Interfaces:**
- Consumes: `LedgerLaneExample` from `/api/examples/ledger-lane`.
- Produces: four-card read-only Ledger Lane campaign section with no email card.

- [ ] Write component tests for Ledger Lane content, absence of Northstar/email, final creative URL, and read-only labels.
- [ ] Run the focused test and confirm it fails against the current Northstar component.
- [ ] Refactor the existing cards around the returned saved channels without changing spotlight/reduced-motion behavior.
- [ ] Run focused and full tests, typecheck, and production build.

### Task 4: End-to-end preview verification

**Files:**
- No product-code files.

- [ ] Start the production preview at `http://127.0.0.1:3000`.
- [ ] Verify the JSON endpoint exposes only the allowlisted DTO and the creative endpoint hash matches the final asset.
- [ ] Browser-check hero plus bento at desktop and mobile widths, including image aspect ratio, copy visibility, no horizontal overflow, and no browser errors.
- [ ] Report the local URL, campaign record, asset filename/hash, saved channels used, and omitted channels.
