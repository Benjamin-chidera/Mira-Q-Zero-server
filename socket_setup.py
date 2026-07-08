import os
import io
import base64
import asyncio
import socketio
import redis.asyncio as async_redis
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

listener_started = False

async def redis_pubsub_listener():
    """
    Listens to 'mira_responses' channel in Redis and forwards messages to socket clients.
    """
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    print(f"[Socket.IO Redis Listener] Starting connection to {redis_url}...")
    try:
        async_redis_client = async_redis.Redis.from_url(redis_url, decode_responses=True)
        pubsub = async_redis_client.pubsub()
        await pubsub.subscribe("mira_responses")
        print("[Socket.IO Redis Listener] Subscribed to channel 'mira_responses'")
        
        while True:
            try:
                # Read message with short timeout or block
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    payload = json.loads(message["data"])
                    sid = payload.get("sid")
                    conversation_id = payload.get("conversation_id")
                    
                    if "error" in payload:
                        print(f"[Socket.IO Redis Listener] Received error for conv={conversation_id}: {payload['error']}")
                        await sio.emit("mira:status", {
                            "conversation_id": conversation_id,
                            "status": f"Research failed: {payload['error']}"
                        }, to=sid)
                    else:
                        print(f"[Socket.IO Redis Listener] Forwarding research response for conv={conversation_id}")
                        await sio.emit("mira:response", {
                            "conversation_id": conversation_id,
                            "role": "agent",
                            "content": payload["response"],
                            "sources": payload["sources"]
                        }, to=sid)
            except Exception as inner_e:
                await asyncio.sleep(1)
    except Exception as e:
        print(f"[Socket.IO Redis Listener] Major exception: {e}")

