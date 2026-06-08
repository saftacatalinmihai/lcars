#include "voice_rec.h"

#ifndef __EMSCRIPTEN__
#include "vosk_api.h"

#define MINIAUDIO_IMPLEMENTATION
#include "miniaudio.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>

#define AUDIO_BUFFER_SIZE (64 * 1024)
#define RESULT_QUEUE_SIZE 32

// Audio ring buffer
static short g_audioBuffer[AUDIO_BUFFER_SIZE];
static volatile int g_audioHead = 0;
static volatile int g_audioTail = 0;
static pthread_mutex_t g_audioMutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_audioCond = PTHREAD_COND_INITIALIZER;

// Result queue (finalized transcript chunks)
static char *g_resultQueue[RESULT_QUEUE_SIZE];
static volatile int g_resultHead = 0;
static volatile int g_resultTail = 0;
static pthread_mutex_t g_resultMutex = PTHREAD_MUTEX_INITIALIZER;

// Partial results
static char g_partialResult[512] = {0};
static pthread_mutex_t g_partialMutex = PTHREAD_MUTEX_INITIALIZER;
static volatile bool g_partialChanged = false;

// Vosk instances
static VoskModel *g_model = NULL;
static VoskRecognizer *g_recognizer = NULL;

// Threading & Recording State
static ma_device g_device;
static pthread_t g_thread;
static volatile bool g_isRecording = false;

// Helper: queue a text result
static void QueueResultText(char *text) {
    pthread_mutex_lock(&g_resultMutex);
    int nextHead = (g_resultHead + 1) % RESULT_QUEUE_SIZE;
    if (nextHead == g_resultTail) {
        // Queue full, free the oldest element to make room
        free(g_resultQueue[g_resultTail]);
        g_resultTail = (g_resultTail + 1) % RESULT_QUEUE_SIZE;
    }
    g_resultQueue[g_resultHead] = text;
    g_resultHead = nextHead;
    pthread_mutex_unlock(&g_resultMutex);
}

// Helper: parse Vosk JSON output for "text"
static void ParseAndQueueResult(const char *jsonStr) {
    if (!jsonStr) return;
    const char *textKey = "\"text\"";
    const char *p = strstr(jsonStr, textKey);
    if (!p) return;
    p += strlen(textKey);
    
    // Find ':'
    while (*p && *p != ':') p++;
    if (!*p) return;
    p++;
    
    // Find opening '"'
    while (*p && *p != '"') p++;
    if (!*p) return;
    p++;
    
    const char *start = p;
    const char *end = start;
    while (*end && *end != '"') {
        end++;
    }
    
    int len = end - start;
    if (len > 0) {
        char *text = malloc(len + 2);
        if (text) {
            memcpy(text, start, len);
            text[len] = ' '; // Add a trailing space for easy continuation
            text[len + 1] = '\0';
            QueueResultText(text);
        }
    }
}

// Helper: parse and update the partial result
static void UpdatePartialResult(const char *jsonStr) {
    if (!jsonStr) return;
    const char *partialKey = "\"partial\"";
    const char *p = strstr(jsonStr, partialKey);
    if (!p) return;
    p += strlen(partialKey);
    
    // Find ':'
    while (*p && *p != ':') p++;
    if (!*p) return;
    p++;
    
    // Find opening '"'
    while (*p && *p != '"') p++;
    if (!*p) return;
    p++;
    
    const char *start = p;
    const char *end = start;
    while (*end && *end != '"') {
        end++;
    }
    
    int len = end - start;
    pthread_mutex_lock(&g_partialMutex);
    if (len > 0 && len < (int)sizeof(g_partialResult) - 1) {
        memcpy(g_partialResult, start, len);
        g_partialResult[len] = '\0';
        g_partialChanged = true;
    } else {
        g_partialResult[0] = '\0';
        g_partialChanged = true;
    }
    pthread_mutex_unlock(&g_partialMutex);
}

