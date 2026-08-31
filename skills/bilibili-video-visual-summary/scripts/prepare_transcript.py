#!/usr/bin/env python3
"""Prepare low-cost platform text or a local ASR transcript for video summary."""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
BV_RE = re.compile(r"(?i)(BV[0-9A-Za-z]{10})")
TAG_RE = re.compile(r"<[^>]+>")


def request(url: str, referer: str | None = None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    return urlopen(Request(url, headers=headers), timeout=45)


def request_json(url: str, referer: str | None = None) -> dict:
    with request(url, referer) as response:
        return json.loads(response.read().decode("utf-8"))


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def extract_bvid(source: str) -> str | None:
    match = BV_RE.search(source)
    return match.group(1) if match else None


def clean_text(value: str) -> str:
    value = TAG_RE.sub("", html.unescape(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def write_segments(segments: list[dict], path: Path) -> None:
    lines = []
    for item in segments:
        start = float(item.get("from", item.get("start", 0)) or 0)
        end = float(item.get("to", item.get("end", start)) or start)
        text = clean_text(str(item.get("content", item.get("text", ""))))
        if text:
            lines.append(f"[{fmt_time(start)}-{fmt_time(end)}] {text}")
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def parse_vtt_timestamp(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return float(minutes) * 60 + float(seconds)
    hours, minutes, seconds = parts
    return float(hours) * 3600 + float(minutes) * 60 + float(seconds)


def parse_vtt(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if "-->" not in line:
            i += 1
            continue
        left, right = [part.strip().split()[0] for part in line.split("-->", 1)]
        i += 1
        text_lines = []
        while i < len(lines) and lines[i].strip():
            text_lines.append(lines[i].strip())
            i += 1
        text = clean_text(" ".join(text_lines))
        if text:
            out.append({"from": parse_vtt_timestamp(left), "to": parse_vtt_timestamp(right), "content": text})
    return out


def get_bilibili_metadata(source: str, bvid: str) -> dict:
    referer = f"https://www.bilibili.com/video/{bvid}/"
    payload = request_json(
        "https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": bvid}),
        referer,
    )
    if payload.get("code") != 0:
        raise RuntimeError(f"Bilibili metadata error: {payload.get('message') or payload.get('code')}")
    data = payload["data"]
    return {
        "source": source,
        "platform": "bilibili",
        "bvid": bvid,
        "aid": data.get("aid"),
        "cid": data.get("cid") or ((data.get("pages") or [{}])[0].get("cid")),
        "title": data.get("title"),
        "author": (data.get("owner") or {}).get("name"),
        "up_mid": (data.get("owner") or {}).get("mid"),
        "duration": data.get("duration"),
        "description": data.get("desc"),
        "raw_subtitle": data.get("subtitle") or {},
    }


def get_platform_summary(meta: dict, out_dir: Path) -> dict | None:
    if not meta.get("cid") or not meta.get("up_mid"):
        return None
    params = {"bvid": meta["bvid"], "cid": meta["cid"], "up_mid": meta["up_mid"]}
    url = "https://api.bilibili.com/x/web-interface/view/conclusion/get?" + urlencode(params)
    payload = request_json(url, f"https://www.bilibili.com/video/{meta['bvid']}/")
    if payload.get("code") != 0 or not payload.get("data"):
        return None
    (out_dir / "platform_summary.json").write_text(
        json.dumps(payload["data"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload["data"]


def subtitle_candidates(meta: dict) -> list[dict]:
    candidates = list((meta.get("raw_subtitle") or {}).get("list") or [])
    if meta.get("cid"):
        params = {"bvid": meta["bvid"], "cid": meta["cid"]}
        try:
            payload = request_json(
                "https://api.bilibili.com/x/player/v2?" + urlencode(params),
                f"https://www.bilibili.com/video/{meta['bvid']}/",
            )
            subtitle = ((payload.get("data") or {}).get("subtitle") or {})
            candidates.extend(subtitle.get("subtitles") or subtitle.get("list") or [])
        except Exception:
            pass
    seen = set()
    unique = []
    for candidate in candidates:
        url = candidate.get("subtitle_url") or candidate.get("url")
        if url and url not in seen:
            seen.add(url)
            unique.append(candidate)
    return unique


def choose_subtitle(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    def rank(item: dict) -> tuple[int, str]:
        label = " ".join(
            str(item.get(key, "")) for key in ("lan", "lan_doc", "lang", "label")
        ).lower()
        if any(mark in label for mark in ("zh-cn", "zh-hans", "中文", "简体")):
            score = 0
        elif any(mark in label for mark in ("zh", "中文", "繁体")):
            score = 1
        else:
            score = 2
        return score, label

    return sorted(candidates, key=rank)[0]


def fetch_bilibili_subtitle(meta: dict, out_dir: Path) -> Path | None:
    candidate = choose_subtitle(subtitle_candidates(meta))
    if not candidate:
        return None
    url = candidate.get("subtitle_url") or candidate.get("url")
    if url.startswith("//"):
        url = "https:" + url
    payload = request_json(url, f"https://www.bilibili.com/video/{meta['bvid']}/")
    segments = payload.get("body") or payload.get("segments") or []
    if not segments:
        return None
    raw_path = out_dir / "subtitle.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript_path = out_dir / "transcript.txt"
    write_segments(segments, transcript_path)
    return transcript_path


def fetch_ytdlp_captions(source: str, out_dir: Path) -> tuple[Path | None, dict]:
    if not shutil.which("yt-dlp"):
        return None, {}
    cap_dir = out_dir / "captions"
    cap_dir.mkdir(exist_ok=True)
    cmd = [
        "yt-dlp", "--skip-download", "--write-info-json", "--write-subs",
        "--write-auto-subs", "--sub-langs", "all", "--sub-format", "vtt",
        "--convert-subs", "vtt", "--no-playlist", "--ignore-errors",
        "-o", str(cap_dir / "video.%(ext)s"), "--", source,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info = {}
    info_path = cap_dir / "video.info.json"
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    files = sorted(cap_dir.glob("video*.vtt"))
    if not files:
        return None, info
    preferred = [p for p in files if any(x in p.name.lower() for x in ("zh", "chinese"))]
    segments = parse_vtt((preferred or files)[0])
    transcript = out_dir / "transcript.txt"
    write_segments(segments, transcript)
    return transcript, info


def download_bilibili_audio(meta: dict, out_dir: Path) -> Path:
    params = {"bvid": meta["bvid"], "cid": meta["cid"], "fnval": 16, "qn": 64, "fourk": 0}
    referer = f"https://www.bilibili.com/video/{meta['bvid']}/"
    payload = request_json("https://api.bilibili.com/x/player/playurl?" + urlencode(params), referer)
    data = payload.get("data") or {}
    audio = ((data.get("dash") or {}).get("audio") or [])
    if not audio:
        raise RuntimeError("Bilibili did not expose a public audio stream")
    selected = max(audio, key=lambda item: int(item.get("bandwidth") or 0))
    url = selected.get("baseUrl") or selected.get("base_url")
    path = out_dir / "audio.m4s"
    with request(url, referer) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)
    return path


def download_generic_audio(source: str, out_dir: Path) -> Path:
    local = Path(source).expanduser()
    if local.exists():
        return local.resolve()
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is required for non-Bilibili URLs")
    template = str(out_dir / "audio.%(ext)s")
    cmd = ["yt-dlp", "-f", "ba/bestaudio", "--no-playlist", "-o", template, "--", source]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("yt-dlp could not download the audio stream")
    files = [p for p in out_dir.glob("audio.*") if p.suffix != ".part"]
    if not files:
        raise RuntimeError("audio download produced no file")
    return files[0]


def transcribe_local(media_path: Path, transcript_path: Path, model_name: str) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed; install it only after the user approves the model download"
        ) from exc
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(media_path), language="zh", beam_size=1, vad_filter=True
    )
    with transcript_path.open("w", encoding="utf-8") as output:
        for segment in segments:
            text = clean_text(segment.text)
            if text:
                output.write(f"[{fmt_time(segment.start)}-{fmt_time(segment.end)}] {text}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--asr", choices=("none", "local"), default="none")
    parser.add_argument("--model", default="small")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = out_dir / "transcript.txt"
    if args.force and transcript.exists():
        transcript.unlink()

    bvid = extract_bvid(args.source)
    meta: dict = {"source": args.source, "platform": "local" if Path(args.source).expanduser().exists() else "other"}
    platform_summary = None
    errors: list[str] = []

    if bvid:
        try:
            meta = get_bilibili_metadata(args.source, bvid)
            (out_dir / "metadata.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                platform_summary = get_platform_summary(meta, out_dir)
            except Exception as exc:
                errors.append(f"platform summary unavailable: {exc}")
            if not transcript.exists():
                try:
                    fetch_bilibili_subtitle(meta, out_dir)
                except Exception as exc:
                    errors.append(f"Bilibili captions unavailable: {exc}")
            if not transcript.exists():
                try:
                    fetch_ytdlp_captions(args.source, out_dir)
                except Exception as exc:
                    errors.append(f"yt-dlp captions unavailable: {exc}")
        except Exception as exc:
            errors.append(str(exc))
    else:
        try:
            cap_path, info = fetch_ytdlp_captions(args.source, out_dir)
            if info:
                meta.update({
                    "title": info.get("title"), "author": info.get("uploader") or info.get("channel"),
                    "duration": info.get("duration"), "platform": info.get("extractor_key") or meta["platform"],
                })
        except Exception as exc:
            errors.append(f"captions unavailable: {exc}")

    if not transcript.exists() and args.asr == "local":
        try:
            media = download_bilibili_audio(meta, out_dir) if bvid and meta.get("cid") else download_generic_audio(args.source, out_dir)
            transcribe_local(media, transcript, args.model)
        except Exception as exc:
            errors.append(f"local ASR failed: {exc}")

    status = {
        "source": args.source,
        "metadata": meta,
        "transcript_path": str(transcript) if transcript.exists() else None,
        "platform_summary_path": str(out_dir / "platform_summary.json") if platform_summary else None,
        "errors": errors,
    }
    (out_dir / "result.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

    report = ["# Video text preparation", "", f"- Source: {args.source}"]
    for key in ("title", "author", "duration", "platform"):
        if meta.get(key) is not None:
            report.append(f"- {key.title()}: {meta[key]}")
    report.extend([
        f"- Transcript: {status['transcript_path'] or 'not available'}",
        f"- Platform summary: {status['platform_summary_path'] or 'not available'}",
    ])
    if errors:
        report.extend(["", "## Notes", *[f"- {item}" for item in errors]])
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if transcript.exists() or platform_summary else 2


if __name__ == "__main__":
    raise SystemExit(main())
