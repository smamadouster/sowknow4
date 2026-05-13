"""
🧠 TOP ARCHITECTURAL HUBS (Most Imported Local Modules)
# [hub]: app.models.document → imported 48 times
# [hub]: app.database → imported 47 times
# [hub]: app.models.user → imported 46 times
# [hub]: app.api.deps → imported 25 times
# [hub]: app.models.base → imported 24 times
# [hub]: app.core.redis_url → imported 19 times
# [hub]: app.services.llm_gateway → imported 19 times
# [hub]: app.models.audit → imported 15 times
# [hub]: app.services.agent_identity → imported 15 times
# [hub]: app.celery_app → imported 14 times
"""

"""
🧠 BACKEND ARCHITECTURE MAP (Auto-generated via Python AST)
"""

### FILE: backend/app/api/admin.py
[local_deps]: app.celery_app, app.api.deps, app.services.whisper_service, app.models.document, app.services.alert_service, app.core.redis_url, app.schemas.user, app.tasks.pipeline_tasks, app.schemas.admin, app.models.chat, app.services.storage_service, app.tasks.pipeline_orchestrator, app.models.failed_task, app.utils.security, app.api.documents_common, app.models.user, app.database, app.models.audit, app.models.article, app.models.processing, app.services.embed_client, app.models.pipeline
[ext_deps]: json, os, uuid, logging, fastapi, asyncio, sqlalchemy, pydantic, redis, datetime, concurrent, typing
[async_fn]: create_audit_log(db, user_id, action, resource_type, resource_id, details, request)
[async_fn]: list_users(page, page_size, search, role, is_active, current_user, db, request)
[async_fn]: get_user_details(user_id, current_user, db, request)
[async_fn]: create_user(user_data, current_user, db, request)
[async_fn]: update_user(user_id, updates, current_user, db, request)
[async_fn]: delete_user(user_id, current_user, db, request)
[async_fn]: reset_user_password(user_id, password_data, current_user, db, request)
[async_fn]: get_audit_logs(page, page_size, action, resource_type, user_id, days, current_user, db, request)
[async_fn]: get_system_stats(current_user, db)
[async_fn]: get_extended_admin_stats(current_user, db)
[async_fn]: get_queue_stats(current_user, db)
[async_fn]: get_anomalies(current_user, db)
[async_fn]: get_pipeline_stats(current_user, db)
[async_fn]: get_uploads_history(current_user, db)
[async_fn]: get_articles_stats(current_user, db)
[async_fn]: get_articles_history(current_user, db)
[async_fn]: get_dashboard(current_user, db)
[async_fn]: list_failed_tasks(page, page_size, task_name, current_user, db)
[async_fn]: get_failed_task(task_id, current_user, db)
[async_fn]: delete_failed_task(task_id, current_user, db)
[async_fn]: test_alert(severity, current_user)
[async_fn]: recover_failed_uploads(error_substring, limit, db)
[async_fn]: get_whisper_model()
[async_fn]: set_whisper_model(request, size, db)
[async_fn]: force_reset_document(document_id, current_user, db, request)
[async_fn]: pipeline_diagnostics(current_user, db)
[class]: _BulkForceResetRequest { methods: [] }
[async_fn]: bulk_force_reset_anomalies(body, current_user, db, request)
[async_fn]: get_upload_pause_status()
[async_fn]: pause_uploads(current_user, request)
[async_fn]: resume_uploads(current_user, request)

---
### FILE: backend/app/api/articles.py
[local_deps]: app.tasks.article_tasks, app.models.article, app.api.deps, app.schemas.article, app.models.user, app.models.document
[ext_deps]: sqlalchemy, uuid, fastapi, logging
[fn]: _bucket_filter(user)
[async_fn]: list_articles(document_id, limit, offset, db, current_user)
[async_fn]: get_article(article_id, db, current_user)
[async_fn]: generate_articles(document_id, request, db, current_user)
[async_fn]: backfill_articles(db, current_user)
[async_fn]: delete_article(article_id, db, current_user)

---
### FILE: backend/app/api/auth.py
[local_deps]: app.database, app.utils.constants, app.middleware.csrf, app.api.deps, app.schemas.token, app.limiter, app.services.token_blacklist, app.models.user, app.utils.security, app.core.redis_url, app.schemas.auth, app.schemas.user
[ext_deps]: uuid, os, logging, fastapi, time, sqlalchemy, secrets, httpx, hashlib, redis, datetime, dotenv
[async_fn]: verify_telegram_user(telegram_user_id, bot_token)
[fn]: blacklist_token(token, expires_in_seconds)
[fn]: is_token_blacklisted(token)
[fn]: set_auth_cookies(response, access_token, refresh_token)
[fn]: clear_auth_cookies(response)
[fn]: get_refresh_token_from_request(request)
[fn]: get_access_token_from_request(request)
[fn]: blacklist_token_until_expiry(token, expected_type)
[async_fn]: authenticate_user(db, email, password)
[async_fn]: register(request, user_data, db)
[async_fn]: login(request, response, form_data, db)
[async_fn]: refresh_token(request, response, db)
[async_fn]: get_me(current_user)
[async_fn]: logout(request, response)
[async_fn]: forgot_password(request, payload, db)
[async_fn]: verify_email(token, db)
[async_fn]: resend_verification(request, payload, db)
[async_fn]: telegram_auth(response, request, auth_data, db)

---
### FILE: backend/app/api/bookmarks.py
[local_deps]: app.database, app.services.space_service, app.schemas.bookmark, app.api.deps, app.schemas.tag, app.models.user, app.services.bookmark_service
[ext_deps]: sqlalchemy, uuid, fastapi, logging
[async_fn]: create_bookmark(data, current_user, db)
[async_fn]: list_bookmarks(page, page_size, tag, current_user, db)
[async_fn]: search_bookmarks(q, page, page_size, current_user, db)
[async_fn]: get_bookmark(bookmark_id, current_user, db)
[async_fn]: update_bookmark(bookmark_id, data, current_user, db)
[async_fn]: delete_bookmark(bookmark_id, current_user, db)
[fn]: _to_response(bookmark, tags)

---
### FILE: backend/app/api/chat.py
[local_deps]: app.database, app.services.chat_service, app.api.deps, app.models.chat, app.services.input_guard, app.limiter, app.models.user, app.schemas.chat
[ext_deps]: json, uuid, fastapi, logging, sqlalchemy
[async_fn]: create_chat_session(request, session_data, current_user, db)
[async_fn]: list_chat_sessions(limit, offset, current_user, db)
[async_fn]: get_chat_session(session_id, current_user, db)
[async_fn]: send_message(session_id, message_data, stream, current_user, db)
[async_fn]: get_session_messages(session_id, limit, offset, current_user, db)
[async_fn]: delete_chat_session(session_id, current_user, db)

---
### FILE: backend/app/api/collections.py
[local_deps]: app.models.collection, app.database, app.services.llm_gateway, app.tasks.document_tasks, app.models.audit, app.api.deps, app.models.article, app.services.collection_service, app.services.input_guard, app.models.user, app.schemas.collection, app.services.collection_chat_service
[ext_deps]: io, json, uuid, fastapi, logging, sqlalchemy, datetime, reportlab, typing
[fn]: _invalidate_collection_cache(collection_id)
[async_fn]: create_audit_log(db, user_id, action, resource_type, resource_id, details)
[async_fn]: create_collection(collection_data, current_user, db)
[async_fn]: preview_collection(request, current_user, db)
[async_fn]: list_collections(page, page_size, visibility, collection_type, pinned_only, favorites_only, current_user, db)
[async_fn]: get_collection_stats(current_user, db)
[async_fn]: get_collection(collection_id, current_user, db)
[async_fn]: get_collection_status(collection_id, current_user, db)
[async_fn]: update_collection(collection_id, update_data, current_user, db)
[async_fn]: delete_collection(collection_id, current_user, db)
[async_fn]: refresh_collection(collection_id, refresh_data, current_user, db)
[async_fn]: add_collection_item(collection_id, item_data, current_user, db)
[async_fn]: update_collection_item(collection_id, item_id, update_data, current_user, db)
[async_fn]: remove_collection_item(collection_id, item_id, current_user, db)
[async_fn]: pin_collection(collection_id, current_user, db)
[async_fn]: favorite_collection(collection_id, current_user, db)
[async_fn]: chat_with_collection(collection_id, chat_data, current_user, db)
[async_fn]: export_collection(collection_id, format, current_user, db)
[async_fn]: get_collection_chat_sessions(collection_id, current_user, db)

---
### FILE: backend/app/api/deps.py
[local_deps]: app.database, app.utils.security, app.services.token_blacklist, app.models.user, app.utils.constants
[ext_deps]: sqlalchemy, fastapi, logging
[async_fn]: get_token_from_request(request)
[async_fn]: get_current_user(request, db)
[async_fn]: require_admin(current_user)
[async_fn]: require_superuser_or_admin(current_user)
[async_fn]: require_admin_only(current_user)
[async_fn]: require_confidential_access(current_user)
[async_fn]: require_confidential_access_or_admin(current_user)
[fn]: require_role()
[async_fn]: get_current_active_user(current_user)

---
### FILE: backend/app/api/documents.py
[local_deps]: app.database, app.api.documents_journal, app.tasks.pipeline_tasks, app.tasks.document_tasks, app.models.audit, app.api.deps, app.models.pipeline, app.services.storage_service, app.tasks.embedding_tasks, app.api.documents_common, app.models.user, app.models.document, app.tasks.pipeline_orchestrator, app.services.similarity_service, app.models.processing, app.schemas.document, app.api.documents_upload
[ext_deps]: uuid, fastapi, logging, asyncio, sqlalchemy, datetime, concurrent, typing
[async_fn]: list_documents(page, page_size, bucket, status, search, document_type, tag, current_user, db)
[async_fn]: get_document(document_id, current_user, db)
[async_fn]: get_document_status(document_id, current_user, db)
[async_fn]: download_document(document_id, current_user, db)
[async_fn]: update_document(document_id, updates, current_user, db)
[async_fn]: delete_document(document_id, current_user, db)
[async_fn]: get_similar_documents(document_id, limit, current_user, db)
[async_fn]: reprocess_document(document_id, force, regenerate_embeddings, reason, current_user, db)

---
### FILE: backend/app/api/documents_common.py
[local_deps]: app.tasks.pipeline_tasks, app.models.audit, app.models.pipeline, app.models.user, app.models.document, app.tasks.pipeline_orchestrator, app.core.redis_url, app.schemas.document
[ext_deps]: json, os, uuid, logging, asyncio, mimetypes, fastapi, sqlalchemy, pydantic, redis, datetime, concurrent, typing
[fn]: _get_redis_client()
[fn]: is_upload_paused()
[fn]: set_upload_paused(paused)
[async_fn]: create_audit_log(db, user_id, action, resource_type, resource_id, details, ip_address, user_agent)
[fn]: get_file_extension(filename)
[fn]: get_mime_type(filename, content)
[fn]: validate_magic_bytes(filename, content)
[class]: JournalEntryRequest { methods: [] }
[async_fn]: _queue_document_for_processing(document, db, success_message)

---
### FILE: backend/app/api/documents_journal.py
[local_deps]: app.database, app.models.audit, app.api.deps, app.services.storage_service, app.api.documents_common, app.models.user, app.services.whisper_service, app.models.document, app.schemas.document
[ext_deps]: os, fastapi, logging, sqlalchemy, tempfile, datetime
[async_fn]: create_journal_entry(entry, x_bot_api_key, current_user, db)
[async_fn]: create_journal_entry_from_voice(file, language, x_bot_api_key, current_user, db)

---
### FILE: backend/app/api/documents_upload.py
[local_deps]: app.database, app.models.audit, app.api.deps, app.services.storage_service, app.api.documents_common, app.models.user, app.models.document, app.services.deduplication_service, app.services.document_orchestrator, app.schemas.document
[ext_deps]: uuid, fastapi, logging, sqlalchemy, typing
[async_fn]: upload_document(file, bucket, title, tags, document_type, transcript, x_bot_api_key, current_user, db)
[async_fn]: _do_upload_document(file, bucket, title, tags, document_type, transcript, x_bot_api_key, current_user, db)
[async_fn]: process_single_file_upload(file, bucket, current_user, db, batch_id)
[async_fn]: upload_batch_documents(files, bucket, x_bot_api_key, current_user, db)
[async_fn]: get_batch_status(batch_id, current_user, db)

