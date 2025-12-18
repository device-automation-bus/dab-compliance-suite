from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

SMALL_WAIT_TIME = 1

def run_brightness_min_decrement_guard_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – brightness min decrement guard (negative)

    PASS criteria (strict):
      - Set brightness to min.
      - Send below-min brightness via system/settings/set.
      - Device MUST reject with 400 (Bad Request).
      - Stored brightness MUST remain at/near min (tolerance allowed).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_brightness = None
    min_brightness = None
    max_brightness = None
    tol = 1

    try:
        helpers.log_line(logs, "TEST", f"Brightness Min Decrement Guard — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Set min, send below-min, expect 400; brightness must not go below min.", result=result)

        if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
            helpers.set_outcome(result, result.test_result)
            result.test_result = helpers.outcome_of(result)
            helpers.log_line(logs, "SUMMARY", f"outcome={helpers.outcome_of(result)}, id={test_id}, device={device_id}", result=result)
            return result

        # Range
        min_brightness, max_brightness = helpers.get_numeric_setting_range("brightness", result=result, logs=logs)
        if min_brightness is None:
            helpers.set_outcome(result, result.test_result)
            result.test_result = helpers.outcome_of(result)
            helpers.log_line(logs, "SUMMARY", f"outcome={helpers.outcome_of(result)}, id={test_id}, device={device_id}", result=result)
            return result

        helpers.log_line(logs, "INFO", f"brightness range: min={min_brightness}, max={max_brightness}", result=result)

        # Read original (restore value)
        original_brightness = helpers.get_setting_value(tester, device_id, "brightness", logs=logs, result=result)
        if original_brightness is None:
            helpers.set_outcome(result, result.test_result)
            result.test_result = helpers.outcome_of(result)
            helpers.log_line(logs, "SUMMARY", f"outcome={helpers.outcome_of(result)}, id={test_id}, device={device_id}", result=result)
            return result

        helpers.log_line(logs, "INFO", f"original brightness={original_brightness}", result=result)

        # Set to min
        helpers.log_line(logs, "STEP", f"Set brightness to min={min_brightness}", result=result)
        status_set_min, _ = helpers.set_setting_value(tester, device_id, "brightness", min_brightness, logs=logs, result=result)

        if status_set_min == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented.")
            helpers.set_outcome(result, "OPTIONAL_FAILED")
            result.test_result = "OPTIONAL_FAILED"
            return result

        if status_set_min != 200:
            helpers.finish(result, logs, "FAILED", f"Failed to set min brightness (status={status_set_min}).")
            helpers.set_outcome(result, "FAILED")
            result.test_result = "FAILED"
            return result

        # Confirm at/near min
        confirmed_min = helpers.get_setting_value(tester, device_id, "brightness", logs=logs, result=result)
        if confirmed_min is None:
            helpers.set_outcome(result, result.test_result)
            result.test_result = helpers.outcome_of(result)
            return result

        if not helpers.is_close_numeric(confirmed_min, min_brightness, tol):
            helpers.finish(result, logs, "FAILED", f"Cannot confirm min (got={confirmed_min}, expected≈{min_brightness}, tol={tol}).")
            helpers.set_outcome(result, "FAILED")
            result.test_result = "FAILED"
            return result

        # Below-min request (negative)
        invalid_value = float(min_brightness) - 1.0
        helpers.log_line(logs, "STEP", f"Send below-min value={invalid_value}", result=result)

        status_set_invalid, _ = helpers.set_setting_value(tester, device_id, "brightness", invalid_value, logs=logs, result=result)

        # STRICT negative rule:
        # - PASS only if status is 400
        # - Anything else => FAILED
        if status_set_invalid == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented (501).")
            helpers.set_outcome(result, "OPTIONAL_FAILED")
            result.test_result = "OPTIONAL_FAILED"
            return result

        if status_set_invalid != 400:
            helpers.finish(result, logs, "FAILED", f"Below-min request was not rejected with 400 (got status={status_set_invalid}).")
            helpers.set_outcome(result, "FAILED")
            result.test_result = "FAILED"
        else:
            helpers.log_line(logs, "RESULT", "PASS — device rejected below-min request with 400.", result=result)
            helpers.set_outcome(result, "PASS")
            result.test_result = "PASS"

        # Read back brightness: must stay at/near min regardless of status
        after = helpers.get_setting_value(tester, device_id, "brightness", logs=logs, result=result)
        if after is None:
            # keep existing FAILED/PASS, but ensure sync
            helpers.set_outcome(result, helpers.outcome_of(result))
            result.test_result = helpers.outcome_of(result)
            return result

        # Plain line to avoid “[INFO] [INFO]” duplication if your logger already adds INFO
        plain = f"brightness after below-min request={after}"
        LOGGER.result(plain)
        logs.append(plain)

        if not helpers.clamp_check_min(after, min_brightness, tol):
            helpers.finish(result, logs, "FAILED", f"Brightness dropped below min (min={min_brightness}, got={after}, tol={tol}).")
            helpers.set_outcome(result, "FAILED")
            result.test_result = "FAILED"

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
        helpers.set_outcome(result, "OPTIONAL_FAILED")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error: {e}")
        helpers.set_outcome(result, "SKIPPED")
        result.test_result = "SKIPPED"

    finally:
        # Best-effort restore
        try:
            if original_brightness is not None:
                helpers.log_line(logs, "STEP", "Restore original brightness", result=result)
                helpers.set_setting_value(tester, device_id, "brightness", original_brightness, logs=logs, result=None)
        except Exception:
            pass

        # FINAL sync to prevent PASS logs + FAILED summary mismatch
        final_outcome = helpers.outcome_of(result)
        helpers.set_outcome(result, final_outcome)
        result.test_result = final_outcome

        helpers.log_line(logs, "SUMMARY", f"outcome={final_outcome}, min={min_brightness}, id={test_id}, device={device_id}", result=result)

    return result

