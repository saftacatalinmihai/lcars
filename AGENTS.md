# AGENTS.md — code style

Workflow, build and tests are in CLAUDE.md; this file is how the C is written.

## Handmade Network C style

- Functions and file-scope globals are plain `static` (headers mostly
  `static inline`). There are no `internal`/`local_persist`/`global_variable`
  macros in this codebase; don't introduce them.
- Keep functions simple, flat, and avoid deep nesting.
- Avoid object-oriented design patterns or excessive abstractions in C.
- Single translation unit (unity build): components are single-header
  libraries with their bodies under `#ifdef LCARS_IMPLEMENTATION`.

## Assertions — use them aggressively

- Every non-trivial function opens with **preconditions** (non-NULL `Arena *`
  and other pointers, file descriptors valid, indices in range, capacities sane) and checks
  **postconditions** on whatever it computed before returning (result non-NULL,
  length within capacity, cursor inside the buffer, count within bounds).
- Assert **invariants** wherever a struct is mutated — arena
  (`offset <= size`), a growable buffer (`len <= cap`), `String` (`len` within
  its allocation) — and assert
  **unreachable** branches (`assert(!"unreachable")` in the default case of an
  exhaustive `switch`).
- Use plain `assert()` from `<assert.h>`; add the include to the header you're
  editing if it isn't already there.
- No build defines `NDEBUG` — not even `lcars-release` — so asserts stay live in
  every variant on purpose: this is a single-user app where crashing loudly beats
  silently corrupting `lcars.db`.
- **Never put side effects inside `assert()`** — no assignments, no calls that do
  real work. The expression must be pure so behavior is identical if `NDEBUG` is
  ever introduced.
- Assert **programmer errors only**. Anything that can legitimately fail at runtime
  — SQLite errors, socket/HTTP request data, missing files, malformed JSON,
  user-typed text — must be *handled*, not asserted. Asserting on external input
  turns a bad request into a crash.
- Asserts complement the existing fail-loud policy (`arena_alloc` OOM
  `abort()`s); they do not replace error handling where a real
  recovery path exists.

## Memory

- No `malloc`/`free` in request handling: a connection's memory is its arena.
- A function that allocates takes an `Arena *` (`lcars_arena.h`) as its first
  argument.
- Use temporary arenas or `arena_reset` to keep lifetimes from leaking.

## Search

- Search code with the `fff` MCP tools (`grep`, `find_files`, `multi_grep`)
  from your first search on. Use Grep/Glob, or grep/find through Bash, only
  if fff is unavailable or fails.