---
### FILE: backend/app/api/graph_rag.py
[local_deps]: app.database, app.services.synthesis_service, app.models.audit, app.api.deps, app.services.temporal_reasoning_service, app.services.graph_rag_service, app.services.search_service, app.models.user, app.models.document, app.services.progressive_revelation_service
[ext_deps]: json, uuid, fastapi, logging, sqlalchemy, typing
[fn]: _search_results_to_dicts(results)
[async_fn]: create_audit_log(db, user_id, action, resource_type, resource_id, details)
[async_fn]: graph_augmented_search(query, document_ids, top_k, expansion_depth, current_user, db)
[async_fn]: graph_aware_answer(query, document_ids, current_user, db)
[async_fn]: find_entity_paths(source, target, max_length, current_user, db)
[async_fn]: get_entity_neighborhood(entity_name, radius, current_user, db)
[async_fn]: synthesize_documents(topic, document_ids, synthesis_type, style, language, max_length, include_timeline, include_entities, current_user, db)
[async_fn]: reason_about_event(event_id, time_window_days, current_user, db)
[async_fn]: analyze_entity_evolution(entity_name, time_months, current_user, db)
[async_fn]: find_temporal_patterns(min_occurrences, current_user, db)
[async_fn]: reveal_entity(entity_id, layer, current_user, db)
[async_fn]: get_family_context(focus_person, depth, include_timeline, current_user, db)
[async_fn]: progressive_search(query, current_user, db)

---
### FILE: backend/app/api/health.py
[local_deps]: app.database, app.core.redis_url, app.celery_app, app.utils.security
[ext_deps]: os, fastapi, logging, asyncio, sqlalchemy, httpx, nats, redis, datetime, typing
[async_fn]: _check_database()
[async_fn]: _check_redis()
[async_fn]: _check_vault()
[async_fn]: _check_nats()
[async_fn]: _check_ollama()
[async_fn]: comprehensive_health()
[async_fn]: deep_health(db)
[async_fn]: auth_check()
[async_fn]: celery_health_check()

---
### FILE: backend/app/api/internal.py
[local_deps]: app.database, app.models.user, app.schemas.document, app.api.documents_upload
[ext_deps]: os, fastapi, logging, sqlalchemy, hmac
[async_fn]: _get_bot_user(db)
[fn]: _validate_api_key(key)
[async_fn]: internal_upload(file, bucket, title, tags, document_type, x_bot_api_key, db)

---
### FILE: backend/app/api/knowledge_graph.py
[local_deps]: app.database, app.services.relationship_service, app.api.deps, app.services.entity_extraction_service, app.models.user, app.models.document, app.models.knowledge_graph, app.services.timeline_service
[ext_deps]: uuid, fastapi, logging, sqlalchemy, datetime, typing
[async_fn]: extract_entities_from_document(document_id, current_user, db)
[async_fn]: list_entities(entity_type, page, page_size, search, current_user, db)
[async_fn]: get_entity_details(entity_id, current_user, db)
[async_fn]: get_knowledge_graph(entity_type, limit, current_user, db)
[async_fn]: get_entity_connections(entity_name, current_user, db)
[async_fn]: get_entity_neighbors(entity_id, relation_type, current_user, db)
[async_fn]: get_shortest_path(source_name, target_name, current_user, db)
[async_fn]: get_timeline(start_date, end_date, current_user, db)
[async_fn]: get_entity_timeline(entity_name, current_user, db)
[async_fn]: get_timeline_insights(limit, current_user, db)
[async_fn]: get_entity_clusters(min_size, current_user, db)
[async_fn]: extract_entities_batch(document_ids, current_user, db)

---
### FILE: backend/app/api/notes.py
[local_deps]: app.database, app.services.space_service, app.models.note_audio, app.api.deps, app.services.note_service, app.models.note, app.schemas.tag, app.models.user, app.schemas.note
[ext_deps]: uuid, fastapi, logging, os, sqlalchemy, datetime
[async_fn]: create_note(data, current_user, db)
[async_fn]: list_notes(page, page_size, tag, current_user, db)
[async_fn]: search_notes(q, page, page_size, current_user, db)
[async_fn]: get_note(note_id, current_user, db)
[async_fn]: update_note(note_id, data, current_user, db)
[async_fn]: delete_note(note_id, current_user, db)
[async_fn]: upload_note_audio(note_id, file, transcript, current_user, db)
[fn]: _to_response(note, tags)

---
### FILE: backend/app/api/pipeline_admin.py
[local_deps]: app.database, app.celery_app, app.api.deps, app.models.document, app.tasks.pipeline_orchestrator, app.core.redis_url, app.models.pipeline
[ext_deps]: redis, sqlalchemy, fastapi, asyncio
[async_fn]: pipeline_status(db)
[async_fn]: retry_failed_pipeline_stages(stage, limit, db)

---
### FILE: backend/app/api/push.py
[local_deps]: app.database, app.models.push_subscription, app.api.deps, app.models.user, app.schemas.push
[ext_deps]: uuid, os, fastapi, logging, sqlalchemy
[async_fn]: get_vapid_public_key()
[async_fn]: subscribe_push(data, current_user, db)
[async_fn]: unsubscribe_push(data, current_user, db)

---
### FILE: backend/app/api/reports.py
[local_deps]: app.schemas.reports, app.celery_app, app.api.deps, app.tasks.report_tasks, app.models.user
[ext_deps]: celery, fastapi, logging, typing
[async_fn]: generate_report(request, current_user)
[async_fn]: get_report_status(task_id, current_user)

---
### FILE: backend/app/api/search_agent_router.py
[local_deps]: app.database, app.api.deps, app.services.input_guard, app.services.search_service, app.models.user, app.services.search_agent, app.models.document, app.services.search_models
[ext_deps]: json, uuid, time, logging, asyncio, fastapi, sqlalchemy
[fn]: _role_from_user(user)
[fn]: _sse_event(event, data)
[fn]: _convert_search_results_to_chunks(search_results)
[fn]: _deduplicate_chunks(chunks)
[async_fn]: search(request, current_user, db)
[async_fn]: search_stream(request, current_user, db)
[async_fn]: search_global(q, types, page, page_size, current_user, db)
[async_fn]: get_intent(payload, current_user)
[async_fn]: search_history(limit, current_user, db)
[async_fn]: _save_search_history(db, user_id, response)

---
### FILE: backend/app/api/search_feedback.py
[local_deps]: app.api.deps, app.models.user, app.database
[ext_deps]: uuid, fastapi, logging, sqlalchemy, pydantic, hashlib
[class]: FeedbackRequest { methods: [] }
[async_fn]: submit_feedback(request, current_user, db)
[async_fn]: get_feedback_stats(document_id, current_user, db)

---
### FILE: backend/app/api/search_suggest.py
[local_deps]: app.api.deps, app.models.document, app.models.user, app.database
[ext_deps]: sqlalchemy, fastapi, logging
[fn]: _get_user_bucket_filter(user)
[async_fn]: search_suggest(q, limit, current_user, db)

---
### FILE: backend/app/api/smart_folders.py
[local_deps]: app.database, app.models.smart_folder, app.celery_app, app.models.audit, app.api.deps, app.models.note, app.tasks.collection_report_tasks, app.models.user, app.schemas.collection, app.tasks.smart_folder_tasks, app.schemas.smart_folder
[ext_deps]: json, celery, uuid, fastapi, logging, asyncio, sqlalchemy, typing
[async_fn]: _create_audit_log(db, user_id, action, resource_type, resource_id, details)
[fn]: _report_to_response(report)
[async_fn]: create_smart_folder(request, current_user)
[async_fn]: get_smart_folder(smart_folder_id, current_user, db)
[async_fn]: refresh_smart_folder(smart_folder_id, current_user, db)
[async_fn]: refine_smart_folder(smart_folder_id, request, current_user, db)
[async_fn]: save_smart_folder_as_note(smart_folder_id, request, current_user, db)
[async_fn]: get_smart_folder_db_status(smart_folder_id, current_user, db)
[async_fn]: get_generation_task_status(task_id, current_user)
[async_fn]: generate_smart_folder_legacy(request, current_user)
[async_fn]: generate_collection_report(request, current_user)
[async_fn]: get_collection_report_status(task_id, current_user)
[async_fn]: get_report_templates(current_user)
[async_fn]: get_report(report_id, current_user, db)
[async_fn]: stream_smart_folder_generation(request, current_user, db)

---
### FILE: backend/app/api/spaces.py
[local_deps]: app.database, app.services.space_service, app.api.deps, app.schemas.tag, app.models.user, app.schemas.space, app.tasks.space_tasks
[ext_deps]: sqlalchemy, uuid, fastapi, logging
[async_fn]: create_space(data, current_user, db)
[async_fn]: list_spaces(page, page_size, search, current_user, db)
[async_fn]: get_space(space_id, item_type, current_user, db)
[async_fn]: update_space(space_id, data, current_user, db)
[async_fn]: delete_space(space_id, current_user, db)
[async_fn]: add_item_to_space(space_id, data, current_user, db)
[async_fn]: remove_item_from_space(space_id, item_id, current_user, db)
[async_fn]: add_rule(space_id, data, current_user, db)
[async_fn]: update_rule(space_id, rule_id, data, current_user, db)
[async_fn]: delete_rule(space_id, rule_id, current_user, db)
[async_fn]: sync_space(space_id, current_user, db)
[async_fn]: search_in_space(space_id, q, item_type, current_user, db)

---
### FILE: backend/app/api/status.py
[local_deps]: app.services.llm_gateway, app.api.deps, app.models.user, app.tasks.pipeline_orchestrator, app.core.redis_url
[ext_deps]: redis, fastapi, typing
[async_fn]: pipeline_health(current_user)
[async_fn]: api_status()

---
### FILE: backend/app/api/subscriptions.py
[local_deps]: app.database, app.api.deps, app.tasks.subscription_tasks, app.models.user, app.schemas.subscription, app.models.subscription
[ext_deps]: sqlalchemy, uuid, fastapi, logging
[fn]: _parse_uuid(s)
[async_fn]: list_subscriptions(current_user, db)
[async_fn]: test_email(current_user)
[async_fn]: sync_subscriptions(items, current_user, db)

---
### FILE: backend/app/api/tags.py
[local_deps]: app.api.deps, app.models.tag
[ext_deps]: sqlalchemy, fastapi
[async_fn]: get_tag_suggestions(q, limit, db, _user)

---
### FILE: backend/app/api/tasks.py
[local_deps]: app.schemas.task, app.database, app.services.space_service, app.api.deps, app.services.task_service, app.schemas.tag, app.models.user
[ext_deps]: sqlalchemy, uuid, fastapi, logging
[async_fn]: create_task(data, current_user, db)
[async_fn]: list_tasks(page, page_size, tag, current_user, db)
[async_fn]: search_tasks(q, page, page_size, current_user, db)
[async_fn]: get_task(task_id, current_user, db)
[async_fn]: update_task(task_id, data, current_user, db)
[async_fn]: delete_task(task_id, current_user, db)
[fn]: _to_response(task, tags)

---
### FILE: backend/app/api/voice.py
[local_deps]: app.models.note_audio, app.api.deps, app.services.storage_service, app.models.note, app.models.user, app.services.whisper_service, app.models.document
[ext_deps]: io, os, uuid, logging, asyncio, fastapi, sqlalchemy, tempfile
[fn]: _is_safari(user_agent)
[async_fn]: _transcode_ogg_to_mp3(audio_bytes)
[async_fn]: _stream_audio_file(file_path, user_agent)
[async_fn]: transcribe_audio(file, language, current_user)
[async_fn]: stream_audio(audio_id, request, current_user, db)

---
### FILE: backend/app/celery_app.py
[local_deps]: app.core.redis_url, app.core.config
[ext_deps]: celery, os, dotenv

---
### FILE: backend/app/core/__init__.py

---
### FILE: backend/app/core/config.py
[ext_deps]: os, logging, pathlib, urllib, pydantic_settings, pydantic
[fn]: load_secret(env_key)
[class]: Settings { methods: [validate_not_placeholder, REDIS_URL, ASYNC_DATABASE_URL, SYNC_DATABASE_URL] }

---
### FILE: backend/app/core/push.py
[ext_deps]: json, os, time, logging, base64, urllib, httpx, struct, cryptography
[fn]: _b64url_encode(data)
[fn]: _b64url_decode(data)
[class]: VAPIDHelper { methods: [__init__, is_configured, public_key, _sign_jwt, send_push, _encrypt_payload] }
[fn]: send_task_alarm_push(endpoint, p256dh, auth, task_title, task_notes)

---
### FILE: backend/app/core/redis_url.py
[ext_deps]: os, urllib
[fn]: safe_redis_url(default_host)

---
### FILE: backend/app/database.py
[local_deps]: app.models.base, app.middleware.rls
[ext_deps]: os, fastapi, sqlalchemy, collections, pgvector, dotenv, typing
[async_fn]: get_db(request)
[async_fn]: init_pgvector()
[async_fn]: create_all_tables()
[fn]: get_vector_type()

---
### FILE: backend/app/limiter.py
[ext_deps]: os, urllib, slowapi
[fn]: _limiter_redis_url()

