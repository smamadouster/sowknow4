# Mobile Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SOWKNOW feel like a native iOS app on iPhone Safari and PWA standalone mode, focusing on Search, Notes, Documents, and Chat pages.

**Architecture:** Progressive enhancement below the `md:` breakpoint (768px). Desktop layout is untouched. New shared components (MobileSheet, MobileBottomSheet, FAB, TagAutocomplete) are created in `frontend/components/mobile/`. A `useIsMobile()` hook gates all mobile-specific rendering. A backend endpoint is added for tag suggestions.

**Tech Stack:** Next.js 14, Tailwind CSS, React touch events, existing Zustand store, FastAPI (one new endpoint)

---

## File Structure

### New files
| File | Purpose |
|------|---------|
| `frontend/hooks/useIsMobile.ts` | Media query hook — returns `true` below 768px |
| `frontend/hooks/useScrollDirection.ts` | Tracks scroll up/down for auto-hiding bottom bar |
| `frontend/components/mobile/MobileSheet.tsx` | Full-screen bottom sheet with swipe-to-dismiss |
| `frontend/components/mobile/MobileBottomSheet.tsx` | Half-height bottom sheet for filters/menus |
| `frontend/components/mobile/FAB.tsx` | Floating action button component |
| `frontend/components/mobile/SwipeableRow.tsx` | Swipe-left-to-reveal-action wrapper for list items |
| `frontend/components/mobile/PullToRefresh.tsx` | Pull-to-refresh wrapper for list pages |
| `frontend/components/TagAutocomplete.tsx` | Tag input with fuzzy search and suggestion chips |
| `frontend/hooks/useTagSuggestions.ts` | Fetches and caches tag suggestions from API |
| `backend/app/api/tags.py` | New API router for tag search/suggestions |

### Modified files
| File | Changes |
|------|---------|
| `frontend/app/layout.tsx` | Add `viewport-fit=cover` meta |
| `frontend/app/globals.css` | Add safe-area CSS utilities, dvh helpers, mobile sheet animations |
| `frontend/tailwind.config.js` | Add safe-area spacing utilities |
| `frontend/app/[locale]/layout.tsx` | Safe-area padding on header |
| `frontend/components/Navigation.tsx` | Redesigned mobile bottom bar, "More" as bottom sheet |
| `frontend/app/[locale]/notes/page.tsx` | FAB, MobileSheet editor, swipe-to-delete, single column |
| `frontend/components/TagSelector.tsx` | Conditionally render TagAutocomplete on mobile |
| `frontend/app/[locale]/search/page.tsx` | Sticky search bar, filter chips, mobile-optimized cards |
| `frontend/app/[locale]/documents/page.tsx` | FAB upload, row layout, filter bottom sheet |
| `frontend/app/[locale]/chat/page.tsx` | Default sidebar closed, session switcher bottom sheet, safe-area input |
| `frontend/app/[locale]/page.tsx` | dvh fix on home page |
| `backend/app/main_minimal.py` | Register tags router |

---

### Task 1: useIsMobile hook

**Files:**
- Create: `frontend/hooks/useIsMobile.ts`

- [ ] **Step 1: Create the hook**

```typescript
// frontend/hooks/useIsMobile.ts
'use client';

import { useState, useEffect } from 'react';

const MOBILE_BREAKPOINT = 768;

export function useIsMobile(): boolean {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    setIsMobile(mql.matches);

    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return isMobile;
}

export function useIsStandalone(): boolean {
  const [isStandalone, setIsStandalone] = useState(false);

  useEffect(() => {
    const mql = window.matchMedia('(display-mode: standalone)');
    setIsStandalone(mql.matches);

    const handler = (e: MediaQueryListEvent) => setIsStandalone(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, []);

  return isStandalone;
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit hooks/useIsMobile.ts 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/useIsMobile.ts
git commit -m "feat(mobile): add useIsMobile and useIsStandalone hooks"
```

---

### Task 2: Foundation — viewport, dvh, safe-area CSS

**Files:**
- Modify: `frontend/app/layout.tsx:4-22` (metadata)
- Modify: `frontend/app/globals.css` (add utilities)
- Modify: `frontend/tailwind.config.js` (safe-area spacing)

- [ ] **Step 1: Add viewport-fit=cover to root layout metadata**

In `frontend/app/layout.tsx`, add the viewport export. Next.js 14 uses `metadata.viewport` or a separate `viewport` export:

```typescript
// Add this export BEFORE the existing metadata export in frontend/app/layout.tsx
export const viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover' as const,
};
```

- [ ] **Step 2: Add mobile CSS utilities to globals.css**

Append to `frontend/app/globals.css`:

```css
/* === Mobile Foundation === */

/* Dynamic viewport height — handles Safari address bar */
.h-dvh {
  height: 100vh;
  height: 100dvh;
}

.min-h-dvh {
  min-height: 100vh;
  min-height: 100dvh;
}

/* Safe area utilities */
.pb-safe {
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.pt-safe {
  padding-top: env(safe-area-inset-top, 0px);
}

.mb-safe {
  margin-bottom: env(safe-area-inset-bottom, 0px);
}

/* Bottom bar height variable (tab bar + safe area) */
:root {
  --bottom-bar-height: 3.5rem; /* 56px */
  --bottom-bar-total: calc(3.5rem + env(safe-area-inset-bottom, 0px));
}

/* Mobile sheet animations */
@keyframes sheet-slide-up {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}

@keyframes sheet-slide-down {
  from {
    transform: translateY(0);
  }
  to {
    transform: translateY(100%);
  }
}

.animate-sheet-up {
  animation: sheet-slide-up 0.3s cubic-bezier(0.32, 0.72, 0, 1);
}

.animate-sheet-down {
  animation: sheet-slide-down 0.2s ease-out forwards;
}

/* FAB positioning — above bottom bar */
.fab-position {
  position: fixed;
  right: 1rem;
  bottom: calc(var(--bottom-bar-total) + 1rem);
  z-index: 35;
}

/* Mobile: increase chat message width */
@media (max-width: 768px) {
  .chat-message {
    max-width: 95%;
  }
}

/* Touch target enforcement */
@media (max-width: 768px) {
  .touch-target {
    min-width: 44px;
    min-height: 44px;
  }
}

/* Hide scrollbar on mobile for horizontal scroll containers */
.scrollbar-hide::-webkit-scrollbar {
  display: none;
}
.scrollbar-hide {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
```

- [ ] **Step 3: Add safe-area spacing to Tailwind config**

In `frontend/tailwind.config.js`, add inside `theme.extend`:

```javascript
spacing: {
  'safe-bottom': 'env(safe-area-inset-bottom, 0px)',
  'safe-top': 'env(safe-area-inset-top, 0px)',
  'bottom-bar': 'var(--bottom-bar-total)',
},
```

- [ ] **Step 4: Fix dvh in locale layout**

In `frontend/app/[locale]/layout.tsx`, change the flex container:

Find: `<div className="flex min-h-[calc(100vh-3.5rem)]">`
Replace: `<div className="flex min-h-[calc(100dvh-3.5rem)]" style={{ minHeight: 'calc(100vh - 3.5rem)' }}>`

The inline style is the fallback for browsers without dvh support. Tailwind's JIT will generate the dvh version.

- [ ] **Step 5: Add safe-area padding to header**

In `frontend/app/[locale]/layout.tsx`, update the header:

Find: `<header className="sticky top-0 z-50 border-b border-white/[0.06] bg-vault-1000/80 backdrop-blur-xl">`
Replace: `<header className="sticky top-0 z-50 border-b border-white/[0.06] bg-vault-1000/80 backdrop-blur-xl pt-safe">`

- [ ] **Step 6: Fix dvh in home page**

In `frontend/app/[locale]/page.tsx`, find:

`<div className="min-h-[calc(100vh-8rem)] bg-vault-1000 relative overflow-hidden">`

Replace with:

