from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_content_recommendations_update_after_watch_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – content/recommendations update after new viewing (functional, manual-assisted)

    Goal:
      - Capture a baseline content/recommendations response.
      - Ask the user to watch a new movie/TV show on the device.
      - Capture a second content/recommendations response.
      - Compare both lists and ask the user to confirm whether recommendations
        appear updated to reflect the newly watched content.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    user_validated = "N/A"
    initial_entries = []
    updated_entries = []

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Verify that content/recommendations reflects new viewing activity after watching new content.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: content/recommendations.", result=result)
        helpers.log_line(logs, "DESC", "PASS if second recommendations call appears updated and user confirms the change.", result=result)

        cap_spec = "ops: content/recommendations"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # Step 1: Baseline recommendations
        helpers.log_line(logs, "STEP", "Fetching baseline recommendations via content/recommendations.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, dab_topic, "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"Baseline content/recommendations returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "content/recommendations is not implemented on this device (status=501).")
            return result

        elif status != 200:
            helpers.finish(result, logs, "FAILED", f"Baseline content/recommendations returned non-200 status={status}.")
            return result

        try:
            body_initial = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"Baseline content/recommendations response is not valid JSON: {e}")
            return result

        initial_entries = body_initial.get("entries", [])
        if not isinstance(initial_entries, list):
            helpers.finish(result, logs, "FAILED", "Baseline content/recommendations 'entries' is not a list.")
            return result

        helpers.log_line(logs, "INFO", f"Baseline recommendations count={len(initial_entries)}.", result=result)

        sample_count = min(3, len(initial_entries))
        for i in range(sample_count):
            entry = initial_entries[i] if isinstance(initial_entries[i], dict) else {}
            helpers.log_line(
                logs,
                "INFO",
                f"Baseline entry[{i}]: appId={entry.get('appId')!r}, entryId={entry.get('entryId')!r}, title={entry.get('title')!r}",
                result=result,
            )

        if not initial_entries:
            helpers.finish(result, logs, "FAILED", "Baseline recommendations list is empty; cannot evaluate update behavior.")
            return result

        # Step 2: User watches new content
        helpers.log_line(logs, "STEP", "Manual step — On the device, watch a new movie/TV show not in existing history.", result=result)
        helpers.log_line(logs, "DESC", "Prefer content that is clearly different from usual recommendations (different genre/app).", result=result)

        user_ready = helpers.yes_or_no(
            result,
            logs,
            "Have you watched new content (a few minutes) and returned to the home screen so recommendations can refresh?"
        )
        if not user_ready:
            helpers.finish(result, logs, "SKIPPED", "User did not complete viewing step; cannot validate recommendations update.")
            return result

        # Step 3: Updated recommendations
        helpers.log_line(logs, "STEP", "Fetching updated recommendations via content/recommendations after new viewing.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, dab_topic, "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"Updated content/recommendations returned status={status}.", result=result)

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"Updated content/recommendations returned non-200 status={status}.")
            return result

        try:
            body_updated = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"Updated content/recommendations response is not valid JSON: {e}")
            return result

        updated_entries = body_updated.get("entries", [])
        if not isinstance(updated_entries, list):
            helpers.finish(result, logs, "FAILED", "Updated content/recommendations 'entries' is not a list.")
            return result

        helpers.log_line(logs, "INFO", f"Updated recommendations count={len(updated_entries)}.", result=result)

        sample_count = min(3, len(updated_entries))
        for i in range(sample_count):
            entry = updated_entries[i] if isinstance(updated_entries[i], dict) else {}
            helpers.log_line(
                logs,
                "INFO",
                f"Updated entry[{i}]: appId={entry.get('appId')!r}, entryId={entry.get('entryId')!r}, title={entry.get('title')!r}",
                result=result,
            )

        if not updated_entries:
            helpers.finish(result, logs, "FAILED", "Updated recommendations list is empty; cannot verify updates.")
            return result

        # Step 4: Structural diff (appId + entryId)
        initial_sig = set()
        for e in initial_entries:
            if isinstance(e, dict):
                initial_sig.add(f"{e.get('appId')!r}|{e.get('entryId')!r}")

        updated_sig = set()
        for e in updated_entries:
            if isinstance(e, dict):
                updated_sig.add(f"{e.get('appId')!r}|{e.get('entryId')!r}")

        new_items = updated_sig - initial_sig
        removed_items = initial_sig - updated_sig

        helpers.log_line(logs, "INFO", f"Structural diff: new_items_count={len(new_items)}, removed_items_count={len(removed_items)}.", result=result)

        if new_items:
            preview = list(new_items)[:5]
            helpers.log_line(logs, "INFO", f"Example new recommendation signatures after viewing: {preview}", result=result)
        else:
            helpers.log_line(logs, "INFO", "No new recommendation signatures detected; updates may be ranking-only or delayed.", result=result)

        # Step 5: Manual confirmation on UI
        user_validated = helpers.yes_or_no(
            result,
            logs,
            "Do recommendations on the device UI appear updated to reflect the new content you watched?"
        )

        if user_validated:
            helpers.finish(result, logs, "PASS", "User confirmed recommendations appear updated after watching new content.")
        else:
            helpers.finish(result, logs, "FAILED", "User reported that recommendations did NOT appear updated after watching new content.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error during content/recommendations update check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, baseline_count={len(initial_entries)}, "
            f"updated_count={len(updated_entries)}, id={test_id}, device={device_id}",
            result=result,
        )

    return result
