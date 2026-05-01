#!/usr/bin/env python3
"""
YouTube Video Research Pipeline Orchestrator
Usage: python3 run.py --topic "Кайтсерфинг в ЮАР" [options]

Options:
  --topic TEXT        Research topic (required)
  --langs en,ru       Comma-separated languages (default: en,ru)
  --n-videos N        Number of videos to search (default: 500)
  --voice NAME        TTS voice name (default: from config)
  --from-step N       Start from step N (skip previous)
  --config PATH       Config file path (default: config.json next to this script)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = SCRIPT_DIR / 'config.json'

STEPS = [
    (1, "Генерация ключевых слов (Gemini)"),
    (2, "Поиск видео на YouTube"),
    (3, "Скачивание субтитров, метаданных, комментариев"),
    (4, "Объединение данных для NotebookLM"),
    (5, "NotebookLM: создание блокнота, отчёт, сценарий"),
    (6, "Парсинг сценария → segments.json (Gemini)"),
    (7, "Генерация картинок и озвучки (Gemini)"),
    (8, "Сборка видео (ffmpeg)"),
    (9, "Субтитры (burn-in)"),
]


def load_config(config_path):
    with open(config_path) as f:
        cfg = json.load(f)
    # Expand ~ in paths
    for key in ['nlm_bin', 'youtube_api_reverser_path', 'work_base_dir', 'output_base_dir']:
        if key in cfg:
            cfg[key] = os.path.expanduser(cfg[key])
    return cfg


def topic_to_slug(topic):
    """Convert topic to filesystem-safe slug (supports Cyrillic)"""
    slug = re.sub(r'[^\w\s-]', '', topic)
    slug = re.sub(r'[\s]+', '_', slug).strip('_')
    return slug[:40] if slug else 'research'


def log(msg, level='INFO'):
    ts = datetime.now().strftime('%H:%M:%S')
    prefix = {'INFO': '→', 'OK': '✓', 'SKIP': '⟳', 'ERROR': '✗', 'STEP': '◉'}.get(level, '·')
    print(f"[{ts}] {prefix} {msg}", flush=True)


def checkpoint_path(work_dir, step_n):
    return Path(work_dir) / f'.step{step_n:02d}.done'


def is_done(work_dir, step_n):
    return checkpoint_path(work_dir, step_n).exists()


def mark_done(work_dir, step_n):
    checkpoint_path(work_dir, step_n).touch()


def run_step(step_n, script_name, args_list, work_dir):
    """Run a step script with given args"""
    script_path = SCRIPT_DIR / script_name
    cmd = [sys.executable, str(script_path)] + args_list
    log(f"Running: {script_name}", 'INFO')
    result = subprocess.run(cmd, cwd=work_dir)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='YouTube Video Research Pipeline')
    parser.add_argument('--topic', required=True, help='Research topic')
    parser.add_argument('--langs', default=None, help='Languages (e.g. en,ru)')
    parser.add_argument('--n-videos', type=int, default=None, help='Number of videos')
    parser.add_argument('--voice', default=None, help='TTS voice name')
    parser.add_argument('--from-step', type=int, default=1, help='Start from step N')
    parser.add_argument('--config', default=str(CONFIG_PATH), help='Config file path')
    args = parser.parse_args()

    # Load config
    cfg = load_config(args.config)

    # Resolve params (CLI args override config defaults)
    langs = args.langs or ','.join(cfg.get('default_langs', ['en', 'ru']))
    n_videos = args.n_videos or cfg.get('default_n_videos', 500)
    voice = args.voice or cfg.get('default_voice', 'Fenrir')
    topic = args.topic
    from_step = args.from_step

    # Create directories
    year = datetime.now().year
    slug = topic_to_slug(topic)
    work_dir = Path(cfg['work_base_dir']) / f'{slug}_research'
    output_dir = Path(cfg['output_base_dir']) / f'{slug}_{year}'

    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'images').mkdir(exist_ok=True)
    (output_dir / 'audio').mkdir(exist_ok=True)
    (work_dir / 'subtitles').mkdir(exist_ok=True)
    (work_dir / 'metadata').mkdir(exist_ok=True)
    (work_dir / 'comments').mkdir(exist_ok=True)

    # Save run config for steps to read
    run_cfg = {
        **cfg,
        'topic': topic,
        'slug': slug,
        'langs': langs,
        'n_videos': n_videos,
        'voice': voice,
        'work_dir': str(work_dir),
        'output_dir': str(output_dir),
    }
    run_cfg_path = work_dir / 'run_config.json'
    with open(run_cfg_path, 'w') as f:
        json.dump(run_cfg, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"  YouTube Video Research Pipeline")
    print(f"  Тема: {topic}")
    print(f"  Языки: {langs}  |  Видео: {n_videos}  |  Голос: {voice}")
    print(f"  Work: {work_dir}")
    print(f"  Output: {output_dir}")
    print("=" * 60)
    print()

    step_scripts = {
        1: 'step1_keywords.py',
        2: 'step2_search.py',
        3: 'step3_download.py',
        4: 'step4_merge.py',
        5: 'step5_notebooklm.py',
        6: 'step6_parse_script.py',
        7: 'step7_media.py',
        8: 'step8_assemble.py',
        9: 'step9_subtitles.py',
    }

    cfg_arg = str(run_cfg_path)
    start_time = time.time()

    for step_n, step_name in STEPS:
        if step_n < from_step:
            log(f"STEP {step_n}/9: {step_name} — пропущен (--from-step {from_step})", 'SKIP')
            continue

        print()
        log(f"STEP {step_n}/9: {step_name}", 'STEP')

        # Check checkpoint
        if step_n != from_step and is_done(work_dir, step_n):
            log(f"Уже выполнен — пропускаем", 'SKIP')
            continue

        step_start = time.time()
        ok = run_step(step_n, step_scripts[step_n], ['--config', cfg_arg], work_dir)
        elapsed = time.time() - step_start

        if ok:
            mark_done(work_dir, step_n)
            log(f"Готово за {elapsed:.0f}с", 'OK')
        else:
            log(f"ОШИБКА на шаге {step_n}! Останавливаемся.", 'ERROR')
            log(f"Чтобы продолжить с этого шага: python3 run.py --topic '{topic}' --from-step {step_n}", 'INFO')
            sys.exit(1)

    total = time.time() - start_time
    print()
    print("=" * 60)
    log(f"ВСЁ ГОТОВО за {total/60:.1f} минут!", 'OK')
    print(f"  Видео: {output_dir}/video_subtitled.mp4")
    print(f"  Отчёт: {output_dir}/report.md")
    print("=" * 60)


if __name__ == '__main__':
    main()
