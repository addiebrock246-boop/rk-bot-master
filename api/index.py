import os, json, requests as req, asyncio, io
from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import vercel_blob

# ========== TERI DETAILS (ALREADY SET) ==========
BOT_TOKEN = "8510609111:AAGX3O_sbuIZOhV45ziYoM-HzlScxNSEl84"
OWNER_ID = 5964851833
UPSTASH_URL = "https://welcomed-flounder-86019.upstash.io"
UPSTASH_TOKEN = "gQAAAAAAAVADAAIgcDE3ZmI1NTk4N2VmMTM0ZTExOWJiNDk5NTNmNjRkMWM1Yg"
BLOB_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")
GAME_RUNNER_URL = "https://rk-game-runner.vercel.app"   # 👈 apna runner project ka URL

# ---------- KV Helpers ----------
def kv_get(key):
    if not UPSTASH_URL:
        raise Exception("UPSTASH_REDIS_REST_URL not set")
    url = f"{UPSTASH_URL}/get/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    resp = req.get(url, headers=headers, timeout=5)
    if resp.status_code != 200:
        raise Exception(f"KV GET failed: {resp.status_code} {resp.text}")
    return resp.json().get("result")

def kv_set(key, value):
    if not UPSTASH_URL:
        raise Exception("UPSTASH_REDIS_REST_URL not set")
    url = f"{UPSTASH_URL}/set/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    resp = req.post(url, headers=headers, data=value, timeout=5)
    if resp.status_code != 200:
        raise Exception(f"KV SET failed: {resp.status_code} {resp.text}")

def kv_delete(key):
    if not UPSTASH_URL:
        return
    url = f"{UPSTASH_URL}/del/{key}"
    headers = {"Authorization": f"Bearer {UPSTASH_TOKEN}"}
    req.get(url, headers=headers, timeout=5)

# ---------- Photo Upload to Vercel Blob ----------
def upload_photo_to_blob(file_data, filename):
    """Upload image bytes to Vercel Blob and return public URL."""
    # add_random_suffix ensures unique filename every time
    resp = vercel_blob.put(filename, file_data, add_random_suffix=True)
    return resp['url']

