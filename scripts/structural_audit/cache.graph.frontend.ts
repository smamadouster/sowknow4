// 🧠 TOP ARCHITECTURAL HUBS (Most Imported Local Modules)
// [hub]: ./globals.css → imported 1 times
// [hub]: ./SearchModal → imported 1 times
// [hub]: ./ChartRenderer → imported 1 times
// [hub]: ./utils → imported 1 times

// 🧠 FRONTEND ARCHITECTURE MAP (Auto-generated via ts-morph)

### FILE: frontend/app/layout.tsx
[local_deps]: ./globals.css
[ext_deps]: next-intl/server
[fn]: default({
  children,
})
[export]: viewport
[export]: metadata

---
### FILE: frontend/components/AppHooks.tsx
[ext_deps]: @/hooks/useTaskAlarms, @/hooks/usePushNotifications, react
[fn]: default()

---
### FILE: frontend/components/BatchUploader.tsx
[ext_deps]: react, next-intl
[fn]: default({
  onComplete,
  onError,
  maxFiles = 20,
})

---
### FILE: frontend/components/CommandPalette.tsx
[local_deps]: ./SearchModal
[ext_deps]: react, next-intl
[fn]: default()

---
### FILE: frontend/components/DateTimePicker.tsx
[ext_deps]: react
[fn]: default({ value, onChange, label })

---
### FILE: frontend/components/LanguageSelector.tsx
[ext_deps]: next-intl, @/i18n/routing, react
[fn]: LanguageSelector()

---
### FILE: frontend/components/Navigation.tsx
[ext_deps]: next/link, next/navigation, next-intl, react, @/lib/store, @/hooks/useSessionTimeout, @/hooks/useScrollDirection, @/components/mobile/MobileBottomSheet
[fn]: Navigation()
[fn]: default()

---
### FILE: frontend/components/OfflineIndicator.tsx
[ext_deps]: react
[fn]: default()

---
### FILE: frontend/components/PrivacyBadge.tsx
[ext_deps]: next-intl
[fn]: default()

---
### FILE: frontend/components/PWAInstallPrompt.tsx
[ext_deps]: react
[fn]: default()

---
### FILE: frontend/components/SearchModal.tsx
[ext_deps]: react, next/navigation, next-intl, @/lib/api
[fn]: default({ isOpen, onClose })

---
### FILE: frontend/components/TagAutocomplete.tsx
[ext_deps]: react, @/hooks/useTagSuggestions
[fn]: default({
  tags,
  onChange,
  required = false,
  placeholder = 'Add tag...',
})

---
### FILE: frontend/components/TagSelector.tsx
[ext_deps]: react, next-intl, @/hooks/useIsMobile, @/components/TagAutocomplete
[fn]: default({ tags, onChange, required = false, placeholder })

---
### FILE: frontend/components/VoiceRecorder.tsx
[ext_deps]: react, next-intl, @/hooks/useVoiceRecorder
[fn]: default({ mode, onAudioReady, onCancel, className = '', lang })

---
### FILE: frontend/hooks/useIsMobile.ts
[ext_deps]: react
[fn]: useIsMobile()
[fn]: useIsStandalone()

---
### FILE: frontend/hooks/usePushNotifications.ts
[ext_deps]: react
[fn]: usePushNotifications()

---
### FILE: frontend/hooks/useScrollDirection.ts
[ext_deps]: react
[fn]: useScrollDirection(threshold)
[type]: ScrollDirection

---
### FILE: frontend/hooks/useSessionTimeout.ts
[ext_deps]: react, next/navigation, next-intl, @/lib/store
[fn]: useSessionTimeout()

---
### FILE: frontend/hooks/useSmartFolderStream.ts
[ext_deps]: react
[fn]: useSmartFolderStream()

---
### FILE: frontend/hooks/useTagSuggestions.ts
[ext_deps]: react
[fn]: useTagSuggestions(query, limit)
[interface]: TagSuggestion { props: [tag_name, count] }

---
### FILE: frontend/hooks/useTaskAlarms.ts
[ext_deps]: react, @/lib/store
[fn]: useTaskAlarms()

---
### FILE: frontend/hooks/useVoiceRecorder.ts
[ext_deps]: react, @/lib/api
[fn]: useVoiceRecorder(options)
[type]: RecordingState

---
### FILE: frontend/i18n/routing.ts
[ext_deps]: next-intl/routing, next-intl/navigation
[export]: routing
[export]: Link
[export]: redirect
[export]: usePathname
[export]: useRouter

---
### FILE: frontend/lib/api.ts
[fn]: getCsrfToken()
[export]: api
[export]: default

---
### FILE: frontend/lib/formatDate.ts
[fn]: formatDate(dateStr, options, locale)
[fn]: formatDateShort(dateStr, locale)

---
### FILE: frontend/lib/store.ts
[ext_deps]: zustand, zustand/middleware
[fn]: canAccessConfidential(user)
[fn]: currentUserCanAccessConfidential()
[export]: useAuthStore
[export]: useChatStore
[export]: useUploadStore
[export]: useSearchCacheStore

