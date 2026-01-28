from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time

def run_exit_app_while_in_background_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.0 – applications/exit while app is in BACKGROUND (negative / graceful-handling)

    PASS if:
      - The request returns promptly (no timeout/crash) AND
      - Either:
          a) exit succeeds (200) and app becomes STOPPED, OR
          b) exit is rejected gracefully with a client error (prefer 400 per suite rule),
             and the device remains stable (no hang).
    OPTIONAL_FAILED if operations not supported (501 / capability gate).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")

    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    status_launch = None
    status_state_bg = None
    status_exit = None
    status_state_after = None

    LAUNCH_WAIT = globals().get("APP_LAUNCH_WAIT", 5)
    BG_WAIT = globals().get("APP_BACKGROUND_WAIT", 3)
    EXIT_WAIT = globals().get("APP_EXIT_WAIT", 3)

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id}, appId={app_id})", result=result)
        helpers.log_line(logs, "DESC", "Launch YouTube, move to BACKGROUND (HOME), then call applications/exit while in BACKGROUND.", result=result)
        helpers.log_line(logs, "DESC", "Goal: validate graceful handling (no crash/timeout). Accept success (200) or clean rejection (prefer 400).", result=result)

        if not app_id:
            helpers.finish(result, logs, "SKIPPED", "config.apps['youtube'] not set.")
            return result

        cap_spec = "ops: applications/launch, applications/get-state, applications/exit, input/key-press | keys: KEY_HOME"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # 1) Launch app
        helpers.log_line(logs, "STEP", f"Launching app via applications/launch (appId={app_id}).", result=result)
        status_launch, _ = helpers.execute_cmd_and_log(
            tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs=logs, result=result
        )

        if status_launch == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/launch returned 501.")
            return result
        if status_launch != 200:
            helpers.finish(result, logs, "FAILED", f"applications/launch returned {status_launch} (expected 200).")
            return result

        helpers.log_line(logs, "WAIT", f"Waiting {LAUNCH_WAIT}s after launch.", result=result)
        time.sleep(LAUNCH_WAIT)

        # 2) Send HOME to background the app
        helpers.log_line(logs, "STEP", "Sending KEY_HOME to move app to background.", result=result)
        status_home, _ = helpers.execute_cmd_and_log(
            tester, device_id, "input/key-press", json.dumps({"keyCode": "KEY_HOME"}), logs=logs, result=result
        )
        if status_home == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "input/key-press returned 501.")
            return result
        if status_home != 200:
            helpers.finish(result, logs, "FAILED", f"input/key-press(KEY_HOME) returned {status_home} (expected 200).")
            return result

        helpers.log_line(logs, "WAIT", f"Waiting {BG_WAIT}s after HOME.", result=result)
        time.sleep(BG_WAIT)

        # 3) Confirm BACKGROUND (or at least not FOREGROUND) via get-state
        helpers.log_line(logs, "STEP", "Reading app state via applications/get-state (expect BACKGROUND or not FOREGROUND).", result=result)
        status_state_bg, body_state_bg = helpers.execute_cmd_and_log(
            tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs=logs, result=result
        )
        if status_state_bg == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/get-state returned 501.")
            return result
        if status_state_bg != 200:
            helpers.finish(result, logs, "FAILED", f"applications/get-state returned {status_state_bg} (expected 200).")
            return result

        state_bg = None
        try:
            parsed = body_state_bg if isinstance(body_state_bg, dict) else json.loads(body_state_bg or "{}")
            state_bg = parsed.get("state")
        except Exception:
            state_bg = None

        helpers.log_line(logs, "INFO", f"state after HOME={state_bg}", result=result)

        # If device does not report BACKGROUND reliably, still proceed, but note it.
        if state_bg == "FOREGROUND":
            helpers.log_line(logs, "INFO", "App still reports FOREGROUND after HOME; proceeding to exit to validate graceful handling.", result=result)

        # 4) Exit while app is background (or not foreground)
        helpers.log_line(logs, "STEP", "Sending applications/exit while app is expected BACKGROUND.", result=result)
        status_exit, _ = helpers.execute_cmd_and_log(
            tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs=logs, result=result
        )

        if status_exit == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/exit returned 501.")
            return result

        helpers.log_line(logs, "WAIT", f"Waiting {EXIT_WAIT}s after exit.", result=result)
        time.sleep(EXIT_WAIT)

        # 5) Read state after exit
        helpers.log_line(logs, "STEP", "Reading app state after exit via applications/get-state.", result=result)
        status_state_after, body_state_after = helpers.execute_cmd_and_log(
            tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs=logs, result=result
        )
        if status_state_after == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/get-state returned 501 after exit.")
            return result
        if status_state_after != 200:
            helpers.finish(result, logs, "FAILED", f"applications/get-state returned {status_state_after} after exit (expected 200).")
            return result

        state_after = None
        try:
            parsed_after = body_state_after if isinstance(body_state_after, dict) else json.loads(body_state_after or "{}")
            state_after = parsed_after.get("state")
        except Exception:
            state_after = None

        helpers.log_line(logs, "INFO", f"state after exit={state_after}", result=result)

        # Outcome logic (graceful handling)
        if status_exit == 200:
            # Prefer STOPPED, but allow BACKGROUND->STOPPED propagation delays; treat not-stopped as FAILED to keep it meaningful.
            if state_after == "STOPPED":
                helpers.finish(result, logs, "PASS", "Exit succeeded (200) while app was backgrounded and state is STOPPED.")
            else:
                helpers.finish(result, logs, "FAILED", f"Exit returned 200 but state is '{state_after}' (expected STOPPED).")
        elif status_exit == 400:
            # Graceful rejection is acceptable for this negative scenario.
            helpers.finish(result, logs, "PASS", "Exit was rejected gracefully with 400 while app was backgrounded (no crash/timeout).")
        else:
            # Any other code: treat as FAILED (keeps expectations clear) but still “graceful” from stability standpoint.
            helpers.finish(result, logs, "FAILED", f"Unexpected exit status {status_exit} while app backgrounded (expected 200 or 400).")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, launch={status_launch}, bg_state_status={status_state_bg}, exit={status_exit}, "
            f"after_state_status={status_state_after}, id={test_id}, device={device_id}, appId={app_id}",
            result=result,
        )

    return result


