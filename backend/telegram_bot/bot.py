"""
SOWKNOW Telegram Bot
Provides mobile-first interface for document upload and knowledge queries
"""
import os
import logging
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from network_utils import ResilientAsyncClient, CircuitBreakerOpenError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import CallbackQueryHandler, ConversationHandler

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
BOT_API_KEY = os.getenv("BOT_API_KEY", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

(SELECTING_BUCKET, CHECKING_DUPLICATE) = range(2)

# Track document processing status updates
# Format: {document_id: {"chat_id": int, "message_id": int, "status": str, "check_count": int}}
document_tracking = {}
MAX_STATUS_CHECKS = 60  # Maximum number of checks (5 seconds * 60 = 5 minutes max)


class TelegramBotClient:
    def __init__(self):
        self.base_url = BACKEND_URL
        self._client = ResilientAsyncClient(
            base_url=BACKEND_URL,
            max_attempts=3,
            min_wait=1,
            max_wait=10,
            timeout=60.0,
            enable_circuit_breaker=True,
        )

    async def close(self) -> None:
        await self._client.close()

    async def login(self, telegram_user_id: int) -> dict:
        try:
            response = await self._client.post(
                "/api/v1/auth/telegram",
                json={"telegram_user_id": telegram_user_id},
                headers={"X-Bot-Api-Key": BOT_API_KEY},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return {"error": str(e)}

    async def check_duplicate(self, filename: str, access_token: str) -> dict:
        try:
            response = await self._client.get(
                f"/api/v1/documents?search={filename}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code == 404:
                return {"exists": False, "documents": []}
            response.raise_for_status()
            data = response.json()
            return {"exists": len(data.get("documents", [])) > 0, "documents": data.get("documents", [])}
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable", "exists": False}
        except Exception as e:
            logger.error(f"Check duplicate error: {str(e)}")
            return {"error": str(e), "exists": False}

    async def upload_document(self, file_bytes: bytes, filename: str, bucket: str, access_token: str) -> dict:
        try:
            files = {"file": (filename, file_bytes)}
            data = {"bucket": bucket}
            headers = {"Authorization": f"Bearer {access_token}"}
            if BOT_API_KEY:
                headers["X-Bot-Api-Key"] = BOT_API_KEY
                logger.info(f"X-Bot-Api-Key header added (length: {len(BOT_API_KEY)})")
            else:
                logger.error("BOT_API_KEY is empty! Cannot authenticate upload.")

            logger.info(f"Uploading document: {filename} ({len(file_bytes)} bytes) to bucket: {bucket}")
            logger.info(f"Backend URL: {self.base_url}/api/v1/documents/upload")
            logger.info(f"Headers: {headers}")
            logger.info(f"BOT_API_KEY present: {bool(BOT_API_KEY)}")

            response = await self._client.post(
                "/api/v1/documents/upload",
                files=files,
                data=data,
                headers=headers,
            )
            logger.info(f"Upload response status: {response.status_code}")
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return {"error": str(e)}

    async def get_document_status(self, document_id: str, access_token: str) -> dict:
        """Get the current status of a document"""
        try:
            response = await self._client.get(
                f"/api/v1/documents/{document_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable"}
        except Exception as e:
            logger.error(f"Get document status error: {str(e)}")
            return {"error": str(e)}

    async def search(self, query: str, access_token: str) -> dict:
        try:
            response = await self._client.post(
                "/api/v1/search",
                json={"query": query, "limit": 5},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return {"error": str(e)}

    async def send_chat_message(self, session_id: str, content: str, access_token: str) -> dict:
        try:
            response = await self._client.post(
                f"/api/v1/chat/sessions/{session_id}/message",
                json={"content": content},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable. Please try again later."}
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return {"error": str(e)}

    def get_circuit_breaker_status(self) -> dict:
        return self._client.get_circuit_breaker_status() or {}


bot_client = TelegramBotClient()

user_context = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    login_result = await bot_client.login(user.id)

    if "error" in login_result:
        await update.message.reply_html(f"👋 <b>Welcome to SOWKNOW!</b>\n\n❌ Error: {login_result['error']}")
        return

    user_context[user.id] = {
        "access_token": login_result.get("access_token"),
        "user": login_result.get("user"),
        "chat_session_id": None,
        "pending_file": None
    }

    welcome_text = f"""👋 <b>Welcome to SOWKNOW, {user.first_name}!</b>

📚 Your personal knowledge assistant:

📤 <b>Upload Documents</b>
• Send me any file (PDF, images, docs)
• I'll ask if you want it PUBLIC or CONFIDENTIAL
• I'll check for duplicates

🔍 <b>Search Knowledge</b>
• Just ask me anything

💬 <b>Chat</b>
• Conversational AI powered by Gemini Flash

📌 Commands:
/start - Show this message
/help - Get help"""

    keyboard = [
        [InlineKeyboardButton("📤 Upload Document", callback_data="upload_prompt")],
        [InlineKeyboardButton("🔍 Search", callback_data="search_prompt")],
        [InlineKeyboardButton("💬 Chat", callback_data="chat_prompt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_html(welcome_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = """📖 <b>SOWKNOW Bot Help</b>

<b>Document Upload:</b>
• Send any file directly
• I'll ask if you want PUBLIC or CONFIDENTIAL
• I'll check for duplicates first

<b>Search:</b>
• Type your question
• Or use /search your query

<b>Chat:</b>
• Just type your question!

<b>Examples:</b>
• "What did I learn about solar energy?"
• "Show me all my documents"
• family photos

❓ Need help? Contact admin."""

    await update.message.reply_html(help_text)


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id not in user_context:
        await update.message.reply_text("❌ Please use /start first to authenticate.")
        return

    document = update.message.document
    photo = update.message.photo

    if document:
        file = document
        filename = document.file_name
    elif photo:
        file = photo[-1]
        filename = f"photo_{file.file_id}.jpg"
    else:
        return

    try:
        file_obj = await file.get_file()
        file_bytes = await file_obj.download_as_bytearray()

        user_context[user.id]["pending_file"] = {
            "file": bytes(file_bytes),
            "filename": filename
        }

        await update.message.reply_text(
            f"📄 <b>{filename}</b>\n\n"
            f"⏳ Checking for duplicates...",
            parse_mode="HTML"
        )

        session = user_context[user.id]
        duplicate_check = await bot_client.check_duplicate(filename, session["access_token"])

        if duplicate_check.get("exists"):
            dupes = duplicate_check.get("documents", [])
            dupe_list = "\n".join([f"• {d.get('title', 'Untitled')}" for d in dupes[:3]])
            await update.message.reply_text(
                f"⚠️ <b>Duplicate found!</b>\n\n"
                f"Similar documents:\n{dupe_list}\n\n"
                f"Do you still want to upload this file?",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"✅ No duplicates found!\n\n"
                f"<b>{filename}</b>\n\n"
                f"🔐 Where should this file go?",
                parse_mode="HTML"
            )

        keyboard = [
            [InlineKeyboardButton("📄 Public", callback_data="bucket_public")],
            [InlineKeyboardButton("🔒 Confidential", callback_data="bucket_confidential")],
            [InlineKeyboardButton("❌ Cancel", callback_data="bucket_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Choose visibility:",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"File download error: {str(e)}")
        await update.message.reply_text(f"❌ Error preparing file: {str(e)}")


async def bucket_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if user.id not in user_context:
        await query.edit_message_text("❌ Session expired. Please use /start again.")
        return

    pending = user_context[user.id].get("pending_file")
    if not pending:
        await query.edit_message_text("❌ No file pending. Please upload a file first.")
        return

    bucket_data = query.data

    if bucket_data == "bucket_cancel":
        user_context[user.id]["pending_file"] = None
        await query.edit_message_text("❌ Upload cancelled.")
        return

    bucket = "confidential" if bucket_data == "bucket_confidential" else "public"
    bucket_emoji = "🔒" if bucket == "confidential" else "📄"

    session = user_context[user.id]

    await query.edit_message_text(f"⏳ Uploading {bucket_emoji} {pending['filename']}...")

    result = await bot_client.upload_document(
        file_bytes=pending["file"],
        filename=pending["filename"],
        bucket=bucket,
        access_token=session["access_token"]
    )

    user_context[user.id]["pending_file"] = None

    if "error" in result:
        await query.edit_message_text(f"❌ Upload failed: {result['error']}")
    else:
        document_id = result.get('document_id', 'N/A')
        # Store message info for status updates
        message = await query.edit_message_text(
            f"✅ <b>Document uploaded!</b>\n\n"
            f"📁 {bucket_emoji} {pending['filename']}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: processing\n\n"
            f"🔄 Processing in progress...",
            parse_mode="HTML"
        )
        # Track document for status updates
        document_tracking[document_id] = {
            "chat_id": query.message.chat_id,
            "message_id": message.message_id if message else query.message.message_id,
            "filename": pending['filename'],
            "bucket_emoji": bucket_emoji,
            "access_token": session["access_token"],
            "last_status": "processing",
            "check_count": 0
        }
        # Schedule status check
        context.job_queue.run_once(
            check_document_status,
            when=5,  # Check after 5 seconds
            data=document_id,
            name=f"status_check_{document_id}"
        )


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text

    if not text or text.startswith("/"):
        return

    if user.id not in user_context:
        await update.message.reply_text("❌ Please use /start first.")
        return

    session = user_context[user.id]

    # Handle text-based bucket selection (fallback for button clicks)
    if text.lower() in ["public", "confidential", "yes", "no"]:
        pending = user_context[user.id].get("pending_file")
        if pending:
            bucket = "public" if text.lower() in ["public", "yes"] else "confidential"
            bucket_emoji = "📄" if bucket == "public" else "🔒"

            status_message = await update.message.reply_text(
                f"⏳ Uploading {bucket_emoji} {pending['filename']}..."
            )

            result = await bot_client.upload_document(
                file_bytes=pending["file"],
                filename=pending["filename"],
                bucket=bucket,
                access_token=session["access_token"]
            )

            user_context[user.id]["pending_file"] = None

            if "error" in result:
                await status_message.edit_text(f"❌ Upload failed: {result['error']}")
            else:
                document_id = result.get('document_id', 'N/A')
                await status_message.edit_text(
                    f"✅ <b>Document uploaded!</b>\n\n"
                    f"📁 {bucket_emoji} {pending['filename']}\n"
                    f"🆔 ID: {document_id}\n"
                    f"📊 Status: processing\n\n"
                    f"🔄 Processing in progress...",
                    parse_mode="HTML"
                )
                # Track document for status updates
                document_tracking[document_id] = {
                    "chat_id": update.message.chat_id,
                    "message_id": status_message.message_id,
                    "filename": pending['filename'],
                    "bucket_emoji": bucket_emoji,
                    "access_token": session["access_token"],
                    "last_status": "processing",
                    "check_count": 0
                }
                # Schedule status check
                context.job_queue.run_once(
                    check_document_status,
                    when=5,  # Check after 5 seconds
                    data=document_id,
                    name=f"status_check_{document_id}"
                )
            return

    await update.message.reply_text("🔍 Searching...")
    result = await bot_client.search(text, session["access_token"])

    if "error" in result:
        await update.message.reply_text(f"❌ Search error: {result['error']}")
        return

    results = result.get("results", [])
    total = result.get("total", 0)

    if total == 0:
        await update.message.reply_text(f"📭 No results for: \"{text}\"")
    else:
        response = f"🔍 Found {total} result(s):\n\n"
        for i, r in enumerate(results[:5], 1):
            snippet = r.get("chunk_text", "")[:150]
            doc_name = r.get("document_name", "Unknown")
            score = r.get("relevance_score", 0)
            response += f"{i}. <b>{doc_name}</b> ({score:.0%})\n{snippet}...\n\n"
        response += f"🤖 {result.get('llm_used', 'gemini').capitalize()}"
        await update.message.reply_html(response, disable_web_page_preview=True)


async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📤 <b>Upload a Document</b>\n\n"
        "Send me any file!\n\n"
        "I'll ask if you want:\n"
        "• 📄 Public - visible to all\n"
        "• 🔒 Confidential - admin only\n\n"
        "I'll also check for duplicates!",
        parse_mode="HTML"
    )


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 <b>Search</b>\n\nType your question!", parse_mode="HTML")


async def chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💬 <b>Chat Mode</b>\n\nJust type your question!", parse_mode="HTML")


async def check_document_status(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check document processing status and update user"""
    document_id = context.job.data
    
    if document_id not in document_tracking:
        logger.warning(f"Document {document_id} not found in tracking")
        return
    
    tracking_info = document_tracking[document_id]
    chat_id = tracking_info["chat_id"]
    message_id = tracking_info["message_id"]
    filename = tracking_info["filename"]
    bucket_emoji = tracking_info["bucket_emoji"]
    access_token = tracking_info["access_token"]
    last_status = tracking_info["last_status"]
    check_count = tracking_info["check_count"]
    
    # Increment check count
    document_tracking[document_id]["check_count"] = check_count + 1
    
    # Check if we've exceeded maximum checks (timeout)
    if check_count >= MAX_STATUS_CHECKS:
        status_text = (
            f"⏱️ <b>Processing timeout</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: still processing\n\n"
            f"⏳ Processing is taking longer than expected. "
            f"Your document will be available for search once complete."
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to update timeout message for document {document_id}: {e}")
        del document_tracking[document_id]
        return
    
    # Get current document status
    result = await bot_client.get_document_status(document_id, access_token)
    
    if "error" in result:
        logger.error(f"Failed to get status for document {document_id}: {result['error']}")
        # Retry after 10 seconds if there was an error
        context.job_queue.run_once(
            check_document_status,
            when=10,
            data=document_id,
            name=f"status_check_{document_id}_retry"
        )
        return
    
    current_status = result.get("status", "unknown")
    
    # Only update if status changed
    if current_status == last_status:
        # Schedule next check
        if current_status in ["processing", "pending", "uploading"]:
            context.job_queue.run_once(
                check_document_status,
                when=5,  # Check every 5 seconds
                data=document_id,
                name=f"status_check_{document_id}"
            )
        return
    
    # Update tracking
    document_tracking[document_id]["last_status"] = current_status
    
    # Format status message based on status
    if current_status == "indexed":
        status_text = (
            f"✅ <b>Document ready!</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}\n\n"
            f"✨ Your document has been processed and is ready for search!"
        )
        # Remove from tracking - we're done
        del document_tracking[document_id]
    elif current_status == "error":
        status_text = (
            f"❌ <b>Processing failed</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}\n\n"
            f"⚠️ There was an error processing your document. Please try again."
        )
        del document_tracking[document_id]
    elif current_status in ["processing", "pending", "uploading"]:
        status_text = (
            f"✅ <b>Document uploaded!</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}\n\n"
            f"🔄 Processing in progress..."
        )
        # Schedule next check
        context.job_queue.run_once(
            check_document_status,
            when=5,  # Check every 5 seconds
            data=document_id,
            name=f"status_check_{document_id}"
        )
    else:
        # Unknown status
        status_text = (
            f"✅ <b>Document uploaded!</b>\n\n"
            f"📁 {bucket_emoji} {filename}\n"
            f"🆔 ID: {document_id}\n"
            f"📊 Status: {current_status}"
        )
        del document_tracking[document_id]
    
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=status_text,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Failed to update message for document {document_id}: {e}")


def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set! Bot cannot start.")
        print("ERROR: TELEGRAM_BOT_TOKEN environment variable is not set!")
        print("Please set TELEGRAM_BOT_TOKEN and restart the bot.")
        return

    logger.info(f"Initializing Telegram bot with token prefix: {BOT_TOKEN[:10]}...")

    try:
        application = Application.builder().token(BOT_TOKEN).build()
        logger.info(f"Job queue enabled: {application.job_queue is not None}")
    except Exception as e:
        logger.error(f"Failed to build application: {e}")
        print(f"ERROR: Failed to initialize bot: {e}")
        return

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(CallbackQueryHandler(bucket_callback, pattern="^bucket_"))

    application.add_handler(CallbackQueryHandler(upload_callback, pattern="^upload_prompt"))
    application.add_handler(CallbackQueryHandler(search_callback, pattern="^search_prompt"))
    application.add_handler(CallbackQueryHandler(chat_callback, pattern="^chat_prompt"))

    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    logger.info("SOWKNOW Telegram Bot handlers registered")

    # Add error handlers for polling
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.error(f"Exception while handling an update: {context.error}")

    application.add_error_handler(error_handler)

    # Start polling with error handling
    try:
        logger.info("Starting SOWKNOW Telegram Bot polling...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        print(f"ERROR: Bot polling failed: {e}")


if __name__ == "__main__":
    main()