---
### FILE: frontend/app/[locale]/layout.tsx
[ext_deps]: next-intl, next-intl/server, next/navigation, @/i18n/routing, @/components/LanguageSelector, @/components/Navigation, @/components/CommandPalette, @/components/PrivacyBadge, @/components/PWAInstallPrompt, @/components/OfflineIndicator, @/components/AppHooks
[fn]: default({
  children,
  params,
})

---
### FILE: frontend/app/[locale]/page.tsx
[ext_deps]: react, next-intl, @/i18n/routing, @/lib/store
[fn]: default()

---
### FILE: frontend/app/i18n/request.ts
[ext_deps]: next/navigation, next-intl/server, @/i18n/routing
[export]: default

---
### FILE: frontend/components/knowledge-graph/EntityDetail.tsx
[ext_deps]: react, @/lib/api
[fn]: EntityDetail({ entityId, onClose })
[interface]: EntityDetail { props: [entity, relationships, mentions] }
[interface]: Relationship { props: [id, target_id, source_id, type, confidence, document_count] }
[interface]: Mention { props: [id, document_id, context, page_number, confidence] }
[fn]: default({ entityId, onClose })
[interface]: default { props: [entity, relationships, mentions] }

---
### FILE: frontend/components/knowledge-graph/EntityList.tsx
[ext_deps]: react, @/lib/api
[fn]: EntityList({ entityType, onSelectEntity, selectedEntityId })
[interface]: Entity { props: [id, name, type, canonical_id, document_count, relationship_count, first_seen, last_seen] }
[fn]: default({ entityType, onSelectEntity, selectedEntityId })

---
### FILE: frontend/components/knowledge-graph/GraphVisualization.tsx
[ext_deps]: react
[fn]: GraphVisualization({
  nodes: initialNodes,
  edges,
  width: propWidth = 800,
  height: propHeight = 600,
  onNodeClick,
  onNodeHover,
})
[interface]: GraphNode { props: [id, name, type, size, color, x, y, fx, fy] }
[interface]: GraphEdge { props: [source, target, label, weight] }
[fn]: default({
  nodes: initialNodes,
  edges,
  width: propWidth = 800,
  height: propHeight = 600,
  onNodeClick,
  onNodeHover,
})

---
### FILE: frontend/components/mobile/FAB.tsx
[fn]: default({ onClick, label, icon })

---
### FILE: frontend/components/mobile/MobileBottomSheet.tsx
[ext_deps]: react
[fn]: default({ open, onClose, title, children, heightPercent = 50 })

---
### FILE: frontend/components/mobile/MobileSheet.tsx
[ext_deps]: react
[fn]: default({ open, onClose, title, headerActions, footer, children })

---
### FILE: frontend/components/mobile/PullToRefresh.tsx
[ext_deps]: react
[fn]: default({ onRefresh, children })

---
### FILE: frontend/components/mobile/SwipeableRow.tsx
[ext_deps]: react
[fn]: default({ children, onSwipeAction, actionLabel, actionColor = 'bg-red-500' })

---
### FILE: frontend/components/smart-folder/ChartRenderer.tsx
[ext_deps]: react, next/dynamic, recharts
[fn]: default({ visualisation })

---
### FILE: frontend/components/smart-folder/CitationPanel.tsx
[fn]: default({ citationIndex, activeCitation, onClose })

---
### FILE: frontend/components/smart-folder/LoadingState.tsx
[fn]: default({ step = "parsing", progressPercent = 0 })

---
### FILE: frontend/components/smart-folder/RefinementBar.tsx
[ext_deps]: react
[fn]: default({ onRefine, loading = false })

---
### FILE: frontend/components/smart-folder/ReportViewer.tsx
[local_deps]: ./ChartRenderer
[ext_deps]: react, react-markdown
[fn]: default({ report, citationIndex, visualisations, onCitationClick })

---
### FILE: frontend/components/smart-folder/SearchBar.tsx
[ext_deps]: react
[fn]: default({ onSubmit, loading = false, placeholder = "Ask about any relationship, project, or topic…" })

---
### FILE: frontend/components/smart-folder/VegaLiteChart.tsx
[ext_deps]: react
[fn]: default({ spec, title })

---
### FILE: frontend/app/[locale]/bookmarks/page.tsx
[local_deps]: ./utils
[ext_deps]: react, next-intl, @/components/TagSelector, @/hooks/useIsMobile, @/components/mobile/MobileSheet, @/components/mobile/FAB, @/components/mobile/SwipeableRow
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/bookmarks/utils.ts
[fn]: parseDomain(url)

---
### FILE: frontend/app/[locale]/chat/page.tsx
[ext_deps]: react, next-intl, @/i18n/routing, react-markdown, rehype-highlight, rehype-sanitize, @/lib/api, @/hooks/useIsMobile, @/components/mobile/MobileBottomSheet
[fn]: default()

