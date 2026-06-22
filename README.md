# GP-Connect Server (Mira-Q-Zero)

A robust, AI-powered FastAPI backend serving the GP-Connect / Mira-Q-Zero platform. This server manages NHS GP connections, patient records, clinical data, and real-time AI consultations via WebSockets and advanced LLM integrations.

## 🚀 Features

- **FastAPI Backend:** High-performance, async-first API framework.
- **Real-Time Communication:** Integrated Socket.IO for seamless real-time AI voice/chat consultations.
- **AI Integration:** Advanced routing and processing powered by LangChain, LangGraph, CrewAI, MistralAI, and OpenAI.
- **Vector Search:** LanceDB and Pinecone integrations for rapid semantic search over clinical and operational data.
- **NHS Integrations:** Utilities for fetching GP availability and managing slots across English and Scottish GP networks.
- **Authentication:** Secure JWT-based authentication with role-based access control (RBAC).
- **Relational Data Management:** Built on top of SQLModel and SQLite/PostgreSQL.

## 🛠️ Technology Stack

- **Language:** Python 3.12+
- **Framework:** FastAPI
- **Database ORM:** SQLModel
- **State Management / AI:** LangChain, LangGraph, CrewAI
- **WebSockets:** python-socketio
- **Package Manager:** `uv` (Fast, modern Python dependency manager)

## 📦 Project Structure

```
server/
├── main.py                    # Application entry point and SocketIO wrapping
├── database.py                # Database connection and engine
├── models.py                  # SQLModel schemas
├── routes/                    # API Endpoints
│   ├── auth.py                # Authentication and authorization
│   ├── bookings.py            # Appointment bookings
│   ├── consultation.py        # AI consultation handling
│   ├── gps.py                 # GP search and management
│   ├── medTech/               # Clinical and patient records
│   └── tts.py                 # Text-to-Speech endpoints
├── utils/                     # Helper modules and AI integrations
│   ├── ai_voice.py            # AI voice generation
│   ├── fetch_english_gps.py   # English GP data fetching
│   ├── fetch_scottish_gps.py  # Scottish GP data fetching
│   └── ...                    # Other utility functions
├── socket_setup.py            # Socket.IO configuration
├── seed_patients.py           # Database seeding script
├── pyproject.toml             # Project metadata and dependencies
└── uv.lock                    # Locked dependencies
```

## ⚙️ Getting Started

### Prerequisites

- Python >= 3.12
- [uv](https://github.com/astral-sh/uv) package manager installed

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Benjamin-chidera/Mira-Q-Zero-server.git
   cd Mira-Q-Zero-server/server
   ```

2. **Set up the virtual environment and install dependencies using `uv`:**
   ```bash
   uv venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   uv sync
   ```

3. **Set up your environment variables:**
   Create a `.env` file in the `server` directory and add the necessary configuration. Example:
   ```ini
   ALLOWED_ORIGINS=http://localhost:5173
   ADMIN_EMAIL=admin@gpconnect.nhs.uk
   ADMIN_PASSWORD=AdminPass123!
   ADMIN_NAME="System Administrator"
   # Add your API keys (OpenAI, Mistral, Pinecone, etc.)
   ```

### Running the Server

Start the development server using `uvicorn`:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at `http://localhost:8000`.  
Swagger UI Documentation: `http://localhost:8000/docs`

### 🐳 Running with Docker Compose

The application is containerized with Docker and Docker Compose. It provisions three services:
1. **web:** The FastAPI web backend.
2. **worker:** The Celery background task worker for agent executions.
3. **redis:** The Redis instance used for caching and Celery broker/backend.

Ensure you have Docker installed, then configure your `.env` file and run:

```bash
docker-compose up --build
```

### 🧠 Redis Caching & Background Workers

To optimize response times and manage long-running agent tasks without blocking the main event loop, we use:
- **Redis Caching:** Query requests are hashed using MD5 of the query and attachment names. Successful CrewAI responses are cached in Redis for 1 hour.
- **Celery Worker:** AI computations are delegated to a Celery worker (`worker` service in compose or run `celery -A celery_worker.celery_app worker --loglevel=info`).
- **Pub/Sub Real-time Flow:** The Celery worker publishes result updates to a Redis pub/sub channel. An async listener running inside the web process listens and pushes the responses to the corresponding Socket.IO client ID.

### 📋 Mira Research Center Status Workflow

Mira Research Center tracks the state of each research session:
- **Ongoing:** Currently active research.
- **Completed:** Marked successful by the practitioner.
- **Failed:** Marked failed (e.g., no relevant studies found). Prompts user for a reason.
- **Abandoned:** Closed or abandoned by the user. Prompts user for a reason.

All updates are audited on the backend, and status changes are persisted in the SQLite/PostgreSQL database.

## 🔒 Default Admin Account

Upon the first run, the system automatically seeds a default administrator account. You can override these defaults via environment variables:

- **Email:** `admin@gpconnect.nhs.uk`
- **Password:** `AdminPass123!`

## 🧑‍💻 Development Rules

- **Clean Code:** Write readable, simple code. Prioritize readability over cleverness.
- **SOLID Principles:** Adhere strictly to single responsibility and dependency inversion.
- **Package Management:** Always use `uv` instead of `pip` for dependency management (`uv add <package>`).