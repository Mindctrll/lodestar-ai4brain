# 12 · Voice and emotion

## Voice stack

| Part | P1 | P2 | Notes |
|---|---|---|---|
| Summon | Tap-to-talk orb + keyboard shortcut | **"Hey Lodestar" wake word with Porcupine Web** | Porcupine's free personal tier allows custom wake words for non-commercial use with an access key; check current terms. openWakeWord's code is Apache-2.0 but its pretrained models are CC BY-NC-SA and it's Python-oriented, so it's a fallback only. Wake words work better with 3+ syllables, which "Hey Lodestar" has. |
| Speech to text | Browser Web Speech API | Whisper in the browser (Transformers.js) or on the server (faster-whisper) for a "private voice" mode | Chrome's Web Speech API sends audio to Google; disclose it in consent. Whisper handles Arabic and French reasonably, Tunisian Derja poorly; say so. |
| Text to speech | Browser SpeechSynthesis | **Kokoro-82M via kokoro-js** (Apache-2.0, runs in the browser, about 300 MB one-time download) | One voice and rate per persona |
| Voice coaching (bonus) | Coach replies are spoken | Lodestar talks you through games ("ready… go") and reads results | Captions always on screen |

**As built (WP2.10).**
- **Tap to talk:** the orb on Home, or Alt+V. A first tap asks for the microphone switch in place.
- **Two ways to listen**, chosen in Settings → Voice. "Your browser" uses Web Speech, and the screen says Chrome sends the audio to Google. "Private" records with an AudioWorklet, converts to 16 kHz mono WAV in the browser, and `POST /voice/transcribe` runs faster-whisper base.en on the server: about 0.4 s for a short request on CPU, model baked into the image. The audio is never stored. Because the browser sends WAV, the server needs no audio codecs; PyAV 19 no longer works with faster-whisper 1.2.1's decoder anyway.
- **Speaking:** replies use the browser's voices, with one rate and pitch per coach. Once someone talks to Lodestar, the replies are spoken too, or always if "Speak Lodestar's replies" is on. Citations like [F1] are left out of speech, and every spoken line is on screen.
- **Themed requests:** a themed request goes to a game that takes themes (`themable` in the registry, Market List today). "Give me a memory game about football" gives "Football memory, coming up: Market List" with the curated football words.
- **Test:** the e2e test plays `tests/fixtures/voice/*.wav` (synthesised with Kokoro-82M) through Chromium's fake microphone.

**As built (WP3.4).**
- **"Hey Lodestar":** Porcupine Web 4.0.1 (`frontend/src/voice/wake.ts`). The person pastes their own Picovoice AccessKey and uploads a "Hey Lodestar" keyword file (.ppn for Web, made in the Picovoice Console) in Settings → Voice. Both stay in that browser's storage and are never sent to Lodestar's server (rule 9; the screen shows only the last 4 characters; a test checks no request carries the key). The engine only runs when it's set up and the microphone switch is on. A wake turn ends by itself after 1.2 s of quiet. With no key, or if the engine can't start, the orb says so and tap-to-talk works exactly as before (tested). `porcupine_params.pv` (Apache-2.0) ships as a Vite asset.
- **False-trigger test:** `frontend/src/voice/wake.test.ts` runs the real engine over background audio and counts detections (allowed: 1 per 30 minutes; Picovoice targets under 1 per 10 hours). It skips unless `PORCUPINE_ACCESS_KEY` and `PORCUPINE_KEYWORD_PPN` are set. By default it uses about 3 minutes built from the speech fixtures and quiet noise; set `WAKE_BACKGROUND_WAV` for the 30-minute run (`tests/fixtures/voice/README.md`).
- **Private, on this device:** a third listening choice runs Whisper base.en (q8, about 80 MB once) in the browser with Transformers.js 4.3.1, so the audio never leaves the device. The server "Private" mode stays as it was, and "Your browser" stays the default.
- **Natural voices:** Kokoro-82M through kokoro-js 1.2.1 (q8, about 90 MB once), one voice per coach (Willow `af_heart`, Spark `am_puck`, Sage `bm_george`, Buddy `am_michael`) at the coach's rate. Lines play one after another; if the model can't load, the browser's voice says the line. kokoro-js brings its own Transformers.js 3.x; both load as separate lazy chunks, so neither is in the main bundle.
- **Voice-guided games:** when replies are spoken, Lodestar reads each game's name and instructions and says "Ready. Go!" on Start. Market List now lists `voice` in its modalities and has a "Say them" button: the transcript is added to the answer box and scored like typing. `voiceAnswer()` in `frontend/src/voice/answer.ts` is the same button for the spoken games (Word Burst, Digits Back, Teach Me).

