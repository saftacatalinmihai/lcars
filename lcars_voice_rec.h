#ifndef LCARS_VOICE_REC_H
#define LCARS_VOICE_REC_H

#include <stdbool.h>
#include <stddef.h>

// Struct representing the voice recognition API passed to the hot-reloaded
// library
typedef struct VoiceRecApi {
  bool (*Init)(const char *modelPath);
  void (*Shutdown)(void);
  bool (*StartRecording)(void);
  void (*StopRecording)(void);
  bool (*IsRecording)(void);
  bool (*PollResult)(char *outBuffer, size_t maxLen);
  bool (*PollPartial)(char *outBuffer, size_t maxLen);
} VoiceRecApi;

// Exposed functions for lcars.c
bool VoiceRec_Init(const char *modelPath);
void VoiceRec_Shutdown(void);
bool VoiceRec_StartRecording(void);
void VoiceRec_StopRecording(void);
bool VoiceRec_IsRecording(void);
bool VoiceRec_PollResult(char *outBuffer, size_t maxLen);
bool VoiceRec_PollPartial(char *outBuffer, size_t maxLen);

#endif // LCARS_VOICE_REC_H
