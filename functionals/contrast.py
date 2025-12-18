from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_contrast_invalid_value_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – contrast invalid values (negative)

    PASS only if:
      - system/settings/set returns 400 for out-of-range contrast
      - stored contrast stays unchanged (within tolerance).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_contrast = None
    invalid_value = None
    tol = 1

    try:
        helpers.log_line(logs, "TEST", f"Contrast Invalid Value Check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Send out-of-range contrast; expect 400 and no change in stored value.", result=result)

        cap_spec = "ops: system/settings/get, system/settings/set | settings: contrast"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        min_contrast, max_contrast = helpers.get_numeric_setting_range("contrast", result, logs)
        if max_contrast is None:
            return result

        helpers.log_line(logs, "INFO", f"contrast range: min={min_contrast}, max={max_contrast}", result=result)

        helpers.log_line(logs, "STEP", "Reading original contrast via system/settings/get.", result=result)
        original_contrast = helpers.get_setting_value(tester, device_id, "contrast", logs=logs, result=result)
        if original_contrast is None:
            return result
        helpers.log_line(logs, "INFO", f"original contrast={original_contrast}", result=result)

        invalid_value = (max_contrast + 10) if isinstance(max_contrast, (int, float)) else 9999
        helpers.log_line(logs, "STEP", f"Sending invalid contrast={invalid_value} via system/settings/set.", result=result)

        status_set, _ = helpers.set_setting_value(tester, device_id, "contrast", invalid_value, logs=logs, result=result)

        if status_set == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set for contrast returned 501.")
        elif status_set != 400:
            helpers.finish(result, logs, "FAILED", f"Expected 400 for invalid contrast, got {status_set}.")
        else:
            helpers.log_line(logs, "INFO", "system/settings/set returned expected 400 for invalid contrast.", result=result)

        helpers.log_line(logs, "STEP", "Reading contrast after invalid request.", result=result)
        current_contrast = helpers.get_setting_value(tester, device_id, "contrast", logs=logs, result=result)
        if current_contrast is None:
            return result

        helpers.log_line(logs, "INFO", f"contrast after invalid request={current_contrast}", result=result)

        if result.test_result not in ("FAILED", "OPTIONAL_FAILED"):
            if helpers.is_close_numeric(current_contrast, original_contrast, tol):
                helpers.finish(result, logs, "PASS", "Device rejected invalid contrast with 400 and kept stored value unchanged.")
            else:
                helpers.finish(result, logs, "FAILED", f"contrast changed after invalid request (original={original_contrast}, current={current_contrast}).")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        try:
            if original_contrast is not None:
                helpers.log_line(logs, "STEP", f"Restoring original contrast={original_contrast}.", result=result)
                helpers.set_setting_value(tester, device_id, "contrast", original_contrast, logs=logs, result=None)
        except Exception:
            pass

        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, invalid={invalid_value}, id={test_id}, device={device_id}", result=result)

    return result

def run_contrast_minimum_value_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – contrast minimum value check
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_contrast = None
    min_contrast = None
    tol = 1

    try:
        helpers.log_line(logs, "TEST", f"Contrast Minimum Value Check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Set contrast to descriptor min and verify via system/settings/get.", result=result)

        cap_spec = "ops: system/settings/get, system/settings/set | settings: contrast"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result  # result.test_result already set (OPTIONAL_FAILED)

        min_contrast, max_contrast = helpers.get_numeric_setting_range("contrast", result, logs)
        if min_contrast is None or max_contrast is None:
            return result

        helpers.log_line(logs, "INFO", f"contrast range: min={min_contrast}, max={max_contrast}", result=result)

        helpers.log_line(logs, "STEP", "Reading original contrast via system/settings/get.", result=result)
        original_contrast = helpers.get_setting_value(tester, device_id, "contrast", logs=logs, result=result)
        if original_contrast is None:
            return result
        helpers.log_line(logs, "INFO", f"original contrast={original_contrast}", result=result)

        helpers.log_line(logs, "STEP", f"Setting contrast to min={min_contrast}.", result=result)
        status_set, _ = helpers.set_setting_value(tester, device_id, "contrast", min_contrast, logs=logs, result=result)

        if status_set == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/settings/set for contrast returned 501.")
            return result
        if status_set != 200:
            helpers.finish(result, logs, "FAILED", f"system/settings/set for contrast min returned {status_set}.")
            return result

        helpers.log_line(logs, "STEP", "Reading contrast after setting min.", result=result)
        current_contrast = helpers.get_setting_value(tester, device_id, "contrast", logs=logs, result=result)
        if current_contrast is None:
            return result

        helpers.log_line(logs, "INFO", f"contrast after set={current_contrast}", result=result)

        if helpers.is_close_numeric(current_contrast, min_contrast, tol):
            helpers.finish(result, logs, "PASS", f"contrast at/near min={min_contrast} within tol={tol}.")
        else:
            helpers.finish(result, logs, "FAILED", f"Expected contrast≈{min_contrast}, got {current_contrast}.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        # best-effort restore; do not change test_result here
        try:
            if original_contrast is not None and min_contrast is not None and not helpers.is_close_numeric(original_contrast, min_contrast, tol):
                helpers.log_line(logs, "STEP", f"Restoring original contrast={original_contrast}.", result=result)
                helpers.set_setting_value(tester, device_id, "contrast", original_contrast, logs=logs, result=None)
        except Exception:
            pass

        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, min={min_contrast}, id={test_id}, device={device_id}", result=result)

    return result
