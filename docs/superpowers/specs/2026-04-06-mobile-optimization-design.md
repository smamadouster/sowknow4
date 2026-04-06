# Mobile Optimization — Progressive Native Enhancement

**Date**: 2026-04-06
**Approach**: Progressive Mobile Enhancement (Approach B)
**Target**: iPhone Safari + PWA standalone mode
**Primary pages**: Search, Notes, Documents, Chat (in priority order)
**Breakpoint**: `md:` (768px) — below = mobile, above = desktop (unchanged)

---

## 1. Foundation — Safe Areas, Viewport & Touch Targets

### Problem
- `100vh` breaks on Safari — address bar not accounted for, content gets cut off
- No `env(safe-area-inset-*)` — bottom nav sits behind the home indicator on notched iPhones
- Bottom nav items below Apple's 44x44px minimum for comfortable thumb tapping
- No `viewport-fit=cover` in the Next.js layout

### Changes

**Dynamic viewport height:**
- Replace all `100vh` with `100dvh` (dynamic viewport height)
- Fallback: `height: 100vh; height: 100dvh;` for older browsers
- Affected files: locale layout, chat page (`h-[calc(100vh-8rem)]`), home page

**Safe-area insets:**
- `padding-bottom: env(safe-area-inset-bottom)` on: bottom tab bar, chat input, FABs, MobileSheet bottom actions
- `padding-top: env(safe-area-inset-top)` on: sticky header
- Requires `viewport-fit=cover` in viewport meta