---
### FILE: backend/app/main.py
[local_deps]: app.database, app.middleware.csrf, app.middleware.transaction, app.limiter, app.api, app.services.messaging, app.middleware.rls, app.services.prometheus_metrics, app.core.redis_url
[ext_deps]: uuid, os, time, logging, fastapi, sqlalchemy, slowapi, starlette, uvicorn, collections, contextlib, threading, redis, dotenv, typing
[class]: ErrorRateTracker { methods: [__init__, record_request, get_error_rate, get_request_count] }
[class]: RequestIDMiddleware { methods: [dispatch] }
[class]: ErrorRateMiddleware { methods: [dispatch] }
[async_fn]: lifespan(app)
[fn]: _error_response(error_type, message, detail, http_status)
[async_fn]: validation_exception_handler(request, exc)
[async_fn]: sqlalchemy_exception_handler(request, exc)
[async_fn]: generic_exception_handler(request, exc)
[async_fn]: root()
[async_fn]: prometheus_metrics()

---
### FILE: backend/app/main_minimal.py
[local_deps]: app.database, app.services.embedding_service, app.services.cache_monitor, app.api, app.services.monitoring, app.services.prometheus_metrics, app.core.redis_url
[ext_deps]: os, time, logging, fastapi, sqlalchemy, uvicorn, httpx, contextlib, redis, datetime, dotenv
[async_fn]: lifespan(app)
[async_fn]: root()
[async_fn]: health()
[async_fn]: embedding_health()
[async_fn]: health_detailed()
[async_fn]: get_cost_stats(days)
[async_fn]: get_queue_stats()
[async_fn]: get_system_stats()
[async_fn]: get_alerts()
[async_fn]: prometheus_metrics()
[async_fn]: api_status()

---
### FILE: backend/app/middleware/csrf.py
[ext_deps]: secrets, starlette, hmac, logging
[fn]: generate_csrf_token()
[class]: CSRFMiddleware { methods: [dispatch] }

---
### FILE: backend/app/middleware/rls.py
[local_deps]: app.utils.security
[ext_deps]: logging, sqlalchemy, jose, starlette, dataclasses
[class]: RLSContext { methods: [] }
[fn]: extract_rls_context(request)
[async_fn]: apply_rls_context(session, context)
[async_fn]: set_rls_context(request, call_next)

---
### FILE: backend/app/middleware/transaction.py
[local_deps]: app.database
[ext_deps]: starlette
[class]: TransactionMiddleware { methods: [dispatch] }

---
### FILE: backend/app/models/__init__.py
[local_deps]: app.models.collection, app.models.note_audio, app.models.smart_folder, app.models.pattern_insight, app.models.push_subscription, app.models.document, app.models.chat, app.models.failed_task, app.models.subscription, app.models.base, app.models.milestone, app.models.task, app.models.tag, app.models.user, app.models.bookmark, app.models.article, app.models.audit, app.models.note, app.models.knowledge_graph, app.models.processing, app.models.space, app.models.pipeline

---
### FILE: backend/app/models/article.py
[local_deps]: app.models.base, app.models.document
[ext_deps]: sqlalchemy, enum, uuid, pgvector
[class]: ArticleStatus { methods: [] }
[class]: Article { methods: [__repr__] }
[fn]: _article_init(target, args, kwargs)

---
### FILE: backend/app/models/audit.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: AuditAction { methods: [] }
[class]: AuditLog { methods: [__repr__] }

---
### FILE: backend/app/models/audit_log.py
[local_deps]: app.models.audit

---
### FILE: backend/app/models/base.py
[ext_deps]: sqlalchemy, uuid, typing
[class]: GUID { methods: [__init__, load_dialect_impl, process_bind_param, process_result_value] }
[class]: TimestampMixin { methods: [__init__] }

---
### FILE: backend/app/models/bookmark.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: BookmarkBucket { methods: [] }
[class]: Bookmark { methods: [] }

---
### FILE: backend/app/models/chat.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: LLMProvider { methods: [] }
[class]: MessageRole { methods: [] }
[class]: ChatSession { methods: [__repr__] }
[class]: ChatMessage { methods: [__repr__] }

---
### FILE: backend/app/models/collection.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: CollectionVisibility { methods: [] }
[class]: CollectionType { methods: [] }
[class]: CollectionStatus { methods: [] }
[class]: Collection { methods: [__repr__] }
[class]: CollectionItem { methods: [__repr__] }
[class]: CollectionChatSession { methods: [__repr__] }
[fn]: _collection_init(target, args, kwargs)

---
### FILE: backend/app/models/deferred_query.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid, datetime
[class]: QueryStatus { methods: [] }
[class]: DeferredQuery { methods: [__repr__] }

---
### FILE: backend/app/models/document.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid, pgvector
[class]: DocumentBucket { methods: [] }
[class]: DocumentStatus { methods: [] }
[class]: DocumentLanguage { methods: [] }
[class]: Document { methods: [__repr__] }
[class]: DocumentTag { methods: [__repr__] }
[class]: DocumentChunk { methods: [__repr__, highlight_text, to_dict] }
[fn]: _document_init(target, args, kwargs)
[fn]: _document_chunk_init(target, args, kwargs)

---
### FILE: backend/app/models/failed_task.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, uuid
[class]: FailedCeleryTask { methods: [] }

---
### FILE: backend/app/models/knowledge_graph.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: EntityType { methods: [] }
[class]: RelationType { methods: [] }
[class]: Entity { methods: [__repr__] }
[class]: EntityRelationship { methods: [__repr__] }
[class]: EntityMention { methods: [__repr__] }
[class]: TimelineEvent { methods: [__repr__] }

---
### FILE: backend/app/models/milestone.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, uuid
[class]: Milestone { methods: [__repr__] }

---
### FILE: backend/app/models/note.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: NoteBucket { methods: [] }
[class]: Note { methods: [] }

---
### FILE: backend/app/models/note_audio.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, uuid
[class]: NoteAudio { methods: [] }

---
### FILE: backend/app/models/pattern_insight.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: PatternInsightType { methods: [] }
[class]: PatternInsight { methods: [__repr__] }

---
### FILE: backend/app/models/pipeline.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: StageEnum { methods: [next_stage] }
[class]: StageStatus { methods: [] }
[class]: PipelineStage { methods: [__init__, __repr__] }

---
### FILE: backend/app/models/processing.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: TaskType { methods: [] }
[class]: TaskStatus { methods: [] }
[class]: ProcessingQueue { methods: [__repr__, update_progress] }

---
### FILE: backend/app/models/push_subscription.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, uuid
[class]: PushSubscription { methods: [] }

---
### FILE: backend/app/models/smart_folder.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: SmartFolderStatus { methods: [] }
[class]: RelationshipType { methods: [] }
[class]: SmartFolder { methods: [__repr__] }
[class]: SmartFolderReport { methods: [__repr__] }

---
### FILE: backend/app/models/space.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: SpaceBucket { methods: [] }
[class]: SpaceItemType { methods: [] }
[class]: SpaceRuleType { methods: [] }
[class]: Space { methods: [] }
[class]: SpaceItem { methods: [] }
[class]: SpaceRule { methods: [] }

---
### FILE: backend/app/models/subscription.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: BillingCycle { methods: [] }
[class]: SubscriptionStatus { methods: [] }
[class]: Subscription { methods: [] }

---
### FILE: backend/app/models/tag.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: TagType { methods: [] }
[class]: TargetType { methods: [] }
[class]: Tag { methods: [] }

---
### FILE: backend/app/models/task.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: TaskStatus { methods: [] }
[class]: TaskPriority { methods: [] }
[class]: TaskBucket { methods: [] }
[class]: Task { methods: [] }

---
### FILE: backend/app/models/user.py
[local_deps]: app.models.base
[ext_deps]: sqlalchemy, enum, uuid
[class]: UserRole { methods: [] }
[class]: User { methods: [__repr__] }

---
### FILE: backend/app/network_utils.py
[ext_deps]: time, logging, asyncio, httpx, tenacity, collections, typing, functools
[fn]: with_retry(max_attempts, min_wait, max_wait, retry_exceptions)
[class]: CircuitBreaker { methods: [__init__, _can_execute, _record_success, _record_failure, status] }
[class]: ResilientAsyncClient { methods: [__init__, _get_client, close, request, get, post, put, delete, get_circuit_breaker_status] }
[class]: CircuitBreakerOpenError { methods: [] }
[async_fn]: resilient_request(method, url, max_attempts, timeout)

---
### FILE: backend/app/performance.py
[local_deps]: app.database
[ext_deps]: json, sqlalchemy, hashlib, functools
[fn]: create_performance_indexes(engine)
[fn]: configure_database_settings(engine)
[fn]: enable_vector_search_optimization(engine)
[fn]: create_materialized_views(engine)
[fn]: refresh_materialized_views(engine)
[fn]: setup_query_caching(redis_client)
[class]: QueryOptimizer { methods: [optimize_search_query, paginate_query, get_search_hints] }
[fn]: apply_performance_tuning(engine)

---
### FILE: backend/app/schemas/__init__.py
[local_deps]: app.schemas.pagination, app.schemas.document, app.schemas.admin, app.schemas.token, app.schemas.search, app.schemas.collection, app.schemas.chat, app.schemas.smart_folder, app.schemas.user

---
### FILE: backend/app/schemas/admin.py
[local_deps]: app.schemas.user
[ext_deps]: uuid, datetime, re, pydantic
[class]: SystemStats { methods: [] }
[class]: QueueStats { methods: [] }
[class]: AnomalyDocument { methods: [] }
[class]: AnomalyBucketResponse { methods: [] }
[class]: DashboardResponse { methods: [] }
[class]: UserManagementResponse { methods: [] }
[class]: UserListResponse { methods: [] }
[class]: UserUpdateByAdmin { methods: [validate_role_change] }
[class]: UserCreateByAdmin { methods: [validate_password] }
[class]: AuditLogEntry { methods: [] }
[class]: AuditLogResponse { methods: [] }
[class]: AdminStatsResponse { methods: [] }
[class]: PasswordReset { methods: [validate_password] }
[class]: PipelineStageStats { methods: [] }
[class]: PipelineStatsResponse { methods: [] }
[class]: UploadsHistoryPoint { methods: [] }
[class]: UploadsHistoryResponse { methods: [] }
[class]: ArticlesHistoryPoint { methods: [] }
[class]: ArticlesHistoryResponse { methods: [] }
[class]: ArticlesStats { methods: [] }

---
### FILE: backend/app/schemas/article.py
[ext_deps]: datetime, uuid, pydantic
[class]: ArticleResponse { methods: [] }
[class]: ArticleListResponse { methods: [] }
[class]: ArticleGenerateRequest { methods: [] }
[class]: ArticleGenerateResponse { methods: [] }
[class]: ArticleBackfillResponse { methods: [] }

---
### FILE: backend/app/schemas/auth.py
[ext_deps]: pydantic
[class]: ForgotPasswordRequest { methods: [] }
[class]: ResendVerificationRequest { methods: [] }
[class]: TelegramAuthRequest { methods: [] }

---
### FILE: backend/app/schemas/bookmark.py
[local_deps]: app.schemas.tag
[ext_deps]: datetime, uuid, pydantic, enum
[class]: BookmarkBucket { methods: [] }
[class]: BookmarkCreate { methods: [] }
[class]: BookmarkUpdate { methods: [] }
[class]: BookmarkResponse { methods: [] }
[class]: BookmarkListResponse { methods: [] }

---
### FILE: backend/app/schemas/chat.py
[ext_deps]: datetime, uuid, pydantic, enum
[class]: LLMProvider { methods: [] }
[class]: MessageRole { methods: [] }
[class]: ChatSessionCreate { methods: [] }
[class]: ChatSessionResponse { methods: [] }
[class]: ChatSessionListResponse { methods: [] }
[class]: SourceDocument { methods: [] }
[class]: ChatMessageCreate { methods: [] }
[class]: ChatMessageResponse { methods: [] }
[class]: ChatMessageListResponse { methods: [] }
[class]: ChatStreamChunk { methods: [] }

---
### FILE: backend/app/schemas/collection.py
[ext_deps]: enum, uuid, pydantic, datetime, typing
[class]: CollectionVisibility { methods: [] }
[class]: CollectionType { methods: [] }
[class]: ParsedIntentResponse { methods: [] }
[class]: CollectionBase { methods: [] }
[class]: CollectionCreate { methods: [] }
[class]: CollectionUpdate { methods: [] }
[class]: CollectionItemBase { methods: [] }
[class]: CollectionItemCreate { methods: [] }
[class]: CollectionItemUpdate { methods: [] }
[class]: CollectionItemResponse { methods: [] }
[class]: CollectionResponse { methods: [] }
[class]: CollectionDetailResponse { methods: [] }
[class]: CollectionListResponse { methods: [] }
[class]: CollectionPreviewRequest { methods: [] }
[class]: CollectionPreviewResponse { methods: [] }
[class]: CollectionChatCreate { methods: [] }
[class]: CollectionChatResponse { methods: [] }
[class]: CollectionBulkAddRequest { methods: [] }
[class]: CollectionBulkRemoveRequest { methods: [] }
[class]: CollectionRefreshRequest { methods: [] }
[class]: CollectionStatsResponse { methods: [] }
[class]: SmartFolderGenerateRequest { methods: [] }
[class]: SmartFolderResponse { methods: [] }
[class]: ReportFormat { methods: [] }
[class]: CollectionReportRequest { methods: [] }
[class]: CollectionReportResponse { methods: [] }
[class]: ExportFormat { methods: [] }
[class]: CollectionExportResponse { methods: [] }

