#ifndef LCARS_ARENA_H
#define LCARS_ARENA_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Arena {
  uint8_t *buffer;
  size_t capacity;
  size_t curr_offset;
  size_t prev_offset;
} Arena;

static inline void arena_init(Arena *arena, void *backing_buffer,
                              size_t capacity) {
  arena->buffer = (uint8_t *)backing_buffer;
  arena->capacity = capacity;
  arena->curr_offset = 0;
  arena->prev_offset = 0;
}

// Every arena in this codebase is a fixed-size, pre-allocated budget
// (State's 32MB doc_arena/16MB scratch_arena, or a connection-handling
// thread's on-stack arena) with no "ask the OS for more" fallback -
// running out means a leak, an oversized input, or a budget that
// genuinely needs raising. Rather than have every one of this file's
// callers remember to check for and handle a NULL return (most didn't),
// arena_alloc/arena_realloc report the failure clearly and abort
// immediately: allocation from these functions always succeeds or the
// process is already gone.
static inline void arena_oom_abort(Arena *arena, size_t requested_size) {
  fprintf(stderr,
         "Fatal error: arena allocation failed (requested %zu bytes, "
         "%zu/%zu already used)\n",
         requested_size, arena ? arena->curr_offset : (size_t)0,
         arena ? arena->capacity : (size_t)0);
  abort();
}

static inline void *arena_alloc_align(Arena *arena, size_t size,
                                      size_t alignment) {
  if (!arena || !arena->buffer) {
    arena_oom_abort(arena, size);
  }

  uintptr_t curr_ptr = (uintptr_t)arena->buffer + arena->curr_offset;
  uintptr_t offset = (alignment - 1);
  uintptr_t aligned_ptr = (curr_ptr + offset) & ~offset;
  size_t relative_offset = aligned_ptr - (uintptr_t)arena->buffer;

  if (relative_offset + size <= arena->capacity) {
    void *ptr = &arena->buffer[relative_offset];
    arena->prev_offset = relative_offset;
    arena->curr_offset = relative_offset + size;
    memset(ptr, 0, size);
    return ptr;
  }
  arena_oom_abort(arena, size);
  return NULL; // unreachable: arena_oom_abort() never returns
}

static inline void *arena_alloc(Arena *arena, size_t size) {
  return arena_alloc_align(arena, size, sizeof(void *));
}

static inline void *arena_realloc_align(Arena *arena, void *old_ptr,
                                        size_t old_size, size_t new_size,
                                        size_t alignment) {
  if (old_ptr == NULL) {
    return arena_alloc_align(arena, new_size, alignment);
  }

  if (!arena || !arena->buffer) {
    arena_oom_abort(arena, new_size);
  }

  uint8_t *old_bytes = (uint8_t *)old_ptr;
  if (old_bytes >= arena->buffer &&
      old_bytes < arena->buffer + arena->capacity) {
    size_t old_offset = old_bytes - arena->buffer;
    if (old_offset == arena->prev_offset) {
      if (old_offset + new_size <= arena->capacity) {
        arena->curr_offset = old_offset + new_size;
        return old_ptr;
      }
      arena_oom_abort(arena, new_size);
    }
  }

  // arena_alloc_align() never returns NULL (it aborts on failure).
  void *new_ptr = arena_alloc_align(arena, new_size, alignment);
  size_t copy_size = old_size < new_size ? old_size : new_size;
  memcpy(new_ptr, old_ptr, copy_size);
  return new_ptr;
}

static inline void *arena_realloc(Arena *arena, void *old_ptr, size_t old_size,
                                  size_t new_size) {
  return arena_realloc_align(arena, old_ptr, old_size, new_size,
                             sizeof(void *));
}

static inline void arena_reset(Arena *arena) {
  if (arena) {
    arena->curr_offset = 0;
    arena->prev_offset = 0;
  }
}

#endif // LCARS_ARENA_H
