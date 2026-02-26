# SOWKNOW — Accessibility Documentation

WCAG 2.1 AA conformance target.  All interactive components have been audited against the
criteria below.  Run `npm run build` and use the axe DevTools browser extension or
Lighthouse accessibility audit to verify scores after changes.

---

## 1. Semantic Structure

| Element | Implementation |
|---------|---------------|
| Skip link | `<a href="#main-content">` at top of `layout.tsx`; visually hidden until focused (`.sr-only focus:not-sr-only`) |
| Landmark roles | `<nav aria-label>`, `<main id="main-content">` in every locale layout |
| Heading hierarchy | h1 on every page; h2 for section headers; no skipped levels |
| Language | `<html lang={locale}>` set per locale in `layout.tsx` |

---

## 2. Navigation (`components/Navigation.tsx`)

### Desktop navigation
- `<nav aria-label={t('main_navigation')}>` wraps all nav links
- Active link: `aria-current="page"` on the matching `<Link>`
- Collapse toggle button: `aria-expanded={!isCollapsed}` + `aria-label={t('toggle_navigation')}`
- Decorative icons: `aria-hidden="true"` on all SVG icon elements

### Mobile drawer
- Hamburger button: `aria-expanded={isMobileOpen}` + `aria-controls="mobile-menu"` + `aria-label`
- Drawer: `role="dialog"` + `aria-modal="true"` + `aria-label` + `aria-hidden={!isMobileOpen}`
- **Focus trap**: Tab / Shift-Tab cycle within the open drawer via `keydown` event listener
- **Escape key**: closes drawer and returns focus to trigger button
- **Body scroll lock**: `document.body.style.overflow = 'hidden'` while drawer is open
- **Route change**: drawer auto-closes on `pathname` change via `useEffect`

### Logout confirmation modal
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby="logout-dialog-title"`
- Focus moves to first button on open
- Escape key dismisses modal

---

## 3. Forms

All auth forms (`login`, `register`, `forgot-password`, `verify-email`) follow this pattern:

| Attribute | Usage |
|-----------|-------|
| `<label htmlFor>` / `<input id>` | Every label–input pair is explicitly associated |
| `aria-describedby` | Points to the per-field error message `<div>` |
| `role="alert"` | Applied to error message containers for immediate announcement |
| `aria-busy={loading}` | On the submit `<button>` during async operations |
| `autoComplete` | `username`, `current-password`, `new-password`, `email` as appropriate |

---

## 4. Chat Interface (`app/[locale]/chat/page.tsx`)

| Feature | Implementation |
|---------|---------------|
| Messages region | `role="log"` + `aria-live="polite"` + `aria-atomic="false"` + `aria-label` |
| Streaming indicator | `role="status"` + `aria-live="polite"` |
| Session list | `role="list"` with `role="listitem"` per session |
| Session buttons | `role="button"` + `tabIndex={0}` + `onKeyDown` (Enter / Space) |
| Delete buttons | `aria-label` includes the session title |
| Delete button visibility | `focus:opacity-100` ensures keyboard users can always see it |

---

## 5. Keyboard Navigation

| Key | Behaviour |
|-----|-----------|
| `Tab` / `Shift-Tab` | Full navigation through all interactive elements |
| `Enter` / `Space` | Activates buttons and custom interactive divs |
| `Escape` | Closes mobile drawer, logout modal, and any open popover |
| Arrow keys | Not required at current scope; reserved for future data-grid or combobox |

Focus indicators use Tailwind's `focus:ring-2 focus:ring-blue-500` (or colour-appropriate variant)
applied to every interactive element.  The global CSS adds `focus-visible` outlines that are
suppressed only for mouse interaction.

---

## 6. Colour & Contrast

- Primary CTA buttons use `bg-yellow-400` (`#FFEB3B`) on dark text — contrast ratio ≥ 4.5:1
- Error states use `text-red-700` on `bg-red-50` — contrast ratio ≥ 4.5:1
- Disabled elements use `opacity-50` — users are informed via `aria-disabled` where relevant
- No information is conveyed by colour alone; icons and text labels accompany all colour coding

---

## 7. Screen Reader Announcements

Dynamic content regions that update without a full page reload use `aria-live`:

| Region | Value | Component |
|--------|-------|-----------|
| Chat message log | `polite` | `chat/page.tsx` |
| Streaming indicator | `polite` | `chat/page.tsx` |
| Form errors | Implicit via `role="alert"` (= `aria-live="assertive"`) | All auth pages |

---

## 8. Testing Procedures

### Automated
1. `npm run build` — must exit 0 with 0 TypeScript errors
2. Lighthouse accessibility audit (Chrome DevTools) — target score ≥ 90
3. axe DevTools browser extension — 0 critical / serious violations

### Manual keyboard walkthrough (per release)
- [ ] Tab through entire page without mouse; confirm logical focus order
- [ ] Open and close mobile drawer using only keyboard
- [ ] Submit login form with Enter; confirm error announced by screen reader
- [ ] Navigate chat sessions list using Tab + Enter; confirm delete accessible
- [ ] Trigger logout modal via keyboard; confirm Escape dismisses it

### Screen reader testing (recommended)
- macOS: VoiceOver (`Cmd-F5`)
- Windows: NVDA (free) with Firefox
- iOS: VoiceOver
- Android: TalkBack

---

## 9. Known Limitations

| Item | Status |
|------|--------|
| Knowledge Graph SVG canvas | Keyboard navigation not yet implemented for individual nodes (mouse-only) |
| Charts (recharts) | SVG charts lack `<title>` / `<desc>` elements; add for full compliance |
| EntityList pagination | Pagination buttons labelled "Previous" / "Next" — could add page count context |

These are tracked as tech-debt and should be addressed before a production v1.0 release.
