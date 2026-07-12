---
description: Scaffold a new ADR in docs/decisions/ following the existing numbering and section structure.
---

Create a new Architecture Decision Record in `docs/decisions/`.

1. List `docs/decisions/*.md`, find the highest existing `NNNN` prefix, and use the next
   4-digit number (zero-padded, e.g. `0005`).
2. If the user hasn't already given a title and context in this conversation, ask for:
   - A short title (used for both the `## Status`/heading title and the kebab-case filename).
   - A one-paragraph summary of the problem/decision being recorded.
3. Create `docs/decisions/{NNNN}-{kebab-case-title}.md` with exactly this structure, matching
   ADR-0001 through ADR-0004:

   ```markdown
   # ADR-{NNNN}: {Title}

   ## Status
   Proposed

   ## Date
   {today's date, YYYY-MM-DD}

   ## Context

   {real context — the problem, constraint, or prior state that motivated this decision}

   ## Decision

   {what was decided}

   ## Consequences

   {what this makes easier/harder, what follow-up work it implies}
   ```

4. Write real Context/Decision/Consequences content based on the actual change being
   discussed — never leave placeholder text like "TBD" or "{decision here}" in the final file.
   If you don't have enough information to write a real Context or Decision section, ask
   before creating the file rather than guessing.
5. Don't mark the ADR `Accepted` yourself — leave `Status: Proposed` unless the user
   explicitly says the decision is already final.
