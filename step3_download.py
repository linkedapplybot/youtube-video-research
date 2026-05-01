#!/usr/bin/env python3
"""
Step 3: Download subtitles, metadata, comments via yt-dlp (parallel)
Stage A: subtitles (10 threads) + metadata (10 threads) in parallel
Stage B: comments (5 threads) after stage A completes
Proxy rotation: each thread gets its own proxy from proxies.txt (round-robin)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return json.load(f)


def load_proxies(cfg):
    """Load proxy list from file specified in config. Returns [] if not configured."""
    proxies_file = cfg.get('proxies_file', '')
    if not proxies_file:
        return []
    p = Path(os.path.expanduser(proxies_file))
    if not p.exists():
        print(f"  [WARN] proxies_file not found: {p}")
        return []
    proxies = [l.strip() for l in p.read_text().splitlines() if l.strip()]
    print(f"  Loaded {len(proxies)} proxies from {p.name}")
    return proxies


def assign_proxy(proxies, index):
    """Round-robin proxy assignment. Returns [] (no extra args) if no proxies."""
    if not proxies:
        return []
    return ['--proxy', proxies[index % len(proxies)]]


def split_urls(urls_path, n_chunks):
    """Split url file into N roughly equal chunk lists"""
    urls = [l.strip() for l in Path(urls_path).read_text().split('\n') if l.strip()]
    chunk_size = max(1, len(urls) // n_chunks + 1)
    return [urls[i:i+chunk_size] for i in range(0, len(urls), chunk_size)]


def write_chunk_files(chunks, prefix, work_dir):
    """Write chunk files and return their paths"""
    paths = []
    for i, chunk in enumerate(chunks):
        p = Path(work_dir) / f'{prefix}_{i:02d}.txt'
        p.write_text('\n'.join(chunk) + '\n')
        paths.append(str(p))
    return paths


def run_parallel(commands):
    """Run list of commands in parallel, wait for all"""
    procs = [subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for cmd in commands]
    for p in procs:
        p.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    work_dir = Path(cfg['work_dir'])
    urls_path = work_dir / 'video_urls.txt'
    n_threads = cfg.get('download_threads', 10)
    n_comment_threads = cfg.get('comment_threads', 5)
    proxies = load_proxies(cfg)

    subs_dir = work_dir / 'subtitles'
    meta_dir = work_dir / 'metadata'
    comm_dir = work_dir / 'comments'

    if not urls_path.exists():
        print("  [ERROR] video_urls.txt not found")
        sys.exit(1)

    total_urls = len([l for l in urls_path.read_text().split('\n') if l.strip()])
    print(f"  Total URLs: {total_urls}")

    # ── STAGE A: Subtitles + Metadata in parallel ──
    chunks = split_urls(urls_path, n_threads)
    subs_chunks = write_chunk_files(chunks, 'chunk', work_dir)

    # Build subtitle download commands (each chunk gets its own proxy)
    sub_langs = 'en-orig,ru-orig,en,ru'
    subs_cmds = []
    for i, chunk_file in enumerate(subs_chunks):
        subs_cmds.append([
            'yt-dlp', '--skip-download', '--write-auto-subs',
            '--sub-langs', sub_langs, '--convert-subs', 'srt',
            '-o', str(subs_dir / '%(id)s.%(ext)s'),
            '-a', chunk_file, '--no-warnings', '-q',
            '--sleep-requests', '0.5',
            *assign_proxy(proxies, i),
        ])

    # Build metadata download commands (offset proxy index by n_threads to avoid overlap)
    meta_cmds = []
    for i, chunk_file in enumerate(subs_chunks):
        meta_cmds.append([
            'yt-dlp', '--skip-download', '--write-info-json',
            '--no-write-playlist-metafiles',
            '-o', str(meta_dir / '%(id)s'),
            '-a', chunk_file, '--no-warnings', '-q',
            *assign_proxy(proxies, n_threads + i),
        ])

    proxy_info = f" (proxies: {min(len(proxies), n_threads*2)}/{len(proxies)})" if proxies else ""
    print(f"  [A] Starting subtitles + metadata ({n_threads} threads each){proxy_info}...")
    t0 = time.time()
    run_parallel(subs_cmds + meta_cmds)
    print(f"  [A] Done in {time.time()-t0:.0f}s")

    # Cleanup subtitle chunk files
    for f in subs_chunks:
        Path(f).unlink(missing_ok=True)

    subs_count = len(list(subs_dir.iterdir()))
    meta_count = len(list(meta_dir.glob('*.json')))
    print(f"  Subtitles: {subs_count} files, Metadata: {meta_count} files")

    # ── STAGE B: Comments (optional) ──
    if not cfg.get('download_comments', False):
        print("  [SKIP] Comments download disabled (set download_comments: true in config)")
        print("  [OK] Download complete")
        return

    comm_chunks = split_urls(urls_path, n_comment_threads)
    comm_chunk_files = write_chunk_files(comm_chunks, 'comm_chunk', work_dir)

    comm_cmds = []
    for i, chunk_file in enumerate(comm_chunk_files):
        comm_cmds.append([
            'yt-dlp', '--skip-download', '--write-comments',
            '--extractor-args', 'youtube:max_comments=100,all,all,all',
            '-o', str(comm_dir / '%(id)s.%(ext)s'),
            '-a', chunk_file, '--no-warnings', '-q',
            '--sleep-requests', '1',
            *assign_proxy(proxies, i),
        ])

    proxy_info = f" (proxies: {min(len(proxies), n_comment_threads)}/{len(proxies)})" if proxies else ""
    print(f"  [B] Starting comments ({n_comment_threads} threads){proxy_info}...")
    t0 = time.time()
    run_parallel(comm_cmds)
    print(f"  [B] Done in {time.time()-t0:.0f}s")

    # Cleanup comment chunk files
    for f in comm_chunk_files:
        Path(f).unlink(missing_ok=True)

    comm_count = len(list(comm_dir.glob('*.json')))
    print(f"  Comments: {comm_count} files")
    print(f"  [OK] Download complete")


if __name__ == '__main__':
    main()
