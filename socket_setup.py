import os
import io
import base64
import asyncio
import socketio
from mistralai.client import Mistral

# Initialize the Socket.IO async server with ASGI mode and CORS enabled for all origins
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Initialize Mistral client using the environment variable key
client = Mistral(api_key=os.getenv("MISTRAL_API_KEY"))

# Define model names used for voice services
CHAT_MODEL = "mistral-large-latest"
TTS_MODEL = "voxtral-mini-tts-2603"
STT_MODEL = "voxtral-mini-latest"

async def infer_gender(name: str) -> str:
    """
    Infers the gender of the practitioner based on their name to assign
    a natural-sounding male or female text-to-speech voice.
    Defaults to female if unsure or on failure.
    """
    if not name or name.strip() == "":
        return "female"  # Default fallback
    try:
        loop = asyncio.get_event_loop()
        prompt = f"Return strictly 'male' or 'female' based on the likely gender of this practitioner's name: {name}. If unsure, return 'female'."
        
        # Run blocking API call in the thread pool executor to keep event loop free
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
        print(f"[Socket.IO] Error inferring gender: {e}")
        return "female"

@sio.event
async def connect(sid, environ):
    """
    Invoked when a client connects to the Socket.IO server.
    Logs connection for auditing and session tracking.
    """
    print(f"[Socket.IO] Client connected: {sid}")

@sio.event
async def disconnect(sid):
    """
    Invoked when a client disconnects from the Socket.IO server.
    Logs disconnection to keep session state accurate.
    """
    print(f"[Socket.IO] Client disconnected: {sid}")

@sio.on("tts")
async def handle_tts(sid, data):
    """
    Handles real-time Text-to-Speech requests via Socket.IO.
    Accepts: data = {"text": "...", "practitioner_name": "..."}
    Returns: Raw audio binary bytes directly via acknowledgment callback on success.
    """
    try:
        text = data.get("text")
        practitioner_name = data.get("practitioner_name")

        if not text:
            return {"error": "Missing 'text' parameter"}

        # Infer practitioner gender for customized GB voice selection
        gender = "female"
        if practitioner_name:
            gender = await infer_gender(practitioner_name)

        # Select a suitable preset British Mistral voice
        # gb_oliver_neutral is male (GB), gb_jane_neutral is female (GB)
        voice_id = "gb_oliver_neutral" if gender == "male" else "gb_jane_neutral"

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.audio.speech.complete(
                model=TTS_MODEL,
                input=text,
                voice_id=voice_id,
                response_format="mp3",
            )
        )

        if response and response.audio_data:
            # Decode the base64 audio data returned by Mistral API
            audio_bytes = base64.b64decode(response.audio_data)
            # Return raw binary bytes directly to the client callback!
            return audio_bytes
        else:
            return {"error": "Mistral TTS returned no audio data"}

    except Exception as e:
        print(f"[Socket.IO] TTS Error: {e}")
        return {"error": f"Failed to generate TTS: {str(e)}"}

@sio.on("stt")
async def handle_stt(sid, data):
    """
    Handles real-time Speech-to-Text requests via Socket.IO.
    Accepts: data = {"audio": binary_audio_bytes, "filename": "recording.wav"}
    Returns: Dict containing the transcribed 'text' via acknowledgment callback.
    """
    try:
        audio_bytes = data.get("audio")
        file_name = data.get("filename", "recording.wav")

        if not audio_bytes:
            return {"error": "Missing 'audio' data"}

        loop = asyncio.get_event_loop()
        content_type = "audio/wav" if file_name.endswith(".wav") else "audio/webm"
        
        # Invoke transcription model in the thread executor
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
        print(f"[Socket.IO] STT Error: {e}")
        return {"error": f"Failed to generate STT: {str(e)}"}
