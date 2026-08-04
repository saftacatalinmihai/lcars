#ifndef LCARS_ARENA_H
#define LCARS_ARENA_H

// Included here rather than per-module because this is the one header every
// translation unit pulls in (lcars_http.h reaches it without going through
// lcars_types.h), and asserts are used pervasively - see AGENTS.md. Note
// that no build defines NDEBUG, not even lcars-release: a violated invariant
// should take the process down loudly rather than corrupt lcars.db.
#include <assert.h>
#include <stdbool.h>
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

// The structural invariant every initialized Arena holds between
// operations: it has a backing buffer, and neither the bump pointer nor the
// previous-allocation marker has escaped it. Every function below asserts
// this on entry and on exit, so a corrupted arena is caught at the
// operation that broke it rather than at some much later allocation.
static inline bool arena_valid(const Arena *arena) {
  return arena != NULL && arena->buffer != NULL &&
         arena->curr_offset <= arena->capacity &&
         arena->prev_offset <= arena->capacity;
}

static inline void arena_init(Arena *arena, void *backing_buffer,
                              size_t capacity) {
  assert(arena != NULL);
  assert(backing_buffer != NULL);
  assert(capacity > 0);

  arena->buffer = (uint8_t *)backing_buffer;
  arena->capacity = capacity;
  arena->curr_offset = 0;
  arena->prev_offset = 0;

  assert(arena_valid(arena));
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
  // A non-power-of-two alignment makes the (alignment - 1) mask below
  // compute a garbage address instead of failing, so catch it here rather
  // than hand out a misaligned pointer.
  assert(alignment > 0 && (alignment & (alignment - 1)) == 0);

  if (!arena || !arena->buffer) {
    arena_oom_abort(arena, size);
  }
  assert(arena_valid(arena));

  uintptr_t curr_ptr = (uintptr_t)arena->buffer + arena->curr_offset;
  uintptr_t offset = (alignment - 1);
  uintptr_t aligned_ptr = (curr_ptr + offset) & ~offset;
  size_t relative_offset = aligned_ptr - (uintptr_t)arena->buffer;

  assert(relative_offset >= arena->curr_offset); // aligning only moves forward
  // A `size` large enough to wrap the addition below would make the capacity
  // check pass and hand back a buffer far smaller than requested. That can
  // only come from a bogus (e.g. negative-turned-unsigned) length, which is
  // a caller bug, not a legitimate out-of-memory.
  assert(relative_offset + size >= relative_offset);

  if (relative_offset + size <= arena->capacity) {
    void *ptr = &arena->buffer[relative_offset];
    arena->prev_offset = relative_offset;
    arena->curr_offset = relative_offset + size;
    memset(ptr, 0, size);
    assert(arena_valid(arena));
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
    // old_size describes a block that doesn't exist; a non-zero value means
    // the caller is tracking its sizes wrong and the memcpy below would have
    // read from nowhere had old_ptr been set.
    assert(old_size == 0);
    return arena_alloc_align(arena, new_size, alignment);
  }

  if (!arena || !arena->buffer) {
    arena_oom_abort(arena, new_size);
  }
  assert(arena_valid(arena));

  uint8_t *old_bytes = (uint8_t *)old_ptr;
  if (old_bytes >= arena->buffer &&
      old_bytes < arena->buffer + arena->capacity) {
    // A block inside this arena can never claim to extend past its end.
    assert((size_t)(old_bytes - arena->buffer) + old_size <= arena->capacity);
    size_t old_offset = old_bytes - arena->buffer;
    if (old_offset == arena->prev_offset) {
      if (old_offset + new_size <= arena->capacity) {
        arena->curr_offset = old_offset + new_size;
        assert(arena_valid(arena));
        return old_ptr;
      }
      arena_oom_abort(arena, new_size);
    }
  }

  // arena_alloc_align() never returns NULL (it aborts on failure).
  void *new_ptr = arena_alloc_align(arena, new_size, alignment);
  size_t copy_size = old_size < new_size ? old_size : new_size;
  memcpy(new_ptr, old_ptr, copy_size);
  assert(arena_valid(arena));
  return new_ptr;
}

static inline void *arena_realloc(Arena *arena, void *old_ptr, size_t old_size,
                                  size_t new_size) {
  return arena_realloc_align(arena, old_ptr, old_size, new_size,
                             sizeof(void *));
}

static inline void arena_reset(Arena *arena) {
  assert(arena_valid(arena));
  if (arena) {
    arena->curr_offset = 0;
    arena->prev_offset = 0;
  }
  assert(arena->curr_offset == 0 && arena->prev_offset == 0);
}

#endif // LCARS_ARENA_H