---
### FILE: backend/app/schemas/document.py
[ext_deps]: datetime, uuid, pydantic, enum
[class]: DocumentBucket { methods: [] }
[class]: DocumentStatus { methods: [] }
[class]: DocumentLanguage { methods: [] }
[class]: DocumentBase { methods: [] }
[class]: DocumentCreate { methods: [] }
[class]: DocumentUpdate { methods: [validate_stored_filename] }
[class]: DocumentResponse { methods: [compute_error_message] }
[class]: DocumentListResponse { methods: [] }
[class]: DocumentTagCreate { methods: [] }
[class]: DocumentTagResponse { methods: [] }
[class]: DocumentUploadResponse { methods: [] }
[class]: DocumentChunkResponse { methods: [] }
[class]: DocumentStatusResponse { methods: [] }
[class]: BatchUploadResponse { methods: [] }
[class]: BatchStatusResponse { methods: [] }
[class]: ReprocessRequest { methods: [] }

---
### FILE: backend/app/schemas/note.py
[local_deps]: app.schemas.tag
[ext_deps]: datetime, uuid, pydantic, enum
[class]: NoteBucket { methods: [] }
[class]: NoteCreate { methods: [] }
[class]: NoteUpdate { methods: [] }
[class]: NoteResponse { methods: [] }
[class]: NoteListResponse { methods: [] }

---
### FILE: backend/app/schemas/pagination.py
[ext_deps]: base64, json, pydantic, typing
[class]: PaginationParams { methods: [offset] }
[class]: PaginatedResponse { methods: [create] }
[class]: CursorPaginationParams { methods: [] }
[class]: CursorPaginatedResponse { methods: [] }
[fn]: encode_cursor(data)
[fn]: decode_cursor(cursor)

---
### FILE: backend/app/schemas/push.py
[ext_deps]: datetime, uuid, pydantic
[class]: PushSubscriptionCreate { methods: [] }
[class]: PushSubscriptionResponse { methods: [] }

---
### FILE: backend/app/schemas/reports.py
[ext_deps]: pydantic
[class]: GenerateReportRequest { methods: [] }
[class]: GenerateReportResponse { methods: [] }

---
### FILE: backend/app/schemas/search.py
[ext_deps]: uuid, pydantic
[class]: SearchRequest { methods: [] }
[class]: SearchResultChunk { methods: [] }
[class]: SearchResponse { methods: [] }

---
### FILE: backend/app/schemas/smart_folder.py
[local_deps]: app.models.smart_folder
[ext_deps]: datetime, uuid, pydantic, typing
[class]: SmartFolderBase { methods: [] }
[class]: SmartFolderCreate { methods: [] }
[class]: SmartFolderUpdate { methods: [] }
[class]: SmartFolderResponse { methods: [] }
[class]: SmartFolderListResponse { methods: [] }
[class]: CitationEntry { methods: [] }
[class]: ReportSection { methods: [] }
[class]: SourceQuality { methods: [] }
[class]: GeneratedContent { methods: [] }
[class]: SmartFolderReportResponse { methods: [] }
[class]: SmartFolderGenerateRequest { methods: [] }
[class]: SmartFolderRefineRequest { methods: [] }
[class]: SmartFolderSaveRequest { methods: [] }
[class]: GenerationStatusResponse { methods: [] }
[class]: MilestoneBase { methods: [] }
[class]: MilestoneCreate { methods: [] }
[class]: MilestoneResponse { methods: [] }
[class]: PatternInsightBase { methods: [] }
[class]: PatternInsightCreate { methods: [] }
[class]: PatternInsightResponse { methods: [] }

---
### FILE: backend/app/schemas/space.py
[local_deps]: app.schemas.tag
[ext_deps]: datetime, uuid, pydantic, enum
[class]: SpaceBucket { methods: [] }
[class]: SpaceItemType { methods: [] }
[class]: SpaceRuleType { methods: [] }
[class]: SpaceCreate { methods: [] }
[class]: SpaceUpdate { methods: [] }
[class]: SpaceItemResponse { methods: [] }
[class]: SpaceRuleResponse { methods: [] }
[class]: SpaceResponse { methods: [] }
[class]: SpaceDetailResponse { methods: [] }
[class]: SpaceListResponse { methods: [] }
[class]: SpaceItemAdd { methods: [] }
[class]: SpaceRuleCreate { methods: [] }
[class]: SpaceRuleUpdate { methods: [] }

---
### FILE: backend/app/schemas/subscription.py
[ext_deps]: datetime, uuid, pydantic
[class]: SubscriptionSyncItem { methods: [] }
[class]: SubscriptionResponse { methods: [] }
[class]: SubscriptionListResponse { methods: [] }

---
### FILE: backend/app/schemas/tag.py
[ext_deps]: datetime, uuid, pydantic, enum
[class]: TagType { methods: [] }
[class]: TargetType { methods: [] }
[class]: TagCreate { methods: [] }
[class]: TagResponse { methods: [] }
[class]: TagListResponse { methods: [] }

---
### FILE: backend/app/schemas/task.py
[local_deps]: app.schemas.tag
[ext_deps]: datetime, uuid, pydantic, enum
[class]: TaskStatus { methods: [] }
[class]: TaskPriority { methods: [] }
[class]: TaskBucket { methods: [] }
[class]: TaskCreate { methods: [] }
[class]: TaskUpdate { methods: [] }
[class]: TaskResponse { methods: [] }
[class]: TaskListResponse { methods: [] }

---
### FILE: backend/app/schemas/token.py
[ext_deps]: pydantic
[class]: Token { methods: [] }
[class]: TokenPayload { methods: [] }
[class]: LoginResponse { methods: [] }

---
### FILE: backend/app/schemas/user.py
[ext_deps]: enum, uuid, re, pydantic, datetime, typing
[class]: UserRole { methods: [] }
[class]: UserBase { methods: [] }
[class]: UserCreate { methods: [validate_password] }
[class]: UserUpdate { methods: [] }
[class]: UserInDB { methods: [convert_uuid_to_str] }
[class]: UserPublic { methods: [convert_uuid_to_str] }

---
### FILE: backend/app/services/_spreadsheet_extractor.py
[ext_deps]: json, sys, openpyxl, xlrd
[fn]: extract_xlsx(file_path)
[fn]: extract_xls(file_path)

---
### FILE: backend/app/services/agent_identity.py
[fn]: build_identity_block(agent_name, mission, persona, constraints, include_vault_protocol, extra_sections)
[fn]: build_service_prompt(service_name, mission, constraints, task_prompt, persona, include_vault_protocol)

---
### FILE: backend/app/services/agents/__init__.py
[local_deps]: app.services.agents.researcher_agent, app.services.agents.answer_agent, app.services.agents.agent_orchestrator, app.services.agents.clarification_agent, app.services.agents.verification_agent

---
### FILE: backend/app/services/agents/agent_orchestrator.py
[local_deps]: app.services.agents.researcher_agent, app.services.agents.clarification_agent, app.services.agents.verification_agent, app.services.agents.answer_agent
[ext_deps]: enum, time, logging, dataclasses, collections, datetime, typing
[class]: OrchestratorState { methods: [] }
[class]: AgentResult { methods: [] }
[class]: OrchestratorRequest { methods: [] }
[class]: OrchestratorResult { methods: [__post_init__] }
[class]: AgentOrchestrator { methods: [__init__, orchestrate, _run_clarification, _run_research, _run_verification, _run_answer_generation, _notify_progress, stream_orchestrate] }

---
### FILE: backend/app/services/agents/answer_agent.py
[local_deps]: app.services.agent_identity, app.services.llm_gateway
[ext_deps]: json, logging, re, dataclasses, typing
[class]: AnswerRequest { methods: [] }
[class]: AnswerResult { methods: [__post_init__] }
[class]: AnswerAgent { methods: [__init__, generate_answer, _determine_answer_type, _build_generation_context, _generate_answer_content, _extract_key_points, _prepare_sources, _generate_caveats, _suggest_followup_questions, _calculate_answer_confidence] }

---
### FILE: backend/app/services/agents/clarification_agent.py
[local_deps]: app.services.agent_identity, app.services.llm_gateway
[ext_deps]: json, dataclasses, logging, typing
[class]: ClarificationRequest { methods: [] }
[class]: ClarificationResult { methods: [__post_init__] }
[class]: ClarificationAgent { methods: [__init__, _has_confidential_documents, clarify, _fallback_clarification, _extract_json, suggest_search_improvements] }

---
### FILE: backend/app/services/agents/researcher_agent.py
[local_deps]: app.services.knowledge_graph.models, app.services.llm_gateway, app.services.knowledge_graph.pool, app.services.search_service, app.services.graph_rag_service, app.services.agent_identity, app.services.knowledge_graph.traversal, app.services.embed_client
[ext_deps]: json, logging, re, dataclasses, collections, typing
[class]: ResearchQuery { methods: [] }
[class]: ResearchResult { methods: [__post_init__] }
[class]: ResearcherAgent { methods: [__init__, _is_graph_traversal_query, _extract_traversal_pair, _run_graph_traversal, _has_confidential_documents, _get_llm_service, research, _gather_context, _extract_themes, _find_related_topics, _identify_information_gaps, _suggest_followup_queries, _prepare_sources, _calculate_research_confidence, explore_entity_connections] }

---
### FILE: backend/app/services/agents/verification_agent.py
[local_deps]: app.services.agent_identity, app.services.llm_gateway
[ext_deps]: json, dataclasses, logging, typing
[class]: VerificationRequest { methods: [] }
[class]: VerificationResult { methods: [__post_init__] }
[class]: VerificationAgent { methods: [__init__, verify, verify_batch, _analyze_claim, _check_source_for_claim, _generate_verification_notes, detect_inconsistencies, _find_conflicts, assess_source_reliability] }

---
### FILE: backend/app/services/alert_service.py
[local_deps]: app.services.email_notifier, app.services.telegram_notifier
[ext_deps]: logging
[class]: AlertService { methods: [__init__, send_alert, send_task_failure_alert, send_anomaly_alert, telegram_configured, email_configured] }

---
### FILE: backend/app/services/article_generation_service.py
[local_deps]: app.services.llm_gateway
[ext_deps]: json, logging, asyncio, httpx, hashlib, typing
[fn]: _content_hash(title, body)
[fn]: _title_similarity(a, b)
[class]: ArticleGenerationService { methods: [__init__, create_chunk_windows, _create_windows, extract_articles_from_window, _parse_articles_json, deduplicate_articles, generate_articles_for_document] }

---
### FILE: backend/app/services/auto_tagging_service.py
[local_deps]: app.services.agent_identity, app.models.tag, app.models.document, app.services.llm_gateway
[ext_deps]: json, uuid, logging, warnings, sqlalchemy, datetime, typing
[class]: AutoTaggingService { methods: [__init__, tag_document, _prepare_text_for_analysis, _build_tagging_system_prompt, _extract_tags_with_llm, _extract_json, detect_language, suggest_similar_documents] }

---
### FILE: backend/app/services/base_llm_service.py
[ext_deps]: collections, abc, typing
[class]: BaseLLMService { methods: [chat_completion, health_check] }

---
### FILE: backend/app/services/bookmark_service.py
[local_deps]: app.models.user, app.models.tag, app.models.bookmark
[ext_deps]: sqlalchemy, uuid, logging, urllib
[fn]: _escape_like(value)
[class]: BookmarkService { methods: [create_bookmark, get_bookmark, list_bookmarks, update_bookmark, delete_bookmark, search_bookmarks, get_tags_for_bookmark, _apply_access_filter, _extract_domain] }

---
### FILE: backend/app/services/cache_monitor.py
[ext_deps]: json, logging, threading, datetime, typing
[class]: DailyCacheStats { methods: [__init__, record_hit, record_miss, record_query, hits, misses, tokens_saved, queries, hit_rate, to_dict] }
[class]: CacheMonitor { methods: [__init__, _get_or_create_today_stats, _cleanup_old_stats, record_cache_hit, record_cache_miss, get_hit_rate, get_stats_summary, get_today_stats, get_tokens_saved_today, get_total_tokens_saved, reset_today_stats, get_all_dates, export_stats_json, get_retention_days, set_retention_days] }

