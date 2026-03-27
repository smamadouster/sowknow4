/**
 * Zustand store for authentication state
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'user' | 'admin' | 'superuser';
  can_access_confidential: boolean;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  _hasHydrated: boolean;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setHasHydrated: (state: boolean) => void;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: () => Promise<void>;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      _hasHydrated: false,

      setUser: (user) => set({ user, isAuthenticated: !!user }),

      setLoading: (loading) => set({ isLoading: loading }),

      setError: (error) => set({ error }),

      setHasHydrated: (state) => set({ _hasHydrated: state }),

      login: async (email, password) => {
        set({ isLoading: true, error: null });
        try {
          const { api } = await import('./api');
          const response = await api.login(email, password);

          if (response.error || response.status !== 200) {
            set({
              error: response.error || 'Login failed',
              isLoading: false,
            });
            return;
          }

          if (response.data) {
            // After successful login, fetch user info
            const meResponse = await api.getMe();
            if (meResponse.data && !meResponse.error) {
              set({
                user: meResponse.data as User,
                isAuthenticated: true,
                isLoading: false,
                error: null,
              });
            }
          }
        } catch (error) {
          set({
            error: error instanceof Error ? error.message : 'Login failed',
            isLoading: false,
          });
        }
      },

      logout: async () => {
        set({ isLoading: true });
        try {
          const { api } = await import('./api');
          await api.logout();
        } catch (error) {
          console.error('Logout error:', error);
        } finally {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        }
      },

      checkAuth: async () => {
        set({ isLoading: true });
        try {
          const { api } = await import('./api');
          const response = await api.getMe();

          if (response.data && !response.error) {
            set({
              user: response.data as User,
              isAuthenticated: true,
              isLoading: false,
            });
          } else {
            set({
              user: null,
              isAuthenticated: false,
              isLoading: false,
            });
          }
        } catch (error) {
          set({
            user: null,
            isAuthenticated: false,
            isLoading: false,
          });
        }
      },
    }),
    {
      name: 'sowknow-auth',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);

/**
 * Check if a user object can access confidential documents.
 * Uses the can_access_confidential field from the API, falling back to role check.
 */
export function canAccessConfidential(user: User | null | undefined): boolean {
  if (!user) return false;
  return user.can_access_confidential || user.role === 'admin' || user.role === 'superuser';
}

/**
 * Check if current user can access confidential documents
 */
export function currentUserCanAccessConfidential(): boolean {
  const state = useAuthStore.getState();
  return canAccessConfidential(state.user);
}

/**
 * Chat store for managing chat sessions
 */
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: Array<{
    document_id: string;
    document_name: string;
    chunk_id: string;
    relevance_score: number;
  }>;
  llm_used?: 'kimi' | 'ollama';
  created_at: string;
}

interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

interface ChatState {
  sessions: ChatSession[];
  currentSession: ChatSession | null;
  messages: ChatMessage[];
  isLoading: boolean;
  isStreaming: boolean;
  llmUsed: 'kimi' | 'ollama' | null;
  setSessions: (sessions: ChatSession[]) => void;
  setCurrentSession: (session: ChatSession | null) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  setLoading: (loading: boolean) => void;
  setStreaming: (streaming: boolean) => void;
  setLlmUsed: (llm: 'kimi' | 'ollama' | null) => void;
  createSession: (title: string) => Promise<void>;
  loadSessions: () => Promise<void>;
  loadMessages: (sessionId: string) => Promise<void>;
  sendMessage: (content: string) => Promise<void>;
}

export const useChatStore = create<ChatState>()((set, get) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  isLoading: false,
  isStreaming: false,
  llmUsed: null,

  setSessions: (sessions) => set({ sessions }),

  setCurrentSession: (session) => set({ currentSession: session, messages: [] }),

  setMessages: (messages) => set({ messages }),

  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message],
  })),

  setLoading: (isLoading) => set({ isLoading }),

  setStreaming: (isStreaming) => set({ isStreaming }),

  setLlmUsed: (llmUsed) => set({ llmUsed }),

  createSession: async (title) => {
    set({ isLoading: true });
    try {
      const { api } = await import('./api');
      const response = await api.createSession(title);

      if (response.data && !response.error) {
        const newSession = response.data as ChatSession;
        set((state) => ({
          sessions: [newSession, ...state.sessions],
          currentSession: newSession,
          messages: [],
          isLoading: false,
        }));
      }
    } catch (error) {
      console.error('Error creating session:', error);
      set({ isLoading: false });
    }
  },

  loadSessions: async () => {
    try {
      const { api } = await import('./api');
      const response = await api.getSessions();

      if (response.data && !response.error) {
        set({ sessions: (response.data as { sessions: ChatSession[] }).sessions || [] });
      }
    } catch (error) {
      console.error('Error loading sessions:', error);
    }
  },

  loadMessages: async (sessionId) => {
    set({ isLoading: true });
    try {
      const { api } = await import('./api');
      const response = await api.getMessages(sessionId);

      if (response.data && !response.error) {
        set({ messages: (response.data as { messages: ChatMessage[] }).messages || [] });
      }
    } catch (error) {
      console.error('Error loading messages:', error);
    } finally {
      set({ isLoading: false });
    }
  },

  sendMessage: async (content) => {
    const { currentSession, messages, llmUsed } = get();

    if (!currentSession) {
      await get().createSession('New Chat');
    }

    const session = get().currentSession;
    if (!session) return;

    // Add user message
    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    };
    get().addMessage(userMessage);

    // Stream assistant response
    set({ isStreaming: true });

    // Create placeholder for assistant message
    const assistantMessage: ChatMessage = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
    };
    get().addMessage(assistantMessage);

    let accumulatedContent = '';

    try {
      const { api } = await import('./api');
      await api.sendMessageStream(
        session.id,
        content,
        // onChunk
        (chunk: string) => {
          accumulatedContent += chunk;
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === assistantMessage.id
                ? { ...msg, content: accumulatedContent }
                : msg
            ),
          }));
        },
        // onComplete
        () => {
          set((state) => ({
            messages: state.messages.map((msg) =>
              msg.id === assistantMessage.id
                ? { ...msg, content: accumulatedContent }
                : msg
            ),
            isStreaming: false,
          }));
        },
        // onError
        (error: string) => {
          set({
            isStreaming: false,
            messages: [...get().messages.slice(0, -1)], // Remove placeholder
          });
          console.error('Stream error:', error);
        }
      );
    } catch (error) {
      console.error('Error sending message:', error);
      set({ isStreaming: false });
    }
  },
}));

/**
 * Upload store — tracks active file uploads globally so Navigation
 * can warn the user before logging out while an upload is in progress.
 */
interface UploadState {
  isUploading: boolean;
  setIsUploading: (value: boolean) => void;
}

export const useUploadStore = create<UploadState>()((set) => ({
  isUploading: false,
  setIsUploading: (value) => set({ isUploading: value }),
}));
