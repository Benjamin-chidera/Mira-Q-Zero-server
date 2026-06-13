import os
import io
import base64
import asyncio
import socketio
from dotenv import load_dotenv
from mistralai.client import Mistral
from sqlmodel import Session, select
from database import engine
from utils.mira.ai_research_models import ResearchConversation, ResearchMessage
from datetime import datetime
import json
import re



# Ensure .env is loaded before reading environment variables.
# socket_setup.py is imported in main.py before load_dotenv() runs there,
# so we must call it here to guarantee MISTRAL_API_KEY is available.
load_dotenv()

# Initialize the Socket.IO async server with ASGI mode and CORS enabled for all origins
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    max_http_buffer_size=20 * 1024 * 1024,  # 20MB — default 1MB causes drops for long recordings
)

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

        # Log the request details for debugging
        print(f"[Socket.IO] STT request from {sid}: file={file_name}, size={len(audio_bytes)} bytes")
        
        # Check that the API key is loaded
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            print("[Socket.IO] ERROR: MISTRAL_API_KEY is not set!")
            return {"error": "MISTRAL_API_KEY is not configured"}

        loop = asyncio.get_event_loop()
        content_type = "audio/wav" if file_name.endswith(".wav") else "audio/webm"
        
        # Invoke transcription model with a 30-second timeout to prevent indefinite hangs
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.audio.transcriptions.complete(
                    model=STT_MODEL,
                    file={
                        "file_name": file_name,
                        "content": audio_bytes,
                        "content_type": content_type,
                    },
                ),
            ),
            timeout=30.0,
        )
        
        transcribed_text = result.text if result and result.text else ""
        print(f"[Socket.IO] STT result: '{transcribed_text[:100]}'")
        return {"text": transcribed_text}

    except asyncio.TimeoutError:
        print(f"[Socket.IO] STT Timeout: Mistral API took longer than 30 seconds")
        return {"error": "STT request timed out. Please try again."}
    except Exception as e:
        print(f"[Socket.IO] STT Error: {e}")
        return {"error": f"Failed to generate STT: {str(e)}"}

@sio.on("mira:send_message")
async def handle_mira_message(sid, data):
    """
    Handles real-time chat research requests for Mira.
    Receives text, PDFs, Images, and URLs. Routes through LangGraph + CrewAI.
    """
    try:
        from utils.mira.ai_research import run_mira_research
        
        conversation_id = data.get("conversation_id")
        practitioner_id = data.get("practitioner_id")
        content = data.get("content")
        attachments = data.get("attachments", [])

        if not conversation_id or not practitioner_id:
            return {"error": "Missing 'conversation_id' or 'practitioner_id'"}

        print(f"[Socket.IO] Mira Research request from {sid} for conversation {conversation_id}")
        
        # Notify frontend that Mira is analyzing the request
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Mira is analyzing your request..."
        }, to=sid)

        # Execute the research graph in the executor pool to keep Socket.io non-blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: run_mira_research(
                conversation_id=conversation_id,
                practitioner_id=practitioner_id,
                query=content,
                attachments=attachments
            )
        )

        # Stream the final response and citations back to the client
        await sio.emit("mira:response", {
            "conversation_id": conversation_id,
            "role": "agent",
            "content": result["response"],
            "sources": result["sources"]
        }, to=sid)

        return {"success": True}

    except Exception as e:
        print(f"[Socket.IO] Mira Research Error: {e}")
        await sio.emit("mira:status", {
            "conversation_id": data.get("conversation_id"),
            "status": f"Research failed: {str(e)}"
        }, to=sid)
        return {"error": f"Failed to run Mira research: {str(e)}"}

def clean_text_for_tts(text: str) -> str:
    """
    Cleans markdown formatting and raw/angle-bracketed URLs from the text
    so that the TTS model speaks naturally and does not read raw URLs out loud.
    Example: "[CDC Guidelines](https://www.cdc.gov)" -> "CDC Guidelines"
    """
    if not text:
        return ""
    # 1. Replace markdown links [Anchor Text](URL) with Anchor Text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 2. Remove angle-bracketed URLs: <http://...> or <https://...>
    text = re.sub(r'<https?://[^>]+>', '', text)
    # 3. Remove raw URLs
    text = re.sub(r'https?://[^\s]+', '', text)
    # 4. Remove bold markers **
    text = text.replace('**', '')
    # 5. Remove asterisk list markers
    text = re.sub(r'^\s*[\*\-]\s+', '', text, flags=re.MULTILINE)
    return text.strip()


