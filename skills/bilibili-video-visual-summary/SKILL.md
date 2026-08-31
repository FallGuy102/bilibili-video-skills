---
name: bilibili-video-visual-summary
description: Summarize both spoken content and important on-screen visuals from Bilibili and other video URLs or local video files. Use when slides, formulas, gameplay, interfaces, demonstrations, editing, or visual evidence materially affect the answer. Do not use for speech-only summaries where frame analysis would add unnecessary cost.
---

# Bilibili Video Visual Summary

Combine a timestamped transcript with a deliberately small set of informative frames. This is sparse multimodal inspection, not continuous frame-by-frame viewing; disclose that limitation when motion between samples matters.

## Workflow

1. Obtain text before frames:

   ```bash
   python3 "<skill-dir>/scripts/prepare_transcript.py" "<video-url-or-local-path>" --out-dir "<temporary-dir>/text" --asr none
   ```

   If no usable transcript exists, rerun with `--asr local --model small`. Prefer `base` for ordinary speech and `small` for Chinese technical material.

2. Read the transcript first. Identify moments where the speaker directs attention to the screen, such as “看这里”, “如图”, “这个界面”, “这个公式”, “接下来演示”, or equivalent contextual cues. Record their timestamps.

3. Extract targeted frames plus limited global coverage:

   ```bash
   python3 "<skill-dir>/scripts/extract_frames.py" "<video-url-or-local-path>" --out-dir "<temporary-dir>/visual" --mode scene --max-frames 20 --timestamps "MM:SS,MM:SS"
   ```

   Defaults are intentionally conservative. Use:

   - `--mode keyframes` for a fast structural scan.
   - `--mode scene` for slides, cuts, interfaces, or demonstrations.
   - `--mode uniform` when visual changes are subtle or scene detection under-produces.
   - `--start` and `--end` to inspect a relevant interval densely instead of increasing the whole-video budget.
   - `--resolution 1024` only when small text, formulas, or UI labels are unreadable at the default resolution.

4. Inspect every selected JPEG with the available image-viewing tool. Align each image with the transcript using its timestamp from `frames.json` or `report.md`.

5. Answer from both evidence streams. Separate what was said from what was visibly shown when the distinction matters. Mention sampling limitations for fast action, animation, brief UI changes, or events between frames.

## Frame-budget rules

- Start with 12–30 frames for a typical 10–20 minute explanatory video.
- Prefer transcript-cued frames over a large uniform sample.
- For gameplay or bug reproduction, focus on the relevant short interval and sample more densely; do not use hundreds of frames across the entire video by default.
- Never use an uncapped frame mode. Image context is the dominant cost.
- Do not re-extract frames for follow-up questions while the existing frames and transcript remain available.

## Access and safety

- The helpers use public Bilibili endpoints first and do not read browser cookies automatically.
- If a URL requires login, payment, regional access, or an account session, ask for a user-provided local video instead of bypassing the restriction.
- Local ASR remains local. Ask before installing a substantial model or dependency.

## Output expectations

For an unspecified request, summarize the narrative or argument, important visual evidence, notable transitions or demonstrations, conclusion, and caveats. For game-design footage, distinguish rules explained in speech from behavior demonstrated on screen.
