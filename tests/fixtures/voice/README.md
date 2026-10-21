# Voice fixtures

Recorded speech for the voice round-trip tests (docs/plan/12, UW4). 16 kHz, mono, 16-bit PCM WAV.

| File | Says |
|---|---|
| `give_me_a_memory_game_about_football.wav` | "Give me a memory game about football." |
| `i_slept_badly.wav` | "I slept like four hours." |

Synthesised once with Kokoro-82M (Apache-2.0, `kokoro-onnx`, voice `af_heart`), resampled to
16 kHz, with a quarter second of silence before and 1.75 s after: the browser test loops the file
as a fake microphone, so a recording can end in silence. No real person's voice is recorded here.