---
### FILE: frontend/app/[locale]/collections/page.tsx
[ext_deps]: react, next/link, next-intl, @/i18n/routing, @/lib/api
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/dashboard/page.tsx
[ext_deps]: react, next-intl, next/navigation, recharts, @/lib/api, @/lib/store
[fn]: default()

---
### FILE: frontend/app/[locale]/documents/page.tsx
[ext_deps]: react, react-dropzone, next-intl, next/link, next/navigation, @/lib/store, @/lib/api, @/lib/formatDate, @/hooks/useIsMobile, @/components/mobile/FAB, @/components/mobile/MobileBottomSheet, @/components/mobile/PullToRefresh
[fn]: default()

---
### FILE: frontend/app/[locale]/forgot-password/page.tsx
[ext_deps]: react, next-intl
[fn]: default()

---
### FILE: frontend/app/[locale]/journal/page.tsx
[ext_deps]: react, next-intl, @/lib/formatDate, @/lib/api, @/components/VoiceRecorder
[fn]: default()

---
### FILE: frontend/app/[locale]/knowledge-graph/page.tsx
[ext_deps]: react, @/lib/api, @/components/knowledge-graph/GraphVisualization, @/components/knowledge-graph/GraphVisualization, @/components/knowledge-graph/EntityList, @/components/knowledge-graph/EntityList, @/components/knowledge-graph/EntityDetail, next-intl
[fn]: default()

---
### FILE: frontend/app/[locale]/login/page.tsx
[ext_deps]: react, next/navigation, next-intl, @/lib/store
[fn]: default()

---
### FILE: frontend/app/[locale]/monitoring/page.tsx
[ext_deps]: react, next-intl
[fn]: default()

---
### FILE: frontend/app/[locale]/notes/page.tsx
[ext_deps]: react, next-intl, next/navigation, @/components/TagSelector, @/components/VoiceRecorder, @/hooks/useIsMobile, @/components/mobile/MobileSheet, @/components/mobile/FAB, @/components/mobile/SwipeableRow, @/components/mobile/PullToRefresh
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/offline/page.tsx
[ext_deps]: next-intl, next-intl
[fn]: default()

---
### FILE: frontend/app/[locale]/register/page.tsx
[ext_deps]: react, next/navigation, next-intl
[fn]: default()

---
### FILE: frontend/app/[locale]/search/page.tsx
[ext_deps]: react, react, next-intl, next/link, next/navigation, @/lib/api, @/lib/store, @/components/VoiceRecorder, @/hooks/useIsMobile
[fn]: default()

---
### FILE: frontend/app/[locale]/settings/page.tsx
[ext_deps]: react, next-intl, @/lib/api, @/lib/formatDate
[fn]: default()

---
### FILE: frontend/app/[locale]/smart-folders/page.tsx
[ext_deps]: react, next-intl, @/lib/api, @/hooks/useSmartFolderStream, @/components/smart-folder/SearchBar, @/components/smart-folder/LoadingState, @/components/smart-folder/ReportViewer, @/components/smart-folder/CitationPanel, @/components/smart-folder/RefinementBar
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/spaces/page.tsx
[ext_deps]: react, next-intl, @/i18n/routing
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/subscriptions/page.tsx
[ext_deps]: react, next-intl, @/hooks/useIsMobile, @/components/mobile/MobileSheet, @/components/mobile/FAB, @/lib/api
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/tasks/page.tsx
[ext_deps]: react, next-intl, next/navigation, @/components/TagSelector, @/components/DateTimePicker, @/hooks/useIsMobile, @/components/mobile/MobileSheet, @/components/mobile/FAB, @/components/mobile/SwipeableRow, @/components/mobile/PullToRefresh
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/api/health/route.ts
[ext_deps]: next/server
[fn]: GET()

---
### FILE: frontend/app/[locale]/admin/search-debug/page.tsx
[ext_deps]: react, next-intl, @/lib/api
[fn]: default()

---
### FILE: frontend/app/[locale]/collections/[id]/page.tsx
[ext_deps]: react, next/navigation, next-intl, @/lib/api
[fn]: default()

---
### FILE: frontend/app/[locale]/documents/[id]/page.tsx
[ext_deps]: react, next/navigation, next-intl, next/link, @/lib/store, @/lib/api, @/lib/formatDate
[fn]: default()

---
### FILE: frontend/app/[locale]/notes/[id]/page.tsx
[ext_deps]: react, next/navigation, next-intl, @/lib/api, @/components/TagSelector, @/components/VoiceRecorder
[fn]: default()

---
### FILE: frontend/app/[locale]/spaces/[id]/page.tsx
[ext_deps]: react, next-intl, next/navigation
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/tasks/[id]/page.tsx
[ext_deps]: react, next-intl, next/navigation, @/components/TagSelector, @/components/DateTimePicker
[fn]: default()
[export]: dynamic

---
### FILE: frontend/app/[locale]/verify-email/[token]/page.tsx
[ext_deps]: react, next/navigation, next-intl
[fn]: default()

---
