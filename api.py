import uuid
from pathlib import Path
import wave
import os
import torch
import numpy as np
import io
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
import whisper
import subprocess
from ollama import chat
from piper import PiperVoice
from piper.download_voices import download_voice

device = "cuda" if torch.cuda.is_available() else "cpu"
MAX_DURATION_MS = 30_000

app = FastAPI(
    title="Ragebait API",
    description="An API to detect the best ragebait from audio files.",
    version="1.0.0",
)

whisper_model = whisper.load_model("turbo")
os.makedirs("voices", exist_ok=True)
download_voice("ro_RO-mihai-medium", download_dir=Path(os.getcwd()) / "voices")
voice = PiperVoice.load("voices/ro_RO-mihai-medium.onnx")

AUDIO_STORAGE = {}
SAMPLE_RATE = 16000


def load_audio_bytes(audio_bytes: bytes, sr: int = SAMPLE_RATE):
    """Decode audio from bytes using ffmpeg, resample to sr, mono."""
    process = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-threads",
            "0",
            "-i",
            "pipe:0",  # read from stdin
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sr),
            "pipe:1",  # write to stdout
        ],
        input=audio_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    audio = np.frombuffer(process.stdout, np.int16).astype(np.float32) / 32768.0
    return audio


def chunk_and_transcribe(audio_bytes: bytes, model) -> str:
    audio = load_audio_bytes(audio_bytes, sr=SAMPLE_RATE)
    full_text = ""

    num_samples_per_chunk = (MAX_DURATION_MS * SAMPLE_RATE) // 1000
    for start in range(0, len(audio), num_samples_per_chunk):
        print(f"Processing chunk starting at sample {start}")
        end = min(start + num_samples_per_chunk, len(audio))
        chunk = audio[start:end]

        if len(chunk) == 0:
            continue

        result = model.transcribe(chunk, language="ro", fp16=False)
        print(f"Chunk result: {result['text']}")
        full_text += result["text"] + " "

    return full_text.strip()


def ragebait(transcript: str) -> str:
    prompt = f"""Ești un bot sarcastic, care provoacă furie prin meme-uri.
Treaba ta este să iei următorul transcript și să-l faci praf cu umor negru, sarcasm sau comentarii de tip meme.
Fii scurt, la obiect și amuzant — ca și cum ai posta o legendă de meme sau un răspuns de trolling.
Nu te explica, doar dă roast-ul. Maxim 200 de caractere. Folosește emoji-uri și slang.
Transcript: ```{transcript}```
Răspunsul trebuie să fie în limba română."""

    response = chat(
        model="gemma3:1b",
        messages=[
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    text = response.message.content
    print(f"Ragebait response: {text}")

    return text


@app.post("/bait")
async def process_audio(file: UploadFile = File(...)):
    if file.content_type != "audio/wav":
        raise HTTPException(status_code=400, detail="Only WAV files are supported")

    audio_bytes = await file.read()

    transcript = chunk_and_transcribe(audio_bytes, whisper_model)
    text = ragebait(transcript)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice.synthesize_wav(text, wav_file)

    audio_storage_id = uuid.uuid4()
    AUDIO_STORAGE[audio_storage_id] = buffer.getvalue()

    return JSONResponse(
        content={
            "text": text,
            "id": str(audio_storage_id),
        }
    )


@app.get("/audio/{audio_id}")
async def get_audio(audio_id: uuid.UUID):
    audio_data = AUDIO_STORAGE.get(audio_id)
    if not audio_data:
        raise HTTPException(status_code=404, detail="Audio not found")

    wav_io = io.BytesIO(audio_data)
    wav_io.seek(0)

    return StreamingResponse(
        wav_io,
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename='{audio_id}.wav'"}
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