@sio.event
async def connect(sid, environ):
    """
    Invoked when a client connects to the Socket.IO server.
    Logs connection for auditing and session tracking.
    """
    global listener_started
    if not listener_started:
        listener_started = True
        asyncio.create_task(redis_pubsub_listener())
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
    Queues them in Celery for background processing.
    """
    try:
        from celery_worker import process_research_task
        from utils.mira.ai_research import get_cache_key
        from utils.redis_client import redis_client
        
        conversation_id = data.get("conversation_id")
        practitioner_id = data.get("practitioner_id")
        content = data.get("content")
        attachments = data.get("attachments", [])

        if not conversation_id or not practitioner_id:
            return {"error": "Missing 'conversation_id' or 'practitioner_id'"}

        print(f"[Socket.IO] Mira Research request from {sid} for conversation {conversation_id}")
        
        # Check cache first for instant delivery!
        if redis_client:
            try:
                cache_key = get_cache_key(content, attachments)
                val = redis_client.get(cache_key)
                if val:
                    cached_result = json.loads(val)
                    print(f"[Socket.IO] Cache hit for query: '{content[:30]}'")
                    
                    # Store user message and cached agent response in sqlite database
                    # via run_mira_research (it will also hit the cache and handle DB writing)
                    loop = asyncio.get_event_loop()
                    from utils.mira.ai_research import run_mira_research
                    await loop.run_in_executor(
                        None,
                        lambda: run_mira_research(conversation_id, practitioner_id, content, attachments)
                    )
                    
                    # Emit cached result immediately
                    await sio.emit("mira:response", {
                        "conversation_id": conversation_id,
                        "role": "agent",
                        "content": cached_result["response"],
                        "sources": cached_result["sources"]
                    }, to=sid)
                    return {"success": True}
            except Exception as cache_err:
                print(f"[Socket.IO Cache Check] Error: {cache_err}")

        # Notify frontend that Mira is analyzing the request
        await sio.emit("mira:status", {
            "conversation_id": conversation_id,
            "status": "Mira is analyzing your request..."
        }, to=sid)

        # Trigger Celery background task
        process_research_task.delay(conversation_id, practitioner_id, content, attachments, sid)
        print(f"[Socket.IO] Triggered Celery task process_research_task for conv={conversation_id}")

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


async def _run_with_retry(loop, func, timeout_seconds=45.0, max_retries=1, label="API call"):
    """
    Runs a blocking function in the executor with a timeout and automatic retry.
    Prevents production hangs when external APIs (Mistral, NVIDIA) are slow.
    """
    for attempt in range(1 + max_retries):
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, func),
                timeout=timeout_seconds,
            )
            return result
        except asyncio.TimeoutError:
            if attempt < max_retries:
                print(f"[Socket.IO] {label} timed out (attempt {attempt + 1}/{max_retries + 1}), retrying...")
                continue
            print(f"[Socket.IO] {label} failed after {max_retries + 1} attempts (timeout={timeout_seconds}s)")
            raise asyncio.TimeoutError(f"{label} timed out after {max_retries + 1} attempts")


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
            # Auto-create conversation if it doesn't exist (lazy creation on call start)
            conv = session.get(ResearchConversation, conversation_id)
            if not conv:
                conv = ResearchConversation(
                    id=conversation_id,
                    practitioner_id=practitioner_id,
                    title="Voice Call - " + datetime.utcnow().strftime("%b %d"),
                    preview="Call starting...",
                    conversation_type="call"
                )
                session.add(conv)
                session.commit()
                session.refresh(conv)

                # Seed transient patient details context if conversation ID starts with transient_patient_
                if conversation_id.startswith("transient_patient_"):
                    try:
                        parts = conversation_id.split("_")
                        patient_id = int(parts[2])
                        from models import Patient, Medication, Allergy, PatientDocument, ClinicalNotes, OperativeNote, PACSImaging
                        patient = session.get(Patient, patient_id)
                        if patient:
                            meds = session.exec(select(Medication).where(Medication.patient_id == patient_id).where(Medication.status == "Active")).all()
                            allergies = session.exec(select(Allergy).where(Allergy.patient_id == patient_id).where(Allergy.status == "Active")).all()
                            docs = session.exec(select(PatientDocument).where(PatientDocument.patient_id == patient_id)).all()
                            notes = session.exec(select(ClinicalNotes).where(ClinicalNotes.patient_id == patient_id)).all()
                            op_notes = session.exec(select(OperativeNote).where(OperativeNote.patient_id == patient_id)).all()
                            pacs = session.exec(select(PACSImaging).where(PACSImaging.patient_id == patient_id)).all()

                            meds_str = ", ".join([f"{m.drug_name} ({m.dosage} - {m.frequency})" for m in meds]) if meds else "None"
                            allergies_str = ", ".join([f"{a.substance} (Reaction: {a.reaction})" for a in allergies]) if allergies else "None"
                            docs_str = "\n".join([f"- {d.title}: {d.content}" for d in docs]) if docs else "None"
                            notes_str = "\n".join([f"- {n.content} (Author: {n.author})" for n in notes]) if notes else "None"
                            op_notes_str = "\n".join([f"- {o.procedure_name}: {o.procedure_performed}. Narrative: {o.narrative_text}" for o in op_notes]) if op_notes else "None"
                            pacs_str = "\n".join([f"- Accession {p.accession_number} ({p.modality}): {p.radiologist_report}" for p in pacs]) if pacs else "None"

                            context = (
                                f"You are on a direct call with the doctor discussing NHS Patient: {patient.name} (Age: {patient.age}, Gender: {patient.gender}, NHS: {patient.nhs_number}).\n"
                                f"Here is the patient's complete file context loaded from GP-Connect:\n"
                                f"Active Medications: {meds_str}\n"
                                f"Active Allergies: {allergies_str}\n"
                                f"Documents / Discharge Summaries:\n{docs_str}\n"
                                f"Clinical Notes:\n{notes_str}\n"
                                f"Operative Notes:\n{op_notes_str}\n"
                                f"PACS Imaging Reports:\n{pacs_str}\n\n"
                                f"Keep your spoken answers extremely concise, patient-centered, and clinically precise. Assist the doctor in reviewing or auditing this patient's records."
                            )

                            sys_msg = ResearchMessage(
                                id=f"msg_sys_context_{datetime.utcnow().timestamp()}",
                                conversation_id=conversation_id,
                                role="system",
                                content=context,
                                attachments_json="[]"
                            )
                            session.add(sys_msg)
                            session.commit()
                    except Exception as ex:
                        print(f"[Socket.IO] Error seeding transient patient context: {ex}")

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

        # Try to run a quick Tavily search to fetch context if the query is a general knowledge question
        search_context = ""
        try:
            from langchain_community.tools import TavilySearchResults
            tavily_tool = TavilySearchResults(max_results=3)
            if tavily_tool and len(user_text.strip()) > 5:
                print(f"[Socket.IO Call] Running Tavily search for: '{user_text}'")
                search_results = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: tavily_tool.invoke(user_text)
                    ),
                    timeout=5.0
                )
                search_context = f"\n=== Web Search Results (Current Year: {datetime.now().year}) ===\n{str(search_results)}\n"
                print(f"[Socket.IO Call] Tavily returned results: {str(search_results)[:200]}")
        except Exception as search_err:
            print(f"[Socket.IO Call] Tavily search skipped/failed: {search_err}")

        with Session(engine) as session:
            stmt = select(ResearchMessage).where(
                ResearchMessage.conversation_id == conversation_id
            ).order_by(ResearchMessage.created_at)
            db_messages = session.exec(stmt).all()
            
            system_prompt_content = (
                "You are Mira, a friendly and highly professional real-time voice-based clinical research assistant on a call with a practitioner.\n"
                f"Today's date is {datetime.now().strftime('%d %b %Y')}. The current year is {datetime.now().year}.\n"
                "Give concise, conversational, and direct answers that are easy to understand when spoken aloud. "
                "Keep your response short (1 to 3 sentences maximum, 50 words max).\n"
                "The practitioner CAN see the text transcript on their screen, so you are encouraged to include helpful references and reference hyperlinks in standard markdown format (e.g. [CDC COVID treatments](https://www.cdc.gov/coronavirus/2019-ncov/index.html)) or naked URLs when citing sources. They will render as clickable links.\n"
                "Avoid raw markdown symbols other than links and bold text (do not use headers, bullet lists, or tables)."
            )
            
            if search_context:
                system_prompt_content += f"\n\nHere is real-time search context to answer the user's question:\n{search_context}\n"

            messages_payload = [
                {
                    "role": "system",
                    "content": system_prompt_content
                }
            ]
            
            for msg in db_messages:
                role = "user" if msg.role == "user" else "assistant" if msg.role == "agent" else "system"
                messages_payload.append({
                    "role": role,
                    "content": msg.content
                })
                
        # Call Mistral Chat (with timeout + retry to prevent production hangs)
        chat_response = await _run_with_retry(
            loop,
            lambda: client.chat.complete(
                model=CHAT_MODEL,
                messages=messages_payload,
                temperature=0.4
            ),
            timeout_seconds=45.0,
            label="Mistral Chat"
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
        
        tts_response = await _run_with_retry(
            loop,
            lambda: client.audio.speech.complete(
                model=TTS_MODEL,
                input=cleaned_spoken_text if cleaned_spoken_text else agent_text,
                voice_id=voice_id,
                response_format="mp3"
            ),
            timeout_seconds=30.0,
            label="Mistral TTS"
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
                # Auto-create conversation if it doesn't exist
                conv = session.get(ResearchConversation, conversation_id)
                if not conv:
                    practitioner_id = int(data.get("practitioner_id", 0)) or 1
                    conv = ResearchConversation(
                        id=conversation_id,
                        practitioner_id=practitioner_id,
                        title="Voice Call - " + datetime.utcnow().strftime("%b %d"),
                        preview="Processing attachments...",
                        conversation_type="call"
                    )
                    session.add(conv)
                    session.commit()
                    session.refresh(conv)

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



@sio.on("mira:ask_patient_question")
async def handle_ask_patient_question(sid, data):
    """
    Handles real-time Ask Mira queries from the patient summary drawer.
    Accepts: data = {"patient_id": 123, "question": "..."}
    """
    try:
        from utils.mira.analysis import get_patient_profile_context, llm
        from sqlmodel import Session
        from database import engine
        
        patient_id = data.get("patient_id")
        question = data.get("question")
        
        if not patient_id or not question:
            return {"error": "Missing 'patient_id' or 'question'"}
            
        print(f"[Socket.IO] Ask Mira request from {sid} for patient {patient_id}")
        
        loop = asyncio.get_event_loop()
        
        def run_llm():
            with Session(engine) as session:
                ctx = get_patient_profile_context(patient_id, session)
                patient = ctx.get("patient")
                if not patient:
                    raise Exception("Patient not found")
                    
                profile_text = ctx.get("profile_text", "")
                if not llm:
                    raise Exception("AI service is currently offline.")

                prompt = f"""
You are Mira, a clinical AI assistant. You are answering a question from a practitioner about this patient.
Answer the question accurately, professionally, and concisely using the provided patient clinical profile.
If the profile does not contain the answer, state that it is not in the patient's records.

[PATIENT CLINICAL PROFILE]
{profile_text}

Practitioner Question: {question}

Provide your answer in clear, markdown-friendly text. Keep it clinical and brief.
"""
                response = llm.invoke(prompt)
                return response.content.strip()

        # Run blocking LLM call in a thread with a 45-second timeout
        answer = await _run_with_retry(
            loop, 
            run_llm, 
            timeout_seconds=45.0, 
            max_retries=1, 
            label="Patient Ask Mira LLM"
        )
        
        await sio.emit("mira:ask_patient_question_response", {
            "patient_id": patient_id,
            "answer": answer
        }, to=sid)
        
        return {"success": True}

    except Exception as e:
        print(f"[Socket.IO] Mira Ask Patient Error: {e}")
        await sio.emit("mira:ask_patient_question_error", {
            "patient_id": data.get("patient_id"),
            "error": str(e)
        }, to=sid)
        return {"error": str(e)}