// Miniaudio recording callback
static void AudioCaptureCallback(ma_device *pDevice, void *pOutput, const void *pInput, ma_uint32 frameCount) {
    (void)pOutput;
    (void)pDevice;
    if (pInput && frameCount > 0) {
        pthread_mutex_lock(&g_audioMutex);
        const short *samples = (const short *)pInput;
        for (ma_uint32 i = 0; i < frameCount; i++) {
            int nextHead = (g_audioHead + 1) % AUDIO_BUFFER_SIZE;
            if (nextHead != g_audioTail) {
                g_audioBuffer[g_audioHead] = samples[i];
                g_audioHead = nextHead;
            }
        }
        pthread_cond_signal(&g_audioCond);
        pthread_mutex_unlock(&g_audioMutex);
    }
}

// Speech recognition worker thread
static void *VoiceWorkerThread(void *arg) {
    (void)arg;
    short chunk[1600]; // 100ms buffer at 16kHz
    
    while (g_isRecording) {
        int count = 0;
        
        pthread_mutex_lock(&g_audioMutex);
        while (g_audioHead == g_audioTail && g_isRecording) {
            pthread_cond_wait(&g_audioCond, &g_audioMutex);
        }
        
        // Read available samples
        while (g_audioHead != g_audioTail && count < 1600) {
            chunk[count++] = g_audioBuffer[g_audioTail];
            g_audioTail = (g_audioTail + 1) % AUDIO_BUFFER_SIZE;
        }
        pthread_mutex_unlock(&g_audioMutex);
        
        if (count > 0 && g_isRecording) {
            int finalized = vosk_recognizer_accept_waveform(g_recognizer, (const char *)chunk, count * sizeof(short));
            if (finalized) {
                const char *resultStr = vosk_recognizer_result(g_recognizer);
                ParseAndQueueResult(resultStr);
            } else {
                const char *partialStr = vosk_recognizer_partial_result(g_recognizer);
                UpdatePartialResult(partialStr);
            }
        }
    }
    
    // Process remaining audio in buffer
    int count = 0;
    pthread_mutex_lock(&g_audioMutex);
    while (g_audioHead != g_audioTail && count < 1600) {
        chunk[count++] = g_audioBuffer[g_audioTail];
        g_audioTail = (g_audioTail + 1) % AUDIO_BUFFER_SIZE;
    }
    pthread_mutex_unlock(&g_audioMutex);
    
    if (count > 0) {
        vosk_recognizer_accept_waveform(g_recognizer, (const char *)chunk, count * sizeof(short));
    }
    
    // Finalize
    const char *resultStr = vosk_recognizer_final_result(g_recognizer);
    ParseAndQueueResult(resultStr);
    
    return NULL;
}

// Public API
bool VoiceRec_Init(const char *modelPath) {
    g_model = vosk_model_new(modelPath);
    if (!g_model) {
        fprintf(stderr, "VoiceRec: Failed to load Vosk model from '%s'\n", modelPath);
        return false;
    }
    g_recognizer = vosk_recognizer_new(g_model, 16000.0f);
    if (!g_recognizer) {
        fprintf(stderr, "VoiceRec: Failed to create Vosk recognizer\n");
        vosk_model_free(g_model);
        g_model = NULL;
        return false;
    }
    printf("VoiceRec: Initialized successfully with model '%s'\n", modelPath);
    return true;
}

void VoiceRec_Shutdown(void) {
    if (g_isRecording) {
        VoiceRec_StopRecording();
    }
    if (g_recognizer) {
        vosk_recognizer_free(g_recognizer);
        g_recognizer = NULL;
    }
    if (g_model) {
        vosk_model_free(g_model);
        g_model = NULL;
    }
    
    // Free any leftover results in queue
    pthread_mutex_lock(&g_resultMutex);
    while (g_resultHead != g_resultTail) {
        free(g_resultQueue[g_resultTail]);
        g_resultTail = (g_resultTail + 1) % RESULT_QUEUE_SIZE;
    }
    pthread_mutex_unlock(&g_resultMutex);
    
    printf("VoiceRec: Shutdown complete\n");
}

