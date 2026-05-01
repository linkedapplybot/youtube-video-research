#!/usr/bin/env python3
"""
Step 7: Generate images (Gemini) + audio/TTS (Gemini) in parallel
Output: output_dir/images/*.png, output_dir/audio/*.wav
"""
import argparse
import json
import os
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock, Thread


def load_config(path):
    with open(path) as f:
        return json.load(f)


IMAGE_MODELS = [
    'gemini-3.1-flash-image-preview',   # 1500 RPD free, highest quality
    'gemini-3-pro-image-preview',        # ~100 RPD free, fallback
    'gemini-2.5-flash-image',            # low RPD, last resort
]


def generate_images(segments, images_dir, gemini_api_key, image_model=None, workers=5):
    from google import genai
    from google.genai import types

    # Determine model order: preferred first, then fallbacks
    models = [image_model] + [m for m in IMAGE_MODELS if m != image_model] if image_model else IMAGE_MODELS
    model_idx_lock = Lock()
    current_model_idx = [0]  # list for mutability in closure

    # Collect all tasks
    tasks = []
    for seg in segments:
        for i, prompt in enumerate(seg.get('image_prompts', [])):
            out_path = images_dir / f"{seg['id']}_{i+1:02d}.png"
            tasks.append((seg['id'], i + 1, prompt, out_path))

    total = len(tasks)
    done_count = [0]
    errors = [0]

    def generate_one(task):
        seg_id, img_num, prompt, out_path = task
        label = f"{seg_id}_{img_num:02d}"

        if out_path.exists():
            print(f"  [IMG SKIP] {out_path.name}")
            return True

        with model_idx_lock:
            idx = current_model_idx[0]
        done_count[0] += 1
        print(f"  [IMG {done_count[0]}/{total}] {label}")

        client = genai.Client(api_key=gemini_api_key)

        for attempt in range(5):
            with model_idx_lock:
                model = models[min(current_model_idx[0], len(models) - 1)]
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=['IMAGE'],
                        image_config=types.ImageConfig(aspect_ratio='16:9')
                    )
                )
                candidates = response.candidates
                if not candidates or not candidates[0].content or not candidates[0].content.parts:
                    print(f"  [IMG WARN] Empty response for {label}, retrying...")
                    time.sleep(5)
                    continue
                for part in candidates[0].content.parts:
                    if part.inline_data is not None:
                        out_path.write_bytes(part.inline_data.data)
                        print(f"  [IMG OK] {out_path.name} ({model.split('/')[-1]})")
                        return True
                print(f"  [IMG WARN] No image data for {label}")
                return False
            except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                    with model_idx_lock:
                        next_idx = current_model_idx[0] + 1
                        if next_idx < len(models):
                            print(f"  [IMG 429] {model} exhausted → switching to {models[next_idx]}")
                            current_model_idx[0] = next_idx
                        else:
                            wait = 60 * attempt
                            print(f"  [IMG 429] All models exhausted, waiting {wait}s...")
                            time.sleep(wait)
                elif '500' in err_str or '503' in err_str or 'INTERNAL' in err_str or 'UNAVAILABLE' in err_str:
                    wait = 10 * (attempt + 1)
                    print(f"  [IMG {err_str[:3]}] {label}: server error, retry in {wait}s ({attempt+1}/5)...")
                    time.sleep(wait)
                else:
                    print(f"  [IMG ERR] {label}: {e}")
                    return False
        return False

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(generate_one, t) for t in tasks]
        for f in as_completed(futures):
            if not f.result():
                errors[0] += 1

    print(f"  Images: {total - errors[0]}/{total} generated, {errors[0]} errors")


def generate_audio(segments, audio_dir, gemini_api_key, voice):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=gemini_api_key)
    done = 0
    errors = 0

    for seg in segments:
        out_path = audio_dir / f"{seg['id']}.wav"
        if out_path.exists():
            print(f"  [TTS SKIP] {out_path.name}")
            done += 1
            continue

        narration = seg.get('narration', '')
        if not narration:
            print(f"  [TTS SKIP] {seg['id']}: no narration")
            continue

        print(f"  [TTS] {seg['id']}: {seg.get('title','')[:40]}...")
        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash-preview-tts',
                    contents=narration,
                    config=types.GenerateContentConfig(
                        response_modalities=['AUDIO'],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name=voice,
                                )
                            )
                        ),
                    )
                )
                data = response.candidates[0].content.parts[0].inline_data.data
                with wave.open(str(out_path), 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(24000)
                    wf.writeframes(data)
                print(f"  [TTS OK] {out_path.name}")
                done += 1
                break
            except Exception as e:
                err_str = str(e)
                if '429' in err_str or 'RESOURCE_EXHAUSTED' in err_str:
                    wait = 60 * (attempt + 1)
                    print(f"  [TTS 429] {seg['id']}: quota exhausted, waiting {wait}s (attempt {attempt+1}/5)...")
                    time.sleep(wait)
                else:
                    print(f"  [TTS ERR] {seg['id']}: {e}")
                    errors += 1
                    break
        time.sleep(2)

    print(f"  Audio: {done}/{len(segments)} generated, {errors} errors")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg['output_dir'])
    images_dir = output_dir / 'images'
    audio_dir = output_dir / 'audio'
    gemini_api_key = cfg['gemini_api_key']
    voice = cfg.get('voice', cfg.get('default_voice', 'Fenrir'))
    image_model = cfg.get('image_model', IMAGE_MODELS[0])
    image_workers = cfg.get('image_workers', 5)

    segments_path = output_dir / 'segments.json'
    if not segments_path.exists():
        print("  [ERROR] segments.json not found")
        sys.exit(1)

    data = json.loads(segments_path.read_text())
    segments = data.get('segments', [])
    print(f"  Loaded {len(segments)} segments, voice: {voice}, image model: {image_model} ({image_workers} workers)")

    # Check if already done
    total_images_needed = sum(len(s.get('image_prompts', [])) for s in segments)
    existing_images = len(list(images_dir.glob('*.png')))
    existing_audio = len(list(audio_dir.glob('*.wav')))

    if existing_images >= total_images_needed * 0.9 and existing_audio >= len(segments):
        print(f"  [SKIP] Already have {existing_images} images and {existing_audio} audio files")
        return

    # Run images and audio in parallel threads
    img_thread = Thread(
        target=generate_images,
        args=(segments, images_dir, gemini_api_key, image_model, image_workers),
        daemon=True
    )
    tts_thread = Thread(
        target=generate_audio,
        args=(segments, audio_dir, gemini_api_key, voice),
        daemon=True
    )

    print("  Starting images + audio generation in parallel...")
    img_thread.start()
    tts_thread.start()

    img_thread.join()
    tts_thread.join()

    final_images = len(list(images_dir.glob('*.png')))
    final_audio = len(list(audio_dir.glob('*.wav')))
    print(f"  [OK] Images: {final_images}, Audio: {final_audio}")


if __name__ == '__main__':
    main()