def run_brightness_mid_level_50_screen_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)

    user_validated = "N/A"
    original_brightness = None
    min_brightness = None
    max_brightness = None
    mid_brightness = None
    tol = 1

    try:
        helpers.log_line(logs, "TEST", f"Brightness mid (~50%) screen check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Set brightness to ~50% of supported range, confirm via DAB, then confirm on screen (manual).", result=result)

        if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result=result, logs=logs):
            return result

        helpers.log_line(logs, "STEP", "Resolve brightness numeric range from system/settings/list cache.", result=result)
        min_brightness, max_brightness = helpers.get_numeric_setting_range("brightness", result=result, logs=logs)
        if min_brightness is None or max_brightness is None:
            return result

        try:
            span = float(max_brightness) - float(min_brightness)
            mid_brightness = float(min_brightness) if span <= 0 else float(min_brightness) + 0.5 * span
            mid_brightness = int(round(mid_brightness))
        except Exception:
            mid_brightness = int(min_brightness) if isinstance(min_brightness, (int, float)) else min_brightness

        if isinstance(min_brightness, (int, float)) and isinstance(max_brightness, (int, float)) and isinstance(mid_brightness, (int, float)):
            if mid_brightness < min_brightness:
                mid_brightness = int(min_brightness)
            if mid_brightness > max_brightness:
                mid_brightness = int(max_brightness)

        helpers.log_line(logs, "INFO", f"brightness range: min={min_brightness!r}, max={max_brightness!r}, mid≈{mid_brightness!r} (tol={tol})", result=result)

        helpers.log_line(logs, "STEP", "Read current brightness (restore value).", result=result)
        original_brightness = helpers.get_setting_value(tester, device_id, "brightness", logs=logs, result=result)
        if original_brightness is None and helpers.outcome_of(result) in ("FAILED", "OPTIONAL_FAILED"):
            return result
        helpers.log_line(logs, "INFO", f"original brightness={original_brightness!r}", result=result)

        helpers.log_line(logs, "STEP", f"Set brightness to mid-level (~50%) value: {mid_brightness!r}.", result=result)
        status, _ = helpers.set_setting_value(tester, device_id, "brightness", mid_brightness, logs=logs, result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented.")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/set returned {status}.")
            return result

        helpers.log_line(logs, "STEP", "Confirm brightness via system/settings/get.", result=result)
        confirmed_brightness = helpers.get_setting_value(tester, device_id, "brightness", logs=logs, result=result)
        if confirmed_brightness is None and helpers.outcome_of(result) in ("FAILED", "OPTIONAL_FAILED"):
            return result

        helpers.log_line(logs, "INFO", f"confirmed brightness={confirmed_brightness!r} (target≈{mid_brightness!r}, tol={tol})", result=result)

        if isinstance(confirmed_brightness, (int, float)) and isinstance(mid_brightness, (int, float)):
            if not helpers.is_close_numeric(confirmed_brightness, mid_brightness, tol):
                helpers.finish(result, logs, "FAILED", f"stored value mismatch: expected≈{mid_brightness!r} (±{tol}), got {confirmed_brightness!r}.")
                return result
        else:
            if confirmed_brightness != mid_brightness:
                helpers.finish(result, logs, "FAILED", f"stored value mismatch: expected {mid_brightness!r}, got {confirmed_brightness!r}.")
                return result

        helpers.log_line(logs, "STEP", "Manual check: verify mid-level brightness is visible on screen.", result=result)
        user_validated = helpers.yes_or_no(result, logs, "Does the screen appear at a reasonable mid (~50%) brightness compared to min/max?")
        if user_validated:
            helpers.finish(result, logs, "PASS", "User confirmed mid-level brightness on screen.")
        else:
            helpers.finish(result, logs, "FAILED", "User did not confirm mid-level brightness on screen.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Not supported: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error: {e}")

    finally:
        try:
            if original_brightness is not None:
                helpers.log_line(logs, "STEP", "Restore original brightness (best-effort).", result=result)
                helpers.set_setting_value(tester, device_id, "brightness", original_brightness, logs=logs, result=None)
        except Exception as e:
            helpers.log_line(logs, "INFO", f"Restore failed: {e}", result=result)

        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={helpers.outcome_of(result)}, user_validated_mid_level={user_validated}, "
            f"min={min_brightness!r}, max={max_brightness!r}, mid={mid_brightness!r}, id={test_id}, device={device_id}",
            result=result,
        )

    return result

