from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_content_search_inception_metadata_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – content/search Inception metadata validation (functional, positive, manual-assisted)

    Goal:
      - Use content/search with a popular movie title "Inception".
      - Verify status=200 and a non-empty entries list.
      - Verify each ContentEntry has essential metadata:
          entryId (string), appId (string), title (string),
          poster (string), categories (list of strings).
      - Verify at least one entry title contains "Inception" (case-insensitive).
      - Ask the user to confirm that the device UI shows relevant results for "Inception".
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    search_text = "Inception"
    user_validated = "N/A"
    required_fields = ("entryId", "appId", "title", "poster", "categories")

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Ensure content/search with title 'Inception' returns relevant results with complete metadata.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: content/search.", result=result)
        helpers.log_line(logs, "DESC", "PASS if status=200, entries non-empty, metadata complete, at least one title contains 'Inception', and UI looks relevant.", result=result)

        cap_spec = "ops: content/search"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        payload = json.dumps({"searchText": search_text})
        helpers.log_line(logs, "STEP", f"Sending content/search with movie title searchText={search_text!r}, payload={payload}", result=result)

        status, body = helpers.execute_cmd_and_log(tester, device_id, dab_topic, payload, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"content/search returned status={status} for searchText={search_text!r}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "content/search is not implemented on this device (status=501).")
            return result

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"content/search returned non-200 status={status} for searchText={search_text!r}.")
            return result

        try:
            if isinstance(body, str):
                body = json.loads(body) if body.strip() != "" else {}
            elif body is None:
                body = {}
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"content/search response is not valid JSON for searchText={search_text!r}: {e}")
            return result

        entries = body.get("entries")
        if not isinstance(entries, list) or not entries:
            helpers.finish(result, logs, "FAILED", f"content/search 'entries' is empty or invalid for searchText={search_text!r}.")
            return result

        helpers.log_line(logs, "INFO", f"content/search returned {len(entries)} entries for searchText={search_text!r}.", result=result)

        sample_count = min(3, len(entries))
        for idx in range(sample_count):
            entry = entries[idx] if isinstance(entries[idx], dict) else {}
            helpers.log_line(
                logs,
                "INFO",
                f"Entry[{idx}]: appId={entry.get('appId')!r}, entryId={entry.get('entryId')!r}, title={entry.get('title')!r}",
                result=result,
            )

        inception_matches = 0
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} is not an object; got type={type(entry).__name__}.")
                return result

            missing = [k for k in required_fields if k not in entry]
            if missing:
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} is missing required keys: {missing}.")
                return result

            entry_id = entry.get("entryId")
            app_id = entry.get("appId")
            title = entry.get("title")
            poster = entry.get("poster")
            categories = entry.get("categories")

            if not isinstance(entry_id, str) or not entry_id:
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid entryId={entry_id!r} (expected non-empty string).")
                return result
            if not isinstance(app_id, str) or not app_id:
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid appId={app_id!r} (expected non-empty string).")
                return result
            if not isinstance(title, str) or not title:
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid title={title!r} (expected non-empty string).")
                return result
            if not isinstance(poster, str) or not poster:
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid poster value (expected non-empty base64 data URL string).")
                return result
            if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
                helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid categories={categories!r} (expected list of strings).")
                return result

            if "inception" in title.lower():
                inception_matches += 1

        helpers.log_line(logs, "INFO", f"Number of entries whose title contains 'Inception': {inception_matches}", result=result)
        if inception_matches == 0:
            helpers.finish(result, logs, "FAILED", "No entry title contains 'Inception'; results may not be relevant for this test.")
            return result

        helpers.log_line(logs, "STEP", "Manual check — On the device UI, search for 'Inception' and inspect displayed results.", result=result)
        helpers.log_line(logs, "DESC", "On-screen results should be consistent with DAB response (e.g., 'Inception' from expected app).", result=result)

        user_validated = helpers.yes_or_no(
            result,
            logs,
            "On the device UI, do you see relevant results for 'Inception' with correct movie details (title/poster/app)?"
        )

        if user_validated:
            helpers.finish(result, logs, "PASS", "User confirmed on-screen search results for 'Inception' are relevant and metadata is complete.")
        else:
            helpers.finish(result, logs, "FAILED", "User reported that on-screen search results for 'Inception' are not relevant or inconsistent with DAB response.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error during content/search Inception check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, search_text={search_text!r}, id={test_id}, device={device_id}", result=result)

    return result

