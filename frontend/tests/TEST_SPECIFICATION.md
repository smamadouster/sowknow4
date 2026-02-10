# Frontend Test Specification

## Testing Framework Status: NOT CONFIGURED

The SOWKNOW frontend does **NOT** have a testing framework configured. The `package.json` does not include any testing dependencies (Jest, React Testing Library, Cypress, etc.).

## Required Testing Dependencies

To implement the tests below, the following packages should be added:

```json
{
  "devDependencies": {
    "@testing-library/react": "^14.0.0",
    "@testing-library/jest-dom": "^6.1.0",
    "@testing-library/user-event": "^14.5.0",
    "jest": "^29.7.0",
    "jest-environment-jsdom": "^29.7.0",
    "@types/jest": "^29.5.0",
    "ts-jest": "^29.1.0"
  }
}
```

## Test Scripts to Add

```json
{
  "scripts": {
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage"
  }
}
```

## Critical Component Tests

### 1. Authentication Flow Tests

**File**: `__tests__/authentication.test.tsx`

**Tests to implement**:
- [ ] User can register with valid credentials
- [ ] User cannot register with duplicate email
- [ ] User can login with valid credentials
- [ ] User cannot login with invalid credentials
- [ ] JWT token is stored in httpOnly cookie (not localStorage)
- [ ] Protected routes redirect to login when not authenticated
- [ ] User can logout
- [ ] Auth state persists across page refreshes
- [ ] Expired tokens trigger re-authentication

**Components to test**:
- `/app/layout.tsx` - Auth provider integration
- Any login/register forms
- Protected route wrappers

### 2. RBAC (Role-Based Access Control) Tests

**File**: `__tests__/rbac.test.tsx`

**Tests to implement**:
- [ ] Regular users cannot access confidential documents
- [ ] Admin users can access all document buckets
- [ ] Superusers can access all document buckets
- [ ] Confidential documents are hidden from regular users in search results
- [ ] Confidential collections are not visible to regular users
- [ ] Admin panel is only accessible to admin/superuser roles
- [ ] Client-side RBAC prevents UI rendering of restricted elements
- [ ] API requests include proper role-based headers

**Components to test**:
- Document list components
- Collection components
- Search results components
- Admin panel components

### 3. Language Switching Tests

**File**: `__tests__/language.test.tsx`

**Tests to implement**:
- [ ] Application defaults to French locale
- [ ] Language can be switched to English
- [ ] Language can be switched back to French
- [ ] Language preference persists across page refreshes
- [ ] All UI elements update when language changes
- [ ] Date/number formatting updates with locale
- [ ] Language selector component works correctly
- [ ] Translations are loaded correctly for both locales
- [ ] Missing translations fall back gracefully

**Components to test**:
- `/components/LanguageSelector.tsx`
- `/app/layout.tsx` - NextIntlClientProvider
- All pages with `useTranslations()` hooks

### 4. Knowledge Graph Component Tests

**File**: `__tests__/knowledge-graph.test.tsx`

**Tests to implement**:
- [ ] Graph visualization renders correctly
- [ ] Entity list displays entities
- [ ] Entity detail panel shows information
- [ ] Relationships are displayed on graph
- [ ] Graph filtering works
- [ ] Graph responds to user interactions
- [ ] Empty states display correctly
- [ ] Loading states display during data fetch
- [ ] Error states display on API failures

**Components to test**:
- `/components/knowledge-graph/GraphVisualization.tsx`
- `/components/knowledge-graph/EntityList.tsx`
- `/components/knowledge-graph/EntityDetail.tsx`
- `/app/knowledge-graph/page.tsx`

### 5. Collections Component Tests

**File**: `__tests__/collections.test.tsx`

**Tests to implement**:
- [ ] Collections list displays user's collections
- [ ] User can create new collection
- [ ] User can edit collection name/description
- [ ] User can delete collection
- [ ] Confidential collections are marked appropriately
- [ ] Collection chat interface works
- [ ] Documents can be added to collection
- [ ] Documents can be removed from collection
- [ ] Empty state displays when no collections

**Components to test**:
- `/app/collections/page.tsx`
- `/components/collections/*`