`<div className="min-h-[calc(100dvh-8rem)] bg-vault-1000 relative overflow-hidden" style={{ minHeight: 'calc(100vh - 8rem)' }}>`

- [ ] **Step 7: Commit**

```bash
git add frontend/app/layout.tsx frontend/app/globals.css frontend/tailwind.config.js frontend/app/[locale]/layout.tsx frontend/app/[locale]/page.tsx
git commit -m "feat(mobile): foundation — viewport-fit, dvh, safe-area CSS utilities"
```

---

### Task 3: MobileSheet component

**Files:**
- Create: `frontend/components/mobile/MobileSheet.tsx`

- [ ] **Step 1: Create the MobileSheet component**

```tsx
// frontend/components/mobile/MobileSheet.tsx
'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface MobileSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Extra buttons in the header (e.g., "New Note") */
  headerActions?: React.ReactNode;
  /** Sticky footer content (e.g., Save/Cancel buttons) */
  footer?: React.ReactNode;
  children: React.ReactNode;
}

const DISMISS_THRESHOLD = 0.3; // 30% of screen height

export default function MobileSheet({ open, onClose, title, headerActions, footer, children }: MobileSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragStartY = useRef<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);
  const [isClosing, setIsClosing] = useState(false);

  // Lock body scroll when open
  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    // Only start drag from the header/drag-handle area (first 60px)
    const touch = e.touches[0];
    const rect = sheetRef.current?.getBoundingClientRect();
    if (rect && touch.clientY - rect.top < 60) {
      dragStartY.current = touch.clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (dragStartY.current === null) return;
    const delta = e.touches[0].clientY - dragStartY.current;
    if (delta > 0) {
      setDragOffset(delta);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (dragStartY.current === null) return;
    const screenHeight = window.innerHeight;
    if (dragOffset > screenHeight * DISMISS_THRESHOLD) {
      setIsClosing(true);
      setTimeout(() => {
        onClose();
        setIsClosing(false);
        setDragOffset(0);
      }, 200);
    } else {
      setDragOffset(0);
    }
    dragStartY.current = null;
  }, [dragOffset, onClose]);

  if (!open && !isClosing) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-50 bg-black/60 backdrop-blur-sm transition-opacity duration-200 ${
          isClosing ? 'opacity-0' : 'opacity-100'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Sheet'}
        className={`fixed inset-x-0 bottom-0 z-50 bg-vault-950 rounded-t-2xl shadow-2xl flex flex-col ${
          isClosing ? 'animate-sheet-down' : 'animate-sheet-up'
        }`}
        style={{
          top: 'env(safe-area-inset-top, 0px)',
          transform: dragOffset > 0 ? `translateY(${dragOffset}px)` : undefined,
          transition: dragOffset > 0 ? 'none' : undefined,
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-white/20" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-4 pb-3 border-b border-white/[0.06]">
          <h2 className="text-base font-semibold text-text-primary font-display">{title}</h2>
          <div className="flex items-center gap-2">
            {headerActions}
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/[0.06] flex items-center justify-center text-text-muted hover:text-text-primary transition-colors"
              aria-label="Close"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-4 py-4">
          {children}
        </div>

        {/* Sticky footer */}
        {footer && (
          <div className="border-t border-white/[0.06] px-4 py-3 pb-safe bg-vault-950">
            {footer}
          </div>
        )}
      </div>
    </>
  );
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -20`

- [ ] **Step 3: Commit**

```bash
git add frontend/components/mobile/MobileSheet.tsx
git commit -m "feat(mobile): add MobileSheet full-screen bottom sheet component"
```

---

### Task 4: MobileBottomSheet component

**Files:**
- Create: `frontend/components/mobile/MobileBottomSheet.tsx`

- [ ] **Step 1: Create the MobileBottomSheet component**

```tsx
// frontend/components/mobile/MobileBottomSheet.tsx
'use client';

import { useEffect, useRef, useCallback, useState } from 'react';

interface MobileBottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  /** Height as percentage of viewport. Default: 50 */
  heightPercent?: number;
}

const DISMISS_THRESHOLD = 0.25;

export default function MobileBottomSheet({ open, onClose, title, children, heightPercent = 50 }: MobileBottomSheetProps) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const dragStartY = useRef<number | null>(null);
  const [dragOffset, setDragOffset] = useState(0);
  const [isClosing, setIsClosing] = useState(false);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0];
    const rect = sheetRef.current?.getBoundingClientRect();
    if (rect && touch.clientY - rect.top < 60) {
      dragStartY.current = touch.clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (dragStartY.current === null) return;
    const delta = e.touches[0].clientY - dragStartY.current;
    if (delta > 0) {
      setDragOffset(delta);
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (dragStartY.current === null) return;
    const sheetHeight = (window.innerHeight * heightPercent) / 100;
    if (dragOffset > sheetHeight * DISMISS_THRESHOLD) {
      setIsClosing(true);
      setTimeout(() => {
        onClose();
        setIsClosing(false);
        setDragOffset(0);
      }, 200);
    } else {
      setDragOffset(0);
    }
    dragStartY.current = null;
  }, [dragOffset, heightPercent, onClose]);

  if (!open && !isClosing) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-50 bg-black/50 transition-opacity duration-200 ${
          isClosing ? 'opacity-0' : 'opacity-100'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sheet */}
      <div
        ref={sheetRef}
        role="dialog"
        aria-modal="true"
        aria-label={title || 'Menu'}
        className={`fixed inset-x-0 bottom-0 z-50 bg-vault-950 rounded-t-2xl shadow-2xl flex flex-col ${
          isClosing ? 'animate-sheet-down' : 'animate-sheet-up'
        }`}
        style={{
          maxHeight: `${heightPercent}vh`,
          transform: dragOffset > 0 ? `translateY(${dragOffset}px)` : undefined,
          transition: dragOffset > 0 ? 'none' : undefined,
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 rounded-full bg-white/20" />
        </div>

        {/* Header (if title provided) */}
        {title && (
          <div className="flex items-center justify-between px-4 pb-3 border-b border-white/[0.06]">
            <h2 className="text-sm font-semibold text-text-primary font-display">{title}</h2>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-full bg-white/[0.06] flex items-center justify-center text-text-muted hover:text-text-primary transition-colors"
              aria-label="Close"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        )}

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 pb-safe">
          {children}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/mobile/MobileBottomSheet.tsx
git commit -m "feat(mobile): add MobileBottomSheet half-height sheet component"
```

---

### Task 5: FAB component

**Files:**
- Create: `frontend/components/mobile/FAB.tsx`

- [ ] **Step 1: Create the FAB component**

```tsx
// frontend/components/mobile/FAB.tsx
'use client';

interface FABProps {
  onClick: () => void;
  label: string;
  icon?: React.ReactNode;
}

export default function FAB({ onClick, label, icon }: FABProps) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      className="fab-position w-14 h-14 rounded-full bg-gradient-to-br from-amber-400 to-amber-600 text-vault-1000 shadow-lg shadow-amber-500/30 flex items-center justify-center active:scale-95 transition-transform md:hidden"
    >
      {icon || (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
        </svg>
      )}
    </button>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/components/mobile/FAB.tsx
git commit -m "feat(mobile): add FAB floating action button component"
```

---

### Task 6: useScrollDirection hook

**Files:**
- Create: `frontend/hooks/useScrollDirection.ts`

- [ ] **Step 1: Create the hook**