@sio.on("mira:voice_message")
async def handle_mira_voice_message(sid, data):
    """
    Handles voice-based communication for Mira.
    Accepts: data = {
        "conversation_id": "...",
        "practitioner_id": 1,
        "audio": "<base64_audio_data>",
        "filename": "utterance.wav"
    }
    1. Transcribes audio bytes via Mistral STT (voxtral-mini-latest)
    2. Saves transcribed text to database as ResearchMessage (role="user")
    3. Broadcasts the transcribed user text to the client
    4. Generates a voice-friendly, concise clinical reply using Mistral Chat (mistral-large-latest)
    5. Saves Mira's reply to database as ResearchMessage (role="agent")
    6. Converts the reply to speech using Mistral TTS (voxtral-mini-tts-2603)
    7. Emits the final response text and audio bytes (base64) back to client
    """
    try:
        conversation_id = data.get("conversation_id")
        practitioner_id = data.get("practitioner_id")
        audio_b64 = data.get("audio")
        file_name = data.get("filename", "utterance.wav")

        if not conversation_id or not practitioner_id or not audio_b64:
            return {"error": "Missing 'conversation_id', 'practitioner_id', or 'audio' data"}

        print(f"[Socket.IO Call] Voice message from {sid} for conversation {conversation_id}")
        
        # 1. Decode audio bytes
        audio_bytes = base64.b64decode(audio_b64)
        
        # 2. Run Mistral STT
        loop = asyncio.get_event_loop()
        content_type = "audio/wav" if file_name.endswith(".wav") else "audio/webm"
        
        # Notify user that transcription is in progress
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Transcribing..."
        }, to=sid)

        stt_result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: client.audio.transcriptions.complete(
                    model=STT_MODEL,
                    file={
                        "file_name": file_name,
                        "content": audio_bytes,
                        "content_type": content_type,
                    },
                ),
            ),
            timeout=30.0,
        )
        
        user_text = stt_result.text if stt_result and stt_result.text else ""
        if not user_text.strip():
            print("[Socket.IO Call] STT result was empty.")
            return {"error": "No speech detected"}
            
        print(f"[Socket.IO Call] User Said: {user_text}")
        
        # 3. Save User Message to Database
        with Session(engine) as session:
            user_message = ResearchMessage(
                id=f"msg_u_{datetime.utcnow().timestamp()}",
                conversation_id=conversation_id,
                role="user",
                content=user_text,
                attachments_json="[]"
            )
            session.add(user_message)
            session.commit()
            
        # Emit the transcript to client immediately
        await sio.emit("mira:voice_transcript", {
            "conversation_id": conversation_id,
            "role": "user",
            "content": user_text
        }, to=sid)

        # 4. Generate LLM Reply
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Mira is thinking..."
        }, to=sid)

        with Session(engine) as session:
            stmt = select(ResearchMessage).where(
                ResearchMessage.conversation_id == conversation_id
            ).order_by(ResearchMessage.created_at)
            db_messages = session.exec(stmt).all()
            
            messages_payload = [
                {
                    "role": "system",
                    "content": (
                        "You are Mira, a friendly and highly professional real-time voice-based clinical research assistant on a call with a practitioner.\n"
                        "Give concise, conversational, and direct answers that are easy to understand when spoken aloud. "
                        "Keep your response short (1 to 3 sentences maximum, 50 words max).\n"
                        "The practitioner CAN see the text transcript on their screen, so you are encouraged to include helpful references and reference hyperlinks in standard markdown format (e.g. [CDC COVID treatments](https://www.cdc.gov/coronavirus/2019-ncov/index.html)) or naked URLs when citing sources. They will render as clickable links.\n"
                        "Avoid raw markdown symbols other than links and bold text (do not use headers, bullet lists, or tables)."
                    )
                }
            ]
            
            for msg in db_messages:
                role = "user" if msg.role == "user" else "assistant" if msg.role == "agent" else "system"
                messages_payload.append({
                    "role": role,
                    "content": msg.content
                })
                
        # Call Mistral Chat
        chat_response = await loop.run_in_executor(
            None,
            lambda: client.chat.complete(
                model=CHAT_MODEL,
                messages=messages_payload,
                temperature=0.4
            )
        )
        
        agent_text = chat_response.choices[0].message.content.strip()
        print(f"[Socket.IO Call] Mira Replied: {agent_text}")
        
        # 5. Save Agent Response to Database
        with Session(engine) as session:
            agent_message = ResearchMessage(
                id=f"msg_a_{datetime.utcnow().timestamp()}",
                conversation_id=conversation_id,
                role="agent",
                content=agent_text,
                sources_json="[]"
            )
            session.add(agent_message)
            
            # Update Conversation Preview
            conv = session.get(ResearchConversation, conversation_id)
            if conv:
                conv.preview = agent_text[:100] + "..."
                conv.updated_at = datetime.utcnow()
                session.add(conv)
            session.commit()

        # 6. Generate TTS Audio for the Agent response
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Speaking..."
        }, to=sid)

        voice_id = "gb_jane_neutral" # Default to Jane (female GB voice)
        
        # Clean text for spoken audio to prevent spelling out raw URLs
        cleaned_spoken_text = clean_text_for_tts(agent_text)
        
        tts_response = await loop.run_in_executor(
            None,
            lambda: client.audio.speech.complete(
                model=TTS_MODEL,
                input=cleaned_spoken_text if cleaned_spoken_text else agent_text,
                voice_id=voice_id,
                response_format="mp3"
            )
        )
        
        audio_b64_out = ""
        if tts_response and tts_response.audio_data:
            audio_b64_out = tts_response.audio_data
            
        # 7. Emit voice response
        await sio.emit("mira:voice_response", {
            "conversation_id": conversation_id,
            "role": "agent",
            "content": agent_text,
            "audio": audio_b64_out
        }, to=sid)

        return {"success": True}

    except Exception as e:
        print(f"[Socket.IO Call] Voice Message Error: {e}")
        await sio.emit("mira:status", {
            "conversation_id": data.get("conversation_id"),
            "status": f"Call error: {str(e)}"
        }, to=sid)
        return {"error": f"Failed to handle voice message: {str(e)}"}

