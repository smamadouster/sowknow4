/**
 * API client for SOWKNOW backend
 *
 * SECURITY NOTE: Backend uses httpOnly cookies for authentication.
 * Cookies are sent automatically with credentials: 'include'.
 * No JavaScript token access required (prevents XSS attacks).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

interface ApiResponse<T> {
  data?: T;
  error?: string;
  status: number;
}

// --- Bookmark types ---
interface BookmarkTag { id: string; tag_name: string; tag_type: string; }
interface BookmarkItem { id: string; url: string; title: string; description: string | null; favicon_url: string | null; bucket: string; tags: BookmarkTag[]; created_at: string; updated_at: string; }
interface BookmarkListData { bookmarks: BookmarkItem[]; total: number; page: number; page_size: number; }

// --- Note types ---
interface NoteItem { id: string; title: string; content: string | null; bucket: string; tags: BookmarkTag[]; created_at: string; updated_at: string; }
interface NoteListData { notes: NoteItem[]; total: number; page: number; page_size: number; }

// --- Space types ---
interface SpaceTagItem { id: string; tag_name: string; tag_type: string; }
interface SpaceItemData { id: string; space_id: string; item_type: string; document_id: string | null; bookmark_id: string | null; note_id: string | null; added_by: string; added_at: string; note: string | null; is_excluded: boolean; item_title: string | null; item_url: string | null; item_tags: SpaceTagItem[]; }
interface SpaceRuleData { id: string; space_id: string; rule_type: string; rule_value: string; is_active: boolean; match_count: number; created_at: string; }
interface SpaceSummary { id: string; name: string; description: string | null; icon: string | null; bucket: string; is_pinned: boolean; item_count: number; created_at: string; updated_at: string; }
interface SpaceDetailData extends SpaceSummary { items: SpaceItemData[]; rules: SpaceRuleData[]; }
interface SpaceListData { spaces: SpaceSummary[]; total: number; page: number; page_size: number; }

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
    // Note: Backend uses httpOnly cookies for security
    // Cookies are sent automatically with credentials: 'include'
    // No need to read tokens from JavaScript
  }

  /**
   * Read the CSRF double-submit cookie set by the backend on login/refresh.
   * The cookie is non-httpOnly so JS can read it and echo it back in a header.
   */
  private getCsrfToken(): string {
    if (typeof document === 'undefined') return '';
    return (
      document.cookie
        .split('; ')
        .find((row) => row.startsWith('csrf_token='))
        ?.split('=')[1] ?? ''
    );
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    const url = `${this.baseUrl}${endpoint}`;

    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    // Only set Content-Type if not already set (e.g., for FormData)
    // Don't override for FormData/Blob — browser must set multipart boundary
    const body = options.body;
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    if (!headers['Content-Type'] && !isFormData) {
      headers['Content-Type'] = 'application/json';
    }

    // CSRF: echo the double-submit cookie back in a header on unsafe methods
    const unsafeMethods = new Set(['POST', 'PUT', 'DELETE', 'PATCH']);
    if (unsafeMethods.has((options.method ?? 'GET').toUpperCase())) {
      const csrfToken = this.getCsrfToken();
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken;
      }
    }

    // Note: Backend uses httpOnly cookies for authentication
    // Cookies are sent automatically with credentials: 'include'
    // No Authorization header needed

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include', // Include cookies for httpOnly cookie auth
      });

      const status = response.status;

      // Handle 401 unauthorized
      if (status === 401) {
        // Try to refresh token before redirecting
        if (typeof window !== 'undefined' && !window.location.pathname.includes('/login')) {
          try {
            const refreshResponse = await fetch(`${this.baseUrl}/v1/auth/refresh`, {
              method: 'POST',
              credentials: 'include', // Include cookies for refresh
            });
            if (refreshResponse.ok) {
              // Refresh successful, retry original request
              const retryResponse = await fetch(url, {
                ...options,
                headers,
                credentials: 'include',
              });
              const retryStatus = retryResponse.status;
              if (retryStatus >= 200 && retryStatus < 300) {
                const retryData = await retryResponse.json();
                return { status: retryStatus, data: retryData };
              }
            }
          } catch (refreshError) {
            // Refresh failed, redirect to login
          }
          // Extract locale from current path (e.g. /fr/chat → fr)
          const pathLocale = window.location.pathname.split('/')[1];
          const locale = ['fr', 'en'].includes(pathLocale) ? pathLocale : 'fr';
          window.location.href = `/${locale}/login`;
        }
        return { status, error: 'Unauthorized' };
      }

      // Handle empty responses
      const contentType = response.headers.get('content-type');
      if (!contentType || !contentType.includes('application/json')) {
        if (status >= 200 && status < 300) {
          return { status };
        }
        return { status, error: response.statusText };
      }

      const data = await response.json();

      if (status >= 200 && status < 300) {
        return { status, data };
      }

      return { status, error: data.detail || data.message || response.statusText };
    } catch (error) {
      return {
        status: 0,
        error: error instanceof Error ? error.message : 'Network error',
      };
    }
  }

  // Auth endpoints
  async login(email: string, password: string) {
    const formData = new URLSearchParams();
    formData.append('username', email);
    formData.append('password', password);

    return this.request('/v1/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: formData.toString(),
      credentials: 'include',
    });
  }

  async register(email: string, password: string, full_name: string) {
    return this.request('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name }),
    });
  }

  async logout() {
    return this.request('/v1/auth/logout', {
      method: 'POST',
    });
  }

  async getMe() {
    return this.request('/v1/auth/me');
  }

  // Document endpoints
  async uploadDocument(file: File, bucket: string = 'public') {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('bucket', bucket);

    return this.request<{ document_id: string; filename: string; status: string; message: string }>('/v1/documents/upload', {
      method: 'POST',
      headers: {}, // Let browser set Content-Type for FormData
      body: formData,
    });
  }

  async uploadAudioDocument(audioBlob: Blob, bucket: string, transcript: string, documentType: string = 'journal', tags: string = '') {
    const formData = new FormData();
    const type = audioBlob.type || 'audio/webm';
    let ext = 'webm';
    if (type.includes('mp4') || type.includes('m4a')) ext = 'm4a';
    else if (type.includes('ogg')) ext = 'ogg';
    else if (type.includes('wav')) ext = 'wav';
    else if (type.includes('mpeg') || type.includes('mp3')) ext = 'mp3';
    else if (type.includes('aac')) ext = 'aac';
    formData.append('file', audioBlob, `voice-note.${ext}`);
    formData.append('bucket', bucket);
    formData.append('document_type', documentType);
    formData.append('transcript', transcript);
    if (tags) formData.append('tags', tags);

    return this.request<{ document_id: string; filename: string; status: string; message: string }>('/v1/documents/upload', {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  async uploadNoteAudio(noteId: string, audioBlob: Blob, transcript: string) {
    const formData = new FormData();
    const type = audioBlob.type || 'audio/webm';
    let ext = 'webm';
    if (type.includes('mp4') || type.includes('m4a')) ext = 'm4a';
    else if (type.includes('ogg')) ext = 'ogg';
    else if (type.includes('wav')) ext = 'wav';
    else if (type.includes('mpeg') || type.includes('mp3')) ext = 'mp3';
    else if (type.includes('aac')) ext = 'aac';
    formData.append('file', audioBlob, `voice-note.${ext}`);
    if (transcript) formData.append('transcript', transcript);

    return this.request<{ audio_id: string; url: string; transcript: string }>(`/v1/notes/${noteId}/audio`, {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  async createJournalEntry(text: string, title?: string, tags: string[] = []) {
    return this.request<{ document_id: string; filename: string; status: string; message: string }>('/v1/documents/journal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, title, tags }),
    });
  }

  async createJournalEntryFromVoice(audioBlob: Blob, lang?: string) {
    const formData = new FormData();
    const type = audioBlob.type || 'audio/webm';
    let ext = 'webm';
    if (type.includes('mp4') || type.includes('m4a')) ext = 'm4a';
    else if (type.includes('ogg')) ext = 'ogg';
    else if (type.includes('wav')) ext = 'wav';
    else if (type.includes('mpeg') || type.includes('mp3')) ext = 'mp3';
    else if (type.includes('aac')) ext = 'aac';
    formData.append('file', audioBlob, `voice-journal.${ext}`);
    if (lang && lang !== 'auto') {
      formData.append('language', lang);
    }

    return this.request<{ document_id: string; filename: string; status: string; message: string }>('/v1/documents/journal/voice', {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  async transcribeAudio(audioBlob: Blob) {
    const formData = new FormData();
    const type = audioBlob.type || 'audio/webm';
    let ext = 'webm';
    if (type.includes('mp4') || type.includes('m4a')) ext = 'm4a';
    else if (type.includes('ogg')) ext = 'ogg';
    else if (type.includes('wav')) ext = 'wav';
    else if (type.includes('mpeg') || type.includes('mp3')) ext = 'mp3';
    else if (type.includes('aac')) ext = 'aac';
    formData.append('file', audioBlob, `voice.${ext}`);

    return this.request<{ transcript: string }>('/v1/voice/transcribe', {
      method: 'POST',
      headers: {},
      body: formData,
    });
  }

  getAudioStreamUrl(audioId: string): string {
    return `${this.baseUrl}/v1/voice/audio/${audioId}/stream`;
  }

  async getDocuments(page: number = 1, pageSize: number = 50, bucket?: string, search?: string, sortBy?: string, sortDir?: string, documentType?: string, tag?: string) {
    interface DocumentsResponse {
      documents: Array<{
        id: string;
        filename: string;
        original_filename: string;
        bucket: string;
        status: string;
        file_size: number;
        mime_type: string;
        page_count: number;
        created_at: string;
        updated_at: string;
      }>;
      total: number;
      page: number;
      page_size: number;
    }

    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    if (bucket) params.append('bucket', bucket);
    if (search) params.append('search', search);
    if (sortBy) params.append('sort_by', sortBy);
    if (sortDir) params.append('sort_dir', sortDir);
    if (documentType) params.append('document_type', documentType);
    if (tag) params.append('tag', tag);

    return this.request<DocumentsResponse>(`/v1/documents?${params.toString()}`);
  }

  async getDocument(id: string) {
    return this.request(`/v1/documents/${id}`);
  }

  async deleteDocument(id: string) {
    return this.request(`/v1/documents/${id}`, {
      method: 'DELETE',
    });
  }

  async reprocessDocument(id: string, force: boolean = false) {
    return this.request<{ document_id: string; status: string; task_id: string; message: string }>(`/v1/documents/${id}/reprocess`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force }),
    });
  }

  async downloadDocument(id: string) {
    const url = `${this.baseUrl}/v1/documents/${id}/download`;
    window.open(url, '_blank');
  }

  // Search endpoints
  async search(query: string, limit: number = 50, offset: number = 0) {
    return this.request('/v1/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit, offset }),
    });
  }

  async suggest(q: string, limit: number = 5) {
    interface SuggestResponse {
      query: string;
      suggestions: Array<{
        id: string;
        title: string;
        type: 'document' | 'bookmark' | 'note' | 'tag';
        bucket?: string | null;
      }>;
    }
    const params = new URLSearchParams({ q, limit: limit.toString() });
    return this.request<SuggestResponse>(`/v1/search/suggest?${params.toString()}`);
  }

  // Chat endpoints
  async createSession(title: string, documentScope?: string[]) {
    return this.request('/v1/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({
        title,
        document_scope: documentScope,
      }),
    });
  }

  async getSessions(limit: number = 50, offset: number = 0) {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    return this.request(`/v1/chat/sessions?${params.toString()}`);
  }

  async getSession(id: string) {
    return this.request(`/v1/chat/sessions/${id}`);
  }

  async deleteSession(id: string) {
    return this.request(`/v1/chat/sessions/${id}`, {
      method: 'DELETE',
    });
  }

  async getMessages(sessionId: string, limit: number = 100) {
    return this.request(`/v1/chat/sessions/${sessionId}/messages?limit=${limit}`);
  }

  async sendMessageStream(
    sessionId: string,
    content: string,
    onChunk: (chunk: string) => void,
    onComplete: () => void,
    onError: (error: string) => void
  ) {
    const url = `${this.baseUrl}/v1/chat/sessions/${sessionId}/message?stream=true`;

    try {
      const streamHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      const csrfToken = this.getCsrfToken();
      if (csrfToken) {
        streamHeaders['X-CSRF-Token'] = csrfToken;
      }

      const response = await fetch(url, {
        method: 'POST',
        headers: streamHeaders,
        credentials: 'include', // httpOnly cookies sent automatically
        body: JSON.stringify({ content }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error('No reader available');
      }

      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();

        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Process SSE lines
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);

            if (data === '[DONE]') {
              onComplete();
              continue;
            }

            try {
              const parsed = JSON.parse(data);

              if (parsed.type === 'message') {
                onChunk(parsed.content);
              } else if (parsed.type === 'llm_info') {
                // Handle LLM info (model used, etc.)
                console.log('LLM Info:', parsed);
              } else if (parsed.type === 'sources') {
                // Handle sources
                console.log('Sources:', parsed.sources);
              } else if (parsed.type === 'error') {
                onError(parsed.error || 'Unknown error');
              } else if (parsed.type === 'done') {
                onComplete();
              }
            } catch (e) {
              // Skip invalid JSON
              console.error('Error parsing SSE data:', e);
            }
          }
        }
      }

      onComplete();
    } catch (error) {
      onError(error instanceof Error ? error.message : 'Unknown error');
    }
  }

  // Admin endpoints
  async getStats() {
    return this.request('/v1/admin/stats');
  }

  async getQueueStats() {
    return this.request('/v1/admin/queue-stats');
  }

  async getAnomalies() {
    return this.request('/v1/admin/anomalies');
  }

  async getDashboard() {
    return this.request('/v1/admin/dashboard');
  }

  async getUploadsHistory() {
    return this.request<{ history: Array<{ day: string; count: number }> }>('/v1/admin/uploads-history');
  }

  async getArticlesHistory() {
    return this.request<{ history: Array<{ day: string; count: number }> }>('/v1/admin/articles-history');
  }

  async getArticlesStats() {
    return this.request<{ total_articles: number; indexed_articles: number; pending_articles: number; generating_articles: number; error_articles: number }>('/v1/admin/articles-stats');
  }

  async getPipelineStats() {
    return this.request<{
      stages: Array<{
        stage: string;
        pending: number;
        running: number;
        failed: number;
        throughput_per_hour: number;
        throughput_per_10min: number;
        health: 'green' | 'yellow' | 'red';
      }>;
      total_active: number;
      bottleneck_stage: string | null;
      overall_health: 'green' | 'yellow' | 'red';
    }>('/v1/admin/pipeline-stats');
  }

  // Collection endpoints
  async getCollections(page: number = 1, pageSize: number = 20) {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    return this.request(`/v1/collections?${params.toString()}`);
  }

  async createCollection(name: string, query: string) {
    return this.request('/v1/collections', {
      method: 'POST',
      body: JSON.stringify({ name, query }),
    });
  }

  async getCollectionStatus(collectionId: string): Promise<ApiResponse<{
    id: string;
    status: string;
    name: string;
    document_count: number;
    ai_summary: string | null;
    error?: string;
  }>> {
    return this.request(`/v1/collections/${collectionId}/status`);
  }

  async getCollection(id: string) {
    return this.request(`/v1/collections/${id}`);
  }

  async updateCollection(id: string, data: { name?: string; description?: string | null; visibility?: string; is_pinned?: boolean; is_favorite?: boolean }) {
    return this.request(`/v1/collections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteCollection(id: string) {
    return this.request(`/v1/collections/${id}`, {
      method: 'DELETE',
    });
  }

  async generateCollectionReport(
    collectionId: string,
    format: 'short' | 'standard' | 'comprehensive' = 'standard',
    language: 'en' | 'fr' = 'en',
    includeCitations: boolean = true
  ) {
    return this.request('/v1/smart-folders/reports/generate', {
      method: 'POST',
      body: JSON.stringify({
        collection_id: collectionId,
        format,
        language,
        include_citations: includeCitations,
      }),
    });
  }

  // Knowledge Graph endpoints
  async extractEntities(documentId: string) {
    return this.request(`/v1/knowledge-graph/extract/${documentId}`, {
      method: 'POST',
    });
  }

  async getEntities(entityType?: string, page: number = 1, pageSize: number = 50, search?: string) {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
    if (entityType) params.append('entity_type', entityType);
    if (search) params.append('search', search);
    return this.request(`/v1/knowledge-graph/entities?${params.toString()}`);
  }

  async getEntity(entityId: string) {
    return this.request(`/v1/knowledge-graph/entities/${entityId}`);
  }

  async getGraph(entityType?: string, limit: number = 100) {
    const params = new URLSearchParams({
      limit: limit.toString(),
    });
    if (entityType) params.append('entity_type', entityType);
    return this.request(`/v1/knowledge-graph/graph?${params.toString()}`);
  }

  async getEntityConnections(entityName: string) {
    return this.request(`/v1/knowledge-graph/entities/${encodeURIComponent(entityName)}/connections`);
  }

  async getEntityNeighbors(entityId: string, relationType?: string) {
    const params = new URLSearchParams();
    if (relationType) params.append('relation_type', relationType);
    return this.request(`/v1/knowledge-graph/entities/${entityId}/neighbors?${params.toString()}`);
  }

  async getShortestPath(sourceName: string, targetName: string) {
    return this.request(`/v1/knowledge-graph/entities/${encodeURIComponent(sourceName)}/path/${encodeURIComponent(targetName)}`);
  }

  async getTimeline(startDate?: string, endDate?: string) {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    return this.request(`/v1/knowledge-graph/timeline?${params.toString()}`);
  }

  async getEntityTimeline(entityName: string) {
    return this.request(`/v1/knowledge-graph/timeline/${encodeURIComponent(entityName)}`);
  }

  async getTimelineInsights(limit: number = 10) {
    const params = new URLSearchParams({
      limit: limit.toString(),
    });
    return this.request(`/v1/knowledge-graph/insights?${params.toString()}`);
  }

  async getEntityClusters(minSize: number = 2) {
    const params = new URLSearchParams({
      min_size: minSize.toString(),
    });
    return this.request(`/v1/knowledge-graph/clusters?${params.toString()}`);
  }

  async extractEntitiesBatch(documentIds: string[]) {
    return this.request('/v1/knowledge-graph/extract-batch', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds }),
    });
  }

  // --- Bookmarks ---

  async getBookmarks(page: number = 1, pageSize: number = 50, tag?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (tag) params.set('tag', tag);
    return this.request<BookmarkListData>(`/v1/bookmarks?${params}`);
  }

  async createBookmark(url: string, tags: Array<{ tag_name: string; tag_type?: string }>, title?: string, description?: string, bucket: string = 'public') {
    return this.request<BookmarkItem>('/v1/bookmarks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, title, description, bucket, tags }),
    });
  }

  async getBookmark(id: string) {
    return this.request<BookmarkItem>(`/v1/bookmarks/${id}`);
  }

  async updateBookmark(id: string, data: { title?: string; description?: string; tags?: Array<{ tag_name: string; tag_type?: string }> }) {
    return this.request<BookmarkItem>(`/v1/bookmarks/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteBookmark(id: string) {
    return this.request<void>(`/v1/bookmarks/${id}`, { method: 'DELETE' });
  }

  async searchBookmarks(query: string, page: number = 1, pageSize: number = 50) {
    const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize) });
    return this.request<BookmarkListData>(`/v1/bookmarks/search?${params}`);
  }

  // --- Notes ---

  async getNotes(page: number = 1, pageSize: number = 50, tag?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (tag) params.set('tag', tag);
    return this.request<NoteListData>(`/v1/notes?${params}`);
  }

  async createNote(title: string, content?: string, tags: Array<{ tag_name: string; tag_type?: string }> = [], bucket: string = 'public') {
    return this.request<NoteItem>('/v1/notes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content, bucket, tags }),
    });
  }

  async getNote(id: string) {
    return this.request<NoteItem>(`/v1/notes/${id}`);
  }

  async updateNote(id: string, data: { title?: string; content?: string; tags?: Array<{ tag_name: string; tag_type?: string }> }) {
    return this.request<NoteItem>(`/v1/notes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteNote(id: string) {
    return this.request<void>(`/v1/notes/${id}`, { method: 'DELETE' });
  }

  async searchNotes(query: string, page: number = 1, pageSize: number = 50) {
    const params = new URLSearchParams({ q: query, page: String(page), page_size: String(pageSize) });
    return this.request<NoteListData>(`/v1/notes/search?${params}`);
  }

  // --- Spaces ---

  async getSpaces(page: number = 1, pageSize: number = 50, search?: string) {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (search) params.set('search', search);
    return this.request<SpaceListData>(`/v1/spaces?${params}`);
  }

  async createSpace(name: string, description?: string, icon?: string, bucket: string = 'public') {
    return this.request<SpaceSummary>('/v1/spaces', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description, icon, bucket }),
    });
  }

  async getSpace(id: string, itemType?: string) {
    const params = new URLSearchParams();
    if (itemType) params.set('item_type', itemType);
    const qs = params.toString();
    return this.request<SpaceDetailData>(`/v1/spaces/${id}${qs ? `?${qs}` : ''}`);
  }

  async updateSpace(id: string, data: { name?: string; description?: string; icon?: string; is_pinned?: boolean }) {
    return this.request<SpaceSummary>(`/v1/spaces/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteSpace(id: string) {
    return this.request<void>(`/v1/spaces/${id}`, { method: 'DELETE' });
  }

  async addSpaceItem(spaceId: string, itemType: string, itemId: string, note?: string) {
    return this.request<SpaceItemData>(`/v1/spaces/${spaceId}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_type: itemType, item_id: itemId, note }),
    });
  }

  async removeSpaceItem(spaceId: string, itemId: string) {
    return this.request<void>(`/v1/spaces/${spaceId}/items/${itemId}`, { method: 'DELETE' });
  }

  async addSpaceRule(spaceId: string, ruleType: string, ruleValue: string) {
    return this.request<SpaceRuleData>(`/v1/spaces/${spaceId}/rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule_type: ruleType, rule_value: ruleValue }),
    });
  }

  async updateSpaceRule(spaceId: string, ruleId: string, data: { rule_value?: string; is_active?: boolean }) {
    return this.request<SpaceRuleData>(`/v1/spaces/${spaceId}/rules/${ruleId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  }

  async deleteSpaceRule(spaceId: string, ruleId: string) {
    return this.request<void>(`/v1/spaces/${spaceId}/rules/${ruleId}`, { method: 'DELETE' });
  }

  async syncSpace(spaceId: string) {
    return this.request<{ message: string }>(`/v1/spaces/${spaceId}/sync`, { method: 'POST' });
  }

  async searchInSpace(spaceId: string, query: string, itemType?: string) {
    const params = new URLSearchParams({ q: query });
    if (itemType) params.set('item_type', itemType);
    return this.request<{ results: SpaceItemData[]; total: number }>(`/v1/spaces/${spaceId}/search?${params}`);
  }

  // --- Smart Folder v2 ---

  async generateSmartFolder(query: string) {
    return this.request<{ task_id: string; status: string; status_url: string; message: string }>('/v1/smart-folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
  }

  async getSmartFolder(id: string) {
    return this.request<{
      smart_folder: {
        id: string;
        user_id: string;
        name: string;
        query_text: string;
        entity_id: string | null;
        relationship_type: string | null;
        status: string;
        error_message: string | null;
        created_at: string;
        updated_at: string;
      };
      latest_report: {
        id: string;
        smart_folder_id: string;
        generated_content: Record<string, unknown> & {
          title?: string;
          summary?: string;
          timeline?: Array<Record<string, unknown>>;
          patterns?: string[];
          trends?: string[];
          issues?: string[];
          learnings?: string[];
          recommendations?: string[];
          raw_markdown?: string;
        };
        source_asset_ids: string[];
        citation_index: Record<string, unknown>;
        version: number;
        refinement_query: string | null;
        created_at: string;
      } | null;
    }>(`/v1/smart-folders/${id}`);
  }

  async refineSmartFolder(id: string, refinementQuery: string) {
    return this.request<{ task_id: string; status: string; status_url: string; message: string }>(`/v1/smart-folders/${id}/refine`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refinement_query: refinementQuery }),
    });
  }

  async saveSmartFolder(id: string, name?: string) {
    return this.request<{ note_id: string; title: string; message: string }>(`/v1/smart-folders/${id}/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name || null }),
    });
  }

  async getSmartFolderStatus(id: string) {
    return this.request<{
      task_id: string;
      status: string;
      progress_percent: number;
      message: string | null;
      smart_folder_id: string | null;
      report_id: string | null;
      error: string | null;
    }>(`/v1/smart-folders/${id}/status`);
  }

  async getGenerationTaskStatus(taskId: string) {
    return this.request<{ task_id: string; status: string; result: unknown; error: string | null }>(`/v1/smart-folders/generate/status/${taskId}`);
  }
}

export const api = new ApiClient(API_BASE);
export default api;

/**
 * Read the CSRF double-submit cookie (non-httpOnly, set by backend on login).
 * Use this when making state-changing requests (POST/PUT/DELETE/PATCH)
 * via raw fetch() instead of the api client.
 */
export function getCsrfToken(): string {
  if (typeof document === 'undefined') return '';
  return (
    document.cookie
      .split('; ')
      .find((row) => row.startsWith('csrf_token='))
      ?.split('=')[1] ?? ''
  );
}
