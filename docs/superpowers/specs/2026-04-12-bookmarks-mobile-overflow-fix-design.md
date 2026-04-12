# Mobile Overflow Fix + Bookmarks Mobile Adaptation

**Date:** 2026-04-12  
**Status:** Approved  
**Scope:** 3 files changed — `globals.css`, `notes/page.tsx`, `bookmarks/page.tsx`

---

## Problem

Two pages cause horizontal scrolling on iPhone:

- **Notes**: `SwipeableRow` parent grid has no `overflow-x` containment. Small swipe-transform overflow escapes to page level.
- **Bookmarks**: Never adapted for mobile. Raw URL text overflows flex containers, no bottom nav padding, uses old `gray-*` theme instead of vault dark theme, no swipe/FAB/sheet interactions.

Root cause shared by both: `overflow-x: clip` on `html, body` in `globals.css` does not establish scroll containment in all iOS Safari versions. It clips visually but the browser can still scroll horizontally.

---

## Solution

### 1. Global overflow fix — `frontend/app/globals.css`

Change `overflow-x: clip` to `overflow-x: hidden` on both `html` and `body`. `overflow-x: hidden` is well-supported across all iOS Safari versions and prevents horizontal scrolling at the document level.

### 2. Notes overflow containment — `frontend/app/[locale]/notes/page.tsx`

Add `overflow-x-hidden` to the outer `min-h-screen` wrapper div. The `SwipeableRow` component already has `overflow-hidden` on its own container, but the parent grid has no containment — this adds the missing layer.

### 3. Bookmarks mobile adaptation — `frontend/app/[locale]/bookmarks/page.tsx`

Full rewrite to match the Notes page pattern. No new infrastructure — reuses existing `FAB`, `SwipeableRow`, `MobileBottomSheet`, and `useIsMobile` from `@/components/mobile/` and `@/hooks/useIsMobile`.

**Card layout changes:**
- Replace raw URL text with parsed domain name (extracted via `new URL(bookmark.url).hostname`, stripped of `www.`; fall back to the raw URL truncated if parsing throws)
- Show title (bold, 2-line clamp) + optional description (2-line clamp)
- Tags with `flex-wrap` — same pill style as Notes
- `min-w-0` on all flex children to prevent overflow
- `flex-1 min-w-0` on card content column

**Theme:**
- Replace all `gray-*` Tailwind classes with vault dark theme: `bg-vault-900/60`, `text-text-primary`, `text-text-secondary`, `text-text-muted`, `border-white/[0.06]`
- Matches Notes, Search, Chat pages

**Mobile interactions (`isMobile === true`):**
- `SwipeableRow` wrapping each card — swipe left to reveal delete action (same as Notes)
- `FAB` component for the "Add bookmark" primary action — replaces the header button on mobile
- `MobileSheet` for the create form — replaces the fixed modal on mobile (same component Notes uses for its editor)
- `pb-20` on the page container for bottom nav clearance (same as Notes)

**Desktop interactions (`isMobile === false`):**
- Header "+ Add" button retained (hidden on mobile via `hidden md:inline-flex`)
- Fixed modal for create form retained
- No `SwipeableRow` — delete button in card header as before

---

## Architecture

No new components, hooks, or API endpoints. The existing mobile infrastructure introduced in the April 6–7 sprint covers all requirements:

| Existing | Used for |
|---|---|
| `useIsMobile` hook | Conditional mobile/desktop rendering |
| `FAB` | Add bookmark primary action on mobile |
| `SwipeableRow` | Swipe-to-delete on mobile |
| `MobileSheet` | Create bookmark form on mobile |

---

## Error handling

No changes to error handling. The existing fetch/create/delete error paths (`console.error`, loading states) are preserved as-is.

---

## Testing

- Open Notes on iPhone — confirm no horizontal scroll
- Open Bookmarks on iPhone — confirm no horizontal scroll
- Swipe a bookmark card left — confirm delete action reveals and works
- Tap FAB — confirm create sheet opens
- Create a bookmark — confirm it appears in the list
- Open on desktop — confirm layout is unchanged (header button, fixed modal, no SwipeableRow)
