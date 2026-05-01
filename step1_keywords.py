#!/usr/bin/env python3
"""
Step 1: Generate search keywords for the topic using Gemini
Output: work_dir/keywords.txt
"""
import argparse
import json
import os
import sys
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return json.load(f)


def generate_keywords(topic, langs, gemini_api_key):
    from google import genai

    client = genai.Client(api_key=gemini_api_key)

    lang_names = {
        'en': 'English', 'ru': 'Russian', 'de': 'German',
        'fr': 'French', 'es': 'Spanish', 'af': 'Afrikaans',
        'pt': 'Portuguese', 'it': 'Italian', 'nl': 'Dutch',
    }
    lang_list = [lang_names.get(l.strip(), l.strip()) for l in langs.split(',')]
    langs_str = ', '.join(lang_list)

    prompt = f"""Generate 60-80 YouTube search keywords for the topic: "{topic}"

Languages: {langs_str}

Rules:
- Include the main topic phrase in each language
- Add subtopics: locations, techniques, events, beginner/expert, reviews, tips, gear
- Include year variations: 2024, 2025, 2026
- Include question forms: how to, best, guide, tutorial
- One keyword per line, no numbering, no explanations
- Mix languages naturally

Return ONLY the keywords, one per line."""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )

    keywords = []
    for line in response.text.strip().split('\n'):
        kw = line.strip().lstrip('•-*0123456789. ')
        if kw and len(kw) > 2:
            keywords.append(kw)

    return keywords


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    work_dir = Path(cfg['work_dir'])
    out_path = work_dir / 'keywords.txt'

    # Checkpoint
    if out_path.exists() and out_path.stat().st_size > 0:
        count = len(out_path.read_text().strip().split('\n'))
        print(f"  [SKIP] keywords.txt already exists ({count} keywords)")
        return

    print(f"  Generating keywords for: {cfg['topic']}")
    print(f"  Languages: {cfg['langs']}")

    keywords = generate_keywords(
        cfg['topic'],
        cfg['langs'],
        cfg['gemini_api_key']
    )

    out_path.write_text('\n'.join(keywords), encoding='utf-8')
    print(f"  [OK] Generated {len(keywords)} keywords → {out_path}")


if __name__ == '__main__':
    main()
