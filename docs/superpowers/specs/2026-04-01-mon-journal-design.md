# Mon Journal — Design Spec

## Overview

"Mon Journal" is a personal journal feature within SOWKNOW's confidential bucket. Journal entries are standard confidential documents with a `journal` type marker, enabling reuse of the existing upload pipeline, OCR, search, tags, and Telegram flow. Users can feed entries on the fly via Telegram and search them from both Telegram and the web UI.

## Architecture

Journal entries are regular documents in the **confidential bucket** with metadata markers in the existing `document_metadata` JSONB field:

- `document_metadata.document_type = "journal"`
- `document_metadata.journal_timestamp` — exact date/time of the entry
- `document_metadata.journal_text` — raw text content (for text-only entries without a file)
- `bucket = CONFIDENTIAL`
- Tags from both inline `#hashtags` and auto-tagging

**No new database tables.** All data stored via existing Document, DocumentTag, and DocumentChunk models.

### Text-only entries

For entries with no file attachment, a document record is created with `mime_type = "text/plain"` and the text content saved as a file on disk. This ensures it goes through the normal embedding/indexing pipeline and becomes fully searchable.

### Photos and schemas

Go through the existing upload + OCR pipeline as confidential documents, with journal metadata added.

## Telegram Integration

### Menu Change

A **"📓 Journal"** button is added to the main menu. The menu becomes 4 buttons: Upload, Search, Chat, Journal.

### Journal Mode Flow

1. User taps "📓 Journal"
2. Bot responds: *"Mode journal activ&eacute;. Envoyez vos textes, photos ou sch&eacute;mas. Utilisez #tags pour &eacute;tiqueter. Tapez /done pour quitter."*
3. User sends any combination of text, photos, or media groups
4. Each message is immediately:
   - Timestamped with current date/time
   - Scanned for `#hashtags` (extracted as user tags, stripped from stored text)
   - Uploaded to confidential bucket with `document_type: journal` metadata
   - Auto-tagging triggered in background via Celery
5. Bot confirms each entry: *"&#x2705; Not&eacute; &agrave; 14:32"*
6. User sends `/done` or taps "Quitter Journal" button to exit and return to main menu

### Media Groups

Multiple photos sent together are handled with the existing 2-second grouping buffer. All photos in the group are tagged as a single journal entry batch.

### Search from Telegram

- When in journal mode, a "&#x1F50E; Chercher" inline button is shown
- User taps it, sends search query, results scoped to journal entries only
- Results show entry text snippet, date, and tags
- Top 5 results returned as inline messages with date headers

## Tags & Search

### Tag Capture

- **Manual**: Inline `#hashtags` in message text are extracted as tags with `tag_type = "user"`
- **Automatic**: After upload, the existing AutoTaggingService runs in Celery — generates topic, entity, and importance tags with `auto_generated = true`
- All tags stored in the existing `document_tags` table, linked to the journal document

### Web Search

- Existing search page gets a "Journal" filter option in the document type/bucket filters
- When active, search queries scoped to `document_metadata.document_type = "journal"`
- Semantic and keyword search work as-is — journal text gets chunked, embedded, and indexed through the normal pipeline

### Telegram Search

- Scoped to `document_type = "journal"` + `bucket = CONFIDENTIAL`
- Uses the existing search service API internally
- Returns top 5 results with text snippet, date, and tags

## Frontend — Journal Timeline View

### New Page

Route: `/[locale]/journal`

Added to the main navigation sidebar. Only visible to users with confidential access (Admin, Super User).

### Timeline Layout

- Entries displayed chronologically, newest first
- Each entry card shows:
  - Date/time header (e.g. "1 avril 2026, 14:32")
  - Text content (or OCR-extracted text for photos)
  - Image thumbnail if the entry is a photo/schema
  - Tags as colored pills
  - Click to expand full content / full-size image
- Infinite scroll pagination
- Filter bar at top: search box + tag filter dropdown

### Access Control

Same RBAC as confidential documents:
- **Admin**: Full access
- **Super User**: View-only
- **User**: Cannot see the page at all

## Components Modified

### Backend
- `backend/telegram_bot/bot.py` — Add journal mode, menu button, journal search
- `backend/app/api/documents.py` — Add journal filter parameter to list/search endpoints
- `backend/app/api/search_agent_router.py` — Add journal scope filter

### Frontend
- `frontend/app/[locale]/journal/page.tsx` — New journal timeline page
- `frontend/components/` — Journal entry card component
- Navigation sidebar — Add journal link (conditional on role)
- Search page — Add journal filter toggle

### No Changes Needed
- Document model (uses existing JSONB metadata)
- DocumentTag model (uses existing tag types)
- Upload pipeline (reused as-is)
- OCR pipeline (reused as-is)
- Embedding pipeline (reused as-is)
- AutoTaggingService (reused as-is)