### 6. Smart Folders Component Tests

**File**: `__tests__/smart-folders.test.tsx`

**Tests to implement**:
- [ ] Smart folders list displays
- [ ] User can create smart folder with filters
- [ ] Smart folder auto-updates with matching documents
- [ ] Smart folder can be edited
- [ ] Smart folder can be deleted
- [ ] Filter conditions work correctly
- [ ] Empty state displays correctly

**Components to test**:
- `/app/smart-folders/page.tsx`

### 7. Search Component Tests

**File**: `__tests__/search.test.tsx`

**Tests to implement**:
- [ ] Search input accepts user queries
- [ ] Search results display correctly
- [ ] Search results are ranked by relevance
- [ ] Confidential documents don't appear for regular users
- [ ] Search works across collections
- [ ] Empty query shows appropriate message
- [ ] No results state displays correctly
- [ ] Search debouncing works
- [ ] Search history is maintained

**Components to test**:
- Search bar components
- Search results components
- Filter components

### 8. Chat Interface Tests

**File**: `__tests__/chat.test.tsx`

**Tests to implement**:
- [ ] Chat messages display correctly
- [ ] User can send messages
- [ ] AI responses stream in correctly
- [ ] Markdown rendering works in responses
- [ ] Chat history is maintained
- [ ] New chat session can be started
- [ ] Chat sessions can be switched
- [ ] Context is maintained within session
- [ ] Error states display on failures

**Components to test**:
- Chat interface components
- Message components
- Session management

### 9. File Upload Tests

**File**: `__tests__/upload.test.tsx`

**Tests to implement**:
- [ ] File upload dialog opens
- [ ] Files can be selected
- [ ] Multiple files can be selected
- [ ] File validation works (type, size)
- [ ] Upload progress displays
- [ ] Upload success displays correctly
- [ ] Upload errors display correctly
- [ ] Files can be categorized as public/confidential

**Components to test**:
- Upload components (likely using react-dropzone)

### 10. Error Handling Tests

**File**: `__tests__/errors.test.tsx`

**Tests to implement**:
- [ ] 401 errors redirect to login
- [ ] 403 errors display permission denied
- [ ] 404 errors display not found
- [ ] 500 errors display server error
- [ ] Network errors display connection issue
- [ ] Error messages are bilingual (FR/EN)
- [ ] Error boundaries catch React errors
- [ ] Graceful degradation on API failures

## Integration Tests (E2E)

**Framework needed**: Cypress or Playwright

### Critical User Flows

1. **Registration and Login Flow**
   - User navigates to app
   - User registers account
   - User receives confirmation
   - User can login
   - User accesses dashboard

2. **Document Upload and Search Flow**
   - User uploads document
   - Document is processed
   - User searches for content
   - Results display correctly

3. **Confidential Document Flow**
   - Admin uploads confidential document
   - Regular user cannot see it
   - Admin can search and view it
   - Audit log is created

4. **Knowledge Graph Flow**
   - User uploads documents
   - Entities are extracted
   - Knowledge graph displays
   - User can explore relationships

5. **Multi-language Flow**
   - App loads in French
   - User switches to English
   - All text updates
   - User interacts in English
   - User switches back to French

## Performance Tests

- [ ] Initial page load < 3 seconds
- [ ] Navigation between pages < 500ms
- [ ] Search results display < 2 seconds
- [ ] Large document lists paginate smoothly
- [ ] Knowledge graph renders < 2 seconds
- [ ] Chat messages stream smoothly

## Accessibility Tests

- [ ] All interactive elements are keyboard accessible
- [ ] ARIA labels are present
- [ ] Color contrast meets WCAG standards
- [ ] Screen reader compatibility
- [ ] Focus management works correctly

## Notes

- All tests should support both French and English locales
- Tests should mock API responses to avoid dependencies
- Tests should be deterministic
- Test coverage goal: > 80%

## Current State

**Testing Framework**: NOT INSTALLED
**Tests Written**: 0
**Test Coverage**: 0%

**To enable testing**:
1. Install testing dependencies
2. Configure Jest with Next.js
3. Create test setup files
4. Implement the tests specified above