```typescript
// frontend/hooks/useScrollDirection.ts
'use client';

import { useState, useEffect, useRef } from 'react';

export type ScrollDirection = 'up' | 'down' | null;

/**
 * Returns 'up' or 'down' based on scroll direction.
 * Used to auto-hide the bottom bar on scroll down.
 */
export function useScrollDirection(threshold: number = 10): ScrollDirection {
  const [direction, setDirection] = useState<ScrollDirection>(null);
  const lastScrollY = useRef(0);
  const ticking = useRef(false);

  useEffect(() => {
    lastScrollY.current = window.scrollY;

    const updateDirection = () => {
      const scrollY = window.scrollY;
      const diff = scrollY - lastScrollY.current;

      if (Math.abs(diff) < threshold) {
        ticking.current = false;
        return;
      }

      setDirection(diff > 0 ? 'down' : 'up');
      lastScrollY.current = scrollY > 0 ? scrollY : 0;
      ticking.current = false;
    };

    const onScroll = () => {
      if (!ticking.current) {
        window.requestAnimationFrame(updateDirection);
        ticking.current = true;
      }
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [threshold]);

  return direction;
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/hooks/useScrollDirection.ts
git commit -m "feat(mobile): add useScrollDirection hook for auto-hide bottom bar"
```

---

### Task 7: Bottom tab bar redesign

**Files:**
- Modify: `frontend/components/Navigation.tsx`

This is the largest single task. The Navigation component currently has:
- Desktop sidebar (lines 252-363) — **unchanged**
- Mobile bottom nav (lines 366-398) — **redesigned**
- Mobile slide-in drawer (lines 400-498) — **replaced with MobileBottomSheet**
- Logout modal (lines 500-555) — **uses MobileBottomSheet on mobile**

- [ ] **Step 1: Add imports at the top of Navigation.tsx**

At the top of `frontend/components/Navigation.tsx`, add these imports after the existing ones:

```typescript
import { useIsMobile } from '@/hooks/useIsMobile';
import { useScrollDirection } from '@/hooks/useScrollDirection';
import MobileBottomSheet from '@/components/mobile/MobileBottomSheet';
```

- [ ] **Step 2: Define mobile tab items**

Inside the `Navigation` function, after `const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);` (line 174), add:

```typescript
const isMobile = useIsMobile();
const scrollDirection = useScrollDirection();
const [moreSheetOpen, setMoreSheetOpen] = useState(false);

// Mobile tabs: Search, Notes, Documents, Chat, More
const mobileTabItems: NavItem[] = [
  navItems.find(i => i.labelKey === 'search')!,
  navItems.find(i => i.labelKey === 'notes')!,
  navItems.find(i => i.labelKey === 'documents')!,
  navItems.find(i => i.labelKey === 'chat')!,
];

// Items shown in the "More" bottom sheet
const moreItems = mainItems.filter(
  item => !mobileTabItems.some(tab => tab.href === item.href)
);
```

- [ ] **Step 3: Replace the mobile bottom navigation section**

Find the existing mobile bottom navigation block (lines 365-398, the `{/* Mobile bottom navigation */}` section). Replace it entirely with:

```tsx
{/* Mobile bottom navigation */}
<nav
  className={`md:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-white/[0.06] bg-vault-950/95 backdrop-blur-xl pb-safe transition-transform duration-200 ${
    scrollDirection === 'down' ? 'translate-y-full' : 'translate-y-0'
  }`}
  aria-label={t('main_navigation')}
>
  <div className="flex items-center justify-around h-14 px-1">
    {mobileTabItems.map((item) => {
      const active = isActive(item.href);
      return (
        <Link
          key={item.href}
          href={item.href}
          aria-current={active ? 'page' : undefined}
          className={`relative flex flex-col items-center justify-center gap-0.5 px-3 py-1.5 rounded-lg min-w-[64px] min-h-[44px] transition-all ${
            active ? 'text-amber-400' : 'text-text-muted'
          }`}
        >
          {active && (
            <span className="absolute top-0.5 left-1/2 -translate-x-1/2 w-5 h-1 rounded-full bg-amber-400" />
          )}
          <span aria-hidden="true">{item.icon}</span>
          <span className="text-[10px] font-medium truncate max-w-[64px]">{t(item.labelKey)}</span>
        </Link>
      );
    })}
    {/* More button */}
    <button
      onClick={() => setMoreSheetOpen(true)}
      aria-label={t('toggle_navigation')}
      className="relative flex flex-col items-center justify-center gap-0.5 px-3 py-1.5 rounded-lg min-w-[64px] min-h-[44px] text-text-muted"
    >
      <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
      </svg>
      <span className="text-[10px] font-medium">Menu</span>
    </button>
  </div>
</nav>
```

- [ ] **Step 4: Replace the mobile slide-in drawer with MobileBottomSheet**

Find the existing mobile drawer code (the backdrop div at line ~400 and the `id="mobile-menu"` div). Remove both (the backdrop `<div className={`fixed inset-0 z-50 bg-black/60...` and the `<div id="mobile-menu"...`). Replace with:

```tsx
{/* More navigation bottom sheet */}
<MobileBottomSheet
  open={moreSheetOpen}
  onClose={() => setMoreSheetOpen(false)}
  title="Navigation"
  heightPercent={65}
>
  <nav className="space-y-1">
    {moreItems.map((item) => {
      const active = isActive(item.href);
      return (
        <Link
          key={item.href}
          href={item.href}
          onClick={() => setMoreSheetOpen(false)}
          aria-current={active ? 'page' : undefined}
          className={`flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium transition-all min-h-[44px] ${
            active
              ? 'bg-amber-500/10 text-amber-400'
              : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
          }`}
        >
          <span aria-hidden="true">{item.icon}</span>
          <span>{t(item.labelKey)}</span>
        </Link>
      );
    })}

    {/* Admin section */}
    {visibleAdminItems.length > 0 && (
      <>
        <div className="pt-2 pb-1 px-3">
          <div className="border-t border-white/[0.06]" />
          <p className="text-[10px] font-semibold text-text-muted/60 uppercase tracking-widest mt-2">Admin</p>
        </div>
        {visibleAdminItems.map((item) => {
          const active = isActive(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMoreSheetOpen(false)}
              aria-current={active ? 'page' : undefined}
              className={`flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium transition-all min-h-[44px] ${
                active
                  ? 'bg-amber-500/10 text-amber-400'
                  : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04]'
              }`}
            >
              <span aria-hidden="true">{item.icon}</span>
              <span>{t(item.labelKey)}</span>
            </Link>
          );
        })}
      </>
    )}

    {/* Logout */}
    <div className="pt-2">
      <div className="border-t border-white/[0.06]" />
      <button
        onClick={() => { setMoreSheetOpen(false); setShowLogoutConfirm(true); }}
        className="flex items-center gap-3 w-full px-3 py-3 rounded-xl text-sm font-medium text-text-muted hover:text-red-400 hover:bg-red-500/5 transition-all min-h-[44px] mt-1"
      >
        <svg className="w-[18px] h-[18px] shrink-0" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
        <span>{t('logout')}</span>
      </button>
    </div>
  </nav>
</MobileBottomSheet>
```

- [ ] **Step 5: Remove the old isMobileOpen state and related effects**

The old `isMobileOpen` state and its effects (lines 173, 184-231) are no longer needed for the mobile drawer since we replaced it with `moreSheetOpen` and `MobileBottomSheet`. Remove:
- `const [isMobileOpen, setIsMobileOpen] = useState(false);` — replace all `isMobileOpen` references with `moreSheetOpen` and `setIsMobileOpen` with `setMoreSheetOpen`
- Remove the `useEffect` that closes the drawer on pathname change (line 184-186) — MobileBottomSheet handles its own state
- Remove the keyboard trap `useEffect` (lines 188-222) — MobileBottomSheet handles Escape
- Remove the body scroll lock `useEffect` (lines 224-231) — MobileBottomSheet handles this

- [ ] **Step 6: Verify the frontend compiles**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

Fix any type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/components/Navigation.tsx
git commit -m "feat(mobile): redesign bottom tab bar — Search/Notes/Docs/Chat + More sheet"
```

---

### Task 8: SwipeableRow and PullToRefresh components

**Files:**
- Create: `frontend/components/mobile/SwipeableRow.tsx`
- Create: `frontend/components/mobile/PullToRefresh.tsx`

- [ ] **Step 1: Create SwipeableRow**