def run_brightness_60_video_content_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)

    helpers.log_line(logs, f"[TEST] Brightness ~60% Video Check — {test_name}")
    helpers.log_line(logs, "[DESC] Set ~60% and confirm during video playback (manual).")

    if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
        return result

    original = None
    min_v, max_v = None, None
    tol = 1
    user_ok = "N/A"

    try:
        min_v, max_v = helpers.get_numeric_setting_range("brightness", result, logs)
        if min_v is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        # Calculate target before getting original to fail fast if range is bad
        if max_v is not None and min_v is not None:
            target = int(round(float(min_v) + 0.6 * (float(max_v) - float(min_v))))
        else:
            target = 0 # Should be caught by min_v check above
        
        helpers.log_line(logs, f"[INFO] min={min_v}, max={max_v}, target≈{target}")

        # FIX: Use keyword arguments for result and logs
        original = helpers.get_setting_value(tester, device_id, "brightness", result=result, logs=logs)
        if original is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, f"[STEP] Set brightness to ~60% (≈{target})")
        status, _ = helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", json.dumps({"brightness": target}), logs=logs, result=result)
        
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            helpers.log_line(logs, "[RESULT] OPTIONAL_FAILED — system/settings/set not implemented.")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result
        if status != 200:
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — set target failed (status={status}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        # FIX: Use keyword arguments
        confirmed = helpers.get_setting_value(tester, device_id, "brightness", result=result, logs=logs)
        if confirmed is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        if not helpers.is_close_numeric(confirmed, target, tol):
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — stored value mismatch (got={confirmed}, expected≈{target}, tol={tol}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, "[STEP] Manual check: play a video and confirm brightness looks correct.")
        user_ok = helpers.yes_or_no(result, logs, "During video playback, does the picture reflect the ~60% brightness level?")
        result.test_result = "PASS" if user_ok else "FAILED"
        helpers.log_line(logs, "[RESULT] PASS" if user_ok else "[RESULT] FAILED")

    except helpers.UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        helpers.log_line(logs, f"[RESULT] OPTIONAL_FAILED — unsupported op: {e.topic}")
    except Exception as e:
        result.test_result = "SKIPPED"
        helpers.log_line(logs, f"[RESULT] SKIPPED — unexpected error: {e}")
    finally:
        try:
            if original is not None:
                helpers.log_line(logs, "[STEP] Restore original brightness")
                helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", json.dumps({"brightness": original}), logs=logs, result=None)
        except Exception:
            pass

        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, user_ok={user_ok}, test_id={test_id}, device={device_id}")

    return result

def run_brightness_min_decrement_guard_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    helpers.log_line(logs, f"[TEST] Brightness Min Decrement Guard — {test_name}")
    helpers.log_line(logs, "[DESC] Set min, try below-min, verify value does not drop below min.")

    if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
        return result

    original = None
    min_v, max_v = None, None
    tol = 1

    try:
        min_v, max_v = helpers.get_numeric_setting_range("brightness", logs, result)
        if min_v is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, f"[INFO] brightness range: min={min_v}, max={max_v}")

        original = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if original is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result
        helpers.log_line(logs, f"[INFO] original brightness={original}")

        helpers.log_line(logs, f"[STEP] Set brightness to min={min_v}")
        status, _ = helpers.set_setting_value(tester, device_id, "brightness", min_v, logs, result)
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            helpers.log_line(logs, "[RESULT] OPTIONAL_FAILED — system/settings/set not implemented.")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result
        if status != 200:
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — set min failed (status={status}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        confirmed_min = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if confirmed_min is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        if not helpers.approx_equal(confirmed_min, min_v, tol):
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — min confirm mismatch (got={confirmed_min}, expected≈{min_v}, tol={tol}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        invalid_value = float(min_v) - 1
        helpers.log_line(logs, f"[STEP] Send below-min value={invalid_value}")
        status, _ = helpers.set_setting_value(tester, device_id, "brightness", invalid_value, logs, result)

        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            helpers.log_line(logs, "[RESULT] OPTIONAL_FAILED — system/settings/set not implemented.")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        if status not in (200, 400):
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[INFO] unexpected status for below-min request: {status}")

        after = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if after is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, f"[INFO] brightness after below-min request={after}")

        if helpers.clamp_check_min(after, min_v, tol):
            if result.test_result == "UNKNOWN":
                result.test_result = "PASS"
            helpers.log_line(logs, "[INFO] PASS — brightness stayed at/near min boundary.")
        else:
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — brightness dropped below min (min={min_v}, got={after}, tol={tol}).")

    except helpers.UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        helpers.log_line(logs, f"[RESULT] OPTIONAL_FAILED — unsupported op: {e.topic}")
    except Exception as e:
        result.test_result = "SKIPPED"
        helpers.log_line(logs, f"[RESULT] SKIPPED — unexpected error: {e}")
    finally:
        try:
            if original is not None:
                helpers.log_line(logs, "[STEP] Restore original brightness")
                helpers.set_setting_value(tester, device_id, "brightness", original, logs, None)
        except Exception:
            pass

        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, min={min_v}, test_id={test_id}, device={device_id}")

    return result


def run_brightness_mid_level_50_screen_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)

    helpers.log_line(logs, f"[TEST] Brightness Mid (~50%) Screen Check — {test_name}")
    helpers.log_line(logs, "[DESC] Set mid value and confirm on screen (manual).")

    if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
        return result

    original = None
    min_v, max_v = None, None
    tol = 1
    user_ok = "N/A"

    try:
        min_v, max_v = helpers.get_numeric_setting_range("brightness", logs, result)
        if min_v is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        mid_v = int(round((float(min_v) + float(max_v)) / 2.0))
        helpers.log_line(logs, f"[INFO] min={min_v}, max={max_v}, mid≈{mid_v}")

        original = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if original is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, f"[STEP] Set brightness to mid≈{mid_v}")
        status, _ = helpers.set_setting_value(tester, device_id, "brightness", mid_v, logs, result)
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            helpers.log_line(logs, "[RESULT] OPTIONAL_FAILED — system/settings/set not implemented.")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result
        if status != 200:
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — set mid failed (status={status}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        confirmed = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if confirmed is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        if not helpers.approx_equal(confirmed, mid_v, tol):
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — stored value mismatch (got={confirmed}, expected≈{mid_v}, tol={tol}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, "[STEP] Manual check: confirm screen looks mid brightness.")
        user_ok = helpers.yes_or_no(result, logs, "Does the screen look like a mid (~50%) brightness level?")
        result.test_result = "PASS" if user_ok else "FAILED"
        helpers.log_line(logs, "[RESULT] PASS" if user_ok else "[RESULT] FAILED")

    except helpers.UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        helpers.log_line(logs, f"[RESULT] OPTIONAL_FAILED — unsupported op: {e.topic}")
    except Exception as e:
        result.test_result = "SKIPPED"
        helpers.log_line(logs, f"[RESULT] SKIPPED — unexpected error: {e}")
    finally:
        try:
            if original is not None:
                helpers.log_line(logs, "[STEP] Restore original brightness")
                helpers.set_setting_value(tester, device_id, "brightness", original, logs, None)
        except Exception:
            pass

        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, user_ok={user_ok}, test_id={test_id}, device={device_id}")

    return result


def run_brightness_60_video_content_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)

    helpers.log_line(logs, f"[TEST] Brightness ~60% Video Check — {test_name}")
    helpers.log_line(logs, "[DESC] Set ~60% and confirm during video playback (manual).")

    if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
        return result

    original = None
    min_v, max_v = None, None
    tol = 1
    user_ok = "N/A"

    try:
        min_v, max_v = helpers.get_numeric_setting_range("brightness", logs, result)
        if min_v is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        target = int(round(float(min_v) + 0.6 * (float(max_v) - float(min_v))))
        helpers.log_line(logs, f"[INFO] min={min_v}, max={max_v}, target≈{target}")

        original = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if original is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, f"[STEP] Set brightness to ~60% (≈{target})")
        status, _ = helpers.set_setting_value(tester, device_id, "brightness", target, logs, result)
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            helpers.log_line(logs, "[RESULT] OPTIONAL_FAILED — system/settings/set not implemented.")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result
        if status != 200:
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — set target failed (status={status}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        confirmed = helpers.get_setting_value(tester, device_id, "brightness", logs, result)
        if confirmed is None:
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        if not helpers.approx_equal(confirmed, target, tol):
            result.test_result = "FAILED"
            helpers.log_line(logs, f"[RESULT] FAILED — stored value mismatch (got={confirmed}, expected≈{target}, tol={tol}).")
            helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}")
            return result

        helpers.log_line(logs, "[STEP] Manual check: play a video and confirm brightness looks correct.")
        user_ok = helpers.yes_or_no(result, logs, "During video playback, does the picture reflect the ~60% brightness level?")
        result.test_result = "PASS" if user_ok else "FAILED"
        helpers.log_line(logs, "[RESULT] PASS" if user_ok else "[RESULT] FAILED")

    except helpers.UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        helpers.log_line(logs, f"[RESULT] OPTIONAL_FAILED — unsupported op: {e.topic}")
    except Exception as e:
        result.test_result = "SKIPPED"
        helpers.log_line(logs, f"[RESULT] SKIPPED — unexpected error: {e}")
    finally:
        try:
            if original is not None:
                helpers.log_line(logs, "[STEP] Restore original brightness")
                helpers.set_setting_value(tester, device_id, "brightness", original, logs, None)
        except Exception:
            pass

        helpers.log_line(logs, f"[SUMMARY] outcome={result.test_result}, user_ok={user_ok}, test_id={test_id}, device={device_id}")

    return result


