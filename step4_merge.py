#!/usr/bin/env python3
"""
Step 4: Merge subtitles + metadata + comments into text files for NotebookLM
Output: output_dir/data_part_NN.txt (max 490KB each)
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

MAX_FILE_SIZE = 490 * 1024   # 490KB
MAX_TRANSCRIPT_CHARS = 8000  # truncate very long transcripts


def load_config(path):
    with open(path) as f:
        return json.load(f)


def clean_srt(content):
    content = re.sub(r'^WEBVTT.*?\n\n', '', content, flags=re.DOTALL)
    content = re.sub(r'\d+\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\n', '', content)
    content = re.sub(r'\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}[,\.]\d{3}.*?\n', '', content)
    content = re.sub(r'<[^>]+>', '', content)
    content = re.sub(r'\{[^}]+\}', '', content)
    lines = [l.strip() for l in content.split('\n') if l.strip()]
    deduped, prev = [], None
    for line in lines:
        if line != prev:
            deduped.append(line)
        prev = line
    return ' '.join(deduped)


def get_subtitle(video_id, subs_dir):
    for ext in ['en-orig.srt', 'en.srt', 'ru-orig.srt', 'ru.srt',
                'en-orig.vtt', 'en.vtt', 'ru-orig.vtt', 'ru.vtt']:
        path = Path(subs_dir) / f'{video_id}.{ext}'
        if path.exists():
            try:
                return clean_srt(path.read_text(encoding='utf-8', errors='ignore'))
            except Exception:
                pass
    return ''


def get_comments(video_id, comm_dir):
    path = Path(comm_dir) / f'{video_id}.info.json'
    if not path.exists():
        return [], 0
    try:
        data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
        comments = data.get('comments', [])
        result = []
        for c in comments[:100]:
            text = c.get('text', '').replace('\n', ' ').strip()
            if text:
                result.append(f"[{c.get('author','?')}] ({c.get('like_count',0)}): {text}")
        return result, len(comments)
    except Exception:
        return [], 0


def get_title(video_id, meta_dir):
    for pattern in [f'{video_id}.info.json', f'{video_id}.*.info.json']:
        for path in glob.glob(str(Path(meta_dir) / pattern)):
            try:
                data = json.loads(Path(path).read_text(encoding='utf-8', errors='ignore'))
                return data.get('title', video_id)
            except Exception:
                pass
    return video_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    work_dir = Path(cfg['work_dir'])
    output_dir = Path(cfg['output_dir'])
    slug = cfg['slug']

    subs_dir = work_dir / 'subtitles'
    meta_dir = work_dir / 'metadata'
    comm_dir = work_dir / 'comments'
    ids_path = work_dir / 'video_ids.txt'

    # Checkpoint
    existing = list(output_dir.glob(f'{slug}_data_part_*.txt'))
    if existing:
        print(f"  [SKIP] {len(existing)} data files already exist")
        return

    video_ids = [l.strip() for l in ids_path.read_text().split('\n') if l.strip()]
    print(f"  Processing {len(video_ids)} videos...")

    current_blocks = []
    current_size = 0
    file_index = 1
    stats = {'with_subs': 0, 'with_comments': 0, 'total_comments': 0}

    def flush():
        nonlocal file_index, current_blocks, current_size
        if not current_blocks:
            return
        out_path = output_dir / f'{slug}_data_part_{file_index:02d}.txt'
        out_path.write_text('\n\n'.join(current_blocks), encoding='utf-8')
        size_kb = current_size // 1024
        print(f"  Written: {out_path.name} ({size_kb}KB, {len(current_blocks)} videos)")
        file_index += 1
        current_blocks.clear()
        current_size = 0

    for vid_id in video_ids:
        title = get_title(vid_id, meta_dir)
        subs = get_subtitle(vid_id, subs_dir)
        comments, n_comments = get_comments(vid_id, comm_dir)

        if subs:
            stats['with_subs'] += 1
        if comments:
            stats['with_comments'] += 1
            stats['total_comments'] += n_comments

        subs_text = subs[:MAX_TRANSCRIPT_CHARS] + '...[truncated]' if len(subs) > MAX_TRANSCRIPT_CHARS else subs
        comments_text = '\n'.join(comments) if comments else '(no comments)'

        block = (
            f"{'='*60}\n"
            f"VIDEO: {title}\nID: {vid_id}\n"
            f"{'='*60}\n\n"
            f"--- TRANSCRIPT ---\n{subs_text if subs_text else '(no transcript)'}\n\n"
            f"--- COMMENTS ({n_comments}) ---\n{comments_text}"
        )

        block_size = len(block.encode('utf-8'))
        if current_size + block_size > MAX_FILE_SIZE and current_blocks:
            flush()

        current_blocks.append(block)
        current_size += block_size

    flush()

    print(f"\n  Stats: {stats['with_subs']} with subtitles, "
          f"{stats['with_comments']} with comments, "
          f"{stats['total_comments']} total comments")
    print(f"  [OK] {file_index - 1} output files in {output_dir}")


if __name__ == '__main__':
    main()
