#!/usr/bin/env python3
"""Download a public video track when needed and extract bounded visual frames."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36"
BV_RE = re.compile(r"(?i)(BV[0-9A-Za-z]{10})")
PTS_RE = re.compile(r"pts_time:([0-9.]+)")


def parse_time(value: str | None) -> float | None:
    if value is None:
        return None
    parts = value.strip().split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    raise ValueError(f"invalid timestamp: {value}")


def fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def request_json(url: str, referer: str) -> dict:
    req = Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urlopen(req, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def request_stream(url: str, referer: str, path: Path) -> None:
    req = Request(url, headers={"User-Agent": UA, "Referer": referer})
    with urlopen(req, timeout=60) as response, path.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def bilibili_video(source: str, out_dir: Path) -> tuple[Path, dict]:
    match = BV_RE.search(source)
    if not match:
        raise RuntimeError("missing BV id")
    bvid = match.group(1)
    referer = f"https://www.bilibili.com/video/{bvid}/"
    view = request_json(
        "https://api.bilibili.com/x/web-interface/view?" + urlencode({"bvid": bvid}), referer
    )
    if view.get("code") != 0:
        raise RuntimeError(f"Bilibili metadata error: {view.get('message')}")
    data = view["data"]
    cid = data.get("cid") or ((data.get("pages") or [{}])[0].get("cid"))
    params = {"bvid": bvid, "cid": cid, "fnval": 16, "qn": 64, "fourk": 0}
    play = request_json(
        "https://api.bilibili.com/x/player/playurl?" + urlencode(params), referer
    )
    videos = (((play.get("data") or {}).get("dash") or {}).get("video") or [])
    if not videos:
        raise RuntimeError("Bilibili did not expose a public video stream")
    avc = [item for item in videos if item.get("codecid") == 7 or "avc" in str(item.get("codecs", ""))]
    candidates = [item for item in (avc or videos) if int(item.get("height") or 0) <= 720] or (avc or videos)
    selected = max(candidates, key=lambda item: int(item.get("bandwidth") or 0))
    url = selected.get("baseUrl") or selected.get("base_url")
    path = out_dir / "video.m4s"
    if not path.exists():
        request_stream(url, referer, path)
    return path, {
        "platform": "bilibili", "bvid": bvid, "cid": cid, "title": data.get("title"),
        "author": (data.get("owner") or {}).get("name"), "duration": data.get("duration"),
        "width": selected.get("width"), "height": selected.get("height"),
    }


def generic_video(source: str, out_dir: Path) -> tuple[Path, dict]:
    local = Path(source).expanduser()
    if local.exists():
        return local.resolve(), {"platform": "local", "title": local.name}
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp is required for non-Bilibili URLs")
    template = str(out_dir / "video.%(ext)s")
    cmd = [
        "yt-dlp", "-f", "bv*[height<=720]/b[height<=720]", "--no-playlist",
        "--write-info-json", "-o", template, "--", source,
    ]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("yt-dlp could not download the public video")
    files = [p for p in out_dir.glob("video.*") if p.suffix not in (".json", ".part")]
    if not files:
        raise RuntimeError("video download produced no file")
    info = {"platform": "other", "source": source}
    info_path = out_dir / "video.info.json"
    if info_path.exists():
        try:
            raw = json.loads(info_path.read_text(encoding="utf-8"))
            info.update({"title": raw.get("title"), "author": raw.get("uploader"), "duration": raw.get("duration")})
        except Exception:
            pass
    return files[0], info


def duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffprobe failed")
    return float(result.stdout.strip())


def scale_filter(width: int) -> str:
    return f"scale={width}:-2:force_original_aspect_ratio=decrease"


def run_candidate_extraction(
    video: Path,
    candidate_dir: Path,
    mode: str,
    width: int,
    start: float,
    end: float,
) -> list[dict]:
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for old in candidate_dir.glob("*.jpg"):
        old.unlink()
    output = str(candidate_dir / "candidate_%05d.jpg")
    base = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y"]
    if start > 0:
        base += ["-ss", f"{start:.3f}"]
    if end > start:
        base += ["-to", f"{end:.3f}"]
    if mode == "keyframes":
        cmd = base + [
            "-skip_frame", "nokey", "-i", str(video), "-vf", f"{scale_filter(width)},showinfo",
            "-fps_mode", "vfr", "-q:v", "4", output,
        ]
    elif mode == "scene":
        vf = f"select='eq(n\\,0)+gt(scene\\,0.28)',{scale_filter(width)},showinfo"
        cmd = base + ["-i", str(video), "-vf", vf, "-fps_mode", "vfr", "-q:v", "4", output]
    else:
        raise ValueError(mode)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg frame extraction failed")
    timestamps = [start + float(value) for value in PTS_RE.findall(result.stderr)]
    files = sorted(candidate_dir.glob("candidate_*.jpg"))
    return [
        {"path": path, "timestamp": timestamps[i] if i < len(timestamps) else start, "reason": mode}
        for i, path in enumerate(files)
    ]


def exact_frame(video: Path, path: Path, timestamp: float, width: int) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{timestamp:.3f}",
        "-i", str(video), "-frames:v", "1", "-vf", scale_filter(width), "-q:v", "4", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not extract frame at {timestamp}")


def even_times(start: float, end: float, count: int) -> list[float]:
    if count <= 1:
        return [start]
    return [start + i * (end - start) / (count - 1) for i in range(count)]


def even_sample(items: list[dict], count: int) -> list[dict]:
    if len(items) <= count:
        return items
    indices = [round(i * (len(items) - 1) / (count - 1)) for i in range(count)] if count > 1 else [0]
    return [items[index] for index in indices]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", choices=("keyframes", "scene", "uniform"), default="scene")
    parser.add_argument("--max-frames", type=int, default=20)
    parser.add_argument("--timestamps", default="")
    parser.add_argument("--resolution", type=int, default=640)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required")
    if args.max_frames < 1:
        raise SystemExit("--max-frames must be positive")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    media_dir = out_dir / "media"
    media_dir.mkdir(exist_ok=True)
    bvid = BV_RE.search(args.source)
    video, meta = bilibili_video(args.source, media_dir) if bvid else generic_video(args.source, media_dir)
    full_duration = duration(video)
    start = parse_time(args.start) or 0.0
    end = parse_time(args.end) if args.end else full_duration
    end = min(float(end), full_duration)
    if end <= start:
        raise SystemExit("focus range is empty")

    frame_dir = out_dir / "frames"
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir()

    pinned = [parse_time(item) for item in args.timestamps.split(",") if item.strip()]
    pinned = sorted({float(item) for item in pinned if item is not None and start <= float(item) <= end})
    global_budget = max(0, args.max_frames - len(pinned))

    selected: list[dict] = []
    if global_budget:
        if args.mode == "uniform":
            selected = [{"timestamp": value, "reason": "uniform", "path": None} for value in even_times(start, end, global_budget)]
        else:
            candidates = run_candidate_extraction(
                video, out_dir / "candidates", args.mode, args.resolution, start, end
            )
            selected = even_sample(candidates, global_budget)
            if len(selected) < min(4, global_budget):
                selected = [{"timestamp": value, "reason": "uniform-fallback", "path": None} for value in even_times(start, end, global_budget)]

    combined = selected + [{"timestamp": value, "reason": "transcript-cue", "path": None} for value in pinned]
    combined.sort(key=lambda item: float(item["timestamp"]))
    deduped: list[dict] = []
    for item in combined:
        if deduped and abs(float(item["timestamp"]) - float(deduped[-1]["timestamp"])) < 1.0:
            if item["reason"] == "transcript-cue":
                deduped[-1] = item
            continue
        deduped.append(item)

    output_items = []
    for index, item in enumerate(deduped):
        timestamp = float(item["timestamp"])
        target = frame_dir / f"frame_{index:03d}_{int(timestamp):06d}.jpg"
        source_path = item.get("path")
        if source_path and Path(source_path).exists():
            shutil.copy2(source_path, target)
        else:
            exact_frame(video, target, timestamp, args.resolution)
        output_items.append({
            "index": index, "timestamp_seconds": round(timestamp, 3), "timestamp": fmt_time(timestamp),
            "reason": item["reason"], "path": str(target),
        })

    candidates_dir = out_dir / "candidates"
    if candidates_dir.exists():
        shutil.rmtree(candidates_dir)

    result = {
        "source": args.source, "metadata": meta, "video_path": str(video),
        "duration": full_duration, "focus": {"start": start, "end": end},
        "mode": args.mode, "resolution": args.resolution, "frames": output_items,
    }
    (out_dir / "frames.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        "# Video visual preparation", "", f"- Source: {args.source}",
        f"- Mode: {args.mode}", f"- Focus: {fmt_time(start)}–{fmt_time(end)}",
        f"- Frames: {len(output_items)}", "", "## Selected frames", "",
    ]
    report.extend(
        f"- {item['timestamp']} — {item['reason']} — `{item['path']}`" for item in output_items
    )
    (out_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
