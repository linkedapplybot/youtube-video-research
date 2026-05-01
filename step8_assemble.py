#!/usr/bin/env python3
"""
Step 8: Assemble video from images + audio using ffmpeg (Ken Burns + crossfade)
Output: output_dir/video_raw.mp4
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

FPS = 25
XFADE_DUR = 0.8   # crossfade between images within segment
SEG_XFADE_DUR = 0.6  # crossfade between segments
KB_VARIATIONS = [
    "zoom-in",   # zoompan zoom in to center
    "zoom-out",  # zoompan zoom out from center
    "pan-lr",    # pan left to right
    "pan-rl",    # pan right to left
]


def load_config(path):
    with open(path) as f:
        return json.load(f)


def get_audio_duration(path):
    with wave.open(str(path), 'r') as wf:
        return wf.getnframes() / float(wf.getframerate())


def get_video_duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'json', str(path)],
        capture_output=True, text=True
    )
    return float(json.loads(result.stdout)['format']['duration'])


def round_frames(duration, fps=FPS):
    return int(duration * fps) / fps


def kb_filter(variation, img_dur, w=1920, h=1080):
    frames = int(img_dur * FPS)
    if variation == "zoom-in":
        return f"zoompan=z='min(zoom+0.0008,1.3)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}"
    elif variation == "zoom-out":
        return f"zoompan=z='if(lte(zoom,1.0),1.3,max(zoom-0.0008,1.0))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}"
    elif variation == "pan-lr":
        return f"zoompan=z='min(zoom+0.0006,1.2)':x='iw/2-(iw/zoom/2)+((zoom-1)*iw/4)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}"
    else:  # pan-rl
        return f"zoompan=z='min(zoom+0.0006,1.2)':x='iw/2-(iw/zoom/2)-((zoom-1)*iw/4)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={FPS}"


def build_segment(seg_id, images, audio_path, out_path, is_first, is_last, cfg):
    w = cfg.get('video_width', 1920)
    h = cfg.get('video_height', 1080)
    fps = cfg.get('video_fps', FPS)
    crf = cfg.get('video_crf', 21)

    audio_dur = get_audio_duration(audio_path)
    n = len(images)
    img_dur = audio_dur / n

    inputs = []
    for img in images:
        inputs += ['-loop', '1', '-t', str(img_dur + XFADE_DUR), '-i', str(img)]
    inputs += ['-i', str(audio_path)]

    audio_idx = n
    filter_parts = []

    for i in range(n):
        variation = KB_VARIATIONS[i % len(KB_VARIATIONS)]
        kbf = kb_filter(variation, img_dur, w, h)
        filter_parts.append(f"[{i}:v]scale={w*2}:{h*2},setsar=1,{kbf},vignette=PI/4[v{i}]")

    # Chain xfades
    if n == 1:
        cur = "v0"
    else:
        actual = round_frames(img_dur, fps)
        filter_parts.append(f"[v0][v1]xfade=transition=fade:duration={XFADE_DUR}:offset={actual}[xf1]")
        for k in range(2, n):
            offset = actual * k
            filter_parts.append(f"[xf{k-1}][v{k}]xfade=transition=fade:duration={XFADE_DUR}:offset={offset}[xf{k}]")
        cur = f"xf{n-1}"

    # Fade in/out
    if is_first:
        filter_parts.append(f"[{cur}]fade=t=in:st=0:d=1.5[faded]")
        cur = "faded"
    if is_last:
        fade_st = max(0, audio_dur - 2.0)
        filter_parts.append(f"[{cur}]fade=t=out:st={fade_st:.2f}:d=2.0[final]")
        cur = "final"

    filter_str = ';'.join(filter_parts)

    cmd = [
        'ffmpeg', '-y', *inputs,
        '-filter_complex', filter_str,
        '-map', f'[{cur}]', '-map', f'{audio_idx}:a',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p', '-r', str(fps), '-shortest',
        str(out_path)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [WARN] Ken Burns failed for {seg_id}, using simple fallback")
        return build_segment_simple(seg_id, images, audio_path, audio_dur, out_path, cfg)
    return True


def build_segment_simple(seg_id, images, audio_path, audio_dur, out_path, cfg):
    """Simple fallback: concat images without Ken Burns"""
    img_dur = audio_dur / len(images)
    concat_file = out_path.parent / f'_tmp_concat_{seg_id}.txt'
    with open(concat_file, 'w') as f:
        for img in images:
            f.write(f"file '{img}'\nduration {img_dur}\n")
        f.write(f"file '{images[-1]}'\n")

    w = cfg.get('video_width', 1920)
    h = cfg.get('video_height', 1080)
    fps = cfg.get('video_fps', FPS)
    crf = cfg.get('video_crf', 21)

    cmd = [
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0', '-i', str(concat_file),
        '-i', str(audio_path),
        '-vf', f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf),
        '-c:a', 'aac', '-b:a', '192k',
        '-pix_fmt', 'yuv420p', '-r', str(fps), '-shortest',
        str(out_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_file.unlink(missing_ok=True)
    return result.returncode == 0


def concat_segments_simple(seg_videos, out_path):
    """Concatenate segments with simple file concat"""
    concat_file = out_path.parent / '_tmp_final_concat.txt'
    with open(concat_file, 'w') as f:
        for v in seg_videos:
            f.write(f"file '{v}'\n")

    cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file),
           '-c', 'copy', str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_file.unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"  [ERROR] {result.stderr[-300:]}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg['output_dir'])
    images_dir = output_dir / 'images'
    audio_dir = output_dir / 'audio'
    final_path = output_dir / 'video_raw.mp4'

    # Checkpoint
    if final_path.exists():
        size_mb = final_path.stat().st_size / 1024 / 1024
        print(f"  [SKIP] video_raw.mp4 already exists ({size_mb:.1f}MB)")
        return

    segments_path = output_dir / 'segments.json'
    if not segments_path.exists():
        print("  [ERROR] segments.json not found")
        sys.exit(1)

    data = json.loads(segments_path.read_text())
    segments = data.get('segments', [])

    seg_videos = []
    for i, seg in enumerate(segments):
        seg_id = seg['id']
        audio_path = audio_dir / f"{seg_id}.wav"
        if not audio_path.exists():
            print(f"  [SKIP] No audio for {seg_id}")
            continue

        images = sorted(images_dir.glob(f"{seg_id}_*.png"))
        if not images:
            # Try without segment images - use a placeholder color
            print(f"  [WARN] No images for {seg_id}, skipping segment")
            continue

        seg_out = output_dir / f'_seg_{seg_id}.mp4'
        if seg_out.exists():
            print(f"  [SKIP] {seg_out.name} already exists")
        else:
            print(f"  [SEG] {seg_id}: {len(images)} images, {get_audio_duration(audio_path):.1f}s")
            is_first = (i == 0)
            is_last = (i == len(segments) - 1)
            ok = build_segment(seg_id, images, audio_path, seg_out, is_first, is_last, cfg)
            if not ok:
                print(f"  [ERROR] Failed to build segment {seg_id}")
                continue

        seg_videos.append(seg_out)

    if not seg_videos:
        print("  [ERROR] No segments to concatenate")
        sys.exit(1)

    print(f"\n  Concatenating {len(seg_videos)} segments...")
    ok = concat_segments_simple(seg_videos, final_path)

    if ok:
        size_mb = final_path.stat().st_size / 1024 / 1024
        print(f"  [OK] video_raw.mp4: {size_mb:.1f}MB")
    else:
        print("  [ERROR] Concatenation failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
