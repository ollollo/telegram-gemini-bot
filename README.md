# Jarvis — Telegram butler bot

Async Telegram bot ([aiogram](https://docs.aiogram.dev/) 3) with Gemini function calling. Jarvis can chat, analyse photos, summarise Gmail, fetch science and gaming RSS, and manage Google Calendar.

## Requirements

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Gemini API key
- Optional: Google Cloud OAuth client for Gmail and Calendar

## Quick start

```bash
git clone <your-repo-url>
cd <repo-directory>
python -m pip install -r requirements.txt
cp .env.example .env   # Windows: copy .env.example .env
```

Edit `.env` and set `BOT_TOKEN` and `GEMINI_API_KEY`. Leave `SYSTEM_INSTRUCTION` unset to keep the built-in Jarvis persona.

```bash
python main.py
```

## Google Cloud OAuth (Gmail + Calendar)

Personal Gmail does **not** work with a service account. Use OAuth2 and save `token.json` locally.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create (or select) a project.
2. Enable **Gmail API** and **Google Calendar API**.
3. Configure the **OAuth consent screen** (External is fine for a personal account). Add your Google account as a test user. Scopes used:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar`
4. Create an OAuth client of type **Desktop app**. Download the JSON and save it as `credentials.json` next to `main.py`.
5. Run:

```bash
python -m utils.setup_oauth
```

Sign in with the Google account that owns the inbox and calendar. This writes `token.json`.

## Security

Do **not** commit or upload:

- `.env`
- `credentials.json`
- `token.json`
- `data/` (local SQLite history)

These paths are listed in `.gitignore`. Rotate any token that was ever pasted into chat, a screenshot, or a public gist.

## Usage

- Text: conversation with sliding-window history (`/clear` wipes it).
- Photo: multimodal analysis.
- “Check my mail”, “science news”, “what is on my calendar tomorrow”, “remind me at 18:00…” trigger tools.

If the time is ambiguous, Jarvis asks before creating a calendar event.

## Layout

```
config.py             # Environment and Jarvis system prompt
database.py           # Async SQLite chat history
gemini_service.py     # Gemini client and function-calling loop
handlers.py           # Telegram routes
main.py               # Polling entrypoint
services/             # Gmail, Calendar, RSS
utils/                # Stream throttling and OAuth helpers
.env.example          # Placeholder environment variables
```