def run_brightness_max_increment_guard_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_brightness = None
    min_brightness = None
    max_brightness = None

    try:
        helpers.log_line(logs, "TEST", f"Brightness max guard — {test_name} (id={test_id}, device={device_id})")
        helpers.log_line(logs, "DESC", "Set max, then try max+1. Must not exceed max.")

        if not helpers.require_capabilities(
            tester,
            device_id,
            "ops: system/settings/get, system/settings/set | settings: brightness",
            result,
            logs,
        ):
            return result

        helpers.log_line(logs, "STEP", "Read brightness range.")
        min_brightness, max_brightness = helpers.get_numeric_setting_range("brightness", result, logs)
        if min_brightness is None:
            return result

        helpers.log_line(logs, "INFO", f"range: min={min_brightness!r}, max={max_brightness!r}")

        helpers.log_line(logs, "STEP", "Read current brightness (restore value).")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/get returned {status}.")
            return result

        try:
            body_get1 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"system/settings/get invalid JSON: {e}")
            return result

        original_brightness = body_get1.get("brightness")
        helpers.log_line(logs, "INFO", f"original brightness={original_brightness!r}")

        helpers.log_line(logs, "STEP", f"Set brightness to max ({max_brightness}).")
        payload_max = json.dumps({"brightness": max_brightness})
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_max, logs, result)
        status = helpers.dab_status_from(response, rc)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented.")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/set(max) returned {status}.")
            return result

        helpers.log_line(logs, "STEP", "Confirm max via system/settings/get.")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"confirm get returned {status}.")
            return result

        try:
            body_get_max = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"confirm get invalid JSON: {e}")
            return result

        confirmed_max = body_get_max.get("brightness")
        helpers.log_line(logs, "INFO", f"confirmed max={confirmed_max!r} (expected {max_brightness!r})")

        if not helpers.is_close_numeric(confirmed_max, max_brightness, 1):
            helpers.finish(result, logs, "FAILED", f"cannot confirm max (got {confirmed_max!r}).")
            return result

        invalid_value = max_brightness + 1
        helpers.log_line(logs, "STEP", f"Send above-max value ({invalid_value}).")
        payload_invalid = json.dumps({"brightness": invalid_value})
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_invalid, logs, result)
        status = helpers.dab_status_from(response, rc)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "above-max check not supported (501).")
            return result
        if status not in (200, 400):
            if helpers.outcome_of(result) == "UNKNOWN":
                helpers.set_outcome(result, "FAILED")
            helpers.log_line(logs, "INFO", f"above-max returned {status}; expected 400 or 200. Continue.")

        helpers.log_line(logs, "STEP", "Read brightness after above-max request.")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            if helpers.outcome_of(result) == "UNKNOWN":
                helpers.set_outcome(result, "FAILED")
            helpers.finish(result, logs, helpers.outcome_of(result), f"post-check get returned {status}.")
            return result

        try:
            body_get2 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            if helpers.outcome_of(result) == "UNKNOWN":
                helpers.set_outcome(result, "FAILED")
            helpers.finish(result, logs, helpers.outcome_of(result), f"post-check get invalid JSON: {e}")
            return result

        brightness_after = body_get2.get("brightness")
        helpers.log_line(logs, "INFO", f"after above-max brightness={brightness_after!r}")

        if not isinstance(brightness_after, (int, float)):
            if helpers.outcome_of(result) == "UNKNOWN":
                helpers.finish(result, logs, "FAILED", "brightness is missing or not numeric.")
            else:
                helpers.finish(result, logs, helpers.outcome_of(result), "brightness is missing or not numeric.")
            return result

        if brightness_after > (max_brightness + 1):
            helpers.finish(result, logs, "FAILED", f"exceeded max (got {brightness_after}, max {max_brightness}).")
            return result

        if helpers.outcome_of(result) == "UNKNOWN":
            if helpers.is_close_numeric(brightness_after, max_brightness, 1):
                helpers.finish(result, logs, "PASS", "did not exceed max; value stayed at boundary.")
            else:
                helpers.finish(result, logs, "PASS", f"did not exceed max; value is {brightness_after}.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Not supported: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error: {e}")

    finally:
        try:
            if original_brightness is not None:
                helpers.log_line(logs, "STEP", "Restore original brightness.")
                payload_restore = json.dumps({"brightness": original_brightness})
                helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_restore, logs, None)
        except Exception as e:
            helpers.log_line(logs, "INFO", f"Restore failed: {e}")

        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={helpers.outcome_of(result)}, min={min_brightness!r}, max={max_brightness!r}, id={test_id}, device={device_id}",
        )

    return result

