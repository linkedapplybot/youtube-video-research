#!/usr/bin/env python3
"""
Step 6: Parse video_script.md into segments.json using Gemini
Output: output_dir/segments.json
Format: {"segments": [{"id", "title", "narration", "image_prompts": [...]}]}
"""
import argparse
import json
import re
import sys
from pathlib import Path


def load_config(path):
    with open(path) as f:
        return json.load(f)


def parse_with_gemini(script_text, topic, gemini_api_key):
    from google import genai

    client = genai.Client(api_key=gemini_api_key)

    prompt = f"""Parse this Russian YouTube video script into segments. Return ONLY a JSON object with a "segments" array. No markdown, no code blocks, no explanations.

Each segment object must have these exact keys:
- id: string like "00_hook", "01_block1", "02_block2", ..., "07_outro"
- title: section title string
- narration: the spoken voice-over text only (clean prose, remove all markdown/emoji/stage directions/visual instructions)
- image_prompts: array of 3 English photorealistic image descriptions (subject + setting + mood + lighting, 16:9)

ID rules: HOOK/Вступление → "00_hook"; numbered blocks → "01_block1" etc.; OUTRO/Заключение → last like "07_outro"

Narration rules: find text labeled "Текст озвучки", "Голос за кадром", "Закадровый текст", "Озвучка", or similar. If no label found, use the main body prose. Must be non-empty.

Script:
{script_text}"""

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
    )

    # Log finish reason for debugging
    if response.candidates:
        finish = response.candidates[0].finish_reason
        print(f"  Gemini finish_reason: {finish}")

    # response.text may be None (e.g. thinking model, RECITATION, etc.)
    text = response.text
    if text is None:
        # Try extracting from candidates directly
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text = ''.join(p.text for p in response.candidates[0].content.parts if hasattr(p, 'text') and p.text)
        if not text:
            raise ValueError(f"Gemini returned empty response (finish_reason={finish if response.candidates else 'unknown'})")
    text = text.strip()

    # Remove markdown code blocks if present
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    return json.loads(text)