```tsx
// frontend/components/mobile/SwipeableRow.tsx
'use client';

import { useRef, useState, useCallback } from 'react';

interface SwipeableRowProps {
  children: React.ReactNode;
  onSwipeAction: () => void;
  actionLabel: string;
  actionColor?: string;
}

const SWIPE_THRESHOLD = 80;

export default function SwipeableRow({ children, onSwipeAction, actionLabel, actionColor = 'bg-red-500' }: SwipeableRowProps) {
  const startX = useRef<number | null>(null);
  const [offsetX, setOffsetX] = useState(0);
  const [showAction, setShowAction] = useState(false);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    startX.current = e.touches[0].clientX;
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (startX.current === null) return;
    const diff = startX.current - e.touches[0].clientX;
    if (diff > 0) {
      setOffsetX(Math.min(diff, 120));
    }
  }, []);

  const handleTouchEnd = useCallback(() => {
    if (offsetX > SWIPE_THRESHOLD) {
      setShowAction(true);
      setOffsetX(100);
    } else {
      setOffsetX(0);
      setShowAction(false);
    }
    startX.current = null;
  }, [offsetX]);

  const handleActionClick = () => {
    onSwipeAction();
    setOffsetX(0);
    setShowAction(false);
  };

  const handleContentClick = () => {
    if (showAction) {
      setOffsetX(0);
      setShowAction(false);
    }
  };

  return (
    <div className="relative overflow-hidden rounded-lg md:overflow-visible">
      {/* Action behind */}
      <div className={`absolute inset-y-0 right-0 flex items-center justify-center ${actionColor} text-white font-medium text-sm px-4`} style={{ width: '100px' }}>
        <button onClick={handleActionClick} className="w-full h-full flex items-center justify-center min-h-[44px]">
          {actionLabel}
        </button>
      </div>

      {/* Content */}
      <div
        className="relative bg-vault-950 transition-transform"
        style={{
          transform: `translateX(-${offsetX}px)`,
          transition: startX.current !== null ? 'none' : 'transform 0.2s ease-out',
        }}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClick={handleContentClick}
      >
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create PullToRefresh**

```tsx
// frontend/components/mobile/PullToRefresh.tsx
'use client';

import { useRef, useState, useCallback } from 'react';

interface PullToRefreshProps {
  onRefresh: () => Promise<void>;
  children: React.ReactNode;
}

const PULL_THRESHOLD = 60;

