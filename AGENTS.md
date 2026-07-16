# Agents.md file

## Code Style
- **Handmade Network C Style**:
  - Use `internal static`, `local_persist static`, and `global_variable static` styles.
  - Keep functions simple, flat, and avoid deep nesting.
  - Avoid object-oriented design patterns or excessive abstractions in C.
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
