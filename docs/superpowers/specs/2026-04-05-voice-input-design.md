# Voice Input & Voice Notes — Design Spec

**Date**: 2026-04-05
**Status**: Approved
**Scope**: Browser voice recording + Telegram voice note transcription for Journal, Notes, and Search

---

## Overview

Add voice input capabilities to SOWKNOW across three features:
- **Journal**: Record voice notes with audio storage + transcription (private by default)
- **Notes**: Dictate into notes with audio attachments + transcript
- **Search**: Speak queries that auto-submit as text (no audio saved)

Additionally, the Telegram bot gains voice note support — voice messages sent to the bot are transcribed via Whisper.cpp and stored as journal entries with audio.

## Transcription Strategy

| Context | Engine | Runs on | Language |
|---------|--------|---------|----------|
| Browser (default) | Web Speech API | Client-side (browser vendor servers) | Auto-detect FR/EN |
| Browser (private mode) | Whisper.cpp via backend | Celery worker | Auto-detect FR/EN |
| Telegram bot | Whisper.cpp | Celery worker | Auto-detect FR/EN |

- Web Speech API is free, real-time, and requires no backend resources
- Whisper.cpp uses the `ggml-small.bin` model (~466MB download, ~200MB RAM at inference)
- Whisper.cpp runs as a subprocess in the existing Celery worker container — no new container

## Frontend Component: `<VoiceRecorder>`

### Props

```tsx
interface VoiceRecorderProps {
  mode: "journal" | "note" | "search";
  onTranscript: (text: string) => void;           // search mode uses this
  onAudioReady: (blob: Blob, transcript: string) => void;  // journal/note modes use this
  locale?: string;  // hint from next-intl, auto-detect overrides
}
```

### Interaction Model (Telegram-style)

**Toggle mode (tap):**
1. Tap mic button — recording starts, button turns red with pulse animation
2. Live waveform bars show audio level (CSS-driven via `AnalyserNode`)
3. Real-time interim transcript appears below (Web Speech API)
4. Tap again — recording stops
5. Preview state: waveform + final transcript, with Send / Cancel / Re-record buttons
6. Send fires `onAudioReady(blob, transcript)`

**Hold-to-talk (long press):**
1. Press and hold mic — recording starts immediately
2. Slide left — "slide to cancel" appears
3. Release — stops recording, enters preview state
4. Release while slid left — cancels recording

**Search mode shortcut:** No preview step. Releasing/tapping stop immediately injects transcript into search input and auto-submits. No audio saved.

### Visual Design
- Circular mic button, vault-amber theme
- Red pulse ring during recording
- Horizontal waveform bars (CSS animation driven by `AnalyserNode` frequency data)
- Muted interim transcript, solid final transcript
- Slide-to-cancel ghost trail on hold mode

### Technical Internals
- `MediaRecorder` API captures audio as WebM/Opus blob
- `SpeechRecognition` (Web Speech API) runs in parallel for real-time transcription
- `AudioContext` + `AnalyserNode` for waveform visualization
- `SpeechRecognition.lang` left unset for auto-detection (FR/EN)
- Graceful degradation: if Web Speech API unavailable (e.g. Firefox), audio is recorded and sent to backend for Whisper.cpp transcription with a "transcribing..." loading state

### Privacy Toggle (Journal & Notes)
- Small shield icon toggle: "Private transcription"
- When enabled: Web Speech API is NOT used. Audio is recorded silently, then sent to backend `POST /api/v1/voice/transcribe` for Whisper.cpp processing
- **Default**: Private ON for journal, OFF for notes, N/A for search
- When private mode is active, interim transcript is replaced by a "will transcribe locally" message

## Browser Integration

### Journal Page (`/[locale]/journal/page.tsx`)

- New "Add Voice Entry" button at top of page
- Expands `<VoiceRecorder mode="journal">` inline
- On send:
  1. Upload audio blob: `POST /api/v1/documents/upload` with `document_type=journal`, `bucket=confidential`, `content_type=audio/webm`, `transcript={text}`
  2. Audio stored as document file, transcript stored as `extracted_text`
- New entry appears in timeline with play button + transcript text
- Play button uses `<audio>` element pointing to `GET /api/v1/audio/{doc_id}/stream`

### Notes Page (`/[locale]/notes/page.tsx`)

- Mic button inside note editor modal, adjacent to content textarea
- Opens `<VoiceRecorder mode="note">` inline below textarea
- On send:
  1. Transcript text **appended** to textarea (not replaced) — allows mixing typed + spoken content
  2. Audio uploaded: `POST /api/v1/notes/{note_id}/audio`
  3. Note can have multiple audio attachments
- Saved note renders audio player(s) alongside text content

### Search Page (`/[locale]/search/page.tsx`)

- Mic icon inside search input (right side)
- Activates `<VoiceRecorder mode="search">` as overlay above input
- On transcript complete:
  1. Text injected into search input
  2. Auto-submits search
  3. No audio saved
- During recording: search input shows pulsing waveform