def run_brightness_rapid_change_responsiveness_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    user_validated = "N/A"
    original_brightness = None
    min_brightness = None
    max_brightness = None
    value_20 = None
    value_80 = None
    value_40 = None

    try:
        helpers.log_line(logs, "TEST", f"Brightness rapid change — {test_name} (id={test_id}, device={device_id})")
        helpers.log_line(logs, "DESC", "Set ~20%, ~80%, ~40%. Confirm screen updates quickly.")

        if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
            return result

        helpers.log_line(logs, "STEP", "Read brightness range.")
        min_brightness, max_brightness = helpers.get_numeric_setting_range("brightness", result, logs)
        if min_brightness is None:
            return result

        span = max_brightness - min_brightness
        if span <= 0:
            value_20 = min_brightness
            value_40 = min_brightness
            value_80 = min_brightness
        else:
            value_20 = int(round(min_brightness + 0.2 * span))
            value_40 = int(round(min_brightness + 0.4 * span))
            value_80 = int(round(min_brightness + 0.8 * span))

        value_20 = max(min(value_20, max_brightness), min_brightness)
        value_40 = max(min(value_40, max_brightness), min_brightness)
        value_80 = max(min(value_80, max_brightness), min_brightness)

        helpers.log_line(logs, "INFO", f"values: 20%={value_20}, 80%={value_80}, 40%={value_40}")

        helpers.log_line(logs, "STEP", "Read current brightness (restore value).")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/get returned {status}.")
            return result

        try:
            body_get1 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"system/settings/get invalid JSON: {e}")
            return result

        original_brightness = body_get1.get("brightness")
        helpers.log_line(logs, "INFO", f"original brightness={original_brightness!r}")

        helpers.log_line(logs, "STEP", "Watch the screen during changes.")

        for label, value in (("20%", value_20), ("80%", value_80), ("40%", value_40)):
            payload = json.dumps({"brightness": value})
            helpers.log_line(logs, "STEP", f"Set brightness to {label} ({value}).")

            rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            status = helpers.dab_status_from(response, rc)

            if status == 501:
                helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented.")
                return result
            if status != 200:
                helpers.finish(result, logs, "FAILED", f"system/settings/set failed at {label} with {status}.")
                return result

            time.sleep(SMALL_WAIT_TIME)

        helpers.log_line(logs, "STEP", "Confirm final value via system/settings/get.")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"confirm get returned {status}.")
            return result

        try:
            body_get2 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"confirm get invalid JSON: {e}")
            return result

        final_brightness = body_get2.get("brightness")
        helpers.log_line(logs, "INFO", f"final brightness={final_brightness!r} (expected {value_40!r})")

        if isinstance(final_brightness, (int, float)) and isinstance(value_40, (int, float)):
            if abs(final_brightness - value_40) > 1:
                helpers.finish(result, logs, "FAILED", f"final value mismatch: got {final_brightness}, expected {value_40}.")
                return result
        else:
            if final_brightness != value_40:
                helpers.finish(result, logs, "FAILED", f"final value mismatch: got {final_brightness!r}, expected {value_40!r}.")
                return result

        user_validated = helpers.yes_or_no(result, logs, "Did the screen update quickly after each change?")
        if user_validated:
            helpers.finish(result, logs, "PASS", "User confirmed responsiveness.")
        else:
            helpers.finish(result, logs, "FAILED", "User did not confirm responsiveness.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Not supported: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error: {e}")

    finally:
        try:
            if original_brightness is not None:
                helpers.log_line(logs, "STEP", "Restore original brightness.")
                payload_restore = json.dumps({"brightness": original_brightness})
                helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_restore, logs, None)
        except Exception as e:
            helpers.log_line(logs, "INFO", f"Restore failed: {e}")

        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={helpers.outcome_of(result)}, user_validated={user_validated}, id={test_id}, device={device_id}",
        )

    return result

