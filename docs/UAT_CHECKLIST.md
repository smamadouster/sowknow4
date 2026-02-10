# SOWKNOW User Acceptance Testing (UAT) Checklist

## UAT Overview

**System**: SOWKNOW Multi-Generational Legacy Knowledge System
**Version**: 3.0.0 (Phase 3 Complete)
**Domain**: https://sowknow.gollamtech.com
**Test Period**: [Start Date] to [End Date]

---

## Test Scenarios

### 1. Authentication & Onboarding

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Register new user | 1. Go to home page<br>2. Click Sign Up<br>3. Enter valid email/password<br>4. Submit | Account created, logged in automatically | ☐ | |
| Login with valid credentials | 1. Go to login page<br>2. Enter registered email/password<br>3. Submit | Redirected to dashboard | ☐ | |
| Login with invalid credentials | 1. Enter wrong password<br>2. Submit | Error message shown | ☐ | |
| Password reset | 1. Click "Forgot password"<br>2. Enter email<br>3. Check email for reset link | Reset email received | ☐ | |
| Logout | 1. Click logout<br>2. Try to access protected page | Redirected to login | ☐ | |

---

### 2. Document Upload & Processing

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Upload PDF document | 1. Click Upload<br>2. Select PDF file<br>3. Choose bucket<br>4. Submit | Upload starts, shows progress | ☐ | |
| Upload DOCX document | 1. Click Upload<br>2. Select DOCX file<br>3. Submit | Document processed successfully | ☐ | |
| Upload image (OCR) | 1. Upload JPG/PNG<br>2. Wait for processing | Text extracted via OCR | ☐ | |
| Upload large file (>50MB) | 1. Upload large file | File accepted or clear size limit shown | ☐ | |
| Upload confidential document | 1. Select "Confidential" bucket<br>2. Upload | Marked as confidential | ☐ | |
| View processing status | 1. Go to Documents<br>2. Check status icons | Shows processing/complete/failed | ☐ | |
| Delete document | 1. Select document<br>2. Click delete<br>3. Confirm | Document removed | ☐ | |

---

### 3. Search Functionality

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Basic keyword search | 1. Enter keyword<br>2. Press Enter | Results shown with relevance | ☐ | |
| Semantic search | 1. Enter natural language query<br>2. Search | Contextually relevant results | ☐ | |
| Search with filters | 1. Enter query<br>2. Apply filters (date, type) | Filtered results | ☐ | |
| Search results pagination | 1. Search for common term<br>2. Navigate pages | Pagination works | ☐ | |
| Open search result | 1. Click on result | Document/content displayed | ☐ | |
| No results handling | 1. Search for non-existent term | "No results" message shown | ☐ | |

---

### 4. Knowledge Graph

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| View knowledge graph | 1. Go to Knowledge Graph<br>2. Wait for loading | Graph displayed with nodes/edges | ☐ | |
| Filter by entity type | 1. Select entity type<br>2. View graph | Filtered graph shown | ☐ | |
| Click entity node | 1. Click on node<br>2. View details | Entity details panel shown | ☐ | |
| Explore connections | 1. Click entity<br>2. View neighbors | Connected entities shown | ☐ | |
| Find entity path | 1. Use path finder<br>2. Enter two entities | Path displayed | ☐ | |
| View timeline | 1. Switch to Timeline tab<br>2. Select date range | Events shown chronologically | ☐ | |
| Entity list | 1. View entity list | All entities with metadata | ☐ | |

---

### 5. Smart Collections

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Create collection | 1. Go to Collections<br>2. Click New<br>3. Enter name and query<br>4. Submit | Collection created with AI summary | ☐ | |
| View collections | 1. Go to Collections | All collections shown | ☐ | |
| Open collection | 1. Click on collection | Documents and summary shown | ☐ | |
| Chat with collection | 1. Open collection chat<br>2. Ask question<br>3. View response | Contextual answer from collection docs | ☐ | |
| Pin collection | 1. Click pin icon | Collection pinned to top | ☐ | |
| Delete collection | 1. Select collection<br>2. Delete | Collection removed | ☐ | |

---