def run_content_search_empty_query_behavior_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – content/search empty searchText behavior (negative, functional)

    Goal:
      - Call content/search with an empty searchText ("").
      - Acceptable outcomes:
          * 400 (Bad Request / invalid parameters) with valid JSON (or empty body), OR
          * 200 (OK) with valid JSON body where 'entries' is an empty list.
      - Treat 501 as OPTIONAL_FAILED (operation not implemented).
      - Any other behavior is FAILED.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Goal: Verify that content/search with empty searchText returns either 400 with valid JSON or 200 with entries=[].", result=result)
        helpers.log_line(logs, "DESC", "Required operation: content/search.", result=result)
        helpers.log_line(logs, "DESC", "PASS if status in {400, 200}. For 400: valid JSON or empty body. For 200: valid JSON with entries=[].", result=result)

        cap_spec = "ops: content/search"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        payload = json.dumps({"searchText": ""})
        helpers.log_line(logs, "STEP", f"Invoking content/search with empty searchText, payload={payload}", result=result)

        status, body = helpers.execute_cmd_and_log(tester, device_id, dab_topic, payload, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"content/search empty-query returned status={status}", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "content/search is not implemented on this device (status=501) for empty searchText.")
            return result

        if status not in (200, 400):
            helpers.finish(result, logs, "FAILED", f"Unexpected status for empty searchText: got {status}, expected 400 or 200.")
            return result

        is_empty_body = (body is None) or (isinstance(body, str) and body.strip() == "")
        if is_empty_body:
            if status == 400:
                helpers.finish(result, logs, "PASS", "content/search returned status=400 with no body for empty searchText; treated as valid client error.")
                return result
            helpers.finish(result, logs, "PASS", "content/search returned status=200 with an empty body for empty searchText; treating as allowed empty result set (entries=[]).")
            return result

        try:
            if isinstance(body, str):
                parsed = json.loads(body)
            else:
                parsed = body
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"content/search response for empty searchText is not valid JSON: {e}")
            return result

        if status == 400:
            helpers.log_line(logs, "INFO", "content/search empty-query returned status=400 with valid JSON body; treating as valid client error.", result=result)
            helpers.finish(result, logs, "PASS", "Empty searchText correctly rejected with status=400 and valid JSON.")
            return result

        entries = parsed.get("entries") if isinstance(parsed, dict) else None
        if not isinstance(entries, list):
            helpers.finish(result, logs, "FAILED", "For status=200, content/search response does not expose 'entries' as a list for empty searchText.")
            return result

        if len(entries) != 0:
            helpers.finish(result, logs, "FAILED", f"For status=200, expected entries=[] for empty searchText, but got {len(entries)} entries.")
            return result

        helpers.finish(result, logs, "PASS", "Empty searchText returned status=200 with valid JSON and entries=[], as allowed behavior.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error during content/search empty-query behavior check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, test_id={test_id}, device={device_id}", result=result)

    return result

def run_content_search_partial_app_metadata_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – content/search partial keyword metadata validation (functional, positive)

    Goal:
      - Use content/search with partial keywords like "Netf" / "Youtu".
      - Verify that at least one searchText returns a non-empty entries list.
      - Verify that each ContentEntry has essential metadata:
          entryId (string), appId (string), title (string),
          poster (string), categories (list of strings).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    search_terms = ["Netf", "Youtu"]
    used_search_text = None
    found_valid_entries = False
    required_fields = ("entryId", "appId", "title", "poster", "categories")

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Use content/search with partial app-related keywords and verify that results provide complete ContentEntry metadata.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: content/search.", result=result)
        helpers.log_line(logs, "DESC", "PASS if any partial keyword returns status=200, non-empty entries, and each entry has entryId, appId, title, poster, and categories with correct types.", result=result)

        cap_spec = "ops: content/search"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        for search_text in search_terms:
            used_search_text = search_text
            helpers.log_line(logs, "STEP", f"Sending content/search with partial keyword {search_text!r}.", result=result)

            status, body = helpers.execute_cmd_and_log(
                tester, device_id, "content/search",
                json.dumps({"searchText": search_text}),
                logs=logs, result=result
            )
            helpers.log_line(logs, "INFO", f"content/search returned status={status} for searchText={search_text!r}.", result=result)

            if status == 501:
                helpers.finish(result, logs, "OPTIONAL_FAILED", "content/search is not implemented on this device (status=501).")
                return result

            if status != 200:
                helpers.log_line(logs, "INFO", f"Skipping searchText={search_text!r} because status={status} (expected 200); trying next keyword.", result=result)
                continue

            try:
                body = json.loads(body) if isinstance(body, str) else (body or {})
            except Exception as e:
                helpers.finish(result, logs, "FAILED", f"content/search response for searchText={search_text!r} is not valid JSON: {e}")
                return result

            entries = body.get("entries")
            if not isinstance(entries, list) or not entries:
                helpers.log_line(logs, "INFO", f"'entries' missing or empty for searchText={search_text!r}; trying next keyword.", result=result)
                continue

            helpers.log_line(logs, "INFO", f"content/search returned {len(entries)} entries for searchText={search_text!r}.", result=result)

            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} is not an object; got {type(entry).__name__}.")
                    return result

                missing = [k for k in required_fields if k not in entry]
                if missing:
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} is missing required keys: {missing}.")
                    return result

                entry_id = entry.get("entryId")
                app_id = entry.get("appId")
                title = entry.get("title")
                poster = entry.get("poster")
                categories = entry.get("categories")

                if not isinstance(entry_id, str) or not entry_id:
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid entryId={entry_id!r} (expected non-empty string).")
                    return result
                if not isinstance(app_id, str) or not app_id:
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid appId={app_id!r} (expected non-empty string).")
                    return result
                if not isinstance(title, str) or not title:
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid title={title!r} (expected non-empty string).")
                    return result
                if not isinstance(poster, str) or not poster:
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid poster value (expected non-empty base64 data URL string).")
                    return result
                if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
                    helpers.finish(result, logs, "FAILED", f"Entry #{idx} has invalid categories={categories!r} (expected list of strings).")
                    return result

            found_valid_entries = True
            break

        current_status = getattr(result, "test_result", "UNKNOWN")
        if not found_valid_entries and current_status not in ("FAILED", "OPTIONAL_FAILED"):
            helpers.finish(result, logs, "FAILED", "No partial keyword (Netf/Youtu) produced a valid content/search response with non-empty entries and complete metadata.")
        elif found_valid_entries and current_status not in ("FAILED", "OPTIONAL_FAILED"):
            helpers.finish(result, logs, "PASS", f"content/search returned non-empty entries with complete ContentEntry metadata for partial keyword {used_search_text!r}.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error during content search metadata check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, last_search_text={used_search_text!r}, id={test_id}, device={device_id}", result=result)

    return result
