'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { Link } from '@/i18n/routing';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeSanitize from 'rehype-sanitize';
import { getCsrfToken } from '@/lib/api';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sources?: { id: string; filename: string; relevance: number }[];
  llm_used?: string;
  cache_hit?: boolean;
  created_at?: string;
}

interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

export default function ChatPage() {
  const t = useTranslations('chat');
  const tCommon = useTranslations('common');
  const locale = useLocale();
  
  const [sessions, setSessions] = useState<Session[]>([]);
  const [currentSession, setCurrentSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamingLlm, setStreamingLlm] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    loadSessions();
  }, []);

  useEffect(() => {
    if (currentSession) {
      loadMessages(currentSession.id);
    }
  }, [currentSession]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const loadSessions = async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/chat/sessions?limit=50`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setSessions(data.sessions || []);
        if (data.sessions?.length > 0) {
          setCurrentSession(data.sessions[0]);
        }
      }
    } catch (e) {
      console.error('Error loading sessions:', e);
    }
  };

  const loadMessages = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_BASE}/v1/chat/sessions/${sessionId}/messages?limit=100`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
      }
    } catch (e) {
      console.error('Error loading messages:', e);
      setError(t('error_loading'));
    }
  };

  const createSession = async () => {
    try {
      const title = `Conversation ${new Date().toLocaleDateString()}`;
      const res = await fetch(`${API_BASE}/v1/chat/sessions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': getCsrfToken(),
        },
        credentials: 'include',
        body: JSON.stringify({ title }),
      });
      if (res.ok) {
        const data = await res.json();
        setSessions([data, ...sessions]);
        setCurrentSession(data);
        setMessages([]);
      }
    } catch (e) {
      console.error('Error creating session:', e);
    }
  };

  const deleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch(`${API_BASE}/v1/chat/sessions/${sessionId}`, {
        method: 'DELETE',
        headers: { 'X-CSRF-Token': getCsrfToken() },
        credentials: 'include',
      });
      if (res.ok) {
        const newSessions = sessions.filter(s => s.id !== sessionId);
        setSessions(newSessions);
        if (currentSession?.id === sessionId) {
          setCurrentSession(newSessions[0] || null);
          setMessages([]);
        }
      }
    } catch (e) {
      console.error('Error deleting session:', e);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || !currentSession || isStreaming) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
    };

    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);
    setIsStreaming(true);
    setError(null);

    const assistantMessage: Message = {
      id: (Date.now() + 1).toString(),
      role: 'assistant',
      content: '',
    };
    setMessages(prev => [...prev, assistantMessage]);
    setStreamingLlm(null);

    try {
      const response = await fetch(
        `${API_BASE}/v1/chat/sessions/${currentSession.id}/message?stream=true`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': getCsrfToken(),
          },
          credentials: 'include',
          body: JSON.stringify({ content: userMessage.content }),
        }
      );

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (!reader) throw new Error('No reader available');

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') continue;

            try {
              const parsed = JSON.parse(data);
              if (parsed.type === 'message' || parsed.type === 'content') {
                setMessages(prev =>
                  prev.map(m =>
                    m.id === assistantMessage.id
                      ? { ...m, content: m.content + parsed.content }
                      : m
                  )
                );
              } else if (parsed.type === 'sources') {
                setMessages(prev =>
                  prev.map(m =>
                    m.id === assistantMessage.id
                      ? { ...m, sources: parsed.sources }
                      : m
                  )
                );
              } else if (parsed.type === 'llm_info') {
                setMessages(prev =>
                  prev.map(m =>
                    m.id === assistantMessage.id
                      ? { ...m, llm_used: parsed.model, cache_hit: parsed.cache_hit }
                      : m
                  )
                );
                setStreamingLlm(parsed.model);
              } else if (parsed.type === 'error') {
                setError(parsed.error || 'Unknown error');
              }
            } catch {
              // Skip invalid JSON
            }
          }
        }
      }
    } catch (e) {
      console.error('Error sending message:', e);
      setError(t('streaming_error'));
    } finally {
      setIsLoading(false);
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] bg-vault-1000">
      {/* Sidebar toggle button (mobile) */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="lg:hidden fixed bottom-20 left-4 z-40 w-10 h-10 rounded-xl bg-vault-800 border border-white/[0.08] flex items-center justify-center text-text-muted shadow-card"
        aria-label="Toggle sidebar"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>

      {/* Sessions Sidebar */}
      <div className={`${sidebarOpen ? 'translate-x-0' : '-translate-x-full'} lg:translate-x-0 fixed lg:relative inset-y-0 left-0 z-30 lg:z-auto w-72 lg:w-64 border-r border-white/[0.06] bg-vault-950 flex flex-col transition-transform duration-300`}>
        {/* Sidebar header */}
        <div className="p-3 border-b border-white/[0.06]">
          <button
            onClick={createSession}
            aria-label={t('new_chat')}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 rounded-xl hover:from-amber-400 hover:to-amber-500 transition-all shadow-lg shadow-amber-500/20 font-medium text-sm font-display"
          >
            <svg className="w-4 h-4" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {t('new_chat')}
          </button>
        </div>

        {/* Sessions list */}
        <div className="flex-1 overflow-y-auto">
          {sessions.length === 0 ? (
            <div className="p-4 text-center text-text-muted text-sm" role="status">
              {t('no_sessions')}
            </div>
          ) : (
            <ol role="list" aria-label={t('sessions_title')} className="p-2">
              {sessions.map(session => (
                <li key={session.id} role="listitem">
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => setCurrentSession(session)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setCurrentSession(session); } }}
                    aria-current={currentSession?.id === session.id ? 'true' : undefined}
                    aria-label={session.title}
                    className={`group flex items-center justify-between p-2.5 rounded-xl cursor-pointer mb-1 transition-all duration-200 ${
                      currentSession?.id === session.id
                        ? 'bg-amber-500/10 text-amber-400 border border-amber-500/10'
                        : 'text-text-secondary hover:text-text-primary hover:bg-white/[0.04] border border-transparent'
                    }`}
                  >
                    <span className="truncate text-sm">{session.title}</span>
                    <button
                      onClick={(e) => deleteSession(session.id, e)}
                      aria-label={`${t('delete_session')}: ${session.title}`}
                      className="opacity-0 group-hover:opacity-100 focus:opacity-100 p-1 hover:text-red-400 transition-all rounded"
                    >
                      <svg className="w-3.5 h-3.5" aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </div>

      {/* Mobile sidebar backdrop */}
      {sidebarOpen && (
        <div
          className="lg:hidden fixed inset-0 z-20 bg-black/50"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Chat Area */}
      <div className="flex-1 flex flex-col">
        {/* Messages */}
        <div
          className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4"
          aria-live="polite"
          aria-atomic="false"
          aria-label={t('messages_region')}
          role="log"
        >
          {!currentSession ? (
            <div className="flex flex-col items-center justify-center h-full text-text-muted">
              <div className="w-20 h-20 rounded-2xl bg-vault-800/50 border border-white/[0.06] flex items-center justify-center mb-4">
                <svg className="w-10 h-10 text-text-muted/40" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
                </svg>
              </div>
              <p className="text-lg mb-2 font-display text-text-secondary">{t('title')}</p>
              <p className="text-sm text-text-muted/60">{t('new_chat')}</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-text-muted">
              <p className="text-lg font-display text-text-secondary">{t('chat_placeholder')}</p>
            </div>
          ) : (
            messages.map(message => (
              <div
                key={message.id}
                className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className={`max-w-[75%] rounded-2xl p-4 ${
                    message.role === 'user'
                      ? 'bg-gradient-to-br from-amber-500 to-amber-600 text-vault-1000 shadow-lg shadow-amber-500/20'
                      : 'bg-vault-800/60 border border-white/[0.06] text-text-primary'
                  }`}
                >
                  {message.role === 'assistant' ? (
                    <ReactMarkdown
                      rehypePlugins={[rehypeSanitize, rehypeHighlight]}
                      components={{
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        h1: ({ children }) => <h1 className="text-xl font-bold mb-2 mt-3 font-display">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-lg font-semibold mb-2 mt-3 font-display">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-base font-semibold mb-1 mt-2 font-display">{children}</h3>,
                        ul: ({ children }) => <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>,
                        ol: ({ children }) => <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>,
                        li: ({ children }) => <li className="text-sm">{children}</li>,
                        code: ({ children, className }) => {
                          const isBlock = className?.startsWith('language-');
                          return isBlock ? (
                            <code className={`${className} text-sm`}>{children}</code>
                          ) : (
                            <code className="bg-vault-900/80 text-amber-300 px-1.5 py-0.5 rounded-md text-sm font-mono">{children}</code>
                          );
                        },
                        pre: ({ children }) => (
                          <pre className="bg-vault-900/80 border border-white/[0.06] rounded-xl p-3 mb-2 overflow-x-auto text-sm">{children}</pre>
                        ),
                        blockquote: ({ children }) => (
                          <blockquote className="border-l-2 border-amber-500/30 pl-3 italic text-text-secondary mb-2">{children}</blockquote>
                        ),
                        a: ({ href, children }) => (
                          <a href={href} target="_blank" rel="noopener noreferrer" className="text-amber-400 underline hover:text-amber-300">{children}</a>
                        ),
                        table: ({ children }) => (
                          <div className="overflow-x-auto mb-2">
                            <table className="min-w-full border border-white/[0.06] rounded-lg text-sm">{children}</table>
                          </div>
                        ),
                        th: ({ children }) => <th className="border border-white/[0.06] px-3 py-1.5 bg-vault-900/50 font-semibold text-left">{children}</th>,
                        td: ({ children }) => <td className="border border-white/[0.06] px-3 py-1.5">{children}</td>,
                        strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                        em: ({ children }) => <em className="italic">{children}</em>,
                        hr: () => <hr className="border-white/[0.06] my-2" />,
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                  ) : (
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  )}
                  
                  {message.sources && message.sources.length > 0 && (
                    <div className={`mt-3 pt-3 border-t ${message.role === 'user' ? 'border-amber-400/30' : 'border-white/[0.06]'}`}>
                      <p className="text-xs font-semibold mb-2 opacity-75 font-display">{t('sources')}</p>
                      <div className="flex flex-wrap gap-1.5">
                        {message.sources.map((source, idx) => (
                          <span
                            key={idx}
                            className={`text-xs px-2 py-1 rounded-lg ${
                              message.role === 'user'
                                ? 'bg-amber-400/20 text-amber-100'
                                : 'bg-vault-900/80 text-text-secondary border border-white/[0.06]'
                            }`}
                          >
                            {source.filename} ({Math.round(source.relevance * 100)}%)
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  
                  {message.llm_used && (
                    <div className={`mt-2 text-xs opacity-75 flex items-center gap-2`}>
                      <span>{t('model_used')}: {message.llm_used}</span>
                      {message.cache_hit && (
                        <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-medium ${
                          message.role === 'user' 
                            ? 'bg-amber-400/20 text-amber-100' 
                            : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        }`}>
                          ⚡ Cache
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          
          {isStreaming && (
            <div className="flex justify-start" role="status" aria-live="polite">
              <div className="bg-vault-800/60 border border-white/[0.06] rounded-2xl p-4">
                <div className="flex items-center gap-2 text-text-muted">
                  <div className="flex gap-1">
                    <div className="w-2 h-2 rounded-full bg-amber-400/60 animate-bounce" style={{ animationDelay: '0ms' }} />
                    <div className="w-2 h-2 rounded-full bg-amber-400/60 animate-bounce" style={{ animationDelay: '150ms' }} />
                    <div className="w-2 h-2 rounded-full bg-amber-400/60 animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                  <span className="text-sm">
                    {streamingLlm?.toLowerCase().includes('ollama')
                      ? '🛡️ Local LLM is thinking... (confidential mode)'
                      : t('thinking')}
                  </span>
                </div>
              </div>
            </div>
          )}
          
          {error && (
            <div className="flex justify-center">
              <div className="bg-red-500/10 border border-red-500/20 text-red-300 px-4 py-2 rounded-xl text-sm">
                {error}
              </div>
            </div>
          )}
          
          <div ref={messagesEndRef} />
        </div>

        {/* Input Area */}
        <div className="border-t border-white/[0.06] p-4 bg-vault-950/50">
          <div className="max-w-3xl mx-auto flex gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('type_message')}
              aria-label={t('type_message')}
              aria-multiline="true"
              className="flex-1 resize-none bg-vault-800/50 border border-white/[0.08] rounded-xl px-4 py-3 text-text-primary placeholder-text-muted/50 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/50 transition-all"
              rows={1}
              disabled={!currentSession || isStreaming}
            />
            <button
              onClick={sendMessage}
              disabled={!input.trim() || !currentSession || isStreaming}
              aria-label={t('send')}
              aria-busy={isLoading}
              className="px-5 py-3 bg-gradient-to-r from-amber-500 to-amber-600 text-vault-1000 rounded-xl hover:from-amber-400 hover:to-amber-500 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-lg shadow-amber-500/20 hover:shadow-amber-500/30 font-medium font-display"
            >
              {isLoading ? (
                <div className="w-5 h-5 border-2 border-vault-1000/30 border-t-vault-1000 rounded-full animate-spin" />
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
