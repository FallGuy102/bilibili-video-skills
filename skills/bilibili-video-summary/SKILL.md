---
name: bilibili-video-summary
description: Summarize the spoken or captioned content of Bilibili and other video URLs or local video files without inspecting visual frames. Use for content summaries, arguments, structure, notes, and timestamped speech analysis when the user does not need information shown only on screen. Do not use for gameplay, slides, interfaces, demonstrations, or other requests where the visuals materially affect the answer.
---

# Bilibili Video Summary

Produce a source-grounded summary from platform text, captions, or audio. Never infer visual events because this skill intentionally does not inspect frames.

## Workflow

1. Run the cheap pass first:

   ```bash
   python3 "<skill-dir>/scripts/prepare_transcript.py" "<video-url-or-local-path>" --out-dir "<temporary-dir>" --asr none
   ```

   The helper checks, in order: Bilibili metadata and in-platform AI summary, exposed manual/AI captions, then generic `yt-dlp` captions. It does not download media during this pass.

2. If the result contains a transcript, summarize it. If only a platform AI summary is available, use it for a quick overview but identify it as a platform-generated summary. For a detailed or high-confidence request, continue to audio transcription.

3. Only when usable text is unavailable or insufficient, run the local ASR fallback:

   ```bash
   python3 "<skill-dir>/scripts/prepare_transcript.py" "<video-url-or-local-path>" --out-dir "<same-temporary-dir>" --asr local --model small
   ```

   Use `base` for ordinary conversational material when speed matters. Use `small` for Chinese technical, academic, or terminology-heavy material. Reuse the same output directory so completed work is cached.

4. Read `report.md`, `transcript.txt`, and `platform_summary.json` when present. Distinguish clearly between the uploader's claims, platform-generated text, transcription uncertainty, and independently verified facts.

5. Answer with the requested level of detail. Include timestamps when they improve usability. Do not paste the whole transcript unless explicitly requested.

## Cost and reliability rules

- Prefer existing captions over ASR. ASR is the expensive fallback.
- Do not convert compressed audio to WAV; `faster-whisper` can read the downloaded stream directly.
- Never download the video track in this skill.
- Do not read browser cookies automatically. If public access fails, explain the limitation or ask the user for a local file; do not bypass login, payment, region, or account restrictions.
- If `faster-whisper` is missing, explain that local transcription requires it and a model download. Ask before installing substantial dependencies.
- Preserve uncertainty around names, formulas, numbers, and uncommon terminology. Use context to correct obvious ASR mistakes, but do not silently invent a correction.

## Output expectations

For an unspecified summary request, cover the central claim, supporting structure, important examples, conclusion, and material caveats. State explicitly that visuals were not analyzed when that limitation could matter.