def run_exit_app_without_parameters_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.0 – applications/exit missing parameters (negative)

    PASS only if:
      - applications/exit returns 400 when request body is empty OR missing appId.
    OPTIONAL_FAILED if:
      - applications/exit not implemented (501) or not supported by capability gate.
    FAILED if:
      - returns 200, or any non-400 (except 501), for these malformed requests.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    status_empty = None
    status_missing = None

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Send applications/exit with empty body and missing appId; expect 400 Bad Request.", result=result)
        helpers.log_line(logs, "DESC", "Goal: confirm graceful rejection (no crash/hang) and correct client error.", result=result)

        cap_spec = "ops: applications/exit"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # Case 1: Empty JSON body
        helpers.log_line(logs, "STEP", "Sending applications/exit with empty body: {}.", result=result)
        status_empty, body_empty = helpers.execute_cmd_and_log(
            tester, device_id, "applications/exit", "{}", logs=logs, result=result
        )

        if status_empty == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/exit returned 501 (not implemented).")
            return result
        if status_empty != 400:
            helpers.finish(result, logs, "FAILED", f"Expected 400 for empty body, got {status_empty}.")
            return result

        # Optional: best-effort check for an error message without making it a hard requirement
        try:
            parsed_empty = body_empty if isinstance(body_empty, dict) else json.loads(body_empty or "{}")
            msg_empty = parsed_empty.get("message") or parsed_empty.get("error") or parsed_empty.get("details")
            if msg_empty:
                helpers.log_line(logs, "INFO", f"error message (empty body)='{msg_empty}'", result=result)
        except Exception:
            pass

        # Case 2: Missing appId (e.g., irrelevant payload)
        helpers.log_line(logs, "STEP", "Sending applications/exit with missing appId: {\"foo\":\"bar\"}.", result=result)
        status_missing, body_missing = helpers.execute_cmd_and_log(
            tester, device_id, "applications/exit", json.dumps({"foo": "bar"}), logs=logs, result=result
        )

        if status_missing == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "applications/exit returned 501 (not implemented) on missing appId payload.")
            return result
        if status_missing != 400:
            helpers.finish(result, logs, "FAILED", f"Expected 400 for missing appId, got {status_missing}.")
            return result

        # Optional: best-effort message capture
        try:
            parsed_missing = body_missing if isinstance(body_missing, dict) else json.loads(body_missing or "{}")
            msg_missing = parsed_missing.get("message") or parsed_missing.get("error") or parsed_missing.get("details")
            if msg_missing:
                helpers.log_line(logs, "INFO", f"error message (missing appId)='{msg_missing}'", result=result)
        except Exception:
            pass

        helpers.finish(result, logs, "PASS", "applications/exit rejected empty/missing appId requests with 400 as expected.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, empty_status={status_empty}, missing_appid_status={status_missing}, id={test_id}, device={device_id}",
            result=result,
        )

    return result