**Viewport meta:**
- Add to root layout: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />`

**Touch targets:**
- Minimum 44x44px on all interactive elements below `md:` breakpoint
- Bottom nav items: `min-w-[64px] min-h-[44px]`
- Buttons in sheets/modals: `py-3` minimum
- Tag chips, filter pills: minimum 44px tap height

---

## 2. Bottom Tab Bar Redesign

### Problem
- Current bottom bar: Home, Search, Documents, Chat, Collections + More
- User's priority pages are Search, Notes, Documents, Chat — Notes isn't in the bar, Home takes a prime slot
- "More" opens as a right-side desktop-style drawer

### Changes

**Tab bar layout (left to right):**
1. Search
2. Notes
3. Documents
4. Chat
5. More

- Home moves into "More" — the 4 core pages ARE the home experience on mobile

**Active tab indicator:**
- Small pill/dot above the icon (iOS-style), replacing current text-color-only highlight

**"More" becomes a bottom sheet:**
- Slides up from bottom with drag handle
- Contains: Home, Collections, Smart Folders, Bookmarks, Spaces, Knowledge Graph, Journal, admin items, Logout
- Swipe down to dismiss

**Auto-hide on scroll:**
- Hide bottom bar on scroll down, show on scroll up (list pages: Documents, Notes)
- Chat page: always visible
- Smooth `translate-y` transition (~200ms)

**Safe-area:**
- `pb-[env(safe-area-inset-bottom)]` on the tab bar

---

## 3. Full-Screen Mobile Sheets (replacing modals)

### Problem
- Notes editor is a centered `max-w-lg` modal — cramped on mobile, no visible close button
- Can't create a new note while one is open
- Centered modals waste screen edges and feel desktop-y

### MobileSheet Component
- Full-screen sheet sliding up from the bottom
- **Drag handle** (pill bar) at the top
- **Close button (X)** top-right, always visible
- **Swipe down to dismiss** — threshold ~30% of screen height
- Full height minus safe-area top inset
- Top border-radius: 16px
- Desktop: unchanged (existing modals remain)
- Detection: `useMediaQuery('(max-width: 768px)')` or Tailwind `md:` breakpoint

### MobileBottomSheet (lighter variant)
- Half-height version for: filters, session lists, "More" nav
- Same drag handle and swipe-to-dismiss
- Content scrollable inside

### Where sheets replace modals:
- **Notes editor** → full-screen MobileSheet
- **Document detail** → full-screen MobileSheet (instead of navigating to `/documents/[id]`)
- **Search filters/sort** → half-height MobileBottomSheet
- **Chat session switcher** → half-height MobileBottomSheet
- **Logout confirmation** → half-height MobileBottomSheet

---

## 4. Page-Specific Mobile Optimizations

### 4a. Search Page
- **Sticky search input** below header, always visible (no scrolling to find it)
- **Voice button** prominent next to search input, 44px touch target
- Results scroll underneath the sticky bar
- **Filter chips**: horizontal scrollable pills below search bar (not dropdowns)
- Result cards: slightly larger padding and text for readability

### 4b. Notes Page
- **List view**: `grid-cols-1` below `md:` (single column, not grid)
- **FAB (Floating Action Button)**: amber circle bottom-right, above tab bar — always-accessible "+" to create a note. Replaces header "New" button.
- **Note editor**: full-screen MobileSheet with:
  - Title input immediately focused (keyboard slides up)
  - "New Note" button in sheet header (close current → start fresh)
  - Save/Cancel in **sticky bottom bar** inside the sheet (above keyboard)
  - Voice recorder with larger touch targets
- **Swipe left on note card** → reveal delete action (red, with confirmation)

### 4c. Documents Page
- **FAB for upload**: same "+" pattern as Notes, bottom-right
- **Document cards**: horizontal rows on mobile (icon + filename + status on one line) — denser, more scannable
- **Upload flow**: MobileSheet with large file picker button (no drag-and-drop — doesn't work on iOS Safari)
- **Filters/sort**: tap filter icon in header → half-height bottom sheet

### 4d. Chat Page
- **Session sidebar hidden by default** on mobile (`sidebarOpen` defaults to `false` below `md:`)
- **Chat input**: sticky bottom with `padding-bottom: env(safe-area-inset-bottom)`, textarea auto-grows, 44px send button
- **Message bubbles**: up to 95% width on mobile
- **New chat button** in header area on mobile (not buried in sidebar)
- **Session switcher**: button in header → bottom sheet listing sessions (replaces slide-in sidebar)

---

## 5. Tag Autocomplete

### Problem
- Current TagSelector has no suggestions/autocomplete
- On mobile, picking tags requires knowing exact names

### TagAutocomplete Component (replaces TagSelector on mobile)
- **Trigger**: suggestions appear after first character typed (e.g., "C" → "Claude", "Confidential", "CSV")
- **Suggestion list**: floating pill list **above the input** on mobile (not below — keyboard would hide it)
- **Sticky suggestion chips**: top 5-8 most-used tags as horizontally scrollable pills above keyboard area, shown before typing — one tap to insert
- **Fuzzy matching**: matches anywhere in tag name, not just prefix ("aud" finds "Claude")
- **Create new tag**: last suggestion is always "Create [your text]" if no exact match
- **Selected tags**: dismissible pills above the input (tap X to remove)
- **Data source**: existing tags via API, sorted by frequency of use
- **Applies to**: Notes editor, Document upload, Search filters — anywhere TagSelector is used

---

## 6. Shared Components & Gestures

### New Components
| Component | Purpose | Used by |
|-----------|---------|---------|
| `MobileSheet` | Full-screen bottom sheet | Notes editor, Document detail, Upload flow |
| `MobileBottomSheet` | Half-height bottom sheet | Filters, session list, "More" nav |
| `FAB` | Floating action button | Notes (+), Documents (+), potentially Search (voice) |
| `TagAutocomplete` | Tag input with suggestions | Notes, Documents, Search |

### Gesture Support
- **Swipe down** on MobileSheet/MobileBottomSheet → dismiss
- **Swipe left on list items** (notes, documents) → reveal action (delete/archive)
- **Pull-to-refresh** on list pages (Notes, Documents, Search results) → triggers refetch
- Implementation: lightweight touch event handlers, CSS `touch-action: pan-y`

### Animations
| Action | Duration | Easing |
|--------|----------|--------|
| Sheet open | ~300ms | spring |
| Sheet close | ~200ms | ease-out |
| FAB appear | ~200ms | scale-in |
| Tab switch content | ~150ms | fade-in |
| Bottom bar hide/show | ~200ms | translate-y |

### PWA Standalone Mode
- Detect via `window.matchMedia('(display-mode: standalone)')`
- Standalone: more space (no Safari chrome), adjust header height
- Safari: keep `dvh` handling for collapsing address bar

---

## 7. What Stays the Same

- **Desktop layout** — sidebar, modals, header all untouched
- **All existing API calls and data flows**
- **Auth, routing, i18n** — unchanged
- **Backend** — zero changes
- **Pages outside core 4** — get foundation improvements (safe-area, dvh, touch targets) but no page-specific redesign

---

## 8. Implementation Order

1. Foundation (dvh, safe-area, viewport-fit, touch targets)
2. MobileSheet + MobileBottomSheet components
3. Bottom tab bar redesign
4. FAB component
5. Notes page mobile optimization
6. TagAutocomplete component
7. Search page mobile optimization
8. Documents page mobile optimization
9. Chat page mobile optimization
10. Gestures (pull-to-refresh, swipe actions)
11. Auto-hide bottom bar on scroll