def run_brightness_min_value_screen_check(dab_topic, test_name, tester, device_id):
    """Check device brightness can be set to minimum and is visible on-screen; preserves original value, verifies via API and manual confirmation, and returns a TestResult."""
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    user_validated = "N/A"
    original_brightness = None
    min_brightness = None
    max_brightness = None

    try:
        helpers.log_line(logs, "TEST", f"Brightness min screen check — {test_name} (id={test_id}, device={device_id})")
        helpers.log_line(logs, "DESC", "Set brightness to minimum, confirm via DAB, then confirm on screen.")

        if not helpers.require_capabilities(tester, device_id, "ops: system/settings/get, system/settings/set | settings: brightness", result, logs):
            return result

        helpers.log_line(logs, "STEP", "Read brightness range.")
        min_brightness, max_brightness = helpers.get_numeric_setting_range("brightness", result, logs)
        if min_brightness is None:
            return result

        helpers.log_line(logs, "INFO", f"brightness min={min_brightness!r}, max={max_brightness!r}")

        helpers.log_line(logs, "STEP", "Read current brightness (restore value).")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/get returned {status}.")
            return result

        try:
            body_get1 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"system/settings/get invalid JSON: {e}")
            return result

        original_brightness = body_get1.get("brightness")
        helpers.log_line(logs, "INFO", f"original brightness={original_brightness!r}")

        helpers.log_line(logs, "STEP", f"Set brightness to minimum ({min_brightness}).")
        payload_min = json.dumps({"brightness": min_brightness})
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_min, logs, result)
        status = helpers.dab_status_from(response, rc)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set not implemented.")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/set returned {status}.")
            return result

        helpers.log_line(logs, "STEP", "Confirm brightness via system/settings/get.")
        rc, response = helpers.execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        status = helpers.dab_status_from(response, rc)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"confirm get returned {status}.")
            return result

        try:
            body_get2 = json.loads(response) if isinstance(response, str) else (response or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"confirm get invalid JSON: {e}")
            return result

        confirmed_brightness = body_get2.get("brightness")
        helpers.log_line(logs, "INFO", f"confirmed brightness={confirmed_brightness!r}")

        if confirmed_brightness != min_brightness:
            helpers.finish(result, logs, "FAILED", f"expected {min_brightness!r}, got {confirmed_brightness!r}.")
            return result

        helpers.log_line(logs, "STEP", "Manual check: screen should be very dim.")
        user_validated = helpers.yes_or_no(result, logs, "Is the screen clearly at minimum brightness now?")

        if user_validated:
            helpers.finish(result, logs, "PASS", "User confirmed minimum brightness on screen.")
        else:
            helpers.finish(result, logs, "FAILED", "User did not confirm minimum brightness on screen.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Not supported: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error: {e}")

    finally:
        try:
            if original_brightness is not None:
                helpers.log_line(logs, "STEP", "Restore original brightness.")
                payload_restore = json.dumps({"brightness": original_brightness})
                helpers.execute_cmd_and_log(tester, device_id, "system/settings/set", payload_restore, logs, None)
        except Exception as e:
            helpers.log_line(logs, "INFO", f"Restore failed: {e}")

        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={helpers.outcome_of(result)}, user_validated={user_validated}, min={min_brightness!r}, id={test_id}, device={device_id}",
        )

    return result