Audio is discarded after transcription. Transcripts are kept 30 days unless the user pins them (`14`).

## Frustration and fatigue: the main path (no camera, no mic)

This is the mandatory non-biometric mode, and it's also the most reliable path.

**Signals** (computed in the browser and on the server):

- error streaks (3+ misses in a row)
- RT slowdown: z-score against the user's own baseline
- RT variability rising
- rapid repeated clicks or taps
- hint requests in a burst
- quitting mid-game, pressing "too hard?"
- optional one-tap mood check after a round (😀 😐 😣 as large buttons with text labels)

**Model.** P1: weighted rules → `frustration_p`, `fatigue_p`. P2: logistic regression trained on our pilot data, where labels come from the mood check and the "Was I right?" button that appears when Lodestar acts on a frustration guess.

**What it can do:** ease difficulty, switch to a lighter game, suggest a break, soften the coach's tone.
**What it can't do:** change the profile, appear in any score.

Evidence: log-only detectors in tutoring systems reach modest agreement (Baker et al., EDM 2012: average Kappa about 0.30), so we present it as a probability with a feedback button, not a fact.

## Optional camera (bonus "emotion-aware")

**Tool:** MediaPipe Face Landmarker (Apache-2.0), in the browser. We use its **52 blendshapes** (brow furrow, eye closure, mouth press) as expression features, not emotion labels.

**Rules (enforced in code):**

1. Off by default; separate consent switch; can be turned off any time.
2. Frames processed only in the browser; never stored, never sent.
3. Output is one coarse number per 10 seconds: `strain_cue` 0–1.
4. Fused with behaviour, with behaviour weight ≥ 0.7: `affect = 0.7·behaviour + 0.3·mean(available cues)`, where the cues are the camera `strain_cue` and the voice `voice_strain_cue` (below), whichever are switched on.
5. Only affects tone and break suggestions; no write path to the profile (`AGENTS.md` rule 3, with a test).
6. A visible indicator: "Camera signal in use".
7. Wording: "strain cues", never "Lodestar reads your emotions".

**As built (WP3.5).**
- `frontend/src/affect/camera.ts`: while a game is on screen and the Camera switch is on, the camera feeds a detached `<video>` (never on the page) and MediaPipe Face Landmarker (`@mediapipe/tasks-vision` 1.1.1, VIDEO mode, one face). Every 0.5 s, four blendshape groups give a strain score: brow furrow 0.35, eye squint 0.2, mouth press 0.25, eye closure 0.2. Every 10 s the mean becomes the `strain_cue`, rounded to one decimal.
- **Downloads only:** the wasm runtime is bundled and served with the app. The model (`face_landmarker.task`, float16, about 3.7 MB) loads from Google's model storage; set `VITE_FACE_MODEL_URL` to serve it yourself.
- **What leaves the browser:** only the latest cue, sent with the round (`POST /affect/cues`) right before the result. The server refuses a cue whose switch is off, rounds it again, and logs it as an `affect.biometric.cue` event. The monitor reads the session's latest cues from the last 10 minutes and fuses them (`backend/agent/affect.py`). Easing and stopping follow behaviour alone; the fused value can only add a break suggestion and soften the coach's tone.
- **Indicator:** "Camera signal in use" with a "Turn off" button, at the top of the page whenever the camera runs. Turning it off stops the camera and the switch.
- **Tests:** `frontend/src/affect/privacy.test.ts` watches fetch, XMLHttpRequest, WebSocket and sendBeacon: nothing is sent while the camera runs, then one request with one coarse number. `tests/backend/agent/test_biometric_cues.py` checks the switch, the coarse value, the 0.3 fusion, "break, never ease" and an unchanged profile. `test_profile_code_never_imports_affect` also checks that scoring and profile code never mention `affect.biometric`.

**Why so careful:**

- Barrett et al. (2019) reviewed the evidence and found facial movements aren't reliable or specific signs of emotions.
- The EU AI Act (Art. 5(1)(f)) has banned AI emotion inference from biometric data in workplaces and educational institutions since 2 February 2025. We're not in the EU, but our design stays clear of it anyway.

## Optional voice tone (audio capture)

The microphone is already on when the user talks to Lodestar (if they allowed it). With a second, separate switch, Lodestar also reads simple **tone features** from that same audio.

**When audio is captured**

- Only while the user is speaking to Lodestar (after the wake word or tap-to-talk) or answering a spoken game.
- Never in the background. The wake-word engine listens locally for its keyword only and keeps nothing.

