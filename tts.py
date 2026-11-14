import requests
import subprocess
import os
import json
import sys
import time
from pathlib import Path

# ===== LOAD .env FILE =====
# Loads OPENROUTER_API_KEY (and any other vars) from a .env file so you don't
# have to `export` it manually. A key already exported in your shell wins.
def load_env_file(path=".env"):
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

load_env_file()
# ===== CONFIG =====
# OPENROUTER_API_KEY will be read from environment variable
URL = "https://openrouter.ai/api/v1/audio/speech"
DIALOGUE_FILE = "t2d12.json"
MAX_RETRIES = 6
DUMMY_TEXT = "."   # try "." instead of " "; change if it still fails
SKIP_EXISTING = True

# Set your desired base output path here
BASE_OUTPUT_DIR = "/Volumes/CrucialP5/kevinpicoaga/Documents/openrouterclaude/FrenchWeb/Dialoguemp3"
# ==================

# OPENROUTER_API_KEY will be read from environment variable
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    print("❌ Set it first: export OPENROUTER_API_KEY='your-key'")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

if not os.path.exists(DIALOGUE_FILE):
    print(f"❌ File not found: {DIALOGUE_FILE}")
    sys.exit(1)

# Extract the base name (e.g., "dialogue7")
base_name = os.path.splitext(os.path.basename(DIALOGUE_FILE))[0]

# Combine the base directory with the specific dialogue folder
OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, base_name)
os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(DIALOGUE_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

model = data.get("model", "google/gemini-3.8-flash-lite-tts")
speaker_voices = {name: info["voice"] for name, info in data["speakers"].items()}
turns = data["turns"]

print(f"📖 Loaded: {data.get('title', DIALOGUE_FILE)}")
print(f"   {len(turns)} turns.\n")
print(f"📁 Output directory: {OUTPUT_DIR}\n")

failed = []

for i, turn in enumerate(turns, start=1):
    speaker = turn["speaker"]
    text = turn["text"].strip()
    voice = speaker_voices[speaker]
    instructions = turn.get("instructions", "").strip()

    part_filename = f"part_{i:02d}"
    pcm_path = os.path.join(OUTPUT_DIR, f"{part_filename}.pcm")
    mp3_path = os.path.join(OUTPUT_DIR, f"{part_filename}.mp3")

    if SKIP_EXISTING and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        print(f"⏭️  [{i}/{len(turns)}] Already exists, skipping.")
        continue

    dummy_voice = "Puck" if voice == "Kore" else "Kore"
    print(f"🎙️ [{i}/{len(turns)}] Generating {speaker} ({voice}): {text[:30]}...")

    main_item = {"speaker": speaker, "voice": voice, "text": text}
    if instructions:                      # don't send empty instructions
        main_item["instructions"] = instructions

    payload = {
        "model": model,
        "input": [
            main_item,
            {"speaker": "Dummy", "voice": dummy_voice, "text": DUMMY_TEXT},
        ],
        "response_format": "pcm",
    }

    audio = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(URL, headers=headers, json=payload, timeout=120)
        except requests.RequestException as e:
            print(f"   ⚠️ Attempt {attempt} network error: {e}")
            resp = None

        if resp is not None and resp.status_code == 200 and len(resp.content) > 1000:
            audio = resp.content
            break

        if resp is not None:
            # NOTE: use `is not None`, never `if resp` (False for 4xx/5xx!)
            print(f"   ⚠️ Attempt {attempt} failed ({resp.status_code}): {resp.text[:300]}")
        wait = min(4 * attempt, 20)
        time.sleep(wait)

    if audio is None:
        print("   ❌ Giving up on this part.")
        failed.append(i)
        continue

    with open(pcm_path, "wb") as f:
        f.write(audio)

    try:
        subprocess.run([
            "ffmpeg", "-f", "s16le", "-ar", "24000", "-ac", "1",
            "-i", pcm_path, "-codec:a", "libmp3lame", "-b:a", "192k",
            "-y", "-loglevel", "error", mp3_path
        ], check=True)
        os.remove(pcm_path)
        print(f"   ✅ Saved: {mp3_path}")
    except Exception as e:
        print(f"   ❌ ffmpeg failed: {e}")
        failed.append(i)

    time.sleep(2.5)

print(f"\n🎉 Done. Output folder: '{OUTPUT_DIR}'")
if failed:
    print(f"⚠️ Failed parts: {failed} — just re-run the script; it skips finished parts.")

# ===== CONCATENATE ALL PARTS =====
final_mp3 = os.path.join(OUTPUT_DIR, f"{base_name}.mp3")

if failed:
    print(f"\n⏭️ Skipping concatenation because parts {failed} failed. Re-run the script to finish them first.")
else:
    part_files = [os.path.join(OUTPUT_DIR, f"part_{i:02d}.mp3") for i in range(1, len(turns) + 1)]
    missing = [p for p in part_files if not os.path.exists(p)]

    if missing:
        print(f"\n❌ Can't concatenate, missing files: {missing}")
    else:
        list_path = os.path.join(OUTPUT_DIR, "concat_list.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in part_files:
                safe_path = os.path.abspath(p).replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")

        try:
            subprocess.run([
                "ffmpeg", "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c", "copy",
                "-y", "-loglevel", "error", final_mp3
            ], check=True)
            print(f"\n🔗 Combined file saved: {final_mp3}")
        except Exception as e:
            print(f"\n❌ Concatenation failed: {e}")
        finally:
            if os.path.exists(list_path):
                os.remove(list_path)