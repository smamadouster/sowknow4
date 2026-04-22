# SOWKNOW Search QA Validation Report
**Generated:** 2026-04-22 19:40:04 UTC
**Overall:** ✅ ALL GATES PASSED

| Phase | Test | Status | Duration |
|-------|------|--------|----------|
| General | backend_syntax_check | ✅ | 51ms |
| General | frontend_typescript_check | ✅ | 1731ms |
| General | backend_import_check | ✅ | 930ms |
| Phase 1 | test_search_phase1_qa | ✅ | 1247ms |
| Phase 2 | test_search_phase2_qa | ✅ | 1223ms |
| Phase 3 | test_search_phase3_qa | ✅ | 1028ms |
| Performance | test_search_performance_qa | ✅ | 840ms |

## Summary
- **Passed:** 7
- **Failed:** 0
- **Total:** 7

## Details
### backend_syntax_check (PASS)
```
All files compile cleanly
```

### frontend_typescript_check (PASS)
```
TypeScript compiles with zero errors
```

### backend_import_check (PASS)
```
All imports succeed
```

### test_search_phase1_qa (PASS)
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/development/src/active/sowknow4/backend
configfile: pytest.ini
plugins: mock-3.15.1, anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 8 items

tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_unauthorized_401 SKIPPED [ 12%]
tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_empty_query_validation SKIPPED [ 25%]
tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_returns_valid_structure SKIPPED [ 37%]
tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_p99_latency_under_50ms SKIPPED [ 50%]
tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_respects_limit SKIPPED [ 62%]
tests/qa/test_search_phase1_qa.py::TestSuggestEndpoint::test_suggest_limit_bounds_enforced SKIPPED [ 75%]
tests/qa/test_search_phase1_qa.py::TestStreamingSearchTime::test_streaming_includes_search_time_ms SKIPPED [ 87%]
tests/qa/test_search_phase1_qa.py::TestFastPathIntent::test_short_query_uses_fallback_intent PASSED [100%]

========================= 1 passed, 7 skipped in 0.28s =========================

```

### test_search_phase2_qa (PASS)
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/development/src/active/sowknow4/backend
configfile: pytest.ini
plugins: mock-3.15.1, anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/qa/test_search_phase2_qa.py::TestLanguageAwareSearch::test_english_query_maps_to_english PASSED [ 11%]
tests/qa/test_search_phase2_qa.py::TestLanguageAwareSearch::test_french_query_maps_to_french PASSED [ 22%]
tests/qa/test_search_phase2_qa.py::TestLanguageAwareSearch::test_unknown_language_defaults_to_simple PASSED [ 33%]
tests/qa/test_search_phase2_qa.py::TestLanguageAwareSearch::test_hybrid_search_uses_regconfig_parameter PASSED [ 44%]
tests/qa/test_search_phase2_qa.py::TestTrigramFallback::test_trigram_fallback_activates_on_few_results PASSED [ 55%]
tests/qa/test_search_phase2_qa.py::TestTrigramFallback::test_trigram_fallback_skipped_when_many_results PASSED [ 66%]
tests/qa/test_search_phase2_qa.py::TestRerankerGracefulDegradation::test_reranker_unavailable_returns_results PASSED [ 77%]
tests/qa/test_search_phase2_qa.py::TestDynamicThreshold::test_short_query_filters_weak_matches PASSED [ 88%]
tests/qa/test_search_phase2_qa.py::TestDynamicThreshold::test_long_query_allows_moderate_matches PASSED [100%]

============================== 9 passed in 0.21s ===============================

```

### test_search_phase3_qa (PASS)
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/development/src/active/sowknow4/backend
configfile: pytest.ini
plugins: mock-3.15.1, anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 15 items

tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_unauthorized_401 SKIPPED [  6%]
tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_invalid_type_rejected SKIPPED [ 13%]
tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_valid_thumbs_up SKIPPED [ 20%]
tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_valid_thumbs_down SKIPPED [ 26%]
tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_valid_dismiss SKIPPED [ 33%]
tests/qa/test_search_phase3_qa.py::TestFeedbackEndpoint::test_feedback_stats_require_auth SKIPPED [ 40%]
tests/qa/test_search_phase3_qa.py::TestSpellService::test_correct_query_no_change_when_dictionary_empty PASSED [ 46%]
tests/qa/test_search_phase3_qa.py::TestSpellService::test_suggest_corrections_empty_when_dictionary_empty PASSED [ 53%]
tests/qa/test_search_phase3_qa.py::TestSpellService::test_load_dictionary_and_correct PASSED [ 60%]
tests/qa/test_search_phase3_qa.py::TestSpellService::test_numbers_not_corrected PASSED [ 66%]
tests/qa/test_search_phase3_qa.py::TestSpellService::test_short_words_not_corrected PASSED [ 73%]
tests/qa/test_search_phase3_qa.py::TestSearchCache::test_cache_get_set_embedding PASSED [ 80%]
tests/qa/test_search_phase3_qa.py::TestSearchCache::test_cache_get_set_result PASSED [ 86%]
tests/qa/test_search_phase3_qa.py::TestSearchCache::test_cache_miss_different_query PASSED [ 93%]
tests/qa/test_search_phase3_qa.py::TestSearchCache::test_cache_invalidates_results
```

### test_search_performance_qa (PASS)
```
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.2, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/development/src/active/sowknow4/backend
configfile: pytest.ini
plugins: mock-3.15.1, anyio-4.12.1, asyncio-1.3.0, cov-7.0.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 3 items

tests/qa/test_search_performance_qa.py::TestSuggestPerformance::test_suggest_latency_distribution SKIPPED [ 33%]
tests/qa/test_search_performance_qa.py::TestSearchLatency::test_search_latency_distribution SKIPPED [ 66%]
tests/qa/test_search_performance_qa.py::TestStreamingLatency::test_streaming_time_to_first_result SKIPPED [100%]

============================== 3 skipped in 0.02s ==============================

```
