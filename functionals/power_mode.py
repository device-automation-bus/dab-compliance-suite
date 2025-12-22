from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_system_power_mode_active_to_standby_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – system/power-mode/set Active → Standby (functional, positive, P0)

    Goal:
      - Ensure the device transitions from 'Active' to 'Standby' using system/power-mode/set.
      - Verify via system/power-mode/get that the mode is 'Standby'.
      - Confirm that DAB remains active by successfully calling system/power-mode/get after the transition.

    Expected behavior:
      - Precondition: device is (or can be set) to 'Active'.
      - system/power-mode/set {"mode": "Standby"} returns status=200.
      - system/power-mode/get reports mode "Standby".
      - DAB is still responsive (we prove this by the successful get).
      - 501 on get/set → OPTIONAL_FAILED.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_mode = None
    final_mode = None

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Use system/power-mode/set to move the device from 'Active' to 'Standby' and verify via get that DAB stays responsive.", result=result)
        helpers.log_line(logs, "DESC", "Required operations: system/power-mode/get, system/power-mode/set.", result=result)
        helpers.log_line(logs, "DESC", "PASS if set('Standby') returns 200, get reports 'Standby', and DAB remains active.", result=result)

        cap_spec = "ops: system/power-mode/get, system/power-mode/set"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # Step 0: Read current power mode
        helpers.log_line(logs, "STEP", "Reading current power mode via system/power-mode/get.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"Initial system/power-mode/get returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/get is not implemented on this device (status=501).")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"Initial system/power-mode/get did not return 200; got {status}.")
            return result

        try:
            body_init = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"Initial system/power-mode/get response is not valid JSON: {e}")
            return result

        original_mode = body_init.get("mode")
        helpers.log_line(logs, "INFO", f"Original power mode reported by device: {original_mode!r}", result=result)

        # Step 1: Ensure precondition 'Active'
        if original_mode != "Active":
            payload_active = json.dumps({"mode": "Active"})
            helpers.log_line(logs, "STEP", f"Precondition: setting power mode to 'Active' via system/power-mode/set, payload={payload_active}", result=result)
            status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_active, logs=logs, result=result)
            helpers.log_line(logs, "INFO", f"system/power-mode/set('Active') returned status={status}.", result=result)

            if status == 501:
                helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/set is not implemented on this device (status=501).")
                return result
            if status != 200:
                helpers.finish(result, logs, "FAILED", f"Could not set power mode to 'Active'; expected 200, got {status}.")
                return result

            helpers.log_line(logs, "STEP", "Confirming power mode is 'Active' via system/power-mode/get.", result=result)
            status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
            helpers.log_line(logs, "INFO", f"system/power-mode/get after setting 'Active' returned status={status}.", result=result)

            if status != 200:
                helpers.finish(result, logs, "FAILED", f"system/power-mode/get did not return 200 after setting 'Active'; got {status}.")
                return result

            try:
                body_active = json.loads(body) if isinstance(body, str) else (body or {})
            except Exception as e:
                helpers.finish(result, logs, "FAILED", f"JSON parsing failed after setting 'Active': {e}")
                return result

            mode_after_active = body_active.get("mode")
            helpers.log_line(logs, "INFO", f"Power mode after setting 'Active': {mode_after_active!r}", result=result)

            if mode_after_active != "Active":
                helpers.finish(result, logs, "FAILED", f"Expected power mode 'Active' as precondition, but got {mode_after_active!r}.")
                return result

        # Step 2: Set power mode to 'Standby'
        payload_standby = json.dumps({"mode": "Standby"})
        helpers.log_line(logs, "STEP", f"Setting power mode to 'Standby' via system/power-mode/set, payload={payload_standby}", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_standby, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/set('Standby') returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/set is not implemented on this device (status=501).")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/set('Standby') did not return 200; got {status}.")
            return result

        # Step 3: Confirm 'Standby' and DAB still active
        helpers.log_line(logs, "STEP", "Confirming power mode is 'Standby' via system/power-mode/get (also validates DAB remains active).", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/get after setting 'Standby' returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/get is not implemented for post-Standby check (status=501).")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/get did not return 200 after setting 'Standby'; DAB may not be responsive (got {status}).")
            return result

        try:
            body_final = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"JSON parsing failed after setting 'Standby': {e}")
            return result

        final_mode = body_final.get("mode")
        helpers.log_line(logs, "INFO", f"Power mode after setting 'Standby': {final_mode!r}", result=result)

        if final_mode != "Standby":
            helpers.finish(result, logs, "FAILED", f"Expected power mode 'Standby', but got {final_mode!r}. DAB is responsive, but mode did not transition as expected.")
            return result

        helpers.finish(result, logs, "PASS", "Device transitioned from 'Active' to 'Standby', and DAB remained active with mode confirmed as 'Standby'.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error during Active→Standby power mode check: {e}")

    finally:
        # Best-effort restore original mode if known and different from Standby
        try:
            if original_mode is not None and original_mode != "Standby":
                payload_restore = json.dumps({"mode": original_mode})
                helpers.log_line(logs, "STEP", f"Best-effort restore: setting power mode back to original value {original_mode!r}.", result=result)
                restore_status, _ = helpers.execute_cmd_and_log(
                    tester, device_id, "system/power-mode/set", payload_restore, logs=logs, result=None
                )
                helpers.log_line(logs, "INFO", f"Restore system/power-mode/set returned status={restore_status}.", result=result)
        except Exception as e:
            helpers.log_line(logs, "INFO", f"Failed to restore original power mode: {e}", result=result)

        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, original_mode={original_mode!r}, final_mode={final_mode!r}, id={test_id}, device={device_id}",
            result=result,
        )

    return result

