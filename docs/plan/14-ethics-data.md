# 14 · Ethics and data

The brief requires consent, retention and deletion to be documented, and no sensitive decision on face or voice alone. Safety is one of the scoring criteria.

## Consent (layered)

| Switch | Default | Required? | What it allows |
|---|---|---|---|
| Core practice data | On | **Yes** (the app can't work without it) | Game results, profile, memory notes |
| Cloud AI | Off until the user adds a key | No | Sending **de-identified facts packets** (no name, no raw events) to the hosted provider the user picked, with their own key. The consent screen names the provider and where it processes data. Off = local Ollama model |
| Microphone | Off | No | Voice commands; Web Speech API sends audio to Google, private mode uses Whisper |
| Camera | Off | No | Local strain cues only (`12`) |
| Voice tone | Off | No | Local speech-rate and pause features |
| Deliberate-mistake games | On, disclosed | No | Spot the AI's Mistake and wrong hints for the ACS |
| Research export | Off | No | Anonymised data for the team's evaluation |

Each switch is logged as a `consent.changed` event with the notice version. Turning a switch off stops that processing immediately.

**Age:** 18+ gate in the prototype. Tunisian law requires a guardian's consent for minors, so a guardian flow is listed as future work.

## Retention

| Data | Kept for |
|---|---|
| Camera frames | **Never stored** |
| Raw audio | Discarded right after transcription |
| Transcripts | 30 days unless pinned |
| Trial events and profile history | 12 months, or until deletion |
| Memory notes (Qdrant + `core.md`) | Until the user deletes them; unused memories decay (`04`) |
| Checkpoints and traces | 30 days |
| API keys | Until the user removes them or deletes their account; encrypted at rest, never exported |

A daily retention job enforces this and logs what it removed (counts only). Old trial events go by dropping monthly Postgres partitions.

## User rights in the app

- **See:** the Memory & data screen shows `core.md`, life context, and all memories.
- **AI keys:** see which providers have a key (last 4 characters only), replace or remove any of them.
- **Edit:** delete or correct any memory line.
- **Export:** one click; a download generated on request from Postgres, Qdrant and the Markdown notes. Nothing is saved on the server.
- **Delete:** one click (with a confirmation step in the page). One Postgres cascade, LangGraph checkpoint threads, Qdrant points and the Markdown notes are removed, followed by a receipt with counts (`04`).

## No sensitive decision on face or voice

- Biometric-derived signals (`affect.biometric.*`) have **no write path** to the profile, scores or plan. A test enforces this.
- They can only influence tone and break suggestions, always fused with behaviour (weight ≥ 0.7).
- The UI shows when a camera or voice signal is in use.

## Tunisian law

- **Organic Law 2004-63 (27 July 2004)** governs personal data in Tunisia. It requires prior declaration of processing to the INPDP, consent that can be withdrawn, a guardian's consent for children, and INPDP authorisation for transfers abroad.
- For the competition prototype we state that processing would be declared to the INPDP before any real deployment.
- **Transfers abroad** (for example, to the US- or China-hosted LLM API the user picked) are the sensitive part. Our answers: only de-identified facts packets leave the server, explicit consent for cloud AI, and a fully local mode.
- A GDPR-aligned replacement bill (PLO 095/2025) is before the Assembly; describe it as pending, not in force. We design to GDPR principles (minimisation, purpose limitation, privacy by design) so we're ready either way.

## EU AI Act awareness

Not legally binding on us, but we follow its spirit:

- Emotion inference from biometrics is banned in EU education and workplaces since 2 Feb 2025 (Art. 5(1)(f)). Our camera feature gives coarse strain cues, never emotion labels, and never affects decisions.
- Fatigue and text sentiment are outside the definition, which is why our main affect path uses behaviour.

## Non-clinical stance

- Language rules in `09`.
- Diagnosis requests get a fixed redirect to professionals.
- Every forecast reads as a statistical estimate.
- Disclaimer on onboarding and the Twin page: "Najma is a practice coach. It doesn't assess medical or psychological conditions."

## Bias and fairness notes

- Norms come from mostly English-speaking online users; may not fit Tunisian students.
- Verbal tasks in English disadvantage Arabic and French speakers; flagged on those dimensions.
- Device and keyboard lag affects RT; we calibrate at onboarding.
- No demographics used in any model input.

## Sources

- Tunisia data protection factsheet: https://dataprotection.africa/wp-content/uploads/2019/10/Tunisia-Factsheet.pdf
- Reform bill overview: https://globallawexperts.com/tunisia-moves-replace-its-twentyyearold-data/
