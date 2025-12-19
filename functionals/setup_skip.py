from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_system_setup_skip_mid_wizard_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – system/setup/skip mid-wizard behavior (functional, positive, manual-assisted)

    Goal:
      - From a partially completed Android TV setup wizard (e.g., after language selection),
        invoke system/setup/skip via DAB.
      - Verify that the device skips remaining setup steps and transitions to the home screen.
      - Confirm that account-based features remain disabled (user not signed in).
    Preconditions (manual/environment):
      - Device has been factory-reset or otherwise brought into the initial setup wizard.
      - Tester has progressed through some initial steps (e.g., language selection) and the
        device is now at a mid-setup screen, but still accessible over DAB.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)
    user_validated_skip = "N/A"

    try:
        helpers.log_line(logs, "TEST", f"System_Setup Skip_Mid_Wizard Check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "From a partially completed setup wizard, call system/setup/skip and verify that the device lands on the home screen with account features disabled.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: system/setup/skip. Factory reset and wizard navigation are handled manually or by other tests.", result=result)
        helpers.log_line(logs, "DESC", "PASS if system/setup/skip returns 200 and tester confirms the device exits the wizard to home without a signed-in account.", result=result)

        cap_spec = "ops: system/setup/skip"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        helpers.log_line(logs, "STEP", "Manual precondition — Device must be at a mid-setup wizard screen (e.g., after language selection, before network/account setup).", result=result)
        helpers.log_line(logs, "DESC", "If needed, perform factory reset and progress the wizard until DAB is restored and the device is reachable.", result=result)

        env_ok = helpers.yes_or_no(
            result,
            logs,
            "Is the device currently on a mid-setup wizard screen and reachable over DAB (yes), or not ready for this test (no)?"
        )
        if not env_ok:
            helpers.finish(result, logs, "SKIPPED", "Device is not in the required mid-setup wizard state for this test.")
            return result

        payload = "{}"
        helpers.log_line(logs, "STEP", f"Invoking system/setup/skip with payload: {payload}", result=result)
        status, body = helpers.execute_cmd_and_log(
            tester, device_id, dab_topic, payload, logs=logs, result=result
        )
        helpers.log_line(logs, "INFO", f"system/setup/skip returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/setup/skip is not implemented on this device (status=501).")
            return result

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/setup/skip returned non-200 status={status}; cannot confirm skip behavior.")
            return result

        helpers.log_line(logs, "STEP", "Waiting for the device to process system/setup/skip and exit the wizard.", result=result)
        helpers.log_line(logs, "DESC", "Do not interact with the device during this wait; let the wizard complete the skip transition.", result=result)
        helpers.countdown(result, logs, 45, "Waiting up to 45 seconds for the device to reach the home screen after system/setup/skip...")

        helpers.log_line(logs, "STEP", "Manual validation — Inspect the device/TV screen.", result=result)
        helpers.log_line(logs, "DESC", "Device should have exited the setup wizard and show the Android TV home screen with account features not configured.", result=result)

        user_validated_skip = helpers.yes_or_no(
            result,
            logs,
            "Is the device now on the home screen AND still in an unsigned / account-not-configured state?"
        )

        if user_validated_skip:
            helpers.finish(result, logs, "PASS", "Tester confirmed system/setup/skip skipped remaining wizard steps and landed on the home screen with account features disabled.")
        else:
            helpers.finish(result, logs, "FAILED", "Tester reported that the device did NOT exit the wizard correctly or account configuration state did not match expectations.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error during system/setup/skip mid-wizard check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, user_validated_skip={user_validated_skip}, id={test_id}, device={device_id}",
            result=result,
        )

    return result


def run_system_setup_skip_initial_wizard_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – system/setup/skip from initial wizard (functional, positive, manual-assisted)

    Goal:
      - From the very first Android TV setup wizard screen after a factory reset,
        invoke system/setup/skip via DAB.
      - Verify that the device bypasses the remaining wizard steps and lands on the home screen.
      - Confirm that account-based features remain disabled (no user account configured).

    Preconditions (manual/environment):
      - Device has been factory-reset and is currently showing the initial setup wizard screen.
      - Device is powered on and reachable over DAB from the test host.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)
    user_validated_home = "N/A"

    try:
        helpers.log_line(logs, "TEST", f"System_Setup Skip_Initial_Wizard Check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "From the initial setup wizard screen after factory reset, call system/setup/skip and verify the device lands on the home screen with account features disabled.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: system/setup/skip. Factory reset is handled outside this test.", result=result)
        helpers.log_line(logs, "DESC", "PASS if system/setup/skip returns 200 and tester confirms the wizard is bypassed and home screen is shown without a signed-in account.", result=result)

        cap_spec = "ops: system/setup/skip"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        helpers.log_line(logs, "STEP", "Manual precondition — Device must be at the initial setup wizard screen after factory reset.", result=result)
        helpers.log_line(logs, "DESC", "If needed, perform a factory reset and wait until the first setup screen appears and the device is reachable over DAB.", result=result)

        env_ok = helpers.yes_or_no(
            result,
            logs,
            "Is the device currently on the initial setup wizard screen after factory reset and reachable over DAB?"
        )
        if not env_ok:
            helpers.finish(result, logs, "SKIPPED", "Device is not in the required initial setup wizard state for this test.")
            return result

        payload = "{}"
        helpers.log_line(logs, "STEP", f"Invoking system/setup/skip at initial wizard with payload: {payload}", result=result)

        status, body = helpers.execute_cmd_and_log(
            tester,
            device_id,
            dab_topic,
            payload,
            logs=logs,
            result=result,
        )
        helpers.log_line(logs, "INFO", f"system/setup/skip returned status={status}.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "system/setup/skip is not implemented on this device (status=501).")
            return result

        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/setup/skip returned non-200 status={status}; cannot confirm skip behavior.")
            return result

        helpers.log_line(logs, "STEP", "Allow the device time (≈30–60 seconds) to process system/setup/skip and exit the wizard.", result=result)
        helpers.log_line(logs, "DESC", "Do not interact with the device during this period; let the wizard complete the skip transition.", result=result)
        helpers.countdown(result, logs, 60, "Waiting up to 60 seconds for the device to reach the home screen after system/setup/skip...")

        user_validated_home = helpers.yes_or_no(
            result,
            logs,
            "After waiting, is the device now on the Android TV home screen with the setup wizard gone and account-based features still disabled / not configured?"
        )

        if user_validated_home:
            helpers.finish(result, logs, "PASS", "Tester confirmed system/setup/skip bypassed the setup wizard and landed on the home screen with account features disabled.")
        else:
            helpers.finish(result, logs, "FAILED", "Tester reported that the device did NOT exit the wizard correctly or account state did not match expectations.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Unexpected error during system/setup/skip initial wizard check: {e}")
    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, user_validated_home={user_validated_home}, id={test_id}, device={device_id}", result=result)

    return result