def parse_with_regex(script_text):
    """Fallback: parse script with regex if Gemini fails.
    Supports both table format and section-based format."""
    segments = []

    # Try table format first: | **Title** | Narration | Visuals |
    table_rows = re.findall(
        r'^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$',
        script_text,
        re.MULTILINE
    )

    if table_rows:
        # Table format detected
        block_idx = 0
        for title_raw, narration_raw, visuals_raw in table_rows:
            title = title_raw.strip()

            # Skip header row
            if title.startswith(':') or title == 'Заголовок' or 'заголовок' in title.lower():
                continue

            # Determine ID from title
            title_upper = title.upper()
            if 'HOOK' in title_upper or 'ВСТУПЛЕНИЕ' in title_upper:
                seg_id = '00_hook'
            elif 'OUTRO' in title_upper or 'ЗАКЛЮЧЕНИЕ' in title_upper:
                seg_id = f'{block_idx:02d}_outro'
            else:
                # Extract block number from title like "2. БЛОК 1:" or "БЛОК 2:"
                num_match = re.search(r'(\d+)', title)
                n = int(num_match.group(1)) if num_match else block_idx
                seg_id = f'{n:02d}_block{n}'

            # Clean narration
            narration = narration_raw.strip()
            narration = re.sub(r'<br\s*/?>', ' ', narration)  # Remove <br> tags
            narration = re.sub(r'\*([^*]+)\*', r'\1', narration)  # Remove *italic*
            narration = re.sub(r'\*\*([^*]+)\*\*', r'\1', narration)  # Remove **bold**
            narration = re.sub(r'`[^`]+`', '', narration)  # Remove `code`
            narration = ' '.join(narration.split())  # Normalize whitespace

            # Generate image prompts from visuals column
            visuals = visuals_raw.strip()
            # Split visual descriptions by period or "Кадры"/"Вид"/"Панорама" etc.
            visual_parts = re.split(r'[.!]\s+', visuals)
            visual_parts = [v.strip() for v in visual_parts if len(v.strip()) > 10]

            image_prompts = []
            for v in visual_parts[:3]:
                # Clean markdown from visual descriptions
                v = re.sub(r'[*_`]', '', v)
                prompt = f"{v}, photorealistic, cinematic lighting, 16:9 aspect ratio"
                image_prompts.append(prompt)

            # Pad to 3 prompts if needed
            while len(image_prompts) < 3:
                image_prompts.append(
                    f"Professional cinematic photography of {title}, photorealistic, 16:9"
                )

            segments.append({
                'id': seg_id,
                'title': title,
                'narration': narration,
                'image_prompts': image_prompts[:3],
            })
            block_idx += 1
    else:
        # Section-based format: **HOOK/БЛОК/OUTRO** with "Голос за кадром"
        parts = re.split(r'\n---\n', script_text)

        for i, part in enumerate(parts):
            if not part.strip():
                continue

            title_match = re.search(r'\*\*(HOOK[^*]*|БЛОК[^*]*|OUTRO[^*]*|ВСТУПЛЕНИЕ[^*]*|ЗАКЛЮЧЕНИЕ[^*]*)\*\*', part, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else f'Section {i}'

            title_upper = title.upper()
            if 'HOOK' in title_upper or 'ВСТУПЛЕНИЕ' in title_upper or i == 0:
                seg_id = '00_hook'
            elif 'OUTRO' in title_upper or 'ЗАКЛЮЧЕНИЕ' in title_upper:
                seg_id = f'{i:02d}_outro'
            else:
                num = re.search(r'\d+', title)
                n = int(num.group()) if num else i
                seg_id = f'{n:02d}_block{n}'

            # Try multiple narration labels
            narration = ''
            for label in [r'Голос за кадром', r'Текст озвучки', r'Закадровый текст', r'Озвучка']:
                narration_match = re.search(
                    label + r'[^:]*:\*?\*?\s*\n+(.*?)(?=\n---|\n\*\*|\Z)',
                    part, re.DOTALL
                )
                if narration_match:
                    narration = narration_match.group(1).strip()
                    narration = re.sub(r'[*_`#]', '', narration)
                    narration = ' '.join(narration.split())
                    break

            image_prompts = [
                f"Professional photography related to {title}, photorealistic, 16:9",
                f"Dynamic action shot related to {title}, cinematic, 16:9",
                f"Scenic landscape view related to {title}, golden hour, photorealistic, 16:9",
            ]

            segments.append({
                'id': seg_id,
                'title': title,
                'narration': narration,
                'image_prompts': image_prompts,
            })

    return {'segments': segments}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg['output_dir'])
    segments_path = output_dir / 'segments.json'

    # Checkpoint
    if segments_path.exists():
        data = json.loads(segments_path.read_text())
        print(f"  [SKIP] segments.json already exists ({len(data.get('segments', []))} segments)")
        return

    script_path = output_dir / 'video_script.md'
    if not script_path.exists():
        print(f"  [ERROR] video_script.md not found")
        sys.exit(1)

    script_text = script_path.read_text(encoding='utf-8')
    print(f"  Script length: {len(script_text)} chars")

    # Try Gemini first, fallback to regex
    data = None
    try:
        print("  Parsing with Gemini...")
        data = parse_with_gemini(script_text, cfg['topic'], cfg['gemini_api_key'])
        n = len(data.get('segments', []))
        print(f"  Gemini parsed {n} segments")
    except Exception as e:
        print(f"  [WARN] Gemini parsing failed: {e}, using regex fallback")
        data = parse_with_regex(script_text)
        print(f"  Regex parsed {len(data.get('segments', []))} segments")

    if not data or not data.get('segments'):
        print("  [ERROR] No segments parsed")
        sys.exit(1)

    # Validate and print summary
    for seg in data['segments']:
        n_prompts = len(seg.get('image_prompts', []))
        n_words = len(seg.get('narration', '').split())
        print(f"  [{seg['id']}] {seg.get('title','')[:50]} — {n_words} words, {n_prompts} image prompts")

    segments_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )
    print(f"  [OK] segments.json saved: {segments_path}")


if __name__ == '__main__':
    main()