---
### FILE: backend/app/services/chat_service.py
[local_deps]: app.services.llm_gateway, app.database, app.services.pii_detection_service, app.models.chat, app.services.search_service, app.services.agent_identity, app.models.user, app.services.cache_monitor, app.services.llm_router, app.models.document, app.services.prometheus_metrics, app.services.context_block_service
[ext_deps]: json, uuid, time, logging, asyncio, sqlalchemy, re, collections, typing
[class]: ChatService { methods: [__init__, get_conversation_history, retrieve_relevant_chunks, build_rag_context, generate_chat_response, generate_chat_response_stream, _has_raw_confidential_context] }

---
### FILE: backend/app/services/chunking_service.py
[ext_deps]: transformers, logging
[fn]: _get_tokenizer()
[fn]: _count_tokens(text)
[fn]: _truncate_to_max_tokens(text, max_tokens)
[class]: ChunkingService { methods: [__init__, count_tokens, chunk_text, chunk_document] }

---
### FILE: backend/app/services/collection_chat_service.py
[local_deps]: app.models.collection, app.services.llm_gateway, app.models.audit, app.models.chat, app.services.agent_identity, app.models.user, app.models.document, app.services.context_block_service
[ext_deps]: json, uuid, logging, sqlalchemy, typing
[async_fn]: create_audit_log(db, user_id, action, resource_type, resource_id, details)
[class]: CollectionChatService { methods: [__init__, get_or_create_chat_session, chat_with_collection, _build_document_context, _chat_with_llm, _chat_with_ollama] }

---
### FILE: backend/app/services/collection_service.py
[local_deps]: app.models.collection, app.services.llm_gateway, app.services.search_service, app.services.agent_identity, app.models.user, app.schemas.collection, app.services.intent_parser, app.models.document, app.services.search_cache
[ext_deps]: uuid, logging, asyncio, sqlalchemy, datetime, typing
[class]: CollectionService { methods: [__init__, _get_user_visibility_filter, create_collection, create_collection_shell, build_collection_pipeline, preview_collection, refresh_collection, _understand_query, _gather_and_verify, _gather_documents_for_intent, _calculate_relevance, _invalidate_cache, _synthesize_summary, _generate_collection_summary, get_collection_stats] }

---
### FILE: backend/app/services/context_block_service.py
[local_deps]: app.core.redis_url, app.models.document
[ext_deps]: redis, sqlalchemy, datetime, logging
[fn]: _get_redis()
[async_fn]: generate_context_block(db)
[async_fn]: get_cached_context_block(db)
[fn]: invalidate_context_block()
[async_fn]: _build_block(db)
[async_fn]: _doc_stats(db, bucket)
[async_fn]: _date_range(db)
[async_fn]: _format_distribution(db)
[async_fn]: _top_topics(db, limit)
[async_fn]: _entity_summary(db)
[fn]: _shorten_mime(mime)

---
### FILE: backend/app/services/deduplication_service.py
[local_deps]: app.models.document
[ext_deps]: difflib, logging, sqlalchemy, hashlib, datetime
[class]: FileHash { methods: [__init__] }
[class]: DeduplicationService { methods: [__init__, calculate_hash, calculate_hash_from_chunks, is_duplicate, register_upload, _add_to_cache, find_similar_files, scan_for_duplicates, cleanup_duplicates] }

---
### FILE: backend/app/services/deferred_query_service.py
[local_deps]: app.services.llm_gateway
[ext_deps]: uuid, os, logging, datetime, typing
[class]: _InMemoryStore { methods: [__init__, add, get, list_pending, update, expire_old] }
[class]: DeferredQueryService { methods: [__init__, enqueue, process_pending, get_status, _call_ollama] }

---
### FILE: backend/app/services/dlq_service.py
[local_deps]: app.database, app.services.alert_service, app.models.failed_task
[ext_deps]: json, logging, asyncio, sqlalchemy, traceback, threading, typing
[class]: DeadLetterQueueService { methods: [store_failed_task, list_failed_tasks] }

---
### FILE: backend/app/services/document_orchestrator.py
[local_deps]: app.tasks.pipeline_tasks, app.models.audit, app.models.pipeline, app.services.storage_service, app.models.user, app.tasks.voice_tasks, app.models.document, app.services.deduplication_service, app.tasks.pipeline_orchestrator, app.schemas.document
[ext_deps]: json, fastapi, logging, asyncio, sqlalchemy, datetime, concurrent, typing
[fn]: get_file_extension(filename)
[fn]: get_mime_type(filename, content)
[fn]: validate_magic_bytes(filename, content)
[class]: DocumentOrchestrator { methods: [ingest_document, _assert_bucket_access, _validate_file, _create_document_record, _attach_user_tags, _log_confidential_upload, _maybe_dispatch_voice_transcription, _queue_for_processing] }

---
### FILE: backend/app/services/email_notifier.py
[ext_deps]: sendgrid, datetime, os, logging
[class]: EmailNotifier { methods: [__init__, is_configured, send_alert] }
[fn]: _build_html(subject, message, severity, metadata)

---
### FILE: backend/app/services/embed_client.py
[ext_deps]: os, time, random, logging, asyncio, httpx
[fn]: _base_urls()
[fn]: _pick_url(attempt)
[fn]: _is_retryable(exc)
[class]: EmbedClient { methods: [__init__, embedding_dim, can_embed, _clear_health_cache, health_check, _circuit_breaker_check, _record_failure, _record_success, _post_with_retry, encode, encode_single, encode_query, encode_async] }

---
### FILE: backend/app/services/embedding_service.py
[local_deps]: app.utils.circuit_breaker
[ext_deps]: gc, os, logging, asyncio, numpy, sentence_transformers, threading, torch, psutil, typing
[class]: EmbeddingService { methods: [__new__, __init__, model, is_loaded, can_embed, _load_model, get_memory_stats, health_check, encode, encode_single, encode_query, encode_async, calculate_similarity, get_average_embedding] }
[class]: ChunkingService { methods: [__init__, count_tokens, chunk_text, chunk_document] }

---
### FILE: backend/app/services/embedding_service_onnx.py
[ext_deps]: os, logging, numpy, transformers, pathlib, onnxruntime
[class]: EmbeddingServiceONNX { methods: [__init__, embedding_dim, model, is_loaded, can_embed, encode, encode_query, health_check, _ensure_loaded, _encode_raw] }

---
### FILE: backend/app/services/entity_extraction_service.py
[local_deps]: app.services.agent_identity, app.models.document, app.services.llm_gateway, app.models.knowledge_graph
[ext_deps]: json, logging, warnings, asyncio, sqlalchemy, datetime, typing
[class]: ExtractedEntity { methods: [__init__] }
[class]: ExtractedRelationship { methods: [__init__] }
[class]: EntityExtractionService { methods: [__init__, extract_entities_from_document, extract_entities_from_document_sync, _get_or_create_entity_sync, _create_relationship_sync, _create_timeline_event_sync, _prepare_document_text, _extract_with_llm, _extract_json, _get_or_create_entity, _create_relationship, _create_timeline_event, get_entity_graph, _get_color_for_type] }

---
### FILE: backend/app/services/graph_rag_service.py
[local_deps]: app.services.llm_gateway, app.services.agent_identity, app.models.document, app.models.knowledge_graph, app.services.context_block_service
[ext_deps]: logging, sqlalchemy, re, collections, typing
[class]: GraphRAGService { methods: [__init__, _strip_sensitive_content, _extract_bucket_from_results, enhance_search_with_graph, _extract_query_entities, _find_entities_in_results, _expand_entities, _build_graph_context, _rank_results_with_graph, generate_graph_aware_answer, find_entity_paths, get_entity_neighborhood] }

---
### FILE: backend/app/services/input_guard.py
[local_deps]: app.core.redis_url, app.services.pii_detection_service
[ext_deps]: logging, re, dataclasses, hashlib, redis
[class]: GuardResult { methods: [] }
[class]: InputGuard { methods: [__init__, _get_redis, process, _detect_language, _scan_pii, _classify_intent, _determine_vault, _check_duplicate, _enforce_token_budget] }

---
### FILE: backend/app/services/intent_parser.py
[local_deps]: app.services.agent_identity, app.services.llm_gateway
[ext_deps]: json, enum, logging, warnings, re, datetime, typing
[class]: DocumentType { methods: [] }
[class]: DateRange { methods: [] }
[class]: ParsedIntent { methods: [__init__, to_dict, to_search_filter, _resolve_date_range] }
[class]: IntentParserService { methods: [__init__, _get_intent_prompt_template, _extract_current_year_context, _fallback_parse, parse_intent, _extract_json, _generate_fallback_name, parse_batch_intents] }

---
### FILE: backend/app/services/kimi_service.py
[local_deps]: app.services.base_llm_service
[ext_deps]: json, os, logging, httpx, tenacity, collections, datetime, typing
[class]: KimiService { methods: [__init__, _estimate_tokens, _truncate_messages, _get_headers, chat_completion, health_check, get_usage_stats] }

---
### FILE: backend/app/services/knowledge_graph/__init__.py
[ext_deps]: extraction, models, traversal

---
### FILE: backend/app/services/knowledge_graph/extraction.py
[ext_deps]: spacy, json, itertools, logging, models, __future__, asyncpg
[fn]: _vec_to_str(vec)
[class]: EntityExtractor { methods: [__init__, process_chunk, _extract_entities, _financial_keyword_scan, _ensure_document_node, _resolve_or_create, _create_edge, _apply_financial_rules, _llm_relationship_extraction] }

---
### FILE: backend/app/services/knowledge_graph/models.py
[ext_deps]: enum, uuid, pydantic, __future__, datetime
[class]: NodeType { methods: [] }
[class]: EdgeType { methods: [] }
[class]: ExtractionMethod { methods: [] }
[class]: GraphNode { methods: [] }
[class]: GraphEdge { methods: [] }
[class]: PathResult { methods: [summary] }
[class]: ConnectionQuery { methods: [] }

---
### FILE: backend/app/services/knowledge_graph/pool.py
[ext_deps]: asyncpg, os, __future__
[fn]: _build_dsn()
[async_fn]: get_graph_pool(min_size, max_size)
[async_fn]: close_graph_pool()

---
### FILE: backend/app/services/knowledge_graph/traversal.py
[ext_deps]: json, extraction, logging, models, __future__, asyncpg
[class]: GraphTraversalService { methods: [__init__, resolve_entity, find_connections, get_neighbours] }
[fn]: _parse_jsonb(value)
[fn]: _row_to_node(row)
[fn]: _row_to_edge(row)

---
### FILE: backend/app/services/llm_gateway.py
[local_deps]: app.services.llm_router
[ext_deps]: collections, logging, typing
[class]: LLMGateway { methods: [__init__, chat_completion, model, check_cache, invalidate_collection_cache, get_usage_stats, chat_completion_non_stream, health_check] }

---
### FILE: backend/app/services/llm_router.py
[local_deps]: app.services.minimax_service, app.services.kimi_service, app.services.pii_detection_service, app.services.openrouter_service, app.services.ollama_service
[ext_deps]: enum, logging, dataclasses, collections, typing
[class]: RoutingReason { methods: [] }
[class]: LLMProvider { methods: [] }
[class]: TaskTier { methods: [] }
[class]: RoutingDecision { methods: [] }
[class]: LLMRouter { methods: [__init__, generate_completion, detect_context_sensitivity, select_provider, _is_ollama_available, get_provider_for_direct_call] }
[class]: LLMServiceAdapter { methods: [__init__, build_messages, call_service] }
[fn]: _build_router()

---
### FILE: backend/app/services/messaging/__init__.py
[ext_deps]: os, logging, asyncio, nats, collections, typing
[class]: MessagingClient { methods: [__init__, nc, js, connect, close, ensure_stream, subscribe, publish, request] }
[async_fn]: get_messaging_client()
[async_fn]: close_messaging_client()

---
### FILE: backend/app/services/minimax_service.py
[local_deps]: app.services.base_llm_service, app.services.monitoring
[ext_deps]: json, os, logging, httpx, collections, typing
[class]: MiniMaxService { methods: [__init__, _estimate_tokens, _truncate_messages, _get_headers, _check_cost_ceiling, chat_completion, chat_completion_non_stream, health_check] }

---
### FILE: backend/app/services/monitoring.py
[local_deps]: app.core.redis_url
[ext_deps]: os, logging, re, dataclasses, prometheus_client, collections, threading, redis, subprocess, datetime, psutil, typing
[class]: APICostRecord { methods: [] }
[class]: AlertConfig { methods: [] }
[class]: AlertState { methods: [] }
[class]: CostTracker { methods: [__init__, record_api_call, get_daily_cost, get_daily_cost_breakdown, is_over_budget, get_remaining_budget, get_stats, track_ocr_operation, _record_cost] }
[class]: CostCeiling { methods: [__init__, _estimate_cost, _is_rate_limited, _check_emergency_spike, check_call_allowed, get_status, reset_emergency] }
[class]: QueueMonitor { methods: [__init__, _get_redis, get_queue_depth, get_all_queue_depths, is_queue_congested, get_worker_status] }
[class]: SystemMonitor { methods: [get_memory_usage, get_cpu_usage, get_disk_usage, get_container_stats, _parse_memory_string] }
[class]: AlertManager { methods: [__init__, register_alert, check_alert, get_active_alerts] }
[fn]: get_cost_tracker()
[fn]: get_cost_ceiling()
[fn]: get_queue_monitor()
[fn]: get_alert_manager()
[fn]: setup_default_alerts()

