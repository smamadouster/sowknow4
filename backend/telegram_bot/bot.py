"""
SOWKNOW Telegram Bot
Provides mobile-first interface for document upload and knowledge queries
"""
import os
import logging
from uuid import uuid4
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.ext import CallbackQueryHandler

import httpx

# Configuration
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramBotClient:
    """Client for communicating with SOWKNOW backend"""

    def __init__(self):
        self.base_url = BACKEND_URL
        self.api_key = None  # Will be set after authentication

    async def login(self, telegram_user_id: int) -> dict:
        """
        Login or register user via Telegram

        Args:
            telegram_user_id: Telegram user ID

        Returns:
            dict with access token and user info
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/auth/telegram",
                    json={"telegram_user_id": telegram_user_id},
                    timeout=10.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Login error: {str(e)}")
            return {"error": str(e)}

    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        bucket: str,
        access_token: str
    ) -> dict:
        """Upload document to backend"""
        try:
            files = {"file": (filename, file_bytes)}
            data = {"bucket": bucket}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/documents/upload",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Upload error: {str(e)}")
            return {"error": str(e)}

    async def search(self, query: str, access_token: str) -> dict:
        """Search documents"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/search",
                    json={"query": query, "limit": 5},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=30.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            return {"error": str(e)}

    async def send_chat_message(
        self,
        session_id: str,
        content: str,
        access_token: str
    ) -> dict:
        """Send message to chat session"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/chat/sessions/{session_id}/message",
                    json={"content": content},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=60.0
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Chat error: {str(e)}")
            return {"error": str(e)}


# Global bot client
bot_client = TelegramBotClient()

# User session storage (in production, use Redis)
user_sessions = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command"""
    user = update.effective_user

    # Authenticate user
    login_result = await bot_client.login(user.id)

    if "error" in login_result:
        await update.message.reply_html(
            f"👋 <b>Welcome to SOWKNOW!</b>\n\n"
            f"❌ Error: {login_result['error']}\n\n"
            f"Please try again later."
        )
        return

    # Store user session
    user_sessions[user.id] = {
        "access_token": login_result.get("access_token"),
        "user": login_result.get("user"),
        "chat_session_id": None
    }

    welcome_text = f"""👋 <b>Welcome to SOWKNOW, {user.first_name}!</b>

📚 I'm your personal knowledge assistant. I can help you:

📤 <b>Upload Documents</b>
• Send me any file (PDF, images, docs, etc.)
• Add "public" or "confidential" in caption
• I'll process and index them for search

🔍 <b>Search Knowledge</b>
• Just ask me anything about your documents
• I'll find relevant information

💬 <b>Chat</b>
• Conversational AI powered by Kimi 2.5
• Your confidential docs stay private (Ollama)

<b>Quick Start:</b>
1. Upload a document
2. Ask a question about it
3. Get instant answers!

📌 Commands:
/start - Show this message
/upload - Upload a document
/search - Search your knowledge
/chat - Start a chat session
/help - Get help"""

    keyboard = [
        [InlineKeyboardButton("📤 Upload Document", callback_data="upload_prompt")],
        [InlineKeyboardButton("🔍 Search", callback_data="search_prompt")],
        [InlineKeyboardButton("💬 Chat", callback_data="chat_prompt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_html(welcome_text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command"""
    help_text = """📖 <b>SOWKNOW Bot Help</b>

<b>Document Upload:</b>
• Send any file directly
• Add caption with visibility:
  - "public" - Anyone can see
  - "confidential" - Admin only
• Supported: PDF, images, docs, etc.

<b>Search:</b>
• Type /search followed by your query
• Or just type your question directly
• Results include source citations

<b>Chat:</b>
• /chat to start a conversation
• Ask questions naturally
• Get answers from your documents

<b>Examples:</b>
• "What did I learn about solar energy?"
• "Show me all my balance sheets"
• "Summarize documents from 2020"

❓ Need more help? Contact admin."""

    await update.message.reply_html(help_text)


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document file uploads"""
    user = update.effective_user

    if user.id not in user_sessions:
        await update.message.reply_text("❌ Please use /start first to authenticate.")
        return

    session = user_sessions[user.id]
    document = update.message.document
    photo = update.message.photo

    # Get file
    if document:
        file = document
        filename = document.file_name
    elif photo:
        # Get largest photo
        file = photo[-1]
        filename = f"photo_{file.file_id}.jpg"
    else:
        return

    # Parse caption for bucket and tags
    caption = update.message.caption or ""
    caption_lower = caption.lower()

    # Determine bucket
    if "confidential" in caption_lower:
        bucket = "confidential"
        bucket_emoji = "🔒"
    else:
        bucket = "public"
        bucket_emoji = "📄"

    # Get file bytes
    try:
        file_obj = await file.get_file()
        file_bytes = await file_obj.download_as_bytearray()

        # Upload to backend
        await update.message.reply_text(f"⏳ Uploading {bucket_emoji} {filename}...")

        result = await bot_client.upload_document(
            file_bytes=file_bytes,
            filename=filename,
            bucket=bucket,
            access_token=session["access_token"]
        )

        if "error" in result:
            await update.message.reply_text(f"❌ Upload failed: {result['error']}")
        else:
            await update.message.reply_text(
                f"✅ Document uploaded successfully!\n\n"
                f"📁 {bucket_emoji} {filename}\n"
                f"🆔 {result.get('document_id', 'N/A')}\n"
                f"📊 Status: {result.get('status', 'processing')}\n\n"
                f"Document is being processed. You'll be able to search it soon!"
            )

    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages (search and chat)"""
    user = update.effective_user
    text = update.message.text

    if not text or text.startswith("/"):
        return

    if user.id not in user_sessions:
        await update.message.reply_text("❌ Please use /start first.")
        return

    session = user_sessions[user.id]

    # Check if it's a search command
    if text.startswith("/search "):
        query = text[8:]
    else:
        query = text

    # Perform search
    await update.message.reply_text("🔍 Searching...")

    result = await bot_client.search(query, session["access_token"])

    if "error" in result:
        await update.message.reply_text(f"❌ Search error: {result['error']}")
        return

    results = result.get("results", [])
    total = result.get("total", 0)

    if total == 0:
        await update.message.reply_text(
            f"📭 No results found for: \"{query}\"\n\n"
            f"💡 Try different keywords or upload more documents."
        )
    else:
        response = f"🔍 Found {total} result(s) for: \"{query}\"\n\n"

        for i, r in enumerate(results[:5], 1):
            snippet = r.get("chunk_text", "")[:150]
            doc_name = r.get("document_name", "Unknown")
            score = r.get("relevance_score", 0)

            response += f"{i}. <b>{doc_name}</b> ({score:.0%})\n"
            response += f"   {snippet}...\n\n"

        if total > 5:
            response += f"... and {total - 5} more results"

        response += f"\n🤖 {result.get('llm_used', 'kimi').capitalize()}"

        await update.message.reply_html(response, disable_web_page_preview=True)


async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle upload button callback"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "📤 <b>Upload a Document</b>\n\n"
        "Send me any file and I'll process it!\n\n"
        "Add to caption:\n"
        "• 'public' - visible to all\n"
        "• 'confidential' - admin only\n\n"
        "Supported: PDF, images, docs, spreadsheets, etc."
    )


async def search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle search button callback"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🔍 <b>Search Your Knowledge</b>\n\n"
        "Type your question or use:\n"
        "/search your query here\n\n"
        "I'll find relevant information from your documents!"
    )


async def chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle chat button callback"""
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "💬 <b>Chat Mode</b>\n\n"
        "Just type your question and I'll answer using your documents!\n\n"
        "Confidential documents will be processed securely using Ollama.\n\n"
        "Type /cancel to exit chat mode."
    )


def main() -> None:
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    # Create application
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upload", upload_callback))
    application.add_handler(CommandHandler("search", handle_text_message))
    application.add_handler(CommandHandler("chat", chat_callback))

    # Callback query handlers
    application.add_handler(CallbackQueryHandler(upload_callback, pattern="^upload_prompt"))
    application.add_handler(CallbackQueryHandler(search_callback, pattern="^search_prompt"))
    application.add_handler(CallbackQueryHandler(chat_callback, pattern="^chat_prompt"))

    # Message handlers
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document_upload))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))

    # Start bot
    logger.info("SOWKNOW Telegram Bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