# ---------- DM HANDLER ----------
DM_PASSWORD = "RISHAVBHAGWANHAI"
authenticated_users = set()

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages during setup."""
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or update.effective_chat.type != "private":
        return
    if user.id != OWNER_ID:
        await msg.reply_text("You are not authorized.")
        return

    state_key = f"setup_state:{user.id}"
    state_json = kv_get(state_key)
    if not state_json:
        await msg.reply_text("No active setup session. Use /setup first.")
        return
    state = json.loads(state_json)

    if state.get("step") != "photo_url":
        await msg.reply_text("I'm not expecting a photo right now. Send text or /cancel.")
        return

    try:
        file = await msg.photo[-1].get_file()
        file_bytes = await file.download_as_bytearray()
        photo_url = upload_photo_to_blob(bytes(file_bytes), f"photo_{user.id}_{file.file_id}.jpg")
        state["data"]["photo_url"] = photo_url
        state["step"] = "caption"
        kv_set(state_key, json.dumps(state))
        await msg.reply_text(f"✅ Photo uploaded! Now send caption text (use \\n for new lines):")
    except Exception as e:
        await msg.reply_text(f"❌ Failed to upload photo: {str(e)}")

async def dm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user or update.effective_chat.type != "private":
        return
    if user.id != OWNER_ID:
        await msg.reply_text("You are not authorized.")
        return

    text = msg.text.strip() if msg.text else ""

    # /debug command
    if text == "/debug":
        await msg.reply_text("Testing KV...")
        try:
            kv_set("test_key", "test_value")
            val = kv_get("test_key")
            if val == "test_value":
                await msg.reply_text("✅ KV is working perfectly!")
            else:
                await msg.reply_text(f"⚠️ KV GET returned unexpected: {val}")
        except Exception as e:
            await msg.reply_text(f"❌ KV Error: {str(e)}")
        return

    # /reset command
    if text == "/reset":
        authenticated_users.discard(user.id)
        await msg.reply_text("🔒 Authentication reset. Send password to continue.")
        return

    # Authentication
    if user.id not in authenticated_users:
        if text == DM_PASSWORD:
            authenticated_users.add(user.id)
            await msg.reply_text(
                "✅ Authenticated.\n\n"
                "📋 Commands:\n"
                "/setup <game_bot_token> — Configure a game bot's /start message\n"
                "/list_bots — List all configured bots (coming soon)\n"
                "/reset — Clear authentication\n"
                "/debug — Test KV connection\n"
                "/cancel — Cancel current setup"
            )
        else:
            await msg.reply_text("Incorrect password.")
        return

    # ---------- Setup Flow ----------
    state_key = f"setup_state:{user.id}"
    state_json = kv_get(state_key)
    state = json.loads(state_json) if state_json else None

    if text.startswith("/setup"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await msg.reply_text("Usage: /setup <game_bot_token>")
            return
        token = parts[1]
        state = {"step": "photo_url", "token": token, "data": {}}
        kv_set(state_key, json.dumps(state))
        await msg.reply_text("📸 Send a photo (or type 'none' to skip, or type a URL):")
        return

    if text == "/cancel" and state:
        kv_delete(state_key)
        await msg.reply_text("🚫 Setup cancelled.")
        return

    if state:
        step = state["step"]
        data = state["data"]
        token = state["token"]

        if step == "photo_url":
            if text.lower() == "none":
                data["photo_url"] = ""
                state["step"] = "caption"
                kv_set(state_key, json.dumps(state))
                await msg.reply_text("No photo will be used. Send caption text (use \\n for new lines):")
            else:
                data["photo_url"] = text
                state["step"] = "caption"
                kv_set(state_key, json.dumps(state))
                await msg.reply_text("Send caption text (use \\n for new lines):")
        elif step == "caption":
            data["caption"] = text.replace("\\n", "\n")
            state["step"] = "second_message"
            kv_set(state_key, json.dumps(state))
            await msg.reply_text("Send second message text (or type 'none' to skip):")
        elif step == "second_message":
            data["second_message"] = text if text.lower() != "none" else ""
            state["step"] = "button_text"
            kv_set(state_key, json.dumps(state))
            await msg.reply_text("Send launch button text:")
        elif step == "button_text":
            data["button_text"] = text
            state["step"] = "button_url"
            kv_set(state_key, json.dumps(state))
            await msg.reply_text("Send game URL (e.g., https://cryptomines.vercel.app):")
        elif step == "button_url":
            data["button_url"] = text
            # Save config
            config_key = f"config:{token}"
            kv_set(config_key, json.dumps(data))
            kv_delete(state_key)
            # ✅ Auto-set webhook to runner
            webhook_url = f"{GAME_RUNNER_URL}/api/{token}"
            set_resp = req.get(f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}")
            if set_resp.status_code == 200 and set_resp.json().get("ok"):
                await msg.reply_text("✅ Game bot configured and webhook set! Users will see updated /start.")
            else:
                await msg.reply_text(f"✅ Config saved but webhook failed: {set_resp.text}. Manually set: {webhook_url}")
        return

    if text == "/list_bots":
        await msg.reply_text("Feature coming soon — will list all configured game bots.")
        return

    await msg.reply_text("Unknown command. Use /setup <token>, /list_bots, /reset, /debug, /cancel.")

# ---------- FLASK ----------
app = Flask(__name__)

@app.route("/api", methods=["POST"])
def webhook():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        data = request.get_json()
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, handle_photo))
        application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, dm_handler))
        loop.run_until_complete(application.initialize())
        update = Update.de_json(data, application.bot)
        loop.run_until_complete(application.process_update(update))
        loop.run_until_complete(application.shutdown())
        return jsonify({"ok": True})
    finally:
        loop.close()

def handler(request):
    return app(request.environ, start_response)
