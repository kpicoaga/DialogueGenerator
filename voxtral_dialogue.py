import json, os, subprocess, sys, time
import numpy as np
import soundfile as sf
from mlx_audio.tts.utils import load

# ===== CONFIG =====
JSON_DIR = "/Volumes/CrucialP5/kevinpicoaga/Documents/openrouterclaude/dialoguegenerator"
BASE_OUTPUT_DIR = "/Volumes/CrucialP5/kevinpicoaga/Documents/openrouterclaude/FrenchWeb/Dialoguemp3"
MODEL_ID = "mlx-community/Voxtral-4B-TTS-2603-mlx-4bit"
VOICES = {"Speaker 1": "fr_male", "Speaker 2": "fr_female"}
MAX_RETRIES = 3
SKIP_EXISTING = True
# ==================

if len(sys.argv) < 2:
    sys.exit("Usage: python voxtral_dialogue.py t2d15")

# Accept "t2d15", "t2d15.json" or a full path
arg = sys.argv[1]
if os.path.isabs(arg) or os.path.exists(arg):
    DIALOGUE_FILE = arg
else:
    name = arg if arg.endswith(".json") else arg + ".json"
    DIALOGUE_FILE = os.path.join(JSON_DIR, name)

if not os.path.exists(DIALOGUE_FILE):
    available = sorted(f for f in os.listdir(JSON_DIR) if f.startswith("t2d") and f.endswith(".json")) if os.path.isdir(JSON_DIR) else []
    sys.exit(f"❌ File not found: {DIALOGUE_FILE}\n   Available in {JSON_DIR}: {available}")
if not os.path.isdir(BASE_OUTPUT_DIR):
    sys.exit(f"❌ Output drive/path not found: {BASE_OUTPUT_DIR}")

base_name = os.path.splitext(os.path.basename(DIALOGUE_FILE))[0]
OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, base_name)
os.makedirs(OUTPUT_DIR, exist_ok=True)

with open(DIALOGUE_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)
turns = data["turns"]
print(f"📖 Loaded: {data.get('title', DIALOGUE_FILE)} ({len(turns)} turns)")
print(f"📁 Output directory: {OUTPUT_DIR}\n")

print("⏳ Loading Voxtral (first run downloads ~2.5 GB)...")
model = load(MODEL_ID)

def synth(text, voice):
    chunks, sr = [], 24000
    for r in model.generate(text=text, voice=voice):
        chunks.append(np.array(r.audio, dtype=np.float32).reshape(-1))
        sr = r.sample_rate
    if not chunks:
        raise RuntimeError("no audio returned")
    audio = np.concatenate(chunks)
    if len(audio) < sr * 0.3:
        raise RuntimeError("audio too short")
    return audio, sr

failed = []
for i, turn in enumerate(turns, start=1):
    speaker, text = turn["speaker"], turn["text"].strip()
    voice = VOICES[speaker]
    wav_path = os.path.join(OUTPUT_DIR, f"part_{i:02d}.wav")
    mp3_path = os.path.join(OUTPUT_DIR, f"part_{i:02d}.mp3")

    if SKIP_EXISTING and os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        print(f"⏭️  [{i}/{len(turns)}] Already exists, skipping.")
        continue

    print(f"🎙️ [{i}/{len(turns)}] {speaker} ({voice}): {text[:30]}...")
    ok = False
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            audio, sr = synth(text, voice)
            sf.write(wav_path, audio, sr)
            subprocess.run([
                "ffmpeg", "-i", wav_path, "-ar", "24000", "-ac", "1",
                "-codec:a", "libmp3lame", "-b:a", "192k",
                "-y", "-loglevel", "error", mp3_path
            ], check=True)
            os.remove(wav_path)
            print(f"   ✅ Saved: {mp3_path}")
            ok = True
            break
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt} failed: {e}")
            time.sleep(2)
    if not ok:
        print("   ❌ Giving up on this part.")
        failed.append(i)

print(f"\n🎉 Done. Output folder: '{OUTPUT_DIR}'")
if failed:
    print(f"⚠️ Failed parts: {failed}. Re-run the script; it skips finished parts.")
    sys.exit(1)

# ===== CONCATENATE ALL PARTS =====
final_mp3 = os.path.join(OUTPUT_DIR, f"{base_name}.mp3")
part_files = [os.path.join(OUTPUT_DIR, f"part_{i:02d}.mp3") for i in range(1, len(turns) + 1)]
missing = [p for p in part_files if not os.path.exists(p)]
if missing:
    sys.exit(f"❌ Can't concatenate, missing files: {missing}")

list_path = os.path.join(OUTPUT_DIR, "concat_list.txt")
with open(list_path, "w", encoding="utf-8") as f:
    for p in part_files:
        f.write("file '" + os.path.abspath(p).replace("'", "'\\''") + "'\n")
try:
    subprocess.run([
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", "-y", "-loglevel", "error", final_mp3
    ], check=True)
    print(f"\n🔗 Combined file saved: {final_mp3}")
finally:
    os.remove(list_path)