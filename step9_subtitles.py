#!/usr/bin/env python3
"""
Step 9: Generate SRT subtitles using faster-whisper word timestamps + burn into video
Output: output_dir/subtitles.srt, output_dir/video_subtitled.mp4
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return json.load(f)


def get_audio_duration(path):
    with wave.open(str(path), 'r') as wf:
        return wf.getnframes() / float(wf.getframerate())


def format_srt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_words(model, audio_path, language='ru'):
    """Return list of (start, end, word) tuples using faster-whisper."""
    segments, _ = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language=language,
    )
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append((w.start, w.end, w.word.strip()))
    return words


def words_to_srt_entries(words, time_offset, idx_start, max_chars=40):
    """
    Group words into 2-line subtitle blocks by character limit.
    Each block spans from first to last word's actual timestamp.
    """
    if not words:
        return [], idx_start

    entries = []
    idx = idx_start

    line1_words = []
    line2_words = []
    line1_len = 0
    line2_len = 0
    block_start = None
    block_last_end = None  # end time of last word added to current block

    def flush_block():
        nonlocal idx, block_start, block_last_end
        if not line1_words and not line2_words:
            return
        line1 = ' '.join(line1_words)
        line2 = ' '.join(line2_words)
        text = (line1 + '\n' + line2).strip()
        entries.append((idx, time_offset + block_start, time_offset + block_last_end, text))
        idx += 1
        block_start = None
        block_last_end = None
        line1_words.clear()
        line2_words.clear()

    for start, end, word in words:
        if not word:
            continue

        word_len = len(word) + 1  # +1 for space

        if line1_len == 0:
            block_start = start
            line1_words.append(word)
            line1_len = word_len
            block_last_end = end
        elif line1_len + word_len <= max_chars:
            line1_words.append(word)
            line1_len += word_len
            block_last_end = end
        elif line2_len == 0:
            line2_words.append(word)
            line2_len = word_len
            block_last_end = end
        elif line2_len + word_len <= max_chars:
            line2_words.append(word)
            line2_len += word_len
            block_last_end = end
        else:
            # Block full — flush, start new block with current word
            flush_block()
            block_start = start
            line1_words.append(word)
            line1_len = word_len
            line2_len = 0
            block_last_end = end

    # Flush remaining words
    if line1_words or line2_words:
        flush_block()

    return entries, idx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg['output_dir'])
    audio_dir = output_dir / 'audio'
    font_size = cfg.get('subtitle_font_size', 14)
    whisper_model_size = cfg.get('whisper_model', 'tiny')
    subtitle_lang = cfg.get('subtitle_lang', 'ru')

    video_in = output_dir / 'video_raw.mp4'
    video_out = output_dir / 'video_subtitled.mp4'
    srt_path = output_dir / 'subtitles.srt'

    # Checkpoint
    if video_out.exists():
        size_mb = video_out.stat().st_size / 1024 / 1024
        print(f"  [SKIP] video_subtitled.mp4 already exists ({size_mb:.1f}MB)")
        return

    if not video_in.exists():
        print("  [ERROR] video_raw.mp4 not found")
        sys.exit(1)

    segments_path = output_dir / 'segments.json'
    if not segments_path.exists():
        print("  [ERROR] segments.json not found")
        sys.exit(1)

    data = json.loads(segments_path.read_text())
    segments = data.get('segments', [])

    # Load Whisper model
    print(f"  Loading Whisper model '{whisper_model_size}'...")
    from faster_whisper import WhisperModel
    model = WhisperModel(whisper_model_size, device="cpu", compute_type="int8")

    # Transcribe each segment audio and build SRT
    all_entries = []
    idx = 1
    time_offset = 0.0

    for seg in segments:
        seg_id = seg['id']
        audio_path = audio_dir / f"{seg_id}.wav"
        if not audio_path.exists():
            continue

        dur = get_audio_duration(audio_path)
        words = transcribe_words(model, audio_path, language=subtitle_lang)

        entries, idx = words_to_srt_entries(words, time_offset, idx)
        all_entries.extend(entries)
        time_offset += dur
        print(f"  [SRT] {seg_id}: {dur:.1f}s → {len(words)} words → {len(entries)} subtitle blocks")

    # Write SRT
    srt_lines = []
    for entry_idx, start, end, text in all_entries:
        srt_lines.append(str(entry_idx))
        srt_lines.append(f"{format_srt_time(start)} --> {format_srt_time(end)}")
        srt_lines.append(text)
        srt_lines.append('')

    srt_path.write_text('\n'.join(srt_lines), encoding='utf-8')
    print(f"  [OK] SRT: {len(all_entries)} blocks → {srt_path.name}")

    # Burn subtitles into video
    srt_escaped = str(srt_path).replace("'", "\\'")

    cmd = [
        'ffmpeg', '-y',
        '-i', str(video_in),
        '-vf', (
            f"subtitles='{srt_escaped}':"
            f"force_style='FontName=Arial,FontSize={font_size},"
            f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
            f"BorderStyle=1,Outline=1,Shadow=0,MarginV=20,Bold=0'"
        ),
        '-c:v', 'libx264', '-preset', 'fast', '-crf', str(cfg.get('video_crf', 21)),
        '-c:a', 'copy',
        '-pix_fmt', 'yuv420p',
        str(video_out)
    ]

    print("  Burning subtitles into video...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [ERROR] {result.stderr[-400:]}")
        sys.exit(1)

    size_mb = video_out.stat().st_size / 1024 / 1024
    dur_result = subprocess.run(
        ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
         '-of', 'json', str(video_out)],
        capture_output=True, text=True
    )
    dur = float(json.loads(dur_result.stdout)['format']['duration'])
    print(f"  [OK] video_subtitled.mp4: {dur/60:.1f} min, {size_mb:.1f}MB")


if __name__ == '__main__':
    main()