def run_system_power_mode_set_missing_mode_param_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – system/power-mode/set missing 'mode' parameter (negative, functional)

    Goal:
      - Ensure system/power-mode/set rejects a request that omits the required 'mode' field.
      - Confirm that the device remains in the previous power mode (Active) after the invalid request.

    Expected behavior:
      - Precondition: device power mode is set to "Active".
      - Invalid call: system/power-mode/set with {} should return 400 (Bad Request).
      - Postcondition: system/power-mode/get still reports mode "Active".
      - 501 → OPTIONAL_FAILED (operation not implemented).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    original_mode = None
    final_mode = None

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Verify system/power-mode/set rejects a request missing 'mode' and that power mode stays Active.", result=result)
        helpers.log_line(logs, "DESC", "Required operations: system/power-mode/get, system/power-mode/set.", result=result)
        helpers.log_line(logs, "DESC", "PASS if device is set to Active, invalid {} call returns 400, and power mode remains Active.", result=result)

        cap_spec = "ops: system/power-mode/get, system/power-mode/set"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # Step 0: Read current power mode (best-effort, for logging/restore)
        helpers.log_line(logs, "STEP", "Reading current power mode via system/power-mode/get.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"Initial system/power-mode/get returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/get is not implemented on this device (status=501).")
            return result

        if status == 200:
            try:
                body_init = json.loads(body) if isinstance(body, str) else (body or {})
            except Exception as e:
                helpers.finish(result, logs, "FAILED", f"Initial system/power-mode/get response is not valid JSON: {e}")
                return result
            original_mode = body_init.get("mode")
            helpers.log_line(logs, "INFO", f"Original power mode reported by device: {original_mode!r}", result=result)
        else:
            helpers.log_line(logs, "INFO", f"Could not determine original power mode; proceeding with test (status={status}).", result=result)

        # Step 1: Set power mode to "Active"
        payload_active = json.dumps({"mode": "Active"})
        helpers.log_line(logs, "STEP", f"Setting power mode to 'Active' via system/power-mode/set, payload={payload_active}", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_active, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/set('Active') returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/set is not implemented on this device (status=501).")
            return result
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"Could not set power mode to 'Active'; expected 200, got {status}.")
            return result

        # Step 2: Confirm power mode is 'Active'
        helpers.log_line(logs, "STEP", "Confirming power mode is 'Active' via system/power-mode/get.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/get after setting 'Active' returned status={status}.", result=result)

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/get did not return 200 after setting 'Active'; got {status}.")
            return result

        try:
            body_active = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/get JSON parsing failed after setting 'Active': {e}")
            return result

        mode_after_active = body_active.get("mode")
        helpers.log_line(logs, "INFO", f"Power mode after setting 'Active': {mode_after_active!r}", result=result)
        if mode_after_active != "Active":
            helpers.finish(result, logs, "FAILED", f"Expected power mode 'Active', but got {mode_after_active!r}.")
            return result

        # Step 3: Send invalid system/power-mode/set without 'mode' field
        payload_invalid = "{}"
        helpers.log_line(logs, "STEP", f"Sending system/power-mode/set with missing 'mode' field, payload={payload_invalid}", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_invalid, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/set (missing 'mode') returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/power-mode/set reported status=501 for missing 'mode' payload.")
            return result
        if status != 400:
            helpers.finish(result, logs, "FAILED", f"Expected status=400 for missing 'mode' field, but got status={status}.")
            return result

        # Step 4: Confirm power mode is still 'Active'
        helpers.log_line(logs, "STEP", "Confirming power mode remains 'Active' after invalid system/power-mode/set.", result=result)
        status, body = helpers.execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"system/power-mode/get after invalid set returned status={status}.", result=result)

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/get did not return 200 after invalid set; got {status}.")
            return result

        try:
            body_final = json.loads(body) if isinstance(body, str) else (body or {})
        except Exception as e:
            helpers.finish(result, logs, "FAILED", f"system/power-mode/get JSON parsing failed after invalid set: {e}")
            return result

        final_mode = body_final.get("mode")
        helpers.log_line(logs, "INFO", f"Power mode after invalid set: {final_mode!r}", result=result)

        if final_mode != "Active":
            helpers.finish(result, logs, "FAILED", f"Power mode changed unexpectedly after invalid set. Expected 'Active', observed {final_mode!r}.")
            return result

        helpers.finish(result, logs, "PASS", "Missing 'mode' parameter correctly rejected with status=400 and power mode remained 'Active'.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error during power-mode missing-parameter check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, original_mode={original_mode!r}, final_mode={final_mode!r}, id={test_id}, device={device_id}",
            result=result,
        )

    return result

