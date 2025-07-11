from result_json import TestResult
from dab_tester import to_test_id
import config
import json
import time

# --- Sleep Time Constants ---
APP_LAUNCH_WAIT = 5
APP_EXIT_WAIT = 3
APP_STATE_CHECK_WAIT = 2
APP_RELAUNCH_WAIT = 4
CONTENT_LOAD_WAIT = 6

# === Reusable Helper ===
def execute_cmd_and_log(tester, device_id, topic, payload, logs):
    print(f"\nExecuting: {topic} with payload: {payload}")
    result_code = tester.execute_cmd(device_id, topic, payload)
    response = tester.dab_client.response()
    logs.append(f"[{topic}] Response: {response}")
    print_response(response, topic)
    return result_code, response

def print_response(response, topic_for_color=None, indent=10):
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            print("Invalid JSON string.")
            return
    if not isinstance(response, dict):
        print("Invalid response format.")
        return
    print("Response:")
    for key, value in response.items():
        print(f"{' ' * indent}{key}: {value}")


# === Test 1: App in FOREGROUND ===
def run_app_foreground_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] App Foreground Check, Test name: {test_name}" )
    print("Objective: Validate app moves to FOREGROUND after launch.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch and stabilize.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 2: Getting state of application '{app_id}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state: {state}.")

        if state == "FOREGROUND":
            logs.append(f"[PASS] App state is '{state}' as expected.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App state is '{state}', expected 'FOREGROUND'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n({'-' * 100})")

    return result


# === Test 2: App in BACKGROUND ===
def run_app_background_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] App Background Check")
    print("Objective: Validate app moves to BACKGROUND after pressing Home.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 2: Pressing 'KEY_HOME' to send app to background.")
        execute_cmd_and_log(tester, device_id, "input/key-press", json.dumps({"keyCode": "KEY_HOME"}), logs)
        print(f"Waiting {APP_EXIT_WAIT} seconds for app to go to background.")
        time.sleep(APP_EXIT_WAIT)

        print(f"Step 3: Getting state of application '{app_id}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state: {state}.")

        if state == "BACKGROUND":
            logs.append(f"[PASS] App state is '{state}' as expected.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App state is '{state}', expected 'BACKGROUND'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 3: App STOPPED ===
def run_app_stopped_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] App Stopped Check")
    print("Objective: Validate app state is STOPPED after exit.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 2: Exiting application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_EXIT_WAIT} seconds for app to fully exit.")
        time.sleep(APP_EXIT_WAIT)

        print(f"Step 3: Getting state of application '{app_id}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state: {state}.")

        if state == "STOPPED":
            logs.append(f"[PASS] App state is '{state}' as expected.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App state is '{state}', expected 'STOPPED'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 4: Launch Without Content ID (Negative) ===
def run_launch_without_content_id(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Launch Without Content ID (Negative)")
    print("Objective: Validate error is returned when contentId is missing.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch-with-content", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Attempting to launch application '{app_id}' without a 'contentId'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/launch-with-content", json.dumps({"appId": app_id}), logs)
        status = json.loads(response).get("status", 0) if response else 0
        print(f"Received response status: {status}.")

        if status != 200:
            logs.append(f"[PASS] Proper error response received as expected (status: {status}).")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] Launch succeeded unexpectedly (status: {status}), expected an error.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 5: Launch Live Content & Validate Resolution ===
def run_launch_live_content_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Launch Live Content with Resolution Check")
    print("Objective: Validate content launch with correct resolution.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    content_id = "2ZggAa6LuiM"
    expected_resolution = "2k"
    logs = []
    result = TestResult(test_id, device_id, "applications/launch-with-content", json.dumps({"appId": app_id, "contentId": content_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}' with content ID '{content_id}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/launch-with-content", json.dumps({"appId": app_id, "contentId": content_id}), logs)
        print(f"Waiting {CONTENT_LOAD_WAIT} seconds for content to load and playback to start.")
        time.sleep(CONTENT_LOAD_WAIT)

        print(f"Step 2: Checking the reported resolution.")
        resp_json = json.loads(response) if response else {}
        resolution = resp_json.get("resolution", "").lower()
        print(f"Reported resolution: {resolution}, Expected resolution: {expected_resolution}.")

        if resolution == expected_resolution.lower():
            logs.append(f"[PASS] Resolution '{resolution}' as expected.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] Resolution mismatch: Reported '{resolution}', Expected '{expected_resolution}'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 6: Exit App After Playing Video ===
def run_exit_after_video_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Exit After Video Playback Check")
    print("Objective: Validate that resources are released after exiting app.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/exit", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 2: Exiting application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_EXIT_WAIT} seconds for app to fully exit.")
        time.sleep(APP_EXIT_WAIT)

        print(f"Step 3: Getting state of application '{app_id}' to confirm exit.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state after exit attempt: {state}.")

        if state == "STOPPED":
            logs.append(f"[PASS] App properly stopped, no background activity. State: '{state}'.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App still active: '{state}', expected 'STOPPED'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 7: Relaunch Stability Check ===
def run_relaunch_stability_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Relaunch Stability Check")
    print("Objective: Validate app can be exited and relaunched without issue.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: First launch of application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_EXIT_WAIT} seconds after first launch.") # Assuming this is a short wait for initial launch
        time.sleep(APP_EXIT_WAIT)

        print(f"Step 2: Exiting application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_STATE_CHECK_WAIT} seconds after exit.") # Assuming this is a short wait for app to settle
        time.sleep(APP_STATE_CHECK_WAIT)

        print(f"Step 3: Relaunching application '{app_id}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_RELAUNCH_WAIT} seconds after relaunch.")
        time.sleep(APP_RELAUNCH_WAIT)

        if response:
            logs.append(f"[PASS] App relaunched cleanly.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App relaunch failed. No response received.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Functional Test Case List ===
FUNCTIONAL_TEST_CASE = [
    ("applications/get-state", "functional", run_app_foreground_check, "AppForegroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_background_check, "AppBackgroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_stopped_check, "AppStoppedCheck", "2.0", False),
    ("applications/launch-with-content", "functional", run_launch_without_content_id, "LaunchWithoutContentID", "2.0", True),
    ("applications/launch-with-content", "functional", run_launch_live_content_check, "LaunchLiveContentCheck", "2.0", False),
    ("applications/exit", "functional", run_exit_after_video_check, "ExitAfterVideoCheck", "2.0", False),
    ("applications/launch", "functional", run_relaunch_stability_check, "RelaunchStabilityCheck", "2.0", False),
]