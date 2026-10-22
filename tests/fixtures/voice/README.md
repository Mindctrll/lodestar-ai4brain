# Voice fixtures

Recorded speech for the voice round-trip tests (docs/plan/12, UW4). 16 kHz, mono, 16-bit PCM WAV.

| File | Says |
|---|---|
| `give_me_a_memory_game_about_football.wav` | "Give me a memory game about football." |
| `i_slept_badly.wav` | "I slept like four hours." |

Synthesised once with Kokoro-82M (Apache-2.0, `kokoro-onnx`, voice `af_heart`), resampled to
16 kHz, with a quarter second of silence before and 1.75 s after: the browser test loops the file
as a fake microphone, so a recording can end in silence. No real person's voice is recorded here.

## Wake-word background audio (WP3.4)

`frontend/src/voice/wake.test.ts` builds about 3 minutes of background from the files above and
quiet noise. For the 30-minute false-trigger run, make a 16 kHz mono 16-bit WAV of everyday sound
with no "Hey Lodestar" in it (talk radio, a podcast, TV, kitchen noise) and point the test at it.
It is not stored in the repo:

```
ffmpeg -i background.mp3 -t 1800 -ac 1 -ar 16000 -sample_fmt s16 /tmp/background_30min.wav
cd frontend && PORCUPINE_ACCESS_KEY=... PORCUPINE_KEYWORD_PPN=/path/hey-lodestar_en_wasm_v4_0_0.ppn \
  WAKE_BACKGROUND_WAV=/tmp/background_30min.wav npx vitest run src/voice/wake.test.ts
```

The test prints the number of triggers and fails above 1 per 30 minutes.
