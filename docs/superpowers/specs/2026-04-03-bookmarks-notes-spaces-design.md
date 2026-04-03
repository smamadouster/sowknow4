# Bookmarks, Notes & Spaces — Design Spec

**Date:** 2026-04-03
**Status:** Approved
**Approach:** C — New Space model, reuse patterns, standalone from Collections

## Overview

Three new features for SOWKNOW:

1. **Bookmarks** — save links with mandatory tags, searchable by metadata
2. **Notes** — plain text notes with tags, stored in DB, searchable
3. **Spaces** — permanent curated workspaces that gather documents, bookmarks, and notes around a real-life topic (e.g., "VOYAGE A DUBAI Avril 2022")

These are distinct from existing Smart Collections, which are ephemeral AI-driven search results. Spaces are permanent and user-curated.

**Inspiration:** [Fabric.so](https://fabric.so/)

## Data Models

### Bookmark

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK → users |
| url | String | Required |
| title | String | Required |
| description | Text | Optional |
| favicon_url | String | Optional, auto-fetched |
| bucket | Enum | PUBLIC / CONFIDENTIAL |
| created_at | DateTime | |
| updated_at | DateTime | |

### Note

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK → users |
| title | String | Required |
| content | Text | Plain text body |
| bucket | Enum | PUBLIC / CONFIDENTIAL |
| created_at | DateTime | |
| updated_at | DateTime | |

### Space

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK → users |
| name | String | Required |
| description | Text | Optional |
| icon | String | Optional emoji or icon name |
| bucket | Enum | PUBLIC / CONFIDENTIAL |
| is_pinned | Boolean | For quick access |
| created_at | DateTime | |
| updated_at | DateTime | |

### SpaceItem (join table)

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| space_id | UUID | FK → spaces |
| item_type | Enum | DOCUMENT / BOOKMARK / NOTE |
| document_id | UUID | FK → documents, nullable |
| bookmark_id | UUID | FK → bookmarks, nullable |
| note_id | UUID | FK → notes, nullable |
| added_by | String | "user" or "rule" |
| added_at | DateTime | |
| note | Text | Optional annotation on the item within this space |
| is_excluded | Boolean | Default false. When true, item won't be re-added by rule sync |

Constraint: exactly one of document_id, bookmark_id, note_id must be non-null, matching item_type.

### SpaceRule (auto-rules)

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| space_id | UUID | FK → spaces |
| rule_type | Enum | TAG / KEYWORD |
| rule_value | String | Tag name or keyword to match |
| is_active | Boolean | Enable/disable individual rules |
| created_at | DateTime | |

### Tag (generalized, replaces DocumentTag)

| Field | Type | Notes |
|-------|------|-------|
| id | UUID | PK |
| tag_name | String | Indexed |
| tag_type | Enum | topic, entity, project, importance, custom |
| target_type | Enum | DOCUMENT / BOOKMARK / NOTE / SPACE |
| target_id | UUID | Polymorphic FK |
| auto_generated | Boolean | AI vs manual |
| confidence_score | Integer | 0-100 for auto tags |
| created_at | DateTime | |

## Tag System Migration

1. Create new `Tag` table with polymorphic `target_type` + `target_id`
2. Migrate all `DocumentTag` rows into `Tag` with `target_type=DOCUMENT`, `target_id=document_id`
3. Update all backend services (`auto_tagging_service`, `search_service`, `documents` API) to use new `Tag` model
4. Drop `DocumentTag` table after migration is verified

New `custom` tag type added for user-created tags on bookmarks/notes. Existing auto-generated tag types (topic, entity, project, importance) remain for documents.

## API Endpoints

### Bookmarks — `/api/v1/bookmarks`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create bookmark (url + tags required) |
| GET | `/` | List user's bookmarks (pagination, tag filter) |
| GET | `/{id}` | Get single bookmark |
| PUT | `/{id}` | Update bookmark (title, description, tags) |
| DELETE | `/{id}` | Delete bookmark |
| GET | `/search` | Search bookmarks by title/description/tags |

On create, backend auto-fetches page title and favicon if not provided by the user.

### Notes — `/api/v1/notes`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create note (title + content + tags) |
| GET | `/` | List user's notes (pagination, tag filter) |
| GET | `/{id}` | Get single note |
| PUT | `/{id}` | Update note |
| DELETE | `/{id}` | Delete note |
| GET | `/search` | Search notes by title/content/tags |

### Spaces — `/api/v1/spaces`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/` | Create space (name required) |
| GET | `/` | List user's spaces (pagination, search by name) |
| GET | `/{id}` | Get space with items |
| PUT | `/{id}` | Update space metadata |
| DELETE | `/{id}` | Delete space (cascade items + rules) |
| POST | `/{id}/items` | Add item(s) to space manually |
| DELETE | `/{id}/items/{item_id}` | Remove item from space |
| POST | `/{id}/rules` | Add auto-rule |
| PUT | `/{id}/rules/{rule_id}` | Update rule |
| DELETE | `/{id}/rules/{rule_id}` | Delete rule |
| POST | `/{id}/sync` | Trigger rule evaluation (Celery task) |
| GET | `/{id}/search` | Search within space items |

### Global Search Extension

Existing `/api/v1/search` endpoint extended with `types` query parameter:
- `?types=document,bookmark,note,space` — returns mixed results with `result_type` field
- Default behavior unchanged (documents only) for backward compatibility

### RBAC

All endpoints enforce existing role-based access:
- Bucket filtering (confidential invisible to regular users)
- Users access only their own bookmarks/notes/spaces
- Admins can see all

## Auto-Rules Engine

### Trigger Scenarios

1. **On-demand sync** — user clicks "Sync" or calls `POST /spaces/{id}/sync`. Runs as Celery task.
2. **On item creation** — when a document is uploaded, bookmark saved, or note created, check all active SpaceRules inline. Auto-add matching items with `added_by="rule"`.

### Rule Evaluation

**TAG rule:** Match any item (document, bookmark, note) with a tag whose `tag_name` matches `rule_value` (case-insensitive).

**KEYWORD rule:** Match items where keyword appears in:
- Documents: chunk text via PostgreSQL full-text search (existing index)
- Bookmarks: title or description (ILIKE)
- Notes: title or content (ILIKE)

Rules within a Space combine with **OR** — item matching any rule gets added. Duplicates skipped.

### User Control

- Items added by rules can be manually removed — soft exclude prevents re-addition on next sync
- Each rule can be toggled on/off independently
- Rules display a count of matched items

## Frontend

### Navigation

Three new sidebar entries:
- **Bookmarks** (link icon)
- **Notes** (pencil icon)
- **Spaces** (folder/grid icon)

### Bookmarks Page (`/bookmarks`)

- Top bar: search field + "Add Bookmark" button
- Add form: URL input, title (auto-filled on paste), description, tag selector (mandatory, min 1)
- List view: cards with favicon, title, URL domain, tags, date. Click opens link in new tab.
- Filter sidebar: by tag, by date range

### Notes Page (`/notes`)

- Top bar: search field + "New Note" button
- Create/edit: title, plain text area, tag selector
- List view: cards with title, content preview (~100 chars), tags, date
- Click opens note in edit mode

### Spaces Page (`/spaces`)

- Top bar: search field + "Create Space" button
- Create form: name, description, optional icon/emoji
- Grid/list of spaces: name, icon, item count, last updated
- Click enters Space detail view

### Space Detail View (`/spaces/{id}`)

- Header: space name, description, edit button
- **Items tab**: unified list — type icon (doc/bookmark/note), title, tags, date, `added_by` badge
- **Rules tab**: list of rules with type, value, match count, toggle, add/delete. "Sync now" button.
- **Add items**: search modal to browse documents/bookmarks/notes and add to space
- Local search bar to filter within space items
- Type filter chips: All / Documents / Bookmarks / Notes

### Global Search Enhancement

Existing `/search` page gets type filter chips above results. Results show type badge (Document, Bookmark, Note, Space).

## Out of Scope

- Existing Smart Collections (untouched, remain ephemeral)
- Existing Smart Folders (untouched)
- OCR/embedding pipeline (bookmarks and notes don't need embeddings)
- Chat/article generation systems
- Rich text editing for notes (plain text only)
- Full page content capture for bookmarks (lightweight metadata only)
