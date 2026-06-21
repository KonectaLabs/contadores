# Plan 098: Cap Inbound WhatsApp Media Download And Transcription

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/providers.py src/backend/audio_transcription.py src/backend/endpoints/contadores.py src/bot/tests/test_whatsapp_inbound_provider.py src/backend/tests/test_audio_transcription.py src/backend/tests/test_contadores.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 047
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: MEDIA-05

## Why This Matters

Inbound WhatsApp media is downloaded into the shared data volume, and inbound audio is then sent through ffmpeg/OpenAI transcription. There is no app-level file-size or audio-duration guard in the download/transcription path. A large inbound media file can consume disk, CPU, memory, or transcription spend before the app decides it should become a human-handled media message.

Plan 077 caps authenticated CRM manual uploads. This plan covers provider-originated inbound media.

## Current State

- Inbound media is downloaded directly to `data/contadores/inbound_media`:

```python
src/bot/providers.py:1442
async def _download_inbound_media(self, *, media_type: str, media: Any) -> str | None:
```

```python
src/bot/providers.py:1448
data_dir = Path(os.getenv("DATA_DIR", Path.cwd() / "data")).expanduser().resolve()
```

```python
src/bot/providers.py:1457
downloaded = await media.download(path=target_dir, filename=filename)
```

- The bot records the downloaded path on the inbound event:

```python
src/bot/providers.py:1541
media_path = await self._download_inbound_media(media_type=event.media_type, media=media)
```

```python
src/bot/providers.py:1547
event.media_path = media_path
```

- Audio transcription opens the whole source or converted file:

```python
src/backend/audio_transcription.py:107
def transcribe_audio_media(media_path: str | None, *, mime_type: str | None = None) -> str:
```

```python
src/backend/audio_transcription.py:118
upload_path = _transcription_source_path(source_path, mime_type, temp_dir)
```

```python
src/backend/audio_transcription.py:120
with upload_path.open("rb") as audio_file:
```

- ffmpeg conversion has no explicit duration/size guard:

```python
src/backend/audio_transcription.py:79
command = [
```

```python
src/backend/audio_transcription.py:93
completed = subprocess.run(command, capture_output=True, text=True, check=False)
```

- README documents inbound audio transcription but not size/duration limits:

```markdown
README.md:1180
- Los audios inbound se transcriben antes de llegar al bot con
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Inbound media scan | `rg -n "download_inbound_media|transcribe_audio_media|WA_INBOUND|MAX.*MEDIA|AUDIO.*MAX|inbound_media" src/bot/providers.py src/backend/audio_transcription.py src/backend/endpoints/contadores.py .env.example README.md src/bot/tests src/backend/tests` | inbound caps and tests are visible |
| Bot inbound tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/bot/tests/test_whatsapp_inbound_provider.py -k "media or audio" -q` | exit 0 |
| Audio tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_audio_transcription.py src/backend/tests/test_contadores.py -k "audio_transcription or inbound_audio" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/bot/providers.py src/backend/audio_transcription.py src/backend/endpoints/contadores.py` | exit 0 |

## Scope

**In scope**:
- Add app-level inbound media size limits before or immediately after provider download.
- Add audio transcription file-size and duration limits before ffmpeg/OpenAI work.
- Keep failed/oversized media as media-only human-handled messages, not dropped conversations.
- Add env-configurable limits if operators need tuning.
- Document limits in `.env.example` and README.

**Out of scope**:
- Manual outbound media upload caps; plan 077 covers that.
- Workstation media retention; plan 048 covers pruning.
- Data backup/restore; plan 047 covers shared data volume protection.
- Changing OpenAI transcription model or using local Whisper.

## Git Workflow

- Branch: `codex/cap-inbound-whatsapp-media`
- Commit message: `Cap inbound WhatsApp media handling`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define conservative limits

Choose readable defaults, for example:

- max inbound media bytes,
- max audio transcription bytes,
- max audio duration seconds if duration can be detected cheaply.

Prefer env vars with documented defaults only where operations need flexibility.

### Step 2: Guard provider download

If the media object exposes size metadata, reject before download.

If it does not, check file size immediately after download and delete oversized files before returning `media_path`.

The inbound event should still be processed as a media placeholder with a reason visible in logs or backend metadata.

### Step 3: Guard transcription

Before ffmpeg or OpenAI upload:

- check source file size,
- check converted file size,
- optionally use ffprobe or safe metadata when available for duration.

Oversized audio should skip transcription and remain an audio media message for human review.

### Step 4: Add tests

Cover:

- oversized media download is not persisted as playable media,
- oversized audio skips transcription,
- valid small audio still transcribes,
- failed transcription still preserves the original audio behavior.

### Step 5: Document operator behavior

Update README and `.env.example` to explain:

- default limits,
- what happens when audio is too large,
- that humans still see media-only messages.

## Test Plan

- Bot inbound media tests pass.
- Audio transcription tests pass.
- Contadores inbound audio tests pass.
- No live provider or OpenAI calls are made in tests.

## Done Criteria

- [ ] Inbound media has app-level size limits.
- [ ] Audio transcription has size and duration safeguards.
- [ ] Oversized media becomes a safe human-review path, not a failed conversation.
- [ ] Limits are tested and documented.

## STOP Conditions

- The WhatsApp provider library cannot expose or safely clean up oversized downloads.
- Real inbound media commonly exceeds proposed defaults and product owner input is needed.
- ffprobe/ffmpeg duration checks would introduce brittle runtime dependencies beyond existing ffmpeg conversion.

## Maintenance Notes

Keep the fallback behavior human-safe: if transcription cannot run, preserve the media placeholder and avoid inventing content.
