# 12 · Voice and emotion

## Voice stack

| Part | P1 | P2 | Notes |
|---|---|---|---|
| Summon | Tap-to-talk orb + keyboard shortcut | **"Hey Najma" wake word with Porcupine Web** | Porcupine's free personal tier allows custom wake words for non-commercial use with an access key; check current terms. openWakeWord's code is Apache-2.0 but its pretrained models are CC BY-NC-SA and it's Python-oriented, so it's a fallback only. Wake words work better with 3+ syllables, which "Hey Najma" has. |
| Speech to text | Browser Web Speech API | Whisper in the browser (Transformers.js) or on the server (faster-whisper) for a "private voice" mode | Chrome's Web Speech API sends audio to Google; disclose it in consent. Whisper handles Arabic and French reasonably, Tunisian Derja poorly; say so. |
| Text to speech | Browser SpeechSynthesis | **Kokoro-82M via kokoro-js** (Apache-2.0, runs in the browser, about 300 MB one-time download) | One voice and rate per persona |
| Voice coaching (bonus) | Coach replies are spoken | Najma talks you through games ("ready… go") and reads results | Captions always on screen |

**As built (WP2.10).**
- **Tap to talk:** the orb on Home, or Alt+V. A first tap asks for the microphone switch in place.
- **Two ways to listen**, chosen in Settings → Voice. "Your browser" uses Web Speech, and the screen says Chrome sends the audio to Google. "Private" records with an AudioWorklet, converts to 16 kHz mono WAV in the browser, and `POST /voice/transcribe` runs faster-whisper base.en on the server: about 0.4 s for a short request on CPU, model baked into the image. The audio is never stored. Because the browser sends WAV, the server needs no audio codecs; PyAV 19 no longer works with faster-whisper 1.2.1's decoder anyway.
- **Speaking:** replies use the browser's voices, with one rate and pitch per coach. Once someone talks to Najma, the replies are spoken too, or always if "Speak Najma's replies" is on. Citations like [F1] are left out of speech, and every spoken line is on screen.
- **Themed requests:** a themed request goes to a game that takes themes (`themable` in the registry, Market List today). "Give me a memory game about football" gives "Football memory, coming up: Market List" with the curated football words.
- **Test:** the e2e test plays `tests/fixtures/voice/*.wav` (synthesised with Kokoro-82M) through Chromium's fake microphone.

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

**Model.** P1: weighted rules → `frustration_p`, `fatigue_p`. P2: logistic regression trained on our pilot data, where labels come from the mood check and the "Was I right?" button that appears when Najma acts on a frustration guess.

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
7. Wording: "strain cues", never "Najma reads your emotions".

**Why so careful:**

- Barrett et al. (2019) reviewed the evidence and found facial movements aren't reliable or specific signs of emotions.
- The EU AI Act (Art. 5(1)(f)) has banned AI emotion inference from biometric data in workplaces and educational institutions since 2 February 2025. We're not in the EU, but our design stays clear of it anyway.

## Optional voice tone (audio capture)

The microphone is already on when the user talks to Najma (if they allowed it). With a second, separate switch, Najma also reads simple **tone features** from that same audio.

**When audio is captured**

- Only while the user is speaking to Najma (after the wake word or tap-to-talk) or answering a spoken game.
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

## Sources

- Barrett et al. (2019): https://www.semanticscholar.org/paper/Emotional-Expressions-Reconsidered:-Challenges-to-Barrett-Adolphs/c489b6787c5af8aca97f4761343a66f3f189b35d
- EU AI Act emotion recognition ban (summary): https://www.thedelatorrereview.com/prohibited-ai-practices-under-the-eu-ai-act-emotion-recognition-at-work-and-school/
- Baker et al. (EDM 2012): https://educationaldatamining.org/EDM2012/uploads/procs/Full_Papers/edm2012_full_1.pdf
- MediaPipe Face Landmarker: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- openWakeWord: https://github.com/dscripka/openWakeWord