@sio.on("mira:call_send_docs")
async def handle_call_send_docs(sid, data):
    """
    Handles uploading/attaching documents in the middle of a call.
    Extracts text/descriptions from PDFs, Images, URLs, and adds them as system context
    to the conversation messages.
    """
    try:
        from utils.mira.ai_research import extract_text_from_pdf, analyze_image_with_nvidia, scrape_url_content
        
        conversation_id = data.get("conversation_id")
        attachments = data.get("attachments", [])
        
        if not conversation_id:
            return {"error": "Missing 'conversation_id'"}
            
        print(f"[Socket.IO Call] Processing docs for call {conversation_id}")
        
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Processing attachments..."
        }, to=sid)

        extracted_parts = []
        for att in attachments:
            att_type = att.get("type")
            att_name = att.get("name", "attachment")
            base64_data = att.get("data")
            url = att.get("url")
            
            extracted_parts.append(f"\n=== Attached {att_type.upper()}: {att_name} ===")
            
            if att_type == "pdf" and base64_data:
                extracted_parts.append(extract_text_from_pdf(base64_data))
            elif att_type == "image" and base64_data:
                extracted_parts.append(analyze_image_with_nvidia(base64_data))
            elif att_type == "url" and url:
                extracted_parts.append(scrape_url_content(url))
                
        full_context = "\n".join(extracted_parts)
        
        if full_context.strip():
            # Save a system context message to the DB
            with Session(engine) as session:
                sys_message = ResearchMessage(
                    id=f"msg_s_{datetime.utcnow().timestamp()}",
                    conversation_id=conversation_id,
                    role="system",
                    content=f"[Context from attached documents:\n{full_context}]",
                    attachments_json=json.dumps(attachments)
                )
                session.add(sys_message)
                session.commit()
                
            # Emit notification to client
            await sio.emit("mira:voice_transcript", {
                "conversation_id": conversation_id,
                "role": "system",
                "content": f"Evidence documents successfully attached to call. Mira is now aware of: {', '.join([att.get('name') for att in attachments])}"
            }, to=sid)
            
            await sio.emit("mira:call_docs_processed", {
                "conversation_id": conversation_id,
                "success": True
            }, to=sid)
            
        return {"success": True}
        
    except Exception as e:
        print(f"[Socket.IO Call] Error sending docs: {e}")
        return {"error": f"Failed to send docs: {str(e)}"}


