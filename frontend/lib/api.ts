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
    if (!headers['Content-Type']) {
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
