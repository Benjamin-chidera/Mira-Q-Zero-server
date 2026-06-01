import os
import base64
import io
import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from mistralai.client import Mistral

router = APIRouter()

client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

# Define model names
CHAT_MODEL = "mistral-large-latest"
TTS_MODEL = "voxtral-mini-tts-2603"
STT_MODEL = "voxtral-mini-latest"

class TTSRequest(BaseModel):
    text: str
    practitioner_name: str | None = None

async def infer_gender(name: str) -> str:
    if not name or name.strip() == "":
        return "female"  # default
    try:
        loop = asyncio.get_event_loop()
        prompt = f"Return strictly 'male' or 'female' based on the likely gender of this practitioner's name: {name}. If unsure, return 'female'."
        
        response = await loop.run_in_executor(
            None,
            lambda: client.chat.complete(
                model=CHAT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
        )
        
        gender = response.choices[0].message.content.strip().lower()
        if "male" in gender and "female" not in gender:
            return "male"
        return "female"
    except Exception as e:
        print(f"Error inferring gender: {e}")
        return "female"

@router.post("/tts")
async def generate_tts(req: TTSRequest):
    try:
        gender = "female"
        if req.practitioner_name:
            gender = await infer_gender(req.practitioner_name)

        # Select a suitable preset Mistral voice
        # gb_oliver_neutral is male (GB), gb_jane_neutral is female (GB)
        voice_id = "gb_oliver_neutral" if gender == "male" else "gb_jane_neutral"

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.audio.speech.complete(
                model=TTS_MODEL,
                input=req.text,
                voice_id=voice_id,
                response_format="mp3",
            )
        )

        if response and response.audio_data:
            # Decode the base64 audio data
            audio_bytes = base64.b64decode(response.audio_data)
            # Create a bytes stream to return as streaming response
            audio_stream = io.BytesIO(audio_bytes)
            return StreamingResponse(audio_stream, media_type="audio/mpeg")
        else:
            raise HTTPException(status_code=500, detail="Mistral TTS returned no audio data")

    except Exception as e:
        print(f"TTS Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate TTS: {str(e)}")

@router.post("/stt")
async def generate_stt(audio: UploadFile = File(...)):
    try:
        audio_bytes = await audio.read()
        loop = asyncio.get_event_loop()
        file_name = audio.filename or "recording.wav"
        content_type = "audio/wav" if file_name.endswith(".wav") else "audio/webm"
        result = await loop.run_in_executor(
            None,
            lambda: client.audio.transcriptions.complete(
                model=STT_MODEL,
                file={
                    "file_name": file_name,
                    "content": audio_bytes,
                    "content_type": content_type,
                },
            )
        )
        return {"text": result.text if result and result.text else ""}
    except Exception as e:
        print(f"STT Error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate STT: {str(e)}")
