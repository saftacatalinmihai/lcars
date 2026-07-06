#ifndef LCARS_ARENA_H
#define LCARS_ARENA_H

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

typedef struct Arena {
  uint8_t *buffer;
  size_t capacity;
  size_t curr_offset;
  size_t prev_offset;
} Arena;

static inline void arena_init(Arena *arena, void *backing_buffer, size_t capacity) {
  arena->buffer = (uint8_t *)backing_buffer;
  arena->capacity = capacity;
  arena->curr_offset = 0;
  arena->prev_offset = 0;
}

static inline void *arena_alloc_align(Arena *arena, size_t size, size_t alignment) {
  if (!arena || !arena->buffer) return NULL;
  
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
  return NULL; // Out of memory
}

static inline void *arena_alloc(Arena *arena, size_t size) {
  return arena_alloc_align(arena, size, sizeof(void*));
}

static inline void *arena_realloc_align(Arena *arena, void *old_ptr, size_t old_size, size_t new_size, size_t alignment) {
  if (old_ptr == NULL) {
    return arena_alloc_align(arena, new_size, alignment);
  }

  if (!arena || !arena->buffer) return NULL;

  uint8_t *old_bytes = (uint8_t *)old_ptr;
  if (old_bytes >= arena->buffer && old_bytes < arena->buffer + arena->capacity) {
    size_t old_offset = old_bytes - arena->buffer;
    if (old_offset == arena->prev_offset) {
      if (old_offset + new_size <= arena->capacity) {
        arena->curr_offset = old_offset + new_size;
        return old_ptr;
      }
      return NULL; // Out of memory
    }
  }

  void *new_ptr = arena_alloc_align(arena, new_size, alignment);
  if (new_ptr) {
    size_t copy_size = old_size < new_size ? old_size : new_size;
    memcpy(new_ptr, old_ptr, copy_size);
  }
  return new_ptr;
}

static inline void *arena_realloc(Arena *arena, void *old_ptr, size_t old_size, size_t new_size) {
  return arena_realloc_align(arena, old_ptr, old_size, new_size, sizeof(void*));
}

static inline void arena_reset(Arena *arena) {
  if (arena) {
    arena->curr_offset = 0;
    arena->prev_offset = 0;
  }
}

#endif // LCARS_ARENA_H
