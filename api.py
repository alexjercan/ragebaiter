import uuid
import io
import os
import wave
import logging
import subprocess
from pathlib import Path
from typing import List

import torch
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
import whisper
from ollama import chat
from piper import PiperVoice
from piper.download_voices import download_voice

# ----------------------------
# Logging setup
# ----------------------------
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ----------------------------
# Device and constants
# ----------------------------
device = "cuda" if torch.cuda.is_available() else "cpu"
MAX_DURATION_MS = 30_000  # Max chunk duration for transcription in ms
SAMPLE_RATE = 16000
AUDIO_STORAGE = {}  # In-memory storage of generated audio
MODEL_NAME = os.getenv("MODEL_NAME", "gemma3:latest")

# ----------------------------
# FastAPI app initialization
# ----------------------------
app = FastAPI(
    title="Ragebait API",
    description="An API to detect the best ragebait from audio files.",
    version="1.0.0",
)

# ----------------------------
# Model and voice setup
# ----------------------------
logger.info("Loading Whisper model...")
whisper_model = whisper.load_model("turbo")

# Ensure voices directory exists and download voice
os.makedirs("voices", exist_ok=True)
logger.info("Downloading Piper voice...")
download_voice("ro_RO-mihai-medium", download_dir=Path(os.getcwd()) / "voices")
download_voice("en_US-lessac-medium", download_dir=Path(os.getcwd()) / "voices")

VOICE_MAP = {
    "ro": PiperVoice.load("voices/ro_RO-mihai-medium.onnx"),
    "en": PiperVoice.load("voices/en_US-lessac-medium.onnx"),
}

PROMPT_MAP = {
    "ro": """Ești un bot sarcastic, care provoacă furie prin meme-uri.
Treaba ta este să iei următorul transcript și să-l faci praf cu umor negru, sarcasm sau comentarii de tip meme.
Fii scurt, la obiect și amuzant — ca și cum ai posta o legendă de meme sau un răspuns de trolling.
Nu te explica, doar dă roast-ul. Maxim 200 de caractere. Folosește emoji-uri și slang.
Transcript: ```{}```
Răspunsul trebuie să fie în limba română.""",
    "en": """You are a sarcastic bot that provokes rage through memes.
Your job is to take the following transcript and roast it with dark humor, sarcasm, or meme-style comments.
Be brief, to the point, and funny — like you're posting a meme caption or a trolling reply.
Don't explain yourself, just deliver the roast. Max 200 characters. Use emojis and slang.
Transcript: ```{}```
The reply must be in English.""",
}


# ----------------------------
# Helper functions
# ----------------------------
def load_audio_bytes(audio_bytes: bytes, sr: int = SAMPLE_RATE) -> np.ndarray:
    """
    Decode audio bytes using ffmpeg, convert to mono, and resample to `sr`.
    Returns a float32 numpy array in range [-1, 1].
    """
    process = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-threads",
            "0",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sr),
            "pipe:1",
        ],
        input=audio_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    audio = np.frombuffer(process.stdout, np.int16).astype(np.float32) / 32768.0
    return audio


def chunk_and_transcribe(audio_bytes: bytes, model, language: str = "en") -> str:
    """
    Split audio into chunks of MAX_DURATION_MS and transcribe each chunk.
    Returns the full concatenated transcript.
    """
    audio = load_audio_bytes(audio_bytes, sr=SAMPLE_RATE)
    full_text = ""
    num_samples_per_chunk = (MAX_DURATION_MS * SAMPLE_RATE) // 1000

    for start in range(0, len(audio), num_samples_per_chunk):
        end = min(start + num_samples_per_chunk, len(audio))
        chunk = audio[start:end]
        if len(chunk) == 0:
            continue

        logger.info(f"Processing audio chunk starting at sample {start}")
        result = model.transcribe(chunk, language=language, fp16=False)
        logger.info(f"Chunk transcription result: {result['text']}")
        full_text += result["text"] + " "

    return full_text.strip()


def ragebait(transcript: str, language: str = "en") -> str:
    """
    Generate a sarcastic meme-style response based on the transcript
    using Ollama chat model.
    """
    prompt = PROMPT_MAP[language].format(transcript)
    logger.info(f"Ragebait prompt: {prompt}")

    response = chat(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.message.content
    logger.info(f"Ragebait response: {text}")
    return text


# ----------------------------
# API endpoints
# ----------------------------
@app.post("/bait")
async def process_audio(
    files: List[UploadFile] = File(...),
    language: str = Query(default="en", alias="language"),
):
    """
    Accept a WAV file, transcribe it, generate a ragebait text, and
    synthesize it to WAV using Piper.
    """
    full_transcript_parts = []
    for file in files:
        audio_bytes = await file.read()
        logger.info(
            f"Received audio file: {file.filename}, size: {len(audio_bytes)} bytes"
        )

        # Transcription
        transcript = chunk_and_transcribe(audio_bytes, whisper_model, language=language)

        # Use filename (without extension) as username
        username = file.filename.rsplit(".", 1)[0]

        # Build per-user transcript entry
        full_transcript_parts.append(f"{username}: {transcript}")

    # Join all transcripts
    transcript = "\n".join(full_transcript_parts)

    # Generate ragebait text
    text = ragebait(transcript, language=language)

    # Synthesize audio
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        voice = VOICE_MAP[language]
        voice.synthesize_wav(text, wav_file)

    # Store audio in memory
    audio_storage_id = uuid.uuid4()
    AUDIO_STORAGE[audio_storage_id] = buffer.getvalue()
    logger.info(f"Generated audio stored with ID: {audio_storage_id}")

    return JSONResponse(
        content={"transcript": transcript, "text": text, "id": str(audio_storage_id)}
    )


@app.get("/audio/{audio_id}")
async def get_audio(audio_id: uuid.UUID):
    """
    Retrieve previously generated audio by ID.
    """
    audio_data = AUDIO_STORAGE.get(audio_id)
    if not audio_data:
        logger.warning(f"Audio not found: {audio_id}")
        raise HTTPException(status_code=404, detail="Audio not found")

    wav_io = io.BytesIO(audio_data)
    wav_io.seek(0)
    logger.info(f"Streaming audio with ID: {audio_id}")
    return StreamingResponse(
        wav_io,
        media_type="audio/wav",
        headers={"Content-Disposition": f"inline; filename='{audio_id}.wav'"},
    )


# ----------------------------
# Main entry
# ----------------------------
if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Ragebait API...")
    uvicorn.run(app, host="0.0.0.0", port=8000)