### 6. Smart Folders

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Generate content | 1. Go to Smart Folders<br>2. Click Generate<br>3. Enter topic/style<br>4. Submit | AI-generated content | ☐ | |
| Choose writing style | 1. Select style (professional, etc.)<br>2. Generate | Content matches style | ☐ | |
| Generate PDF report | 1. Click Generate Report<br>2. Select format<br>3. Submit | PDF downloaded | ☐ | |
| View generated content | 1. Open generated item | Content displayed with sources | ☐ | |

---

### 7. Multi-Agent Search

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Full multi-agent search | 1. Enter complex query<br>2. Submit<br>3. Wait for agents | Comprehensive answer with sources | ☐ | |
| Clarification request | 1. Enter ambiguous query<br>2. Submit | Clarification questions shown | ☐ | |
| View agent results | 1. Check research summary | Agent results displayed | ☐ | |
| Verify information | 1. Check verification summary | Verification status shown | ☐ | |
| Follow-up suggestions | 1. View answer<br>2. Check follow-up questions | Relevant suggestions shown | ☐ | |

---

### 8. Privacy & Security

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Confidential bucket upload | 1. Upload to Confidential<br>2. Check processing | No cloud API usage | ☐ | |
| Access control | 1. Regular user tries admin endpoint | Access denied | ☐ | |
| Session timeout | 1. Login<br>2. Wait for timeout<br>3. Try action | Prompted to re-login | ☐ | |
| Secure cookie handling | 1. Check browser dev tools | Cookies marked httpOnly, Secure | ☐ | |

---

### 9. Performance

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Search response time | 1. Run search query | < 3 seconds for Gemini | ☐ | |
| Graph load time | 1. Load knowledge graph | < 5 seconds | ☐ | |
| Large file upload | 1. Upload 50MB file | Progress shown, completes | ☐ | |
| Concurrent users | 1. Multiple users search simultaneously | All requests succeed | ☐ | |

---

### 10. Mobile Responsiveness

| Scenario | Steps | Expected Result | Status | Notes |
|----------|-------|----------------|--------|-------|
| Mobile search | 1. Open on mobile<br>2. Search | Interface adapts, results shown | ☐ | |
| Mobile navigation | 1. Navigate pages | Menu works, pages accessible | ☐ | |
| Touch interactions | 1. Tap buttons, swipe | Touch targets adequate | ☐ | |

---

## Bug Report Template

```
Bug Title: [Brief description]

Severity: ☐ Critical ☐ High ☐ Medium ☐ Low

Description:
[What happened]

Steps to Reproduce:
1.
2.
3.

Expected Result:
[What should have happened]

Actual Result:
[What actually happened]

Environment:
- Browser: [Chrome/Firefox/Safari + version]
- Device: [Desktop/Mobile/Tablet]
- Screen Size: [resolution]

Screenshots:
[Attach if applicable]

Additional Information:
[Any other relevant details]
```

---

## Feature Request Template

```
Feature Title: [Brief description]

Category: ☐ Search ☐ Knowledge Graph ☐ Collections ☐ Other

Description:
[What feature would you like]

Use Case:
[When and how would you use this feature]

Priority: ☐ High ☐ Medium ☐ Low

Additional Information:
[Any other details]
```

---

## Sign-off Criteria

UAT is complete when:
- ☐ All critical scenarios pass
- ☐ 90%+ of non-critical scenarios pass
- ☐ No critical bugs remain
- ☐ All high-priority bugs are documented
- ☐ Performance criteria met
- ☐ Security requirements satisfied

---

## UAT Sign-off

**Test Lead**: _________________ **Date**: _______

**Acceptance**: ☐ Approved ☐ Approved with Minor Issues ☐ Not Approved

**Comments**:
_________________________________________________________
_________________________________________________________
_________________________________________________________

**Stakeholder Sign-off**: _________________ **Date**: _______

---

## Additional Notes

Use this section to record any issues, workarounds, or observations during testing:

| Date | Issue | Impact | Workaround |
|------|-------|--------|------------|
| | | | |

---

**Questions? Contact**: admin@gollamtech.com