bool VoiceRec_StartRecording(void) {
    if (g_isRecording) return true;
    if (!g_recognizer) return false;
    
    // Clear audio buffer state
    pthread_mutex_lock(&g_audioMutex);
    g_audioHead = 0;
    g_audioTail = 0;
    pthread_mutex_unlock(&g_audioMutex);
    
    // Clear results queue
    pthread_mutex_lock(&g_resultMutex);
    while (g_resultHead != g_resultTail) {
        free(g_resultQueue[g_resultTail]);
        g_resultTail = (g_resultTail + 1) % RESULT_QUEUE_SIZE;
    }
    g_resultHead = 0;
    g_resultTail = 0;
    pthread_mutex_unlock(&g_resultMutex);
    
    // Clear partial results
    pthread_mutex_lock(&g_partialMutex);
    g_partialResult[0] = '\0';
    g_partialChanged = false;
    pthread_mutex_unlock(&g_partialMutex);
    
    // Initialize miniaudio capture device
    ma_device_config deviceConfig = ma_device_config_init(ma_device_type_capture);
    deviceConfig.capture.format   = ma_format_s16;
    deviceConfig.capture.channels = 1;
    deviceConfig.sampleRate       = 16000;
    deviceConfig.dataCallback     = AudioCaptureCallback;
    
    if (ma_device_init(NULL, &deviceConfig, &g_device) != MA_SUCCESS) {
        fprintf(stderr, "VoiceRec: Failed to initialize capture device\n");
        return false;
    }
    
    g_isRecording = true;
    
    if (pthread_create(&g_thread, NULL, VoiceWorkerThread, NULL) != 0) {
        fprintf(stderr, "VoiceRec: Failed to create worker thread\n");
        ma_device_uninit(&g_device);
        g_isRecording = false;
        return false;
    }
    
    if (ma_device_start(&g_device) != MA_SUCCESS) {
        fprintf(stderr, "VoiceRec: Failed to start capture device\n");
        g_isRecording = false;
        pthread_join(g_thread, NULL);
        ma_device_uninit(&g_device);
        return false;
    }
    
    printf("VoiceRec: Recording started\n");
    return true;
}

void VoiceRec_StopRecording(void) {
    if (!g_isRecording) return;
    
    printf("VoiceRec: Stopping recording\n");
    
    // Stop recording device
    ma_device_stop(&g_device);
    
    // Stop worker thread
    g_isRecording = false;
    pthread_mutex_lock(&g_audioMutex);
    pthread_cond_signal(&g_audioCond);
    pthread_mutex_unlock(&g_audioMutex);
    
    pthread_join(g_thread, NULL);
    ma_device_uninit(&g_device);
    printf("VoiceRec: Recording stopped\n");
}

bool VoiceRec_IsRecording(void) {
    return g_isRecording;
}

bool VoiceRec_PollResult(char *outBuffer, size_t maxLen) {
    pthread_mutex_lock(&g_resultMutex);
    if (g_resultHead == g_resultTail) {
        pthread_mutex_unlock(&g_resultMutex);
        return false;
    }
    
    char *text = g_resultQueue[g_resultTail];
    strncpy(outBuffer, text, maxLen);
    outBuffer[maxLen - 1] = '\0';
    
    free(text);
    g_resultTail = (g_resultTail + 1) % RESULT_QUEUE_SIZE;
    pthread_mutex_unlock(&g_resultMutex);
    return true;
}

bool VoiceRec_PollPartial(char *outBuffer, size_t maxLen) {
    pthread_mutex_lock(&g_partialMutex);
    if (!g_partialChanged) {
        pthread_mutex_unlock(&g_partialMutex);
        return false;
    }
    
    strncpy(outBuffer, g_partialResult, maxLen);
    outBuffer[maxLen - 1] = '\0';
    g_partialChanged = false;
    pthread_mutex_unlock(&g_partialMutex);
    return true;
}

#else // __EMSCRIPTEN__