export default function PullToRefresh({ onRefresh, children }: PullToRefreshProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const startY = useRef<number | null>(null);
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const scrollTop = containerRef.current?.scrollTop ?? window.scrollY;
    if (scrollTop <= 0) {
      startY.current = e.touches[0].clientY;
    }
  }, []);

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    if (startY.current === null || refreshing) return;
    const diff = e.touches[0].clientY - startY.current;
    if (diff > 0) {
      // Rubber-band effect: diminishing returns
      setPullDistance(Math.min(diff * 0.4, 100));
    }
  }, [refreshing]);

  const handleTouchEnd = useCallback(async () => {
    if (startY.current === null) return;
    startY.current = null;

    if (pullDistance >= PULL_THRESHOLD && !refreshing) {
      setRefreshing(true);
      setPullDistance(PULL_THRESHOLD);
      try {
        await onRefresh();
      } finally {
        setRefreshing(false);
        setPullDistance(0);
      }
    } else {
      setPullDistance(0);
    }
  }, [pullDistance, refreshing, onRefresh]);

  return (
    <div
      ref={containerRef}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      style={{ touchAction: 'pan-y' }}
    >
      {/* Pull indicator */}
      {(pullDistance > 0 || refreshing) && (
        <div
          className="flex items-center justify-center overflow-hidden transition-all"
          style={{ height: `${pullDistance}px` }}
        >
          <div className={`w-5 h-5 border-2 border-amber-400 border-t-transparent rounded-full ${
            refreshing ? 'animate-spin' : ''
          }`} style={{
            opacity: Math.min(pullDistance / PULL_THRESHOLD, 1),
            transform: `rotate(${pullDistance * 3}deg)`,
          }} />
        </div>
      )}
      {children}
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/components/mobile/SwipeableRow.tsx frontend/components/mobile/PullToRefresh.tsx
git commit -m "feat(mobile): add SwipeableRow and PullToRefresh gesture components"
```

---

### Task 9: Notes page mobile optimization

**Files:**
- Modify: `frontend/app/[locale]/notes/page.tsx`

- [ ] **Step 1: Add imports**

At the top of `frontend/app/[locale]/notes/page.tsx`, add after existing imports:

```typescript
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileSheet from '@/components/mobile/MobileSheet';
import FAB from '@/components/mobile/FAB';
import SwipeableRow from '@/components/mobile/SwipeableRow';
import PullToRefresh from '@/components/mobile/PullToRefresh';
```

- [ ] **Step 2: Add isMobile hook usage**

Inside `NotesPage()`, after `const [pendingAudio, setPendingAudio] = ...` (line 51), add:

```typescript
const isMobile = useIsMobile();
```

- [ ] **Step 3: Add resetAndNewNote function**

After the `handleSearch` function (line 135), add:

```typescript
const resetAndNewNote = () => {
  setEditingNote(null);
  setEditTitle('');
  setEditContent('');
  setEditTags([]);
  setPendingAudio(null);
  setShowEditor(true);
};
```

- [ ] **Step 4: Replace the return JSX**

Replace the entire `return (...)` block (lines 137-282) with:

```tsx
return (
  <div className="min-h-screen bg-vault-1000">
    <div className="max-w-6xl mx-auto px-4 py-6 md:py-8 pb-20 md:pb-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 md:mb-8">
        <h1 className="text-xl md:text-2xl font-bold text-text-primary font-display">{t('title')}</h1>
        {/* Desktop-only new button */}
        <button
          onClick={() => openEditor()}
          className="hidden md:inline-flex px-4 py-2 bg-amber-500 text-vault-1000 rounded-lg hover:bg-amber-600 transition-colors font-medium text-sm"
        >
          {t('new')}
        </button>
      </div>

      {/* Search */}
      <form onSubmit={handleSearch} className="mb-6">
        <input
          type="text"
          value={searchQuery}
          onChange={e => setSearchQuery(e.target.value)}
          placeholder={t('search_placeholder')}
          className="w-full px-4 py-3 rounded-xl border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all min-h-[44px]"
        />
      </form>

      {/* Loading / Empty / Grid */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-amber-500" />
        </div>
      ) : notes.length === 0 ? (
        <p className="text-center text-text-muted py-12">{t('empty')}</p>
      ) : (
        <PullToRefresh onRefresh={async () => { await fetchNotes(); }}>
          <div className="grid gap-3 md:gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
            {notes.map(note => {
              const card = (
                <div
                  className="p-4 bg-vault-900/60 border border-white/[0.06] rounded-xl cursor-pointer hover:border-white/[0.12] transition-all"
                  onClick={() => openEditor(note)}
                >
                  <div className="flex items-start justify-between">
                    <h3 className="font-medium text-text-primary truncate flex-1">{note.title}</h3>
                    {/* Desktop-only delete button */}
                    <button
                      onClick={e => { e.stopPropagation(); handleDelete(note.id); }}
                      className="hidden md:block ml-2 text-text-muted hover:text-red-400 transition-colors"
                    >
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                  {note.content && (
                    <p className="text-sm text-text-secondary mt-2 line-clamp-3">{note.content}</p>
                  )}
                  <div className="flex flex-wrap gap-1 mt-3">
                    {note.tags.map(tag => (
                      <span key={tag.id} className="px-2 py-0.5 text-xs rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                        {tag.tag_name}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-text-muted mt-2">
                    {new Date(note.created_at).toLocaleDateString(locale)}
                  </p>
                </div>
              );

              if (isMobile) {
                return (
                  <SwipeableRow
                    key={note.id}
                    onSwipeAction={() => handleDelete(note.id)}
                    actionLabel={tCommon('delete')}
                  >
                    {card}
                  </SwipeableRow>
                );
              }

              return <div key={note.id}>{card}</div>;
            })}
          </div>
        </PullToRefresh>
      )}

      {/* Pagination */}
      {total > 50 && (
        <div className="flex justify-center gap-2 mt-6">
          <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="px-3 py-2 rounded-lg bg-vault-800 border border-white/[0.06] text-text-secondary disabled:opacity-50 min-h-[44px]">&laquo;</button>
          <span className="px-3 py-2 text-text-muted">{page} / {Math.ceil(total / 50)}</span>
          <button disabled={page >= Math.ceil(total / 50)} onClick={() => setPage(p => p + 1)} className="px-3 py-2 rounded-lg bg-vault-800 border border-white/[0.06] text-text-secondary disabled:opacity-50 min-h-[44px]">&raquo;</button>
        </div>
      )}
    </div>

    {/* FAB — mobile only */}
    {isMobile && (
      <FAB onClick={resetAndNewNote} label={t('new')} />
    )}

    {/* Editor — MobileSheet on mobile, modal on desktop */}
    {showEditor && isMobile && (
      <MobileSheet
        open={showEditor}
        onClose={() => setShowEditor(false)}
        title={editingNote ? editingNote.title : t('new')}
        headerActions={
          editingNote ? (
            <button
              onClick={resetAndNewNote}
              className="px-3 py-1.5 text-xs font-medium text-amber-400 bg-amber-500/10 rounded-lg border border-amber-500/20"
            >
              + {t('new')}
            </button>
          ) : undefined
        }
        footer={
          <div className="flex justify-end gap-3">
            <button
              onClick={() => setShowEditor(false)}
              className="px-4 py-3 rounded-xl text-sm font-medium text-text-secondary hover:bg-white/[0.04] transition-all min-h-[44px]"
            >
              {tCommon('cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !editTitle}
              className="px-6 py-3 rounded-xl bg-amber-500 text-vault-1000 font-medium text-sm hover:bg-amber-600 disabled:opacity-50 min-h-[44px]"
            >
              {saving ? tCommon('loading') : tCommon('save')}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">{t('title_label')} *</label>
            <input
              type="text"
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              autoFocus
              className="w-full px-4 py-3 rounded-xl border border-white/[0.08] bg-vault-800/50 text-text-primary focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all min-h-[44px]"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">{t('content_label')}</label>
            <textarea
              value={editContent}
              onChange={e => setEditContent(e.target.value)}
              rows={10}
              className="w-full px-4 py-3 rounded-xl border border-white/[0.08] bg-vault-800/50 text-text-primary font-mono text-sm focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
            />
            <div className="mt-2 p-3 bg-vault-800/30 rounded-xl border border-white/[0.06]">
              <VoiceRecorder
                mode="note"
                onAudioReady={(blob, transcript) => {
                  setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
                  setPendingAudio({ blob, transcript });
                }}
              />
            </div>
            {pendingAudio && (
              <p className="mt-1 text-xs text-amber-400">{t('audio_pending')}</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
            <TagSelector tags={editTags} onChange={setEditTags} />
          </div>
        </div>
      </MobileSheet>
    )}

    {/* Desktop editor modal */}
    {showEditor && !isMobile && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
        <div className="bg-vault-900 border border-white/[0.08] rounded-xl shadow-xl max-w-lg w-full p-6">
          <h2 className="text-xl font-bold text-text-primary mb-4 font-display">
            {editingNote ? editingNote.title : t('new')}
          </h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('title_label')} *</label>
              <input
                type="text"
                value={editTitle}
                onChange={e => setEditTitle(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('content_label')}</label>
              <textarea
                value={editContent}
                onChange={e => setEditContent(e.target.value)}
                rows={8}
                className="w-full px-3 py-2 rounded-lg border border-white/[0.08] bg-vault-800/50 text-text-primary font-mono text-sm"
              />
              <div className="mt-2 p-3 bg-vault-800/30 rounded-lg border border-white/[0.06]">
                <VoiceRecorder
                  mode="note"
                  onAudioReady={(blob, transcript) => {
                    setEditContent(prev => prev ? `${prev}\n\n${transcript}` : transcript);
                    setPendingAudio({ blob, transcript });
                  }}
                />
              </div>
              {pendingAudio && (
                <p className="mt-1 text-xs text-amber-400">{t('audio_pending')}</p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-text-secondary mb-1">{t('tags_label')}</label>
              <TagSelector tags={editTags} onChange={setEditTags} />
            </div>
          </div>
          <div className="flex justify-end gap-3 mt-6">
            <button
              onClick={() => setShowEditor(false)}
              className="px-4 py-2 rounded-lg border border-white/[0.08] text-text-secondary hover:bg-white/[0.04]"
            >
              {tCommon('cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !editTitle}
              className="px-4 py-2 rounded-lg bg-amber-500 text-vault-1000 hover:bg-amber-600 disabled:opacity-50"
            >
              {saving ? tCommon('loading') : tCommon('save')}
            </button>
          </div>
        </div>
      </div>
    )}
  </div>
);
```

- [ ] **Step 5: Verify compilation**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 6: Commit**

```bash
git add frontend/app/[locale]/notes/page.tsx
git commit -m "feat(mobile): notes page — FAB, MobileSheet editor, swipe-to-delete, pull-to-refresh"
```

---

### Task 10: Tag suggestions API endpoint

**Files:**
- Create: `backend/app/api/tags.py`
- Modify: `backend/app/main_minimal.py` (register router)

- [ ] **Step 1: Create the tags API router**

```python
# backend/app/api/tags.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.tag import Tag

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/suggestions")
async def get_tag_suggestions(
    q: str = Query("", min_length=0, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Return distinct tag names, optionally filtered by query. Sorted by frequency."""
    base = (
        select(
            Tag.tag_name,
            func.count(Tag.id).label("freq"),
        )
        .group_by(Tag.tag_name)
    )

    if q.strip():
        # Case-insensitive substring match (fuzzy-ish)
        base = base.where(Tag.tag_name.ilike(f"%{q.strip()}%"))

    base = base.order_by(func.count(Tag.id).desc()).limit(limit)

    result = await db.execute(base)
    rows = result.all()

    return {
        "tags": [{"tag_name": row.tag_name, "count": row.freq} for row in rows],
    }
```

- [ ] **Step 2: Register the router**

In `backend/app/main_minimal.py`, find where other routers are included (search for `app.include_router` or `api_router.include_router`). Add:

```python
from app.api.tags import router as tags_router
# ... in the router registration section:
app.include_router(tags_router, prefix="/api/v1")
```

Note: the exact registration pattern depends on whether the file uses `app.include_router` directly or an `api_router`. Match the existing pattern.

- [ ] **Step 3: Verify the endpoint**

Run: `cd backend && python -c "from app.api.tags import router; print('OK')"` to check imports.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/tags.py backend/app/main_minimal.py
git commit -m "feat(api): add /api/v1/tags/suggestions endpoint for tag autocomplete"
```

---

### Task 11: TagAutocomplete component

**Files:**
- Create: `frontend/hooks/useTagSuggestions.ts`
- Create: `frontend/components/TagAutocomplete.tsx`
- Modify: `frontend/components/TagSelector.tsx`

- [ ] **Step 1: Create the useTagSuggestions hook**

```typescript
// frontend/hooks/useTagSuggestions.ts
'use client';

import { useState, useEffect, useRef } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

interface TagSuggestion {
  tag_name: string;
  count: number;
}

export function useTagSuggestions(query: string, debounceMs: number = 200) {
  const [suggestions, setSuggestions] = useState<TagSuggestion[]>([]);
  const [topTags, setTopTags] = useState<TagSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // Load top tags once on mount
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/v1/tags/suggestions?limit=8`, {
      credentials: 'include',
      signal: controller.signal,
    })
      .then(res => res.ok ? res.json() : Promise.reject(res))
      .then(data => setTopTags(data.tags || []))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  // Search as user types
  useEffect(() => {
    if (!query.trim()) {
      setSuggestions([]);
      return;
    }

    const timer = setTimeout(() => {
      abortRef.current?.abort();
      abortRef.current = new AbortController();
      setLoading(true);

      fetch(`${API_BASE}/v1/tags/suggestions?q=${encodeURIComponent(query)}&limit=10`, {
        credentials: 'include',
        signal: abortRef.current.signal,
      })
        .then(res => res.ok ? res.json() : Promise.reject(res))
        .then(data => setSuggestions(data.tags || []))
        .catch(() => {})
        .finally(() => setLoading(false));
    }, debounceMs);

    return () => {
      clearTimeout(timer);
      abortRef.current?.abort();
    };
  }, [query, debounceMs]);

  return { suggestions, topTags, loading };
}
```

- [ ] **Step 2: Create the TagAutocomplete component**

```tsx
// frontend/components/TagAutocomplete.tsx
'use client';

import { useState, useCallback, useRef, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { useTagSuggestions } from '@/hooks/useTagSuggestions';

interface TagItem {
  tag_name: string;
  tag_type?: string;
}

interface TagAutocompleteProps {
  tags: TagItem[];
  onChange: (tags: TagItem[]) => void;
  required?: boolean;
  placeholder?: string;
}

export default function TagAutocomplete({ tags, onChange, required = false, placeholder }: TagAutocompleteProps) {
  const tCommon = useTranslations('common');
  const [input, setInput] = useState('');
  const [isFocused, setIsFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { suggestions, topTags, loading } = useTagSuggestions(input);

  const addTag = useCallback((tagName: string) => {
    const trimmed = tagName.trim().toLowerCase();
    if (!trimmed) return;
    if (tags.some(t => t.tag_name === trimmed)) {
      setInput('');
      return;
    }
    onChange([...tags, { tag_name: trimmed, tag_type: 'custom' }]);
    setInput('');
  }, [tags, onChange]);

  const removeTag = useCallback((tagName: string) => {
    onChange(tags.filter(t => t.tag_name !== tagName));
  }, [tags, onChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag(input);
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      removeTag(tags[tags.length - 1].tag_name);
    }
  }, [addTag, input, tags, removeTag]);

  // Filter out already-selected tags from suggestions
  const selectedNames = new Set(tags.map(t => t.tag_name));
  const filteredSuggestions = suggestions.filter(s => !selectedNames.has(s.tag_name));
  const filteredTopTags = topTags.filter(s => !selectedNames.has(s.tag_name));

  const showSuggestions = isFocused && (filteredSuggestions.length > 0 || (input.trim() && !filteredSuggestions.some(s => s.tag_name === input.trim().toLowerCase())));
  const showTopTags = isFocused && !input.trim() && filteredTopTags.length > 0;

  return (
    <div className="space-y-2 relative">
      {/* Selected tags */}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tags.map(tag => (
            <span
              key={tag.tag_name}
              className="inline-flex items-center gap-1 px-3 py-1.5 text-sm rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20 min-h-[36px]"
            >
              {tag.tag_name}
              <button
                type="button"
                onClick={() => removeTag(tag.tag_name)}
                className="ml-0.5 text-amber-400/60 hover:text-amber-400 min-w-[20px] min-h-[20px] flex items-center justify-center"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Suggestion chips (top tags) — shown above input when focused and no query */}
      {showTopTags && (
        <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-1">
          {filteredTopTags.slice(0, 8).map(tag => (
            <button
              key={tag.tag_name}
              type="button"
              onClick={() => addTag(tag.tag_name)}
              className="flex-shrink-0 px-3 py-1.5 text-sm rounded-full bg-vault-800 border border-white/[0.06] text-text-secondary hover:border-amber-500/20 hover:text-amber-400 transition-colors min-h-[36px]"
            >
              {tag.tag_name}
              <span className="ml-1 text-xs text-text-muted/50">{tag.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => setIsFocused(true)}
          onBlur={() => {
            // Delay to allow clicking suggestions
            setTimeout(() => setIsFocused(false), 200);
          }}
          placeholder={placeholder || 'Add tag...'}
          className="flex-1 px-4 py-3 rounded-xl border border-white/[0.08] bg-vault-800/50 text-text-primary placeholder-text-muted/50 focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all min-h-[44px]"
        />
        <button
          type="button"
          onClick={() => addTag(input)}
          disabled={!input.trim()}
          className="px-4 py-3 rounded-xl bg-amber-500 text-vault-1000 hover:bg-amber-600 disabled:opacity-50 min-h-[44px] font-medium"
        >
          +
        </button>
      </div>

      {/* Suggestion dropdown — positioned above input on mobile */}
      {showSuggestions && (
        <div className="absolute bottom-full mb-1 left-0 right-0 bg-vault-900 border border-white/[0.08] rounded-xl shadow-card overflow-hidden z-10 max-h-48 overflow-y-auto">
          {filteredSuggestions.map(tag => (
            <button
              key={tag.tag_name}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => addTag(tag.tag_name)}
              className="w-full flex items-center justify-between px-4 py-3 text-sm text-text-secondary hover:bg-white/[0.04] hover:text-text-primary transition-colors min-h-[44px]"
            >
              <span>{tag.tag_name}</span>
              <span className="text-xs text-text-muted/50">{tag.count} uses</span>
            </button>
          ))}
          {input.trim() && !filteredSuggestions.some(s => s.tag_name === input.trim().toLowerCase()) && (
            <button
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => addTag(input)}
              className="w-full flex items-center gap-2 px-4 py-3 text-sm text-amber-400 hover:bg-amber-500/5 transition-colors min-h-[44px]"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              <span>Create &ldquo;{input.trim()}&rdquo;</span>
            </button>
          )}
        </div>
      )}

      {required && tags.length === 0 && (
        <p className="text-sm text-red-400">At least one tag is required</p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Update TagSelector to use TagAutocomplete on mobile**

Replace the entire content of `frontend/components/TagSelector.tsx` with:

```tsx
'use client';

import { useState, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { useIsMobile } from '@/hooks/useIsMobile';
import TagAutocomplete from '@/components/TagAutocomplete';

interface TagItem {
  tag_name: string;
  tag_type?: string;
}

interface TagSelectorProps {
  tags: TagItem[];
  onChange: (tags: TagItem[]) => void;
  required?: boolean;
  placeholder?: string;
}

export default function TagSelector(props: TagSelectorProps) {
  const isMobile = useIsMobile();

  // On mobile, use the autocomplete version
  if (isMobile) {
    return <TagAutocomplete {...props} />;
  }

  // Desktop: original inline tag input
  return <TagSelectorDesktop {...props} />;
}

function TagSelectorDesktop({ tags, onChange, required = false, placeholder }: TagSelectorProps) {
  const tCommon = useTranslations('common');
  const [input, setInput] = useState('');

  const addTag = useCallback(() => {
    const trimmed = input.trim().toLowerCase();
    if (!trimmed) return;
    if (tags.some(t => t.tag_name === trimmed)) {
      setInput('');
      return;
    }
    onChange([...tags, { tag_name: trimmed, tag_type: 'custom' }]);
    setInput('');
  }, [input, tags, onChange]);

  const removeTag = useCallback((tagName: string) => {
    onChange(tags.filter(t => t.tag_name !== tagName));
  }, [tags, onChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addTag();
    }
    if (e.key === 'Backspace' && !input && tags.length > 0) {
      removeTag(tags[tags.length - 1].tag_name);
    }
  }, [addTag, input, tags, removeTag]);

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2 min-h-[32px]">
        {tags.map(tag => (
          <span
            key={tag.tag_name}
            className="inline-flex items-center gap-1 px-2 py-1 text-sm rounded-full bg-amber-100 dark:bg-amber-900 text-amber-800 dark:text-amber-200"
          >
            {tag.tag_name}
            <button
              type="button"
              onClick={() => removeTag(tag.tag_name)}
              className="ml-1 text-amber-600 dark:text-amber-400 hover:text-amber-800 dark:hover:text-amber-200"
            >
              &times;
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || 'Add tag...'}
          className="flex-1 px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-amber-500 focus:border-transparent"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={!input.trim()}
          className="px-3 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          +
        </button>
      </div>
      {required && tags.length === 0 && (
        <p className="text-sm text-red-500">At least one tag is required</p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Verify compilation**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/useTagSuggestions.ts frontend/components/TagAutocomplete.tsx frontend/components/TagSelector.tsx
git commit -m "feat(mobile): add TagAutocomplete with fuzzy search and suggestion chips"
```

---

### Task 12: Search page mobile optimization

**Files:**
- Modify: `frontend/app/[locale]/search/page.tsx`

- [ ] **Step 1: Add imports**

At the top of `frontend/app/[locale]/search/page.tsx`, add:

```typescript
import { useIsMobile } from '@/hooks/useIsMobile';
import PullToRefresh from '@/components/mobile/PullToRefresh';
```

- [ ] **Step 2: Add isMobile inside SearchPage**

Inside `SearchPage()`, after the existing state declarations (around line 376), add:

```typescript
const isMobile = useIsMobile();
```

- [ ] **Step 3: Make search bar sticky on mobile**

Find the search form wrapper (line ~510):

```tsx
<div className="p-4 sm:p-6 max-w-5xl mx-auto pb-20">
```

Replace with:

```tsx
<div className="p-4 sm:p-6 max-w-5xl mx-auto pb-24 md:pb-20">
```

Then find the search form `<form>` block and its surrounding header. Wrap them in a sticky container for mobile:

Find: `{/* Header */}` (line ~511)

Replace the header + form + voice recorder section (lines 511-571) with:

```tsx
{/* Sticky search area on mobile */}
<div className={`${isMobile ? 'sticky top-14 z-30 bg-vault-1000/95 backdrop-blur-xl -mx-4 px-4 pt-4 pb-2 border-b border-white/[0.04]' : ''}`}>
  {/* Header */}
  <div className="flex items-center gap-4 mb-4 md:mb-6">
    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400/20 to-amber-600/5 border border-amber-400/20 flex items-center justify-center flex-shrink-0">
      <span className="text-amber-400 text-lg">⊛</span>
    </div>
    <div className="flex-1 min-w-0">
      <h1 className="text-lg md:text-xl font-bold text-text-primary tracking-tight font-display">{t('title')}</h1>
    </div>
    {stream.hasConfidential && canSeeConfidential && (
      <div className="ml-auto bg-vault-1000 text-amber-400 px-2 md:px-3 py-1.5 rounded-lg text-xs font-semibold tracking-wide border border-amber-400/20 flex-shrink-0">🔒 {t('confidentialNotice')}</div>
    )}
  </div>

  {/* Search form */}
  <form onSubmit={handleSubmit} className="mb-2">
    <div className="flex items-center bg-vault-800/50 border border-white/[0.08] rounded-xl px-4 shadow-card focus-within:border-amber-400/30 focus-within:ring-2 focus-within:ring-amber-500/10 transition-all">
      <span className="text-lg text-text-muted/40 mr-2 flex-shrink-0">⌕</span>
      <input ref={inputRef} type="text" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); runSearchWithQuery(query); } }} placeholder={t('placeholder')} disabled={isSearching} autoFocus className="flex-1 border-none outline-none bg-transparent text-sm text-text-primary py-3.5 placeholder:text-text-muted/40 min-h-[44px]" />
      <button
        type="button"
        onClick={() => setShowVoiceSearch((v) => !v)}
        className={`flex-shrink-0 p-2 rounded-lg mr-1 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center ${
          showVoiceSearch
            ? 'bg-amber-500/20 text-amber-400'
            : 'text-text-muted/40 hover:text-amber-400 hover:bg-amber-500/10'
        }`}
        title={t('voiceSearch')}
      >
        <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z" />
          <path d="M17 11c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" />
        </svg>
      </button>
      {isSearching ? (
        <button type="button" onClick={() => abortRef.current?.abort()} className="bg-red-500/20 text-red-400 border border-red-500/20 rounded-lg px-3.5 py-2 text-xs font-bold cursor-pointer flex-shrink-0 hover:bg-red-500/30 transition-colors min-h-[44px]">■ {t('stop')}</button>
      ) : (
        <button type="submit" disabled={!query.trim()} className="bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 border-none rounded-lg px-4 py-2 text-xs font-bold cursor-pointer flex-shrink-0 disabled:opacity-40 hover:from-amber-400 hover:to-amber-500 transition-all shadow-lg shadow-amber-500/20 min-h-[44px]">
          {t('searchButton')} →
        </button>
      )}
    </div>
    {stream.intent && (
      <IntentBadge intent={stream.intent} confidenceLabel={t('confidence')} intentLabel={t((`intent.${INTENT_TYPES.includes(stream.intent.type) ? stream.intent.type : 'unknown'}`) as Parameters<typeof t>[0])} />
    )}
  </form>

  {showVoiceSearch && (
    <div className="mb-2 p-3 bg-vault-800/50 border border-white/[0.06] rounded-xl">
      <VoiceRecorder
        mode="search"
        onTranscript={(text) => {
          if (text.trim()) {
            setQuery(text);
            setShowVoiceSearch(false);
            runSearchWithQuery(text);
          }
        }}
        onCancel={() => setShowVoiceSearch(false)}
      />
    </div>
  )}
</div>
```

- [ ] **Step 4: Make TypeFilterChips horizontally scrollable on mobile**

Find the `TypeFilterChips` function definition (line ~306). Replace the outer `<div>` wrapper:

Find: `<div className="flex flex-wrap gap-2 mb-4">`
Replace: `<div className="flex gap-2 mb-4 overflow-x-auto scrollbar-hide md:flex-wrap">`

Also add `flex-shrink-0` to each filter button. In the same function, find:

`className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-all border`

Replace with:

`className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-sm font-medium transition-all border flex-shrink-0 min-h-[44px] md:min-h-0`

- [ ] **Step 5: Increase result card padding on mobile**

In the `ResultCard` function, find the outer div (line ~213):

`className={`bg-vault-900/60 border border-white/[0.06] border-l-4 rounded-lg p-4 mb-2`

Replace with:

`className={`bg-vault-900/60 border border-white/[0.06] border-l-4 rounded-lg p-4 md:p-4 mb-2`

This keeps padding the same but we can add `p-5` for mobile in a follow-up if needed.

- [ ] **Step 6: Verify compilation**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 7: Commit**

```bash
git add frontend/app/[locale]/search/page.tsx
git commit -m "feat(mobile): search page — sticky search bar, scrollable filters, touch targets"
```

---

### Task 13: Documents page mobile optimization

**Files:**
- Modify: `frontend/app/[locale]/documents/page.tsx`

- [ ] **Step 1: Add imports at top**

```typescript
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileSheet from '@/components/mobile/MobileSheet';
import MobileBottomSheet from '@/components/mobile/MobileBottomSheet';
import FAB from '@/components/mobile/FAB';
import PullToRefresh from '@/components/mobile/PullToRefresh';
```

- [ ] **Step 2: Add state**

Inside `DocumentsPage()`, after existing state declarations, add:

```typescript
const isMobile = useIsMobile();
const [showFilterSheet, setShowFilterSheet] = useState(false);
const [showUploadSheet, setShowUploadSheet] = useState(false);
```

- [ ] **Step 3: Add FAB and filter button**

Find the page's main wrapper `<div>`. After the document list/grid closing tag and before the pagination, add:

```tsx
{/* Mobile FAB for upload */}
{isMobile && (
  <FAB onClick={() => setShowUploadSheet(true)} label={t('upload')} />
)}
```

- [ ] **Step 4: Add mobile filter bottom sheet**

For the filters/sort controls on mobile, add after the FAB:

```tsx
{/* Mobile filter sheet */}
<MobileBottomSheet
  open={showFilterSheet}
  onClose={() => setShowFilterSheet(false)}
  title="Filters"
  heightPercent={45}
>
  <div className="space-y-4">
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-2">Bucket</label>
      <div className="flex gap-2">
        {(['all', 'public', 'confidential'] as const).map(b => (
          <button
            key={b}
            onClick={() => { setBucketFilter(b); setShowFilterSheet(false); }}
            className={`flex-1 py-3 rounded-xl text-sm font-medium transition-all min-h-[44px] ${
              bucketFilter === b
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : 'bg-vault-800 text-text-secondary border border-white/[0.06]'
            }`}
          >
            {b}
          </button>
        ))}
      </div>
    </div>
    <div>
      <label className="block text-sm font-medium text-text-secondary mb-2">Sort by</label>
      <div className="grid grid-cols-2 gap-2">
        {(['created_at', 'original_filename', 'file_size', 'status'] as const).map(s => (
          <button
            key={s}
            onClick={() => { setSortBy(s); setShowFilterSheet(false); }}
            className={`py-3 rounded-xl text-sm font-medium transition-all min-h-[44px] ${
              sortBy === s
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                : 'bg-vault-800 text-text-secondary border border-white/[0.06]'
            }`}
          >
            {s.replace('_', ' ')}
          </button>
        ))}
      </div>
    </div>
  </div>
</MobileBottomSheet>
```

- [ ] **Step 5: Add mobile filter icon button in header**

In the documents page header area, add a filter button visible only on mobile. Find the header section and add next to the existing controls:

```tsx
{isMobile && (
  <button
    onClick={() => setShowFilterSheet(true)}
    className="p-2 rounded-lg bg-vault-800 border border-white/[0.06] text-text-muted hover:text-amber-400 transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center md:hidden"
    aria-label="Filters"
  >
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
    </svg>
  </button>
)}
```

- [ ] **Step 6: Add bottom padding for mobile nav bar**

Find the outermost container div and ensure it has `pb-24 md:pb-8` so content doesn't hide behind the bottom bar.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/[locale]/documents/page.tsx
git commit -m "feat(mobile): documents page — FAB upload, filter bottom sheet, touch targets"
```

---

### Task 14: Chat page mobile optimization

**Files:**
- Modify: `frontend/app/[locale]/chat/page.tsx`

- [ ] **Step 1: Add imports**

At the top:

```typescript
import { useIsMobile } from '@/hooks/useIsMobile';
import MobileBottomSheet from '@/components/mobile/MobileBottomSheet';
```

- [ ] **Step 2: Add state and default sidebar to false on mobile**

Inside `ChatPage()`, after existing state declarations, add:

```typescript
const isMobile = useIsMobile();
const [sessionSheetOpen, setSessionSheetOpen] = useState(false);
```

And change the sidebar default. Find:

```typescript
const [sidebarOpen, setSidebarOpen] = useState(true);
```

Replace with:

```typescript
const [sidebarOpen, setSidebarOpen] = useState(false);
```

Then add an effect to open sidebar on desktop:

```typescript
useEffect(() => {
  if (!isMobile) setSidebarOpen(true);
}, [isMobile]);
```

- [ ] **Step 3: Fix the chat container height for dvh**

Find:

```tsx
<div className="flex h-[calc(100vh-8rem)] bg-vault-1000">
```

Replace with:

```tsx
<div className="flex bg-vault-1000" style={{ height: 'calc(100dvh - 3.5rem)', minHeight: 'calc(100vh - 8rem)' }}>
```

- [ ] **Step 4: Add mobile header with session switcher and new chat**

Find the start of the main chat column (the `<div className="flex-1 flex flex-col">` after the sidebar). Add a mobile header at the top of it:

```tsx
{/* Mobile chat header */}
{isMobile && (
  <div className="flex items-center justify-between px-4 py-2 border-b border-white/[0.06] bg-vault-950/80 backdrop-blur-sm md:hidden">
    <button
      onClick={() => setSessionSheetOpen(true)}
      className="flex items-center gap-2 text-sm text-text-secondary min-h-[44px]"
    >
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
      </svg>
      <span className="truncate max-w-[200px]">{currentSession?.title || t('new_chat')}</span>
    </button>
    <button
      onClick={createSession}
      className="p-2 rounded-lg bg-amber-500/10 text-amber-400 border border-amber-500/20 min-w-[44px] min-h-[44px] flex items-center justify-center"
      aria-label={t('new_chat')}
    >
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
      </svg>
    </button>
  </div>
)}
```

- [ ] **Step 5: Add safe-area to chat input area**

Find the chat input container at the bottom. It should be a `<div>` wrapping the textarea and send button. Add `pb-safe` class and ensure min touch targets:

Find the input wrapper div with `<div className="max-w-3xl mx-auto flex gap-2">` and its parent. Update the parent to include safe-area:

```tsx
<div className="border-t border-white/[0.06] bg-vault-950/80 backdrop-blur-sm p-3 md:p-4 pb-safe">
```

Also ensure the send button has `min-w-[44px] min-h-[44px]`.

- [ ] **Step 6: Add session switcher bottom sheet**

After the chat container's closing `</div>`, add:

```tsx
{/* Mobile session switcher */}
<MobileBottomSheet
  open={sessionSheetOpen}
  onClose={() => setSessionSheetOpen(false)}
  title={t('sessions') || 'Sessions'}
  heightPercent={60}
>
  <button
    onClick={() => { createSession(); setSessionSheetOpen(false); }}
    className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 rounded-xl font-medium text-sm mb-3 min-h-[44px]"
  >
    + {t('new_chat')}
  </button>
  <div className="space-y-1">
    {sessions.map(session => (
      <button
        key={session.id}
        onClick={() => { setCurrentSession(session); setSessionSheetOpen(false); }}
        className={`w-full flex items-center justify-between p-3 rounded-xl text-left transition-all min-h-[44px] ${
          currentSession?.id === session.id
            ? 'bg-amber-500/10 text-amber-400'
            : 'text-text-secondary hover:bg-white/[0.04]'
        }`}
      >
        <span className="truncate text-sm">{session.title}</span>
        <button
          onClick={(e) => deleteSession(session.id, e)}
          className="ml-2 text-text-muted hover:text-red-400 min-w-[44px] min-h-[44px] flex items-center justify-center flex-shrink-0"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </button>
    ))}
  </div>
</MobileBottomSheet>
```

- [ ] **Step 7: Verify compilation**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -30`

- [ ] **Step 8: Commit**

```bash
git add frontend/app/[locale]/chat/page.tsx
git commit -m "feat(mobile): chat page — session switcher sheet, safe-area input, mobile header"
```

---

### Task 15: Final integration — mobile chat message width

**Files:**
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Update the mobile chat message width**

Already done in Task 2 (we set `.chat-message` to `max-width: 95%` on mobile). Verify it's in globals.css.

- [ ] **Step 2: Full compilation check**

Run: `cd frontend && npx tsc --noEmit 2>&1 | head -50`

Fix any remaining type errors across all files.

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(mobile): resolve compilation issues from mobile optimization"
```

---

## Summary

| Task | Component | Files |
|------|-----------|-------|
| 1 | useIsMobile hook | 1 new |
| 2 | Foundation (dvh, safe-area, viewport) | 5 modified |
| 3 | MobileSheet | 1 new |
| 4 | MobileBottomSheet | 1 new |
| 5 | FAB | 1 new |
| 6 | useScrollDirection hook | 1 new |
| 7 | Bottom tab bar redesign | 1 modified |
| 8 | SwipeableRow + PullToRefresh | 2 new |
| 9 | Notes page mobile | 1 modified |
| 10 | Tag suggestions API | 1 new, 1 modified |
| 11 | TagAutocomplete | 2 new, 1 modified |
| 12 | Search page mobile | 1 modified |
| 13 | Documents page mobile | 1 modified |
| 14 | Chat page mobile | 1 modified |
| 15 | Final integration | verify |

**Total: 10 new files, 10 modified files, 15 tasks**
