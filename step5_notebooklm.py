#!/usr/bin/env python3
"""
Step 5: NotebookLM - create notebook, upload sources, generate report + video script
Output: output_dir/report.md, output_dir/video_script.md
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


def run_nlm(nlm_bin, args, capture=True):
    cmd = [nlm_bin] + args
    result = subprocess.run(
        cmd, capture_output=capture, text=True
    )
    return result


def wait_for_status(nlm_bin, notebook_id, artifact_id, timeout=600):
    """Poll notebook status until artifact is completed or failed"""
    start = time.time()
    while time.time() - start < timeout:
        result = run_nlm(nlm_bin, ['studio', 'status', notebook_id])
        if result.returncode != 0:
            time.sleep(15)
            continue
        try:
            items = json.loads(result.stdout)
            for item in items:
                if item.get('id') == artifact_id:
                    status = item.get('status', '')
                    if status == 'completed':
                        return True
                    elif status == 'failed':
                        print(f"  [ERROR] Artifact {artifact_id} failed")
                        return False
        except Exception:
            pass
        time.sleep(15)
    print(f"  [ERROR] Timeout waiting for {artifact_id}")
    return False


def create_artifact(nlm_bin, notebook_id, prompt, retries=3):
    """Create a report artifact with retry"""
    for attempt in range(retries):
        result = run_nlm(nlm_bin, [
            'report', 'create', notebook_id,
            '--format', 'Create Your Own',
            '--prompt', prompt,
            '--language', 'ru', '-y'
        ])
        if result.returncode == 0:
            # Extract artifact ID
            for line in result.stdout.split('\n'):
                if 'Artifact ID:' in line or 'ID:' in line:
                    parts = line.split()
                    for part in parts:
                        if len(part) > 20 and '-' in part:
                            return part.strip()
            # Try to parse from output
            import re
            match = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', result.stdout)
            if match:
                return match.group(1)
        print(f"  [RETRY {attempt+1}] Failed to create artifact, waiting 30s...")
        time.sleep(30)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg['output_dir'])
    topic = cfg['topic']
    nlm_bin = os.path.expanduser(cfg.get('nlm_bin', '~/.local/bin/nlm'))
    slug = cfg['slug']

    report_path = output_dir / 'report.md'
    script_path = output_dir / 'video_script.md'
    nb_id_path = output_dir / '.notebook_id'

    # Checkpoint
    if report_path.exists() and script_path.exists():
        print(f"  [SKIP] report.md and video_script.md already exist")
        return

    # Find data files
    data_files = sorted(output_dir.glob(f'{slug}_data_part_*.txt'))
    if not data_files:
        print(f"  [ERROR] No data_part files found in {output_dir}")
        sys.exit(1)
    print(f"  Found {len(data_files)} data files to upload")

    # Create or reuse notebook
    if nb_id_path.exists():
        notebook_id = nb_id_path.read_text().strip()
        print(f"  Reusing notebook: {notebook_id}")
    else:
        result = run_nlm(nlm_bin, ['create', 'notebook', f'{topic} Research'])
        if result.returncode != 0:
            print(f"  [ERROR] Failed to create notebook: {result.stderr}")
            sys.exit(1)
        # Extract notebook ID
        import re
        match = re.search(r'ID:\s*([0-9a-f-]{36})', result.stdout)
        if not match:
            print(f"  [ERROR] Could not parse notebook ID from: {result.stdout}")
            sys.exit(1)
        notebook_id = match.group(1)
        nb_id_path.write_text(notebook_id)
        print(f"  Created notebook: {notebook_id}")

    # Upload files in parallel
    print(f"  Uploading {len(data_files)} files in parallel...")
    procs = []
    for f in data_files:
        p = subprocess.Popen(
            [nlm_bin, 'source', 'add', notebook_id, '--file', str(f)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        procs.append(p)
    for p in procs:
        p.wait()
    print(f"  Uploaded {len(data_files)} sources")

    # Wait for indexing
    print("  Waiting 30s for indexing...")
    time.sleep(30)

    # Generate report
    if not report_path.exists():
        report_prompt = (
            f"Создай детальное исследование на основе транскриптов YouTube видео по теме: {topic}. "
            f"Включи: обзор ключевых тем, важные места и события, мнения аудитории, "
            f"инсайты из комментариев. Приводи цитаты из видео. Язык: русский."
        )
        print("  Generating report...")
        report_id = create_artifact(nlm_bin, notebook_id, report_prompt)
        if not report_id:
            print("  [ERROR] Failed to create report")
            sys.exit(1)
        print(f"  Report ID: {report_id}, waiting for completion...")
        if not wait_for_status(nlm_bin, notebook_id, report_id):
            sys.exit(1)
        run_nlm(nlm_bin, ['download', 'report', notebook_id, '--id', report_id, '-o', str(report_path)], capture=False)
        print(f"  [OK] Report saved: {report_path}")

    # Generate video script
    if not script_path.exists():
        script_prompt = (
            f"Напиши сценарий для YouTube видео (15-20 минут) на тему: {topic}. "
            f"Формат:\n"
            f"- HOOK (30 сек) — провокационный вопрос или шокирующий факт\n"
            f"- 5-6 блоков по 2-4 минуты: заголовок блока, текст озвучки, визуальные подсказки\n"
            f"- OUTRO — призыв к действию\n"
            f"Используй цитаты из видео. Стиль: разговорный, живой. Язык: русский. 3000-4000 слов."
        )
        print("  Generating video script...")
        script_id = create_artifact(nlm_bin, notebook_id, script_prompt)
        if not script_id:
            print("  [ERROR] Failed to create video script")
            sys.exit(1)
        print(f"  Script ID: {script_id}, waiting for completion...")
        if not wait_for_status(nlm_bin, notebook_id, script_id):
            sys.exit(1)
        run_nlm(nlm_bin, ['download', 'report', notebook_id, '--id', script_id, '-o', str(script_path)], capture=False)
        print(f"  [OK] Script saved: {script_path}")

    print(f"  [OK] NotebookLM step complete")


if __name__ == '__main__':
    main()