### Shared Behavior
- `navigator.mediaDevices.getUserMedia` checked on mount
- Permission requested only on first mic tap (not page load)
- If denied: mic button shows tooltip "Microphone access required"
- All browser audio is WebM/Opus format

## Backend Changes

### Modified Endpoint: Document Upload

`POST /api/v1/documents/upload`

Add support for:
- `content_type=audio/webm` and `audio/ogg`
- New optional multipart field `transcript` — if provided, stored as `extracted_text` (skips OCR pipeline)
- Sets `audio_file_path`, `audio_duration_seconds`, `detected_language` on the document row

### New Endpoint: Note Audio Attachment

`POST /api/v1/notes/{note_id}/audio`
- Auth: requires note ownership or admin
- Accepts: multipart audio file + optional `transcript` field
- Stores audio file, creates `note_audio` record
- Returns: `{audio_id, url, duration_seconds, transcript}`

### New Endpoint: Audio Streaming

`GET /api/v1/audio/{audio_id}/stream`
- Auth: same RBAC as parent document/note
- Supports HTTP range requests for seeking
- Returns audio with correct `Content-Type` (audio/webm or audio/ogg)

### New Endpoint: Private Transcription

`POST /api/v1/voice/transcribe`
- Auth: any authenticated user
- Accepts: multipart audio file
- Runs Whisper.cpp on the audio
- Returns: `{transcript, detected_language, duration_seconds}`
- Synchronous with 30s timeout (audio clips are short, <60s typically, ~5-10s processing)
- If audio exceeds 60s, return 413 with "Voice notes must be under 60 seconds"

## Telegram Bot Changes

### Current Flow
User sends text message → saved as journal entry.

### New Voice Note Flow
1. Bot handler detects `message.voice` or `message.audio`
2. Downloads `.ogg` file via Telegram `getFile` API
3. Dispatches Celery task `transcribe_voice_note`:
   - Converts .ogg if needed (Whisper.cpp handles .ogg natively)
   - Runs: `whisper-cpp -m models/ggml-small.bin -f audio.ogg --language auto`
   - Extracts transcript + detected language
4. Stores: audio as document (`document_type=journal`, `bucket=confidential`), transcript as `extracted_text`
5. Bot replies: "Voice note saved" with transcript preview

## Whisper.cpp Setup

- Compiled from source in `Dockerfile.worker` build stage
- Model `ggml-small.bin` downloaded during build (~466MB)
- Binary placed at `/usr/local/bin/whisper-cpp`
- Model at `/app/models/ggml-small.bin`
- Memory: ~200MB transient during transcription, freed after
- Fits within Celery worker's 5632MB memory limit
- No new container required

## Data Model Changes

### Documents Table (existing — add columns)

```sql
ALTER TABLE documents ADD COLUMN audio_file_path TEXT;
ALTER TABLE documents ADD COLUMN audio_duration_seconds FLOAT;
ALTER TABLE documents ADD COLUMN detected_language VARCHAR(5);
```

### Note Audio Table (new)

```sql
CREATE TABLE note_audio (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    note_id UUID NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    duration_seconds FLOAT,
    transcript TEXT,
    detected_language VARCHAR(5),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_note_audio_note_id ON note_audio(note_id);
```

### Alembic Migration
- Single migration file adding the 3 columns + new table
- Reversible (downgrade drops table and columns)

## Audio File Storage

- Path: `./data/audio/{year}/{month}/{uuid}.{ext}`
- Extensions: `.webm` (browser recordings), `.ogg` (Telegram voice notes)
- Same Docker volume mount as document storage
- Same backup policy as documents
- Confidential audio follows bucket isolation (invisible to User role, view-only for Super User)

## Privacy & Security

| Feature | Default Transcription | Audio Sent To | PII Risk |
|---------|----------------------|---------------|----------|
| Journal (browser) | Whisper.cpp (private) | Backend only | None — fully local |
| Notes (browser) | Web Speech API | Browser vendor | Low — user can toggle private |
| Search (browser) | Web Speech API | Browser vendor | Minimal — search queries only |
| Telegram voice | Whisper.cpp | Backend only | None — fully local |

- Journal defaults to private transcription (Whisper.cpp) to match SOWKNOW's privacy-first approach
- Users can toggle private mode on/off for journal and notes
- Search always uses Web Speech API (no sensitive data in queries)
- All audio at rest follows existing RBAC and encryption policies
- Audio playback endpoint enforces same auth as document/note access

## i18n

- All UI labels added to existing next-intl message files (FR + EN)
- Key strings: "Record voice note", "Private transcription", "Slide to cancel", "Transcribing...", "Voice note saved", "Microphone access required"
- No language picker for voice — auto-detection handles FR/EN seamlessly

## Graceful Degradation

| Scenario | Behavior |
|----------|----------|
| Web Speech API unavailable (Firefox) | Record audio, send to backend Whisper.cpp, show "transcribing..." |
| Microphone permission denied | Mic button disabled with tooltip |
| Whisper.cpp backend error | Retry once, then save audio without transcript + flag for manual review |
| Network offline during recording | Recording completes locally, queued for upload when online |