---
### FILE: backend/app/services/note_service.py
[local_deps]: app.models.user, app.models.tag, app.models.note
[ext_deps]: sqlalchemy, uuid, logging
[fn]: _escape_like(value)
[class]: NoteService { methods: [create_note, get_note, list_notes, update_note, delete_note, search_notes, get_tags_for_note, _apply_access_filter] }

---
### FILE: backend/app/services/ocr_service.py
[local_deps]: app.services.monitoring, app.utils.circuit_breaker
[ext_deps]: io, PyPDF2, enum, os, time, logging, PIL, pytesseract, paddleocr, numpy, cv2, typing
[class]: OCRMode { methods: [] }
[class]: OCREngine { methods: [] }
[class]: OCRService { methods: [__init__, _get_paddle_model, _get_language_for_ocr, _resize_image, _preprocess_image, _auto_select_mode, _count_pages, _extract_full, extract_text, _extract_with_paddle, _gundam_mode_paddle, _merge_ocr_results, _parse_paddle_result, _extract_with_tesseract, should_use_ocr, extract_from_pdf_page, get_available_modes, get_default_mode] }

---
### FILE: backend/app/services/ollama_service.py
[local_deps]: app.services.base_llm_service
[ext_deps]: json, os, logging, httpx, tenacity, collections, typing
[class]: OllamaService { methods: [__init__, chat_completion, generate, health_check] }

---
### FILE: backend/app/services/openrouter_service.py
[local_deps]: app.services.cache_monitor, app.core.redis_url, app.services.monitoring
[ext_deps]: json, os, logging, httpx, tenacity, collections, hashlib, redis, datetime, typing
[fn]: _get_redis_client()
[class]: OpenRouterService { methods: [__init__, _generate_cache_key, check_cache, _estimate_tokens, _truncate_messages, _get_headers, select_model_for_tier, _check_cost_ceiling, chat_completion, invalidate_collection_cache, health_check, get_usage_stats, list_models] }

---
### FILE: backend/app/services/performance_service.py
[local_deps]: app.services.cache_monitor, app.models.collection, app.models.document
[ext_deps]: logging, sqlalchemy, sentence_transformers, datetime, psutil, typing
[class]: PerformanceMetrics { methods: [__init__] }
[class]: PerformanceTuningService { methods: [__init__, get_system_metrics, _get_embedding_stats, _get_cache_stats, _get_minimax_stats, _generate_recommendations, optimize_embedding_batch_size, optimize_minimax_cache, profile_embedding_memory, get_cost_analysis] }

---
### FILE: backend/app/services/pii_detection_service.py
[ext_deps]: re, logging, typing
[class]: PIIDetectionService { methods: [__init__, detect_pii, redact_pii, get_pii_summary, detect_pii_in_chunks, _is_valid_credit_card] }

---
### FILE: backend/app/services/progressive_revelation_service.py
[local_deps]: app.services.llm_gateway, app.services.agent_identity, app.models.user, app.models.document, app.models.knowledge_graph
[ext_deps]: sqlalchemy, logging, typing
[class]: RevelationLayer { methods: [] }
[class]: FamilyContext { methods: [__init__] }
[class]: ProgressiveRevelationService { methods: [__init__, reveal_entity_info, generate_family_context, _generate_family_narrative, suggest_revelation_layer, get_progressive_search_results] }

---
### FILE: backend/app/services/prometheus_metrics.py
[ext_deps]: time, logging, collections, typing, functools
[class]: Metric { methods: [__init__, _key, set, inc, observe, format] }
[class]: Counter { methods: [__init__, format] }
[class]: Histogram { methods: [__init__, observe, format] }
[class]: PrometheusMetrics { methods: [__init__, get_instance, counter, gauge, histogram, export] }
[fn]: get_metrics()
[fn]: setup_standard_metrics()
[fn]: track_http_request(func)

---
### FILE: backend/app/services/relationship_service.py
[local_deps]: app.services.entity_extraction_service, app.models.knowledge_graph
[ext_deps]: sqlalchemy, collections, logging, typing
[class]: RelationshipMapper { methods: [__init__, infer_relationships, _infer_single_relationship, find_entity_connections, build_entity_clusters] }
[class]: RelationshipService { methods: [__init__, update_entity_connections, get_entity_neighbors, get_shortest_path] }

---
### FILE: backend/app/services/report_service.py
[local_deps]: app.models.collection, app.services.llm_gateway, app.services.agent_identity, app.models.user, app.models.document, app.services.context_block_service
[ext_deps]: io, uuid, os, logging, sqlalchemy, datetime, reportlab, typing
[class]: ReportFormat { methods: [] }
[class]: ReportService { methods: [__init__, generate_report, _build_document_context, _generate_report_with_openrouter, _generate_pdf_report] }

---
### FILE: backend/app/services/rerank_service.py
[ext_deps]: os, logging, typing, httpx
[fn]: _get_client()
[async_fn]: rerank_passages(query, passages)
[async_fn]: close_rerank_client()

---
### FILE: backend/app/services/search_agent.py
[local_deps]: app.database, app.services.search_service, app.services.agent_identity, app.models.user, app.services.llm_router, app.models.document, app.services.search_cache, app.services.context_block_service
[ext_deps]: json, uuid, time, logging, asyncio, sqlalchemy, re, search_models, typing
[fn]: build_search_queries(intent, original_query)
[fn]: _sanitize_search_query(query)
[fn]: rerank_and_build_results(chunks, query, intent, top_k, user_role)
[fn]: _score_to_label(score)
[fn]: _build_excerpt(text, keywords)
[fn]: _extract_highlights(chunks, keywords)
[fn]: _build_match_reason(chunk, intent)
[fn]: build_citations(results, raw_chunks)
[fn]: _fallback_intent(query)
[async_fn]: _call_llm(messages, system, has_confidential, temperature, max_tokens, context_block)
[fn]: _clean_json(raw)
[async_fn]: parse_intent(query)
[async_fn]: synthesize_answer(query, results, raw_chunks, intent, has_confidential, language, context_block)
[async_fn]: generate_suggestions(original_query, results, intent, has_confidential, context_block)
[fn]: _fallback_suggestions(query, intent)
[async_fn]: _strip_confidential_chunks(chunks, _db)
[async_fn]: run_agentic_search(db, request, user_role, user_id, user)

---
### FILE: backend/app/services/search_cache.py
[local_deps]: app.core.redis_url
[ext_deps]: json, logging, hashlib, redis, typing
[fn]: _get_redis()
[class]: SearchCache { methods: [_embedding_key, _result_key, get_embedding, set_embedding, get_result, set_result, _collection_intent_key, _collection_gather_key, get_collection_intent, set_collection_intent, get_collection_gather, set_collection_gather, invalidate_results] }

---
### FILE: backend/app/services/search_models.py
[local_deps]: app.models.document
[ext_deps]: enum, uuid, pydantic, datetime, typing
[class]: QueryIntent { methods: [] }
[class]: RelevanceLabel { methods: [] }
[class]: SearchMode { methods: [] }
[class]: AgenticSearchRequest { methods: [strip_query] }
[class]: ParsedIntent { methods: [] }
[class]: RawChunk { methods: [] }
[class]: Citation { methods: [] }
[class]: SearchResult { methods: [] }
[class]: SearchSuggestion { methods: [] }
[class]: AgentTrace { methods: [] }
[class]: AgenticSearchResponse { methods: [] }

---
### FILE: backend/app/services/search_service.py
[local_deps]: app.services.pii_detection_service, app.models.user, app.models.document, app.services.search_cache, app.services.embed_client, app.services.rerank_service
[ext_deps]: logging, asyncio, sqlalchemy, re, typing
[class]: SearchResult { methods: [__init__] }
[fn]: _get_regconfig(language_code)
[class]: HybridSearchService { methods: [__init__, _get_user_bucket_filter, semantic_search, keyword_search, tag_search, article_semantic_search, _trigram_fallback_search, article_keyword_search, hybrid_search, _sanitize_tsquery, _keyword_search, _keyword_search_with_metadata, _get_highlighted_text, _get_bucket_filter_for_role, _search_bookmarks, _search_notes, _search_spaces, search_all_types, _search_documents_simple] }

---
### FILE: backend/app/services/silent_agent_loop.py
[ext_deps]: json, logging, dataclasses, collections, typing
[class]: IterationRecord { methods: [] }
[class]: SilentLoopResult { methods: [] }
[class]: SilentAgentLoop { methods: [__init__, _build_messages, _call_llm, run, run_simple] }
[fn]: get_silent_agent_loop()

---
### FILE: backend/app/services/similarity_service.py
[local_deps]: app.models.user, app.models.document
[ext_deps]: logging, sqlalchemy, numpy, re, typing
[class]: SimilarityGroup { methods: [__init__, to_dict] }
[class]: SimilarityGroupingService { methods: [__init__, find_similar_groups, _cluster_by_similarity, _analyze_group, _extract_common_patterns, _generate_group_name, find_similar_to_document] }

---
### FILE: backend/app/services/smart_folder/__init__.py
[local_deps]: app.services.smart_folder.query_parser, app.services.smart_folder.analysis, app.services.smart_folder.report_generator, app.services.smart_folder.entity_resolver, app.services.smart_folder.retrieval

---
### FILE: backend/app/services/smart_folder/agent/__init__.py
[local_deps]: app.services.smart_folder.agent.planner, app.services.smart_folder.agent.synthesizer, app.services.smart_folder.agent.executor

---
### FILE: backend/app/services/smart_folder/agent/executor.py
[local_deps]: app.services.smart_folder.skills, app.services.smart_folder.agent.planner, app.services.smart_folder.skills.base
[ext_deps]: json, logging, typing
[class]: SkillExecutor { methods: [__init__, execute, _execute_step, clear_cache] }

---
### FILE: backend/app/services/smart_folder/agent/planner.py
[local_deps]: app.services.smart_folder.skills, app.services.llm_router
[ext_deps]: json, dataclasses, logging, typing
[class]: PlanStep { methods: [] }
[class]: Plan { methods: [] }
[class]: Planner { methods: [plan] }

---
### FILE: backend/app/services/smart_folder/agent/synthesizer.py
[local_deps]: app.services.llm_router, app.services.smart_folder.report_generator, app.services.smart_folder.skills.base
[ext_deps]: json, logging, typing
[class]: Synthesizer { methods: [synthesize] }

---
### FILE: backend/app/services/smart_folder/agent_runner.py
[local_deps]: app.services.smart_folder.query_parser, app.services.smart_folder.agent.synthesizer, app.models.smart_folder, app.services.smart_folder.agent.executor, app.services.smart_folder.entity_resolver, app.services.smart_folder.report_generator, app.models.user, app.services.smart_folder.agent.planner
[ext_deps]: uuid, logging, sqlalchemy, re, typing
[fn]: _extract_entity_from_query(query)
[class]: SmartFolderAgentRunner { methods: [__init__, run] }

