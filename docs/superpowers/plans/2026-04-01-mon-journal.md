# Mon Journal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a personal journal feature to SOWKNOW where users can capture text, photos, and schemas via Telegram into the confidential bucket, with a dedicated web timeline view and journal-scoped search.

**Architecture:** Journal entries are regular confidential documents with `document_metadata.document_type = "journal"` and `document_metadata.journal_timestamp`. No new DB tables. Text-only entries are saved as `.txt` files. Telegram gets a new "Journal" button and mode. Frontend gets a `/journal` timeline page. Search gets a `journal_only` filter.

**Tech Stack:** FastAPI, SQLAlchemy, python-telegram-bot, Next.js 14, TypeScript, Tailwind CSS, next-intl

---

## File Structure

### Backend — Modified
- `backend/telegram_bot/bot.py` — Add journal mode, menu button, journal search, `/done` handler
- `backend/app/api/documents.py` — Add `document_type` filter to list endpoint, add journal upload helper endpoint
- `backend/app/api/search_agent_router.py` — Add `journal_only` filter param
- `backend/app/services/search_models.py` — Add `journal_only` field to `AgenticSearchRequest`
- `backend/app/services/search_agent.py` — Filter chunks by journal metadata when `journal_only=True`

### Frontend — New
- `frontend/app/[locale]/journal/page.tsx` — Journal timeline page

### Frontend — Modified
- `frontend/components/Navigation.tsx` — Add journal nav item (role-gated)
- `frontend/app/messages/fr.json` — Add journal translations
- `frontend/app/messages/en.json` — Add journal translations

---

## Task 1: Backend — Add `document_type` filter to document list API

**Files:**
- Modify: `backend/app/api/documents.py:677-749`

- [ ] **Step 1: Add `document_type` query parameter to `list_documents`**

In `backend/app/api/documents.py`, modify the `list_documents` function signature to accept a new optional `document_type` parameter and apply a JSONB filter:

```python
@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    bucket: str | None = Query(None),
    status: str | None = Query(None),
    search: str | None = Query(None),
    document_type: str | None = Query(None, description="Filter by document_type in metadata (e.g. 'journal')"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
```

After the existing search filter block (around line 714), add:

```python
    # Apply document_type metadata filter
    if document_type:
        stmt = stmt.where(
            Document.document_metadata["document_type"].astext == document_type
        )
```

- [ ] **Step 2: Test the filter manually**

Run the backend and verify:
```bash
docker exec -it sowknow4-backend python -c "
from app.models.document import Document
from sqlalchemy import select
stmt = select(Document).where(Document.document_metadata['document_type'].astext == 'journal')
print('Query compiles:', stmt.compile())
"
```

Expected: Query compiles without error.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/documents.py
git commit -m "feat(journal): add document_type filter to list_documents endpoint"
```

---

## Task 2: Backend — Add `journal_only` filter to search

**Files:**
- Modify: `backend/app/services/search_models.py:43-58`
- Modify: `backend/app/services/search_agent.py:452-502`

- [ ] **Step 1: Add `journal_only` field to `AgenticSearchRequest`**

In `backend/app/services/search_models.py`, add after line 53 (`include_suggestions: bool = True`):

```python
    journal_only: bool = False
```

- [ ] **Step 2: Filter chunks in `run_agentic_search` when `journal_only=True`**

In `backend/app/services/search_agent.py`, in `run_agentic_search`, after the hybrid retrieval loop builds `all_chunks` (around line 502), add filtering logic. First, add this import at the top of the file:

```python
from sqlalchemy import select as sa_select
from app.models.document import Document
```

Then after the retrieval loop, before deduplication:

```python
    # Stage 3b: Filter to journal entries if requested
    if request.journal_only:
        journal_doc_ids = set()
        doc_ids_to_check = {c.document_id for c in all_chunks}
        if doc_ids_to_check:
            result = await db.execute(
                sa_select(Document.id).where(
                    Document.id.in_(doc_ids_to_check),
                    Document.document_metadata["document_type"].astext == "journal",
                )
            )
            journal_doc_ids = {row[0] for row in result.fetchall()}
        all_chunks = [c for c in all_chunks if c.document_id in journal_doc_ids]
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/search_models.py backend/app/services/search_agent.py
git commit -m "feat(journal): add journal_only filter to agentic search"
```

---

## Task 3: Backend — Add journal text upload endpoint

**Files:**
- Modify: `backend/app/api/documents.py`

This endpoint allows creating a journal entry from raw text (no file attachment), used by the Telegram bot for text-only journal messages.

- [ ] **Step 1: Add the journal entry endpoint**

In `backend/app/api/documents.py`, add after the existing `upload_document` function (after line 392):

```python
from pydantic import BaseModel, Field


class JournalEntryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    tags: list[str] = Field(default_factory=list)
    timestamp: str | None = None  # ISO format, defaults to now


@router.post("/journal", response_model=DocumentUploadResponse)
async def create_journal_entry(
    entry: JournalEntryRequest,
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Create a text-only journal entry in the confidential bucket."""
    # Only admin/superuser can create journal entries (confidential bucket)
    if current_user.role.value not in ["admin", "superuser"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or Super User role required for journal entries",
        )

    # Validate bot API key if provided
    if x_bot_api_key:
        if not BOT_API_KEY or x_bot_api_key != BOT_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Bot API Key")

    # Save text as a .txt file
    from datetime import datetime as dt

    timestamp = entry.timestamp or dt.utcnow().isoformat()
    content = entry.text.encode("utf-8")
    filename = f"journal_{dt.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"

    save_result = storage_service.save_file(
        file_content=content, original_filename=filename, bucket="confidential"
    )

    document = Document(
        filename=save_result["filename"],
        original_filename=filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket.CONFIDENTIAL,
        status=DocumentStatus.PENDING,
        size=save_result["size"],
        mime_type="text/plain",
        language=DocumentLanguage.UNKNOWN,
        uploaded_by=current_user.id,
        document_metadata={
            "document_type": "journal",
            "journal_timestamp": timestamp,
            "journal_text": entry.text[:500],  # Preview in metadata
        },
    )

    db.add(document)
    await db.commit()
    await db.refresh(document)

    # Add user tags
    for tag_name in entry.tags:
        tag = DocumentTag(
            document_id=document.id,
            tag_name=tag_name.strip().lower(),
            tag_type="user",
            auto_generated=False,
        )
        db.add(tag)
    if entry.tags:
        await db.commit()

    # Log confidential upload
    await create_audit_log(
        db=db,
        user_id=current_user.id,
        action=AuditAction.CONFIDENTIAL_UPLOADED,
        resource_type="journal_entry",
        resource_id=str(document.id),
        details={"filename": filename, "type": "journal"},
    )

    # Trigger processing
    try:
        from app.tasks.document_tasks import process_document

        task = process_document.delay(str(document.id))
        document.status = DocumentStatus.PROCESSING
        document.document_metadata = {
            **document.document_metadata,
            "celery_task_id": task.id,
        }
        await db.commit()

        return DocumentUploadResponse(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            message="Journal entry created and queued for processing",
        )
    except Exception as e:
        logger.error(f"Failed to queue journal entry {document.id}: {e}")
        document.status = DocumentStatus.ERROR
        document.document_metadata = {
            **document.document_metadata,
            "processing_error": str(e),
        }
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Journal entry saved but processing failed: {str(e)}",
        )
```

- [ ] **Step 2: Verify the import for `DocumentTag` is already present**

Check top of `documents.py` — `DocumentTag` should already be imported. If not, add it to the existing import from `app.models.document`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/documents.py
git commit -m "feat(journal): add POST /journal endpoint for text-only entries"
```

---

## Task 4: Backend — Add journal metadata to photo uploads via Telegram

**Files:**
- Modify: `backend/telegram_bot/bot.py`

When uploading photos/files in journal mode, the bot needs to pass `document_type: journal` metadata. Since the existing upload API uses multipart form data (not JSON metadata), we'll set the metadata on the document record after upload by calling the document update endpoint — or simpler: add a `document_type` form field to the upload endpoint.

- [ ] **Step 1: Add `document_type` form field to upload endpoint**

In `backend/app/api/documents.py`, modify the `upload_document` function signature to accept `document_type`:

```python
@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    bucket: str = Form("public"),
    title: str | None = Form(None),
    tags: str | None = Form(None),
    document_type: str | None = Form(None),
    x_bot_api_key: str | None = Header(None, alias="X-Bot-Api-Key"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
```

Then, after the document is created (around line 316, after `uploaded_by=current_user.id,`), add metadata setting:

```python
    document = Document(
        filename=save_result["filename"],
        original_filename=file.filename,
        file_path=save_result["file_path"],
        bucket=DocumentBucket(bucket),
        status=DocumentStatus.PENDING,
        size=save_result["size"],
        mime_type=get_mime_type(file.filename, content),
        language=language,
        uploaded_by=current_user.id,
    )

    # Set document metadata (e.g. journal type)
    if document_type:
        from datetime import datetime as dt
        document.document_metadata = {
            "document_type": document_type,
            "journal_timestamp": dt.utcnow().isoformat(),
        }
```

- [ ] **Step 2: Update `TelegramBotClient.upload_document` to accept `document_type`**

In `backend/telegram_bot/bot.py`, modify the `upload_document` method of `TelegramBotClient` (around line 332):

```python
    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        bucket: str,
        access_token: str,
        tags: list[str] | None = None,
        document_type: str | None = None,
    ) -> dict:
        try:
            files = {"file": (filename, file_bytes)}
            data: dict[str, Any] = {"bucket": bucket}
            if tags:
                data["tags"] = ",".join(tags)
            if document_type:
                data["document_type"] = document_type
```

The rest of the method stays the same.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/documents.py backend/telegram_bot/bot.py
git commit -m "feat(journal): add document_type form field to upload endpoint and bot client"
```

---

## Task 5: Telegram — Add Journal mode with menu button

**Files:**
- Modify: `backend/telegram_bot/bot.py`

- [ ] **Step 1: Add journal button to main menu**

In `backend/telegram_bot/bot.py`, modify the `start_command` function (line 492-496). Add the journal button:

```python
    keyboard = [
        [InlineKeyboardButton("📤 Upload Document", callback_data="upload_prompt")],
        [InlineKeyboardButton("🔍 Search", callback_data="search_prompt")],
        [InlineKeyboardButton("💬 Chat", callback_data="chat_prompt")],
        [InlineKeyboardButton("📓 Journal", callback_data="journal_prompt")],
    ]
```

Also add journal to the welcome text (around line 485):

```python
💬 <b>Chat</b>
• Conversational AI powered by Mistral

📓 <b>Journal</b>
• Personal journal in confidential vault
```

- [ ] **Step 2: Add journal callback handler**

After the `chat_callback` function (around line 953), add:

```python
async def journal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    session = await session_manager.get_session(user.id)
    if not session:
        await query.edit_message_text("❌ Session expired. Please use /start again.")
        return

    # Set journal mode in session
    await session_manager.update_session(user.id, {"mode": "journal"})

    keyboard = [
        [InlineKeyboardButton("🔎 Chercher dans le journal", callback_data="journal_search")],
        [InlineKeyboardButton("❌ Quitter Journal", callback_data="journal_exit")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "📓 <b>Mode Journal activé</b>\n\n"
        "Envoyez vos textes, photos ou schémas.\n"
        "Utilisez <code>#tags</code> pour étiqueter.\n\n"
        "Tapez /done pour quitter.",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
```

- [ ] **Step 3: Add journal exit and search callbacks**

After the `journal_callback` function, add:

```python
async def journal_exit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await session_manager.update_session(user.id, {"mode": None})
    await query.edit_message_text("📓 Mode journal terminé. Utilisez /start pour revenir au menu.")


async def journal_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    await session_manager.update_session(user.id, {"mode": "journal_search"})
    await query.edit_message_text(
        "🔎 <b>Recherche Journal</b>\n\nEnvoyez votre recherche :",
        parse_mode="HTML",
    )
```

- [ ] **Step 4: Add `create_journal_entry` and `search_journal` methods to `TelegramBotClient`**

In `TelegramBotClient` class (after the `search` method, around line 405), add:

```python
    async def create_journal_entry(
        self, text: str, tags: list[str], access_token: str
    ) -> dict:
        """Create a text-only journal entry via the backend API."""
        try:
            response = await self._client.post(
                "/api/v1/documents/journal",
                json={"text": text, "tags": tags},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Bot-Api-Key": BOT_API_KEY,
                },
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable."}
        except Exception as e:
            logger.error(f"Journal entry error: {str(e)}")
            return {"error": str(e)}

    async def search_journal(self, query: str, access_token: str) -> dict:
        """Search only journal entries."""
        try:
            response = await self._client.post(
                "/api/v1/search",
                json={"query": query, "limit": 5, "journal_only": True},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            return response.json()
        except CircuitBreakerOpenError as e:
            logger.error(f"Circuit breaker open: {str(e)}")
            return {"error": "Service temporarily unavailable."}
        except Exception as e:
            logger.error(f"Journal search error: {str(e)}")
            return {"error": str(e)}
```

- [ ] **Step 5: Commit**

```bash
git add backend/telegram_bot/bot.py
git commit -m "feat(journal): add journal mode, menu button, and bot client methods"
```

---

## Task 6: Telegram — Handle journal text and photo messages

**Files:**
- Modify: `backend/telegram_bot/bot.py`

- [ ] **Step 1: Add journal text handling in `handle_text_message`**

In `handle_text_message` (around line 815), add journal mode handling right after the session check (after line 827). Insert before the existing text-based bucket selection block (line 829):

```python
    # --- Journal mode: text entries ---
    mode = session.get("mode")

    if mode == "journal":
        # Handle /done command to exit journal mode
        if text.strip().lower() == "/done":
            await session_manager.update_session(user.id, {"mode": None})
            await update.message.reply_text("📓 Mode journal terminé. Utilisez /start pour revenir au menu.")
            return

        # Extract hashtags
        hashtags = re.findall(r"#(\w+)", text)
        clean_text = re.sub(r"#\w+", "", text).strip()

        if not clean_text:
            await update.message.reply_text("⚠️ Le texte est vide (seuls des tags ont été détectés).")
            return

        result = await bot_client.create_journal_entry(
            text=clean_text, tags=hashtags, access_token=session["access_token"]
        )

        if "error" in result:
            await update.message.reply_text(f"❌ Erreur: {result['error']}")
        else:
            from datetime import datetime as dt
            now = dt.now().strftime("%H:%M")
            tag_display = " ".join(f"#{t}" for t in hashtags) if hashtags else ""
            await update.message.reply_text(
                f"✅ Noté à {now} {tag_display}",
                parse_mode="HTML",
            )
        return

    if mode == "journal_search":
        # Search journal entries
        result = await bot_client.search_journal(text, session["access_token"])
        await session_manager.update_session(user.id, {"mode": "journal"})

        if "error" in result:
            await update.message.reply_text(f"❌ Erreur: {result['error']}")
            return

        results = result.get("results", [])
        if not results:
            await update.message.reply_text("🔍 Aucun résultat dans le journal.")
            return

        lines = ["🔍 <b>Résultats du journal :</b>\n"]
        for r in results[:5]:
            title = r.get("document_title", "Sans titre")
            excerpt = r.get("excerpt", "")[:150]
            date = r.get("document_date", "")[:10]
            lines.append(f"📅 <b>{date}</b> — {title}\n{excerpt}\n")

        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
        return
```

- [ ] **Step 2: Add journal photo handling in `handle_document_upload`**

In `handle_document_upload` (around line 569), after the session check (line 576), add journal mode handling before the existing document/photo processing:

```python
    # --- Journal mode: auto-upload to confidential with journal metadata ---
    mode = session.get("mode")
    if mode == "journal":
        document = update.message.document
        photo = update.message.photo

        if document:
            file = document
            filename = document.file_name
        elif photo:
            file = photo[-1]
            filename = f"journal_photo_{file.file_id}.jpg"
        else:
            return

        caption = update.message.caption or ""
        parsed_tags = re.findall(r"#(\w+)", caption)

        try:
            file_obj = await file.get_file()
            file_bytes = bytes(await file_obj.download_as_bytearray())
        except Exception as e:
            logger.error(f"Journal file download error: {str(e)}")
            await update.message.reply_text(f"❌ Erreur: {str(e)}")
            return

        result = await bot_client.upload_document(
            file_bytes=file_bytes,
            filename=filename,
            bucket="confidential",
            access_token=session["access_token"],
            tags=parsed_tags,
            document_type="journal",
        )

        if "error" in result:
            await update.message.reply_text(f"❌ Erreur: {result['error']}")
        else:
            from datetime import datetime as dt
            now = dt.now().strftime("%H:%M")
            tag_display = " ".join(f"#{t}" for t in parsed_tags) if parsed_tags else ""
            document_id = result.get("document_id", "N/A")
            await update.message.reply_text(f"✅ 📷 Noté à {now} {tag_display}")

            # Track for status updates
            if document_id != "N/A":
                document_tracking[document_id] = {
                    "chat_id": update.message.chat_id,
                    "message_id": update.message.message_id,
                    "filename": filename,
                    "bucket_emoji": "🔒",
                    "access_token": session["access_token"],
                    "last_status": "processing",
                    "check_count": 0,
                }
                context.job_queue.run_once(
                    check_document_status,
                    when=5,
                    data=document_id,
                    name=f"status_check_{document_id}",
                )
        return
```

- [ ] **Step 3: Register the new callback handlers in `main()`**

In the `main()` function (around line 1339), add the journal handlers after the chat_callback handler:

```python
    application.add_handler(CallbackQueryHandler(journal_callback, pattern="^journal_prompt"))
    application.add_handler(CallbackQueryHandler(journal_exit_callback, pattern="^journal_exit"))
    application.add_handler(CallbackQueryHandler(journal_search_callback, pattern="^journal_search"))
    application.add_handler(CommandHandler("done", lambda u, c: handle_text_message(u, c)))
```

- [ ] **Step 4: Commit**

```bash
git add backend/telegram_bot/bot.py
git commit -m "feat(journal): handle text/photo messages in journal mode with search"
```

---

## Task 7: Frontend — Add i18n translations for journal

**Files:**
- Modify: `frontend/app/messages/fr.json`
- Modify: `frontend/app/messages/en.json`

- [ ] **Step 1: Add French translations**

In `frontend/app/messages/fr.json`, add `"journal"` to the `"nav"` section (after `"smart_folders"`):

```json
    "journal": "Mon Journal",
```

Add a new top-level `"journal"` section (after the `"chat"` section):

```json
  "journal": {
    "title": "Mon Journal",
    "subtitle": "Journal personnel confidentiel",
    "empty": "Aucune entrée de journal. Utilisez Telegram pour ajouter des entrées.",
    "search_placeholder": "Rechercher dans le journal...",
    "filter_tags": "Filtrer par tags",
    "all_tags": "Tous les tags",
    "loading": "Chargement...",
    "load_more": "Charger plus",
    "entry_text": "Texte",
    "entry_photo": "Photo",
    "entry_schema": "Schéma",
    "tags": "Tags",
    "no_results": "Aucun résultat trouvé"
  },
```

- [ ] **Step 2: Add English translations**

In `frontend/app/messages/en.json`, add `"journal"` to the `"nav"` section:

```json
    "journal": "My Journal",
```

Add a new top-level `"journal"` section:

```json
  "journal": {
    "title": "My Journal",
    "subtitle": "Personal confidential journal",
    "empty": "No journal entries yet. Use Telegram to add entries.",
    "search_placeholder": "Search journal...",
    "filter_tags": "Filter by tags",
    "all_tags": "All tags",
    "loading": "Loading...",
    "load_more": "Load more",
    "entry_text": "Text",
    "entry_photo": "Photo",
    "entry_schema": "Schema",
    "tags": "Tags",
    "no_results": "No results found"
  },
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/messages/fr.json frontend/app/messages/en.json
git commit -m "feat(journal): add i18n translations for journal feature"
```

---

## Task 8: Frontend — Add journal to navigation

**Files:**
- Modify: `frontend/components/Navigation.tsx:21-76`

- [ ] **Step 1: Add `'journal'` to `NavLabelKey` type**

In `frontend/components/Navigation.tsx`, update the type (line 10-12):

```typescript
type NavLabelKey =
  | 'search' | 'documents' | 'chat' | 'collections' | 'smart_folders'
  | 'knowledge_graph' | 'dashboard' | 'monitoring' | 'settings' | 'journal';
```

- [ ] **Step 2: Add journal nav item**

In the `navItems` array (after the smart_folders entry, around line 66), add:

```typescript
  {
    href: '/journal',
    labelKey: 'journal',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
      </svg>
    ),
    roles: ['admin', 'superuser'],
  },
```

Note: We add `roles: ['admin', 'superuser']` to restrict visibility. But `navItems` currently doesn't filter by roles — only `adminItems` does. We need to update the filtering logic.

- [ ] **Step 3: Update nav filtering to respect roles on regular items**

In the component, update the `filteredItems` logic (around line 219):

```typescript
  const filteredItems = activeTab === 'admin'
    ? allItems.filter(item => item.roles?.includes(userRole))
    : navItems.filter(item => !item.roles || item.roles.includes(userRole));

  const mobileItems = activeTab === 'admin'
    ? allItems.filter(item => item.roles?.includes(userRole))
    : navItems.filter(item => !item.roles || item.roles.includes(userRole));
```

- [ ] **Step 4: Commit**

```bash
git add frontend/components/Navigation.tsx
git commit -m "feat(journal): add journal link to navigation (role-gated)"
```

---

## Task 9: Frontend — Create journal timeline page

**Files:**
- Create: `frontend/app/[locale]/journal/page.tsx`

- [ ] **Step 1: Create the journal timeline page**

Create `frontend/app/[locale]/journal/page.tsx`:

```typescript
'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import Image from 'next/image';

interface JournalTag {
  id: string;
  tag_name: string;
  tag_type: string;
  auto_generated: boolean;
}

interface JournalEntry {
  id: string;
  original_filename: string;
  mime_type: string;
  metadata: Record<string, string>;
  tags: JournalTag[];
  created_at: string;
  status: string;
  size: number;
}

export default function JournalPage() {
  const t = useTranslations('journal');
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>('');
  const [allTags, setAllTags] = useState<string[]>([]);
  const [expandedEntry, setExpandedEntry] = useState<string | null>(null);
  const PAGE_SIZE = 20;

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
        bucket: 'confidential',
        document_type: 'journal',
      });
      if (debouncedSearch) params.set('search', debouncedSearch);

      const res = await fetch(`/api/v1/documents?${params}`, {
        credentials: 'include',
      });
      if (!res.ok) throw new Error('Failed to fetch');
      const data = await res.json();
      setEntries(data.documents || []);
      setTotal(data.total || 0);

      // Extract unique tags from results
      const tagSet = new Set<string>();
      (data.documents || []).forEach((doc: JournalEntry) => {
        doc.tags?.forEach((tag) => tagSet.add(tag.tag_name));
      });
      setAllTags((prev) => {
        const merged = new Set([...prev, ...tagSet]);
        return Array.from(merged).sort();
      });
    } catch (e) {
      console.error('Error fetching journal entries:', e);
    } finally {
      setLoading(false);
    }
  }, [page, debouncedSearch]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const filteredEntries = selectedTag
    ? entries.filter((e) => e.tags?.some((t) => t.tag_name === selectedTag))
    : entries;

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('fr-FR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const isImage = (mimeType: string) =>
    mimeType.startsWith('image/');

  const hasMore = page * PAGE_SIZE < total;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">{t('title')}</h1>
        <p className="text-gray-500 mt-1">{t('subtitle')}</p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <input
          type="text"
          placeholder={t('search_placeholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <select
          value={selectedTag}
          onChange={(e) => setSelectedTag(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('all_tags')}</option>
          {allTags.map((tag) => (
            <option key={tag} value={tag}>
              #{tag}
            </option>
          ))}
        </select>
      </div>

      {/* Loading */}
      {loading && (
        <div className="text-center py-12 text-gray-500">{t('loading')}</div>
      )}

      {/* Empty state */}
      {!loading && filteredEntries.length === 0 && (
        <div className="text-center py-12">
          <svg
            className="w-16 h-16 mx-auto text-gray-300 mb-4"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
            />
          </svg>
          <p className="text-gray-500">
            {debouncedSearch || selectedTag ? t('no_results') : t('empty')}
          </p>
        </div>
      )}

      {/* Timeline */}
      {!loading && filteredEntries.length > 0 && (
        <div className="space-y-4">
          {filteredEntries.map((entry) => {
            const journalText =
              entry.metadata?.journal_text || entry.original_filename;
            const journalTimestamp =
              entry.metadata?.journal_timestamp || entry.created_at;
            const expanded = expandedEntry === entry.id;

            return (
              <div
                key={entry.id}
                className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                onClick={() =>
                  setExpandedEntry(expanded ? null : entry.id)
                }
              >
                {/* Date header */}
                <div className="flex items-center justify-between mb-3">
                  <time className="text-sm font-medium text-blue-600">
                    {formatDate(journalTimestamp)}
                  </time>
                  <span className="text-xs text-gray-400 uppercase">
                    {isImage(entry.mime_type) ? t('entry_photo') : t('entry_text')}
                  </span>
                </div>

                {/* Content */}
                <div className={`text-gray-800 ${expanded ? '' : 'line-clamp-3'}`}>
                  {journalText}
                </div>

                {/* Image thumbnail */}
                {isImage(entry.mime_type) && (
                  <div className="mt-3">
                    <img
                      src={`/api/v1/documents/${entry.id}/content`}
                      alt="Journal photo"
                      className={`rounded-lg ${expanded ? 'max-w-full' : 'max-h-48 object-cover'}`}
                    />
                  </div>
                )}

                {/* Tags */}
                {entry.tags && entry.tags.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {entry.tags.map((tag) => (
                      <span
                        key={tag.id}
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                          tag.auto_generated
                            ? 'bg-gray-100 text-gray-600'
                            : 'bg-blue-100 text-blue-700'
                        }`}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedTag(
                            selectedTag === tag.tag_name ? '' : tag.tag_name
                          );
                        }}
                      >
                        #{tag.tag_name}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}

          {/* Load more */}
          {hasMore && (
            <button
              onClick={() => setPage((p) => p + 1)}
              className="w-full py-3 text-blue-600 font-medium hover:bg-blue-50 rounded-lg transition-colors"
            >
              {t('load_more')}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify the page renders**

```bash
cd /home/development/src/active/sowknow4/frontend && npx next build 2>&1 | grep -E "error|journal" | head -20
```

Expected: No errors related to the journal page.

- [ ] **Step 3: Commit**

```bash
git add frontend/app/[locale]/journal/page.tsx
git commit -m "feat(journal): create journal timeline page with search and tag filtering"
```

---

## Task 10: Integration verification

- [ ] **Step 1: Verify backend starts with new endpoints**

```bash
docker compose -f docker-compose.yml restart backend
docker compose -f docker-compose.yml logs backend --tail=20 2>&1 | grep -E "error|ERROR|journal"
```

Expected: No errors. Backend starts successfully.

- [ ] **Step 2: Verify the journal API endpoint is reachable**

```bash
docker exec -it sowknow4-backend python -c "
from app.api.documents import router
routes = [r.path for r in router.routes]
print('Journal route present:', '/journal' in routes)
print('All routes:', routes)
"
```

Expected: `Journal route present: True`

- [ ] **Step 3: Verify Telegram bot restarts with journal handler**

```bash
docker compose -f docker-compose.yml restart telegram-bot
docker compose -f docker-compose.yml logs telegram-bot --tail=10 2>&1 | grep -E "error|ERROR|handler"
```

Expected: No errors. Handlers registered message visible.

- [ ] **Step 4: Commit any fixes needed**

If any fixes were needed, commit them:

```bash
git add -A
git commit -m "fix(journal): integration fixes for journal feature"
```
