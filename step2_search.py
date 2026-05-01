#!/usr/bin/env python3
"""
Step 2: Search YouTube videos using keywords
Output: work_dir/video_urls.txt, video_ids.txt, videos.csv
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    work_dir = Path(cfg['work_dir'])
    urls_path = work_dir / 'video_urls.txt'
    ids_path = work_dir / 'video_ids.txt'
    csv_path = work_dir / 'videos.csv'

    # Checkpoint
    if urls_path.exists():
        count = len(urls_path.read_text().strip().split('\n'))
        if count >= cfg['n_videos'] * 0.8:
            print(f"  [SKIP] video_urls.txt already exists ({count} videos)")
            return

    # Load keywords
    kw_path = work_dir / 'keywords.txt'
    if not kw_path.exists():
        print("  [ERROR] keywords.txt not found, run step1 first")
        sys.exit(1)

    keywords = [l.strip() for l in kw_path.read_text().split('\n') if l.strip()]
    print(f"  Loaded {len(keywords)} keywords")

    # Import YouTube search module
    yt_path = cfg.get('youtube_api_reverser_path', '')
    sys.path.insert(0, yt_path)

    try:
        from youtube_advanced_search import YouTubeAdvancedSearch
    except ImportError as e:
        print(f"  [ERROR] Cannot import YouTubeAdvancedSearch: {e}")
        print(f"  Check youtube_api_reverser_path in config: {yt_path}")
        sys.exit(1)

    config_file = os.path.join(yt_path, 'youtube_api_config.json')
    searcher = YouTubeAdvancedSearch(config_path=config_file)
    target = cfg['n_videos']
    seen_ids = set()
    results = []

    for kw in keywords:
        if len(results) >= target:
            break
        print(f"  [SEARCH] {kw} (collected: {len(results)}/{target})")
        try:
            videos = searcher.search_with_pagination(kw, max_results=50, sort_by='upload_date')
            for v in videos:
                vid_id = v.get('video_id') or v.get('id')
                if vid_id and vid_id not in seen_ids:
                    seen_ids.add(vid_id)
                    results.append(v)
                    if len(results) >= target:
                        break
        except Exception as e:
            print(f"  [WARN] Error on keyword '{kw}': {e}")

    print(f"\n  Total unique videos: {len(results)}")

    # Save CSV
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['video_id', 'title', 'url'])
        writer.writeheader()
        for v in results:
            vid_id = v.get('video_id') or v.get('id', '')
            writer.writerow({
                'video_id': vid_id,
                'title': v.get('title', ''),
                'url': f"https://www.youtube.com/watch?v={vid_id}"
            })

    # Save URLs
    with open(urls_path, 'w') as f:
        for v in results:
            vid_id = v.get('video_id') or v.get('id', '')
            f.write(f"https://www.youtube.com/watch?v={vid_id}\n")

    # Save IDs
    with open(ids_path, 'w') as f:
        for v in results:
            vid_id = v.get('video_id') or v.get('id', '')
            f.write(f"{vid_id}\n")

    print(f"  [OK] Saved {len(results)} videos to {urls_path}")


if __name__ == '__main__':
    main()