---
### FILE: backend/app/services/smart_folder/analysis.py
[local_deps]: app.models.milestone, app.models.pattern_insight
[ext_deps]: uuid, logging, sqlalchemy, dataclasses, datetime, typing
[class]: AnalysisResult { methods: [] }
[class]: AnalysisService { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/entity_resolver.py
[local_deps]: app.models.knowledge_graph
[ext_deps]: difflib, logging, sqlalchemy, dataclasses, typing
[class]: ResolutionResult { methods: [] }
[class]: EntityResolverService { methods: [resolve, search_candidates] }

---
### FILE: backend/app/services/smart_folder/query_parser.py
[local_deps]: app.services.llm_router
[ext_deps]: json, logging, dataclasses, datetime, typing
[class]: ParsedQuery { methods: [] }
[class]: QueryParserService { methods: [parse] }

---
### FILE: backend/app/services/smart_folder/report_generator.py
[local_deps]: app.services.smart_folder.analysis, app.services.smart_folder.retrieval, app.services.llm_router
[ext_deps]: json, uuid, logging, re, dataclasses, typing
[class]: GeneratedReport { methods: [] }
[class]: ReportGeneratorService { methods: [generate, _build_context_string, _build_citation_index, _renumber_citations, _fallback_report] }

---
### FILE: backend/app/services/smart_folder/retrieval.py
[local_deps]: app.models.document, app.services.search_service, app.models.knowledge_graph
[ext_deps]: uuid, logging, sqlalchemy, dataclasses, datetime, typing
[class]: RetrievedAsset { methods: [] }
[class]: RetrievalContext { methods: [] }
[class]: RetrievalService { methods: [__init__, _get_allowed_buckets, retrieve, _clean_search_query, _build_search_query, _retrieve_by_entity_mentions, _retrieve_by_graph_traversal, _retrieve_by_cooccurrence, _retrieve_related_org_docs, _apply_temporal_filter] }

---
### FILE: backend/app/services/smart_folder/skills/__init__.py
[local_deps]: app.services.smart_folder.skills.custom_query, app.services.smart_folder.skills.general_narrative, app.services.smart_folder.skills.project_postmortem, app.services.smart_folder.skills.financial_analysis, app.services.smart_folder.skills.base, app.services.smart_folder.skills.sentiment_tracker, app.services.smart_folder.skills.legal_review

---
### FILE: backend/app/services/smart_folder/skills/base.py
[ext_deps]: dataclasses, logging, typing
[class]: SkillResult { methods: [] }
[class]: BaseSkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/custom_query.py
[local_deps]: app.services.smart_folder.tools.vault_search, app.services.smart_folder.skills.base
[ext_deps]: logging, typing
[class]: CustomQuerySkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/financial_analysis.py
[local_deps]: app.services.smart_folder.tools.chart_generator, app.services.smart_folder.tools.asset_reader, app.services.smart_folder.tools.table_extractor, app.services.smart_folder.tools.trend_analyzer, app.services.smart_folder.skills.base, app.services.smart_folder.tools.vault_search, app.services.smart_folder.tools.ratio_calculator
[ext_deps]: logging, typing
[class]: FinancialAnalysisSkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/general_narrative.py
[local_deps]: app.services.smart_folder.analysis, app.services.smart_folder.report_generator, app.services.smart_folder.skills.base, app.services.smart_folder.retrieval, app.services.smart_folder.tools.document_reader
[ext_deps]: uuid, logging, typing
[class]: GeneralNarrativeSkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/legal_review.py
[local_deps]: app.services.smart_folder.tools.vault_search, app.services.smart_folder.skills.base
[ext_deps]: re, logging, typing
[class]: LegalReviewSkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/project_postmortem.py
[local_deps]: app.models.milestone, app.services.smart_folder.tools.vault_search, app.services.smart_folder.skills.base
[ext_deps]: sqlalchemy, logging, typing
[class]: ProjectPostmortemSkill { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/skills/sentiment_tracker.py
[local_deps]: app.services.smart_folder.tools.vault_search, app.services.smart_folder.skills.base
[ext_deps]: re, logging, typing
[class]: SentimentTrackerSkill { methods: [_score_text, analyze] }

---
### FILE: backend/app/services/smart_folder/tools/__init__.py
[local_deps]: app.services.smart_folder.tools.chart_generator, app.services.smart_folder.tools.vault_search, app.services.smart_folder.tools.citation_marker, app.services.smart_folder.tools.asset_reader, app.services.smart_folder.tools.table_extractor, app.services.smart_folder.tools.trend_analyzer, app.services.smart_folder.tools.refinement_parser, app.services.smart_folder.tools.ratio_calculator

---
### FILE: backend/app/services/smart_folder/tools/asset_reader.py
[local_deps]: app.models.document
[ext_deps]: sqlalchemy, uuid, logging, typing
[class]: AssetReaderTool { methods: [read] }

---
### FILE: backend/app/services/smart_folder/tools/chart_generator.py
[ext_deps]: logging, typing
[class]: ChartGeneratorTool { methods: [line_chart, bar_chart, pie_chart, waterfall_chart] }

---
### FILE: backend/app/services/smart_folder/tools/citation_marker.py
[ext_deps]: uuid, logging, typing
[class]: CitationMarkerTool { methods: [tag, bulk_tag] }

---
### FILE: backend/app/services/smart_folder/tools/document_reader.py
[local_deps]: app.models.document
[ext_deps]: sqlalchemy, uuid, logging, typing
[class]: DocumentReaderTool { methods: [read_document, read_documents, _detect_doc_type] }

---
### FILE: backend/app/services/smart_folder/tools/ratio_calculator.py
[ext_deps]: logging, typing
[class]: RatioCalculatorTool { methods: [_to_float, _find_value, compute_ratios] }

---
### FILE: backend/app/services/smart_folder/tools/refinement_parser.py
[ext_deps]: logging, typing
[class]: RefinementParserTool { methods: [merge] }

---
### FILE: backend/app/services/smart_folder/tools/table_extractor.py
[ext_deps]: io, json, logging, re, csv, typing
[class]: TableExtractorTool { methods: [extract_from_markdown, extract_from_csv, extract] }

---
### FILE: backend/app/services/smart_folder/tools/trend_analyzer.py
[ext_deps]: statistics, logging, typing
[class]: TrendAnalyzerTool { methods: [analyze] }

---
### FILE: backend/app/services/smart_folder/tools/vault_search.py
[local_deps]: app.services.search_service
[ext_deps]: logging, typing
[class]: VaultSearchTool { methods: [search] }

---
### FILE: backend/app/services/smart_folder_service.py
[local_deps]: app.models.collection, app.services.llm_gateway, app.services.search_service, app.models.user, app.models.document
[ext_deps]: uuid, logging, sqlalchemy, re, datetime, typing
[class]: SmartFolderService { methods: [__init__, generate_smart_folder, _classify_intent, _extract_subject, _handle_gather_intent, _handle_generate_intent, _search_documents_for_topic, _build_document_context, _generate_constrained_summary, _generate_with_minimax, _generate_with_openrouter_fallback] }

---
### FILE: backend/app/services/space_service.py
[local_deps]: app.models.note, app.models.user, app.models.tag, app.models.document, app.models.bookmark, app.models.space
[ext_deps]: sqlalchemy, uuid, logging
[fn]: _escape_like(value)
[class]: SpaceService { methods: [create_space, get_space, list_spaces, update_space, delete_space, get_item_count, add_item, remove_item, get_space_item, get_space_items, enrich_space_item, add_rule, update_rule, delete_rule, get_rule, get_rules, get_rule_match_count, sync_space_rules, _sync_tag_rule, _sync_keyword_rule, _is_accessible, search_space_items, check_rules_for_new_item, _keyword_matches_item, _apply_access_filter] }

---
### FILE: backend/app/services/spell_service.py
[ext_deps]: os, symspellpy, logging, typing
[fn]: _get_symspell()
[fn]: load_dictionary_from_terms(terms)
[fn]: correct_query(query)
[fn]: suggest_corrections(query, max_suggestions)

---
### FILE: backend/app/services/storage_service.py
[ext_deps]: uuid, os, logging, base64, pathlib, datetime, cryptography
[class]: EncryptionError { methods: [] }
[fn]: _base64_encode(data)
[fn]: get_encryption_key()
[class]: StorageService { methods: [__init__, _init_encryption, encryption_enabled, _ensure_directories, _encrypt_data, _decrypt_data, get_bucket_path, _safe_bucket_file_path, generate_filename, _is_encrypted_file, save_file, delete_file, get_file, get_file_plaintext, encrypt_file, decrypt_file, needs_migration, file_exists, get_file_info] }

---
### FILE: backend/app/services/structured_logging.py
[ext_deps]: json, os, time, logging, pathlib, collections, contextlib, datetime, sys, typing
[class]: StructuredFormatter { methods: [__init__, format] }
[class]: RequestContext { methods: [set, get, clear, __init__, __enter__, __exit__] }
[class]: RequestContextFilter { methods: [filter] }
[fn]: setup_structured_logging(service_name, environment, level, log_file, enable_console)
[fn]: get_logger(name)
[class]: RequestLogger { methods: [__init__, log_request] }
[class]: QueryLogger { methods: [__init__, log_query] }
[fn]: get_request_logger()
[fn]: get_query_logger()

---
### FILE: backend/app/services/swarm/__init__.py

---
### FILE: backend/app/services/swarm/v2/__init__.py
[ext_deps]: hitl_bridge, flock_alerter, registry, base_agent

---
### FILE: backend/app/services/swarm/v2/base_agent.py
[local_deps]: app.services.messaging
[ext_deps]: json, enum, uuid, logging, asyncio, nats, datetime, abc, typing
[class]: AgentStatus { methods: [] }
[class]: AgentCapability { methods: [] }
[class]: BaseAgent { methods: [__init__, messaging, info, start, stop, _on_message, _on_broadcast, handle_message, handle_broadcast, _heartbeat_loop] }

---
### FILE: backend/app/services/swarm/v2/flock_alerter.py
[local_deps]: app.services.messaging
[ext_deps]: json, enum, time, logging, dataclasses, nats, hashlib, datetime, typing
[class]: AlertLevel { methods: [] }
[class]: AlertEvent { methods: [to_bytes, from_bytes, dedup_key] }
[class]: FlockAlerter { methods: [__init__, messaging, connect, close, _is_rate_limited, alert, subscribe, info, warning, error, critical] }

---
### FILE: backend/app/services/swarm/v2/hitl_bridge.py
[local_deps]: app.services.messaging
[ext_deps]: json, enum, uuid, logging, asyncio, dataclasses, nats, datetime, typing
[class]: HITLStatus { methods: [] }
[class]: HITLRequest { methods: [to_bytes, from_bytes] }
[class]: HITLResponse { methods: [to_bytes, from_bytes] }
[class]: HITLBridge { methods: [__init__, messaging, connect, close, request_approval, respond, subscribe_requests, _on_response] }

---
### FILE: backend/app/services/swarm/v2/registry.py
[local_deps]: app.services.messaging
[ext_deps]: json, logging, nats, datetime, typing
[class]: AgentRegistry { methods: [__init__, messaging, _ensure_kv, connect, register, deregister, get, discover, health_check] }

---
### FILE: backend/app/services/synthesis_service.py
[local_deps]: app.services.llm_gateway, app.services.agent_identity, app.models.document, app.models.knowledge_graph, app.services.context_block_service
[ext_deps]: json, logging, sqlalchemy, collections, datetime, typing
[class]: SynthesisRequest { methods: [__init__] }
[class]: SynthesisResult { methods: [__init__] }
[class]: SynthesisPipelineService { methods: [__init__, synthesize, _fetch_documents, _map_documents, _map_single_document, _gather_entities, _build_timeline, _reduce_synthesis, _extract_key_points, _prepare_sources, _calculate_confidence, _extract_json, batch_synthesize] }

---
### FILE: backend/app/services/task_service.py
[local_deps]: app.models.task, app.models.user, app.models.tag
[ext_deps]: sqlalchemy, uuid, logging
[fn]: _escape_like(value)
[class]: TaskService { methods: [create_task, get_task, list_tasks, update_task, delete_task, search_tasks, get_tags_for_task, get_tasks_with_pending_alarms, mark_alarm_triggered, _apply_access_filter] }

---
### FILE: backend/app/services/telegram_notifier.py
[ext_deps]: json, os, logging, httpx, datetime
[class]: TelegramNotifier { methods: [__init__, is_configured, send_alert] }
[fn]: _escape_md(text)

---
### FILE: backend/app/services/temporal_reasoning_service.py
[local_deps]: app.models.knowledge_graph
[ext_deps]: logging, sqlalchemy, collections, datetime, typing
[class]: TemporalRelation { methods: [] }
[class]: TemporalReasoningService { methods: [__init__, reason_about_temporal_relationships, _determine_relation, _infer_causal_relationships, _get_entity_temporal_context, analyze_evolution, _identify_evolution_stages, _detect_evolution_trends, find_temporal_patterns] }

---
### FILE: backend/app/services/text_extractor.py
[ext_deps]: json, PyPDF2, os, logging, html, pathlib, re, docx, pptx, zipfile, xml, subprocess, csv, ebooklib, sys, typing
[class]: TextExtractor { methods: [__init__, get_file_extension, extract_text, _extract_from_pdf, _extract_from_docx, _extract_from_doc, _extract_from_pptx, _extract_from_ppt, _extract_from_xlsx, _extract_from_xls, _extract_spreadsheet, _extract_from_txt, _extract_from_json, _extract_from_csv, _extract_from_xml, _extract_from_epub, _extract_from_html, _extract_from_rtf, _extract_from_zip, _extract_from_msg, extract_images_from_pdf] }

---
### FILE: backend/app/services/timeline_service.py
[local_deps]: app.models.document, app.models.knowledge_graph
[ext_deps]: logging, sqlalchemy, collections, datetime, typing
[class]: TimelineEventType { methods: [] }
[class]: TimelineConstructionService { methods: [build_document_timeline, build_entity_timeline, detect_evolution_patterns, _identify_evolution_stages, get_timeline_for_period, suggest_timeline_insights] }

---
### FILE: backend/app/services/token_blacklist.py
[local_deps]: app.core.redis_url
[ext_deps]: logging, redis, hashlib
[fn]: _client()
[fn]: _key(token)
[fn]: blacklist_token(token, expires_in_seconds)
[fn]: is_token_blacklisted(token)

---
### FILE: backend/app/services/tool_registry.py
[ext_deps]: datetime, pydantic, typing
[class]: DocumentSearchTool { methods: [] }
[class]: VaultClassifyTool { methods: [] }
[class]: EntityExtractTool { methods: [] }
[class]: ToolRegistry { methods: [get_tool_schemas, get_tool_schema, validate_tool_call, _build_function_schema] }

---
### FILE: backend/app/services/whisper_service.py
[local_deps]: app.utils.circuit_breaker
[ext_deps]: os, logging, asyncio, faster_whisper
[class]: WhisperService { methods: [current_model_size, reload_model, _get_model, _transcribe_sync, transcribe] }

---
### FILE: backend/app/tasks/__init__.py
[local_deps]: app.tasks

---
### FILE: backend/app/tasks/anomaly_tasks.py
[local_deps]: app.database, app.celery_app, app.services.cache_monitor, app.services.monitoring, app.models.document, app.services.alert_service, app.tasks.pipeline_orchestrator, app.models.processing, app.tasks.base, app.core.redis_url
[ext_deps]: celery, os, logging, asyncio, redis, datetime
[fn]: daily_anomaly_report()
[fn]: system_health_check()
[fn]: check_api_costs(daily_budget_threshold)
[fn]: recover_stuck_documents(max_processing_minutes)
[fn]: recover_pending_documents(pending_threshold_minutes)
[fn]: on_daily_anomaly_report_failure(self, exc, task_id, args, kwargs, einfo)
[fn]: fail_stuck_processing_documents(max_processing_minutes)

---
### FILE: backend/app/tasks/article_tasks.py
[local_deps]: app.services.embed_client, app.database, app.models.article, app.models.document, app.tasks.base, app.services.article_generation_service
[ext_deps]: celery, uuid, logging, asyncio, httpx
[fn]: generate_articles_for_document(self, document_id, force)
[fn]: generate_article_embeddings(self, article_ids)
[fn]: backfill_articles()

---
### FILE: backend/app/tasks/backfill_tasks.py
[local_deps]: app.database, app.tasks.article_tasks, app.models.article, app.models.document, app.tasks.pipeline_orchestrator, app.tasks.embedding_tasks
[ext_deps]: datetime, logging, celery
[fn]: classify_and_recover_errors(batch_size, delay_seconds, dry_run)
[fn]: reprocess_failed_documents(date_from, date_to, batch_size, delay_seconds)
[fn]: backfill_missing_embeddings(batch_size, delay_seconds)
[fn]: backfill_missing_articles(batch_size, delay_seconds)
[fn]: backfill_article_embeddings(batch_size, delay_seconds)

---
### FILE: backend/app/tasks/base.py
[local_deps]: app.services.alert_service, app.services.dlq_service
[ext_deps]: os, logging, asyncio, traceback, psutil
[fn]: log_task_memory(task_name, stage)
[fn]: base_task_failure_handler(task_self, exception, task_id, args, kwargs, traceback, is_critical, extra_metadata)
[fn]: store_dlq_on_max_retries(task_self, exception, extra_metadata)

---
### FILE: backend/app/tasks/collection_report_tasks.py
[local_deps]: app.database, app.services.report_service, app.models.audit, app.models.user, app.tasks.base
[ext_deps]: json, celery, uuid, logging, asyncio, sqlalchemy, typing
[fn]: generate_collection_report_task(self, collection_id, report_format, include_citations, language, user_id)

---
### FILE: backend/app/tasks/document_tasks.py
[local_deps]: app.services.embed_client, app.database, app.tasks.article_tasks, app.services.text_extractor, app.services.collection_service, app.services.entity_extraction_service, app.services.chunking_service, app.services.dlq_service, app.models.document, app.services.ocr_service, app.tasks.pipeline_orchestrator, app.models.processing, app.tasks.base, app.services.prometheus_metrics, app.tasks.embedding_tasks, app.services.context_block_service
[ext_deps]: celery, uuid, os, logging, asyncio, sqlalchemy, tempfile, traceback, langdetect, datetime
[fn]: detect_text_language(text, fallback)
[fn]: process_document(self, document_id, task_type)
[fn]: process_batch_documents(document_ids)
[fn]: generate_embeddings(self, chunk_ids)
[fn]: cleanup_old_tasks(days)
[fn]: on_process_document_failure(self, exc, task_id, args, kwargs, einfo)
[fn]: on_generate_embeddings_failure(self, exc, task_id, args, kwargs, einfo)
[fn]: extract_entities_for_document(self, document_id)
[fn]: batch_extract_entities(batch_size, batch_interval)
[fn]: _run_build_pipeline(collection_id, user_id)
[fn]: build_smart_collection(self, collection_id, user_id)
[fn]: reprocess_pending_documents()

---
### FILE: backend/app/tasks/embedding_tasks.py
[local_deps]: app.database, app.celery_app, app.tasks.base, app.models.document, app.services.embed_client
[ext_deps]: uuid, time, logging, sentence_transformers
[fn]: generate_embeddings_batch(self, chunk_ids, model_name)
[fn]: recompute_embeddings_for_document(self, document_id)
[fn]: upgrade_embeddings_model(self, from_model, to_model, batch_size)

---
### FILE: backend/app/tasks/guardian_tasks.py
[ext_deps]: datetime, celery
[fn]: guardian_ping(self)

---
### FILE: backend/app/tasks/health_report_tasks.py
[local_deps]: app.database, app.celery_app, app.models.document, app.core.redis_url, app.models.pipeline
[ext_deps]: smtplib, os, logging, sqlalchemy, email, redis, datetime
[fn]: _smtp_configured()
[fn]: _send_email(subject, html_body, text_body)
[fn]: daily_health_report()

---
### FILE: backend/app/tasks/monitoring_tasks.py
[local_deps]: app.celery_app, app.services.alert_service
[ext_deps]: psutil, logging, asyncio
[fn]: check_worker_memory(self)

---
### FILE: backend/app/tasks/pipeline_orchestrator.py
[local_deps]: app.database, app.tasks.pipeline_tasks, app.models.document, app.core.redis_url, app.models.pipeline
[ext_deps]: celery, uuid, logging, redis, datetime
[fn]: _total_queue_depth()
[fn]: _check_backpressure(from_stage)
[fn]: _get_embed_time_limits(chunk_count)
[fn]: _build_chain(document_id, from_stage)
[fn]: _is_stage_inflight(document_id, stage)
[fn]: dispatch_document(document_id, from_stage)
[fn]: dispatch_batch(document_ids)

---
### FILE: backend/app/tasks/pipeline_sweeper.py
[local_deps]: app.database, app.celery_app, app.models.document, app.tasks.pipeline_orchestrator, app.core.redis_url, app.models.pipeline
[ext_deps]: os, logging, sqlalchemy, redis, datetime
[fn]: pipeline_sweeper()

---
### FILE: backend/app/tasks/pipeline_tasks.py
[local_deps]: app.database, app.tasks.article_tasks, app.celery_app, app.tasks.document_tasks, app.services.knowledge_graph.pool, app.services.knowledge_graph.extraction, app.services.text_extractor, app.services.entity_extraction_service, app.services.chunking_service, app.models.document, app.services.ocr_service, app.services.embed_client, app.models.pipeline, app.services.dlq_service
[ext_deps]: gc, celery, uuid, os, time, logging, asyncio, tempfile, traceback, datetime
[class]: _PermanentPipelineError { methods: [] }
[fn]: update_stage(document_id, stage, status, error, worker_id, db)
[fn]: _sync_document_stage(document_id, stage_value)
[fn]: _clear_document_error(document_id)
[fn]: _stage_task(self, document_id, stage, work_fn)
[fn]: _run_ocr(document_id)
[fn]: _run_chunk(document_id)
[fn]: _run_embed(document_id)
[fn]: _run_index(document_id)
[fn]: _run_articles(document_id)
[fn]: _run_entities(document_id)
[async_fn]: _graph_extract_document(document_id, chunks, bucket)
[fn]: ocr_stage(self, document_id)
[fn]: chunk_stage(self, document_id)
[fn]: embed_stage(self, document_id)
[fn]: index_stage(self, document_id)
[fn]: article_stage(self, document_id)
[fn]: entity_stage(self, document_id)
[fn]: _run_finalize(document_id)
[fn]: finalize_stage(self, document_id)

---
### FILE: backend/app/tasks/report_tasks.py
[local_deps]: app.models.audit, app.database, app.tasks.base, app.models.document
[ext_deps]: fpdf, celery, os, time, logging, openpyxl, sqlalchemy, datetime
[fn]: _ensure_reports_dir()
[fn]: generate_pdf_report(self, report_type, filters, user_id, output_filename)
[fn]: _generate_pdf_content(report_type, filters, output_path)
[fn]: _write_pdf_with_fpdf(FPDF, report_type, filters, output_path, db)
[fn]: _write_text_stub(report_type, filters, output_path, db)
[fn]: generate_excel_export(self, export_type, filters, user_id, output_filename)
[fn]: _generate_excel_content(export_type, filters, output_path)
[fn]: _write_excel_with_openpyxl(openpyxl, export_type, filters, output_path, db)
[fn]: _write_excel_stub(export_type, output_path, db)
[fn]: cleanup_old_reports(self, days_to_keep)
[fn]: on_generate_pdf_report_failure(self, exc, task_id, args, kwargs, einfo)

---
### FILE: backend/app/tasks/smart_folder_tasks.py
[local_deps]: app.database, app.models.smart_folder, app.services.smart_folder_service, app.models.audit, app.services.smart_folder.agent_runner, app.models.user, app.models.document, app.tasks.base
[ext_deps]: json, celery, uuid, logging, asyncio, sqlalchemy, datetime, typing
[fn]: generate_smart_folder_v2_task(self, query, include_confidential, user_id, smart_folder_id, refinement_query)
[fn]: refresh_stale_smart_folders_task(self)
[fn]: generate_smart_folder_task(self, topic, style, length, include_confidential, user_id)

---
### FILE: backend/app/tasks/space_tasks.py
[local_deps]: app.database, app.tasks.base, app.services.space_service, app.models.space
[ext_deps]: sqlalchemy, celery, logging, asyncio
[fn]: sync_space_rules_task(self, space_id)

---
### FILE: backend/app/tasks/subscription_tasks.py
[local_deps]: app.database, app.models.user, app.models.subscription, app.celery_app
[ext_deps]: smtplib, os, logging, sqlalchemy, calendar, email, httpx, datetime
[fn]: _telegram_configured()
[fn]: _send_telegram(message)
[fn]: _smtp_configured()
[fn]: _send_email(to, subject, html_body, text_body)
[fn]: _next_due_date(last_payment, billing_cycle)
[fn]: _upcoming_due_date(last_payment, billing_cycle, today)
[fn]: send_payment_reminders()

---
### FILE: backend/app/tasks/task_alarm_tasks.py
[local_deps]: app.database, app.core.push, app.celery_app, app.models.push_subscription, app.services.task_service, app.models.task
[ext_deps]: sqlalchemy, logging
[fn]: check_task_alarms()

---
### FILE: backend/app/tasks/voice_tasks.py
[local_deps]: app.services.storage_service, app.database, app.services.whisper_service, app.celery_app
[ext_deps]: os, logging, asyncio, sqlalchemy, tempfile
[fn]: transcribe_voice_note(self, audio_file_path, document_id)

---
### FILE: backend/app/utils/circuit_breaker.py
[ext_deps]: time, logging, asyncio, collections, threading, typing, functools
[class]: CircuitBreakerState { methods: [] }
[class]: CircuitBreaker { methods: [__init__, state, _should_open, _cooldown_elapsed, record_success, record_failure, can_execute, call, call_async] }
[class]: CircuitBreakerOpenError { methods: [] }
[fn]: get_breaker(name, failure_threshold, cooldown_seconds)
[fn]: circuit_breaker(name, failure_threshold, cooldown_seconds)

---
### FILE: backend/app/utils/constants.py

---
### FILE: backend/app/utils/security.py
[local_deps]: app.services.token_blacklist, app.database, app.models.user
[ext_deps]: os, fastapi, logging, jose, bcrypt, sqlalchemy, datetime, dotenv, typing
[class]: TokenExpiredError { methods: [__init__] }
[class]: TokenInvalidError { methods: [__init__] }
[class]: _BcryptContext { methods: [verify, hash] }
[fn]: verify_password(plain_password, hashed_password)
[fn]: get_password_hash(password)
[fn]: hash_password(plain)
[fn]: create_access_token(data, expires_delta)
[fn]: create_refresh_token(data)
[fn]: decode_token(token, expected_type)
[async_fn]: get_current_user(token, db)
[async_fn]: require_admin(current_user)
[async_fn]: require_admin_only(current_user)

---