#include <emscripten/emscripten.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Web Speech API JS implementation using EM_JS
EM_JS(bool, VoiceRec_Init_JS, (), {
    if (!window.webVoiceRec) {
        window.webVoiceRec = {
            recognition: null,
            isRecording: false,
            resultsQueue: [],
            partialResult: "",
            partialChanged: false
        };
        
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            console.error("Speech Recognition API not supported in this browser.");
            return false;
        }
        
        var rec = new SpeechRecognition();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = 'en-US';
        
        rec.onresult = function(event) {
            var interim = "";
            for (var i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    var text = event.results[i][0].transcript;
                    window.webVoiceRec.resultsQueue.push(text);
                } else {
                    interim += event.results[i][0].transcript;
                }
            }
            window.webVoiceRec.partialResult = interim;
            window.webVoiceRec.partialChanged = true;
        };
        
        rec.onerror = function(event) {
            console.error("Speech recognition error", event.error);
            window.webVoiceRec.isRecording = false;
        };
        
        rec.onend = function() {
            // Restart if we are supposed to be recording
            if (window.webVoiceRec.isRecording) {
                try {
                    window.webVoiceRec.recognition.start();
                } catch(e) {
                    // Ignore start error if it's already running or has been stopped
                }
            }
        };
        
        window.webVoiceRec.recognition = rec;
    }
    return true;
});

EM_JS(void, VoiceRec_Shutdown_JS, (), {
    if (window.webVoiceRec && window.webVoiceRec.recognition) {
        window.webVoiceRec.isRecording = false;
        window.webVoiceRec.recognition.abort();
        window.webVoiceRec.resultsQueue = [];
        window.webVoiceRec.partialResult = "";
        window.webVoiceRec.partialChanged = false;
    }
});

EM_JS(bool, VoiceRec_StartRecording_JS, (), {
    if (!window.webVoiceRec || !window.webVoiceRec.recognition) {
        return false;
    }
    if (window.webVoiceRec.isRecording) {
        return true;
    }
    window.webVoiceRec.resultsQueue = [];
    window.webVoiceRec.partialResult = "";
    window.webVoiceRec.partialChanged = false;
    window.webVoiceRec.isRecording = true;
    try {
        window.webVoiceRec.recognition.start();
        console.log("Speech recognition started");
        return true;
    } catch(e) {
        console.error("Failed to start speech recognition", e);
        window.webVoiceRec.isRecording = false;
        return false;
    }
});

EM_JS(void, VoiceRec_StopRecording_JS, (), {
    if (window.webVoiceRec && window.webVoiceRec.recognition) {
        window.webVoiceRec.isRecording = false;
        window.webVoiceRec.recognition.stop();
        console.log("Speech recognition stopped");
    }
});

EM_JS(bool, VoiceRec_IsRecording_JS, (), {
    if (window.webVoiceRec) {
        return window.webVoiceRec.isRecording;
    }
    return false;
});

EM_JS(bool, VoiceRec_PollResult_JS, (char *outBuffer, int maxLen), {
    if (!window.webVoiceRec || window.webVoiceRec.resultsQueue.length === 0) {
        return false;
    }
    var text = window.webVoiceRec.resultsQueue.shift();
    // Add trailing space for easy continuation, match desktop logic
    text = text.trim() + " ";
    stringToUTF8(text, outBuffer, maxLen);
    return true;
});

EM_JS(bool, VoiceRec_PollPartial_JS, (char *outBuffer, int maxLen), {
    if (!window.webVoiceRec || !window.webVoiceRec.partialChanged) {
        return false;
    }
    var text = window.webVoiceRec.partialResult;
    stringToUTF8(text, outBuffer, maxLen);
    window.webVoiceRec.partialChanged = false;
    return true;
});

bool VoiceRec_Init(const char *modelPath) {
    (void)modelPath;
    return VoiceRec_Init_JS();
}

void VoiceRec_Shutdown(void) {
    VoiceRec_Shutdown_JS();
}

bool VoiceRec_StartRecording(void) {
    return VoiceRec_StartRecording_JS();
}

void VoiceRec_StopRecording(void) {
    VoiceRec_StopRecording_JS();
}

bool VoiceRec_IsRecording(void) {
    return VoiceRec_IsRecording_JS();
}

bool VoiceRec_PollResult(char *outBuffer, size_t maxLen) {
    return VoiceRec_PollResult_JS(outBuffer, (int)maxLen);
}

bool VoiceRec_PollPartial(char *outBuffer, size_t maxLen) {
    return VoiceRec_PollPartial_JS(outBuffer, (int)maxLen);
}

#endif // __EMSCRIPTEN__
