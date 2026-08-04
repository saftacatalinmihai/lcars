# Agents.md file

## Code Style
- **Handmade Network C Style**:
  - Use `internal static`, `local_persist static`, and `global_variable static` styles.
  - Keep functions simple, flat, and avoid deep nesting.
  - Avoid object-oriented design patterns or excessive abstractions in C.
- **Assertions — use them aggressively**:
  - Every non-trivial function opens with **preconditions** (non-NULL `Arena *` /
    `State *` / element pointers, indices in range, capacities sane) and checks
    **postconditions** on whatever it computed before returning (result non-NULL,
    length within capacity, cursor inside the buffer, count within bounds).
  - Assert **invariants** wherever a struct is mutated — gap buffer
    (`gap_start <= gap_end <= capacity`), arena (`offset <= size`), element array
    (`count <= MAX_ELEMENTS`), `String` (`len` within its allocation) — and assert
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
    — SQLite errors, socket/HTTP request data, missing files, malformed hypermedia,
    user-typed text — must be *handled*, not asserted. Asserting on external input
    turns a bad request into a crash.
  - Asserts complement the existing fail-loud policy (`arena_alloc` OOM `abort()`s,
    the `TODO` macro `abort()`s); they do not replace error handling where a real
    recovery path exists.
- **Memory Management**:
  - Do NOT use standard `malloc`/`free`.
  - Pass a pointer to [Arena](file:///home/mihai/Workspace/lcars/lcars_arena.h#L9) (defined in [lcars_arena.h](file:///home/mihai/Workspace/lcars/lcars_arena.h)) as the first argument to functions requiring allocation.
  - Utilize temporary arenas or resets via [arena_reset](file:///home/mihai/Workspace/lcars/lcars_arena.h#L76) to prevent lifetime leaks.
- **Compilation & Structure**:
  - Use single translation unit style (unity build). The main source file should direct `#include` implementation files.
  - Use single-header libraries for components: wrap implementation details under `#ifdef LCARS_IMPLEMENTATION` guards.

## Compiler & Tools
- For file search/grep, prioritize the custom `fff` MCP tools (which hook into `fff-mcp`). Fall back to shell command grep/find only if MCP tools are unavailable.
- Ensure the code compiles cleanly under the project's warning flags (e.g., `-Wall -Wextra`) after every edit.

## Backlog
- `TODO.md` is the living backlog of open features, bugs, and refactoring ideas —
  check it for context before starting open-ended work, and update it (check off
  finished items, add newly discovered ones) as part of the task, not as an
  afterthought. It is distinct from `REFACTORING.md`, which is a closed, completed
  audit kept for history/rationale only.