**Features** (computed in the browser with an `AudioWorklet` on the Web Audio API):

| Feature | How | What a change can mean |
|---|---|---|
| Speech rate | Syllable-like energy peaks per second | Rushing or slowing down |
| Pause ratio | Share of silence above 300 ms | Hesitation, tiredness |
| Pitch variability | F0 by autocorrelation, standard deviation | Flat or tense voice |
| Loudness trend | RMS level over the utterance | Dropping energy |
| Hesitation words | Count of "um", "uh" in the transcript | Uncertainty (text, not biometric) |

Each feature is compared with **the user's own baseline** (z-score from their first 10 utterances), not with other people. The output is one coarse `voice_strain_cue` 0–1 per utterance.

**Rules:** the same seven as the camera. Separate consent switch, features only (raw audio is never stored and is discarded after transcription), a "Voice signal in use" indicator, fused with behaviour at ≤ 0.3 weight, tone and break suggestions only, no write path to the profile. No speech-emotion model, because it has the same validity problems as faces.

**Spoken game modes** (use the microphone for answers, not tone): Word Burst (say the words), Digits Back (say the digits), Teach Me (explain out loud). Answers are scored from the transcript only; tone features from these are optional and follow the rules above.

**As built (WP3.9).**
- `frontend/src/affect/voiceTone.ts`: with the Voice tone switch on, each tap-to-talk turn (and each spoken answer) also opens an `AudioWorklet` at 16 kHz. It analyses 40 ms windows every 20 ms and posts only two numbers per window (RMS loudness, F0 by normalised autocorrelation, 70–400 Hz); the samples stay on the audio thread. The worklet runs the same `analyseWindow` function as the tests (its source text is put into the worklet).
- **Features per utterance:** speech rate (loudness peaks per second of speaking, pauses left out), pause ratio (silences over 300 ms), pitch SD in semitones, mean loudness in dB and its slope, and hesitation words ("um", "uh", "er", "hmm") per transcript word.
- **Baseline:** the first 10 utterances, kept as sums in this browser's storage (`lodestar.voice.baseline`, removed by "Delete everything"). No cue until it's complete. After that, each feature becomes a z-score with a minimum spread. Rushing or slowing, more pauses, a flatter or quieter voice and more "um" count as strain. The cue is mean(max(0, z)) / 2, capped at 1 and rounded to one decimal.
- **What leaves the browser:** only the latest `voice_strain_cue`, with the next round, through the same `POST /affect/cues` as the camera (refused without the Voice tone switch). The monitor fuses camera and voice as `0.7·behaviour + 0.3·mean(cues)`, so together they never weigh more than 0.3.
- **Indicator:** "Voice signal in use", with "Turn off", while the tone worklet runs.
- **Spoken answers:** `frontend/src/voice/spokenAnswer.ts` has `listenForAnswer({ maxMs, onInterim, onAnswer })`. It needs the Microphone switch (otherwise it throws `MicrophoneOff`, so the game can fall back to typing), adds tone when that switch is on, and stops by itself after `maxMs`. It returns `{ transcript, words, digits }`: `words` drops fillers and punctuation (Word Burst), `digits` reads "four 7 oh two" as [4, 7, 0, 2] (Digits Back), and `transcript` is for Teach Me. Word Burst, Digits Back and Teach Me (and Market List) have a "Say it" button (`frontend/src/voice/answer.ts`, built on `listenForAnswer`) that adds the spoken words, digits or transcript to the same text box, so scoring is unchanged; with the Microphone switch off the button says so and typing still works.
- **Tests:** `frontend/src/affect/voiceTone.test.ts` runs on small synthetic fixtures made on the fly (`frontend/src/test/speechFixtures.ts`: fast, steady, slow, hesitant, flat and quiet speech) and on the real `i_slept_badly.wav`. It also runs the worklet source itself. `frontend/src/affect/privacy.test.ts` shows that only the coarse cue is sent.

## Sources

- Barrett et al. (2019): https://www.semanticscholar.org/paper/Emotional-Expressions-Reconsidered:-Challenges-to-Barrett-Adolphs/c489b6787c5af8aca97f4761343a66f3f189b35d
- EU AI Act emotion recognition ban (summary): https://www.thedelatorrereview.com/prohibited-ai-practices-under-the-eu-ai-act-emotion-recognition-at-work-and-school/
- Baker et al. (EDM 2012): https://educationaldatamining.org/EDM2012/uploads/procs/Full_Papers/edm2012_full_1.pdf
- MediaPipe Face Landmarker: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- openWakeWord: https://github.com/dscripka/openWakeWord
