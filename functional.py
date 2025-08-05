from result_json import TestResult
from dab_tester import to_test_id
import config
import json
import time
import sys
from readchar import readchar
from util.enforcement_manager import EnforcementManager
from util.config_loader import ensure_app_available 

# --- Sleep Time Constants ---
APP_LAUNCH_WAIT = 5
APP_EXIT_WAIT = 3
APP_STATE_CHECK_WAIT = 2
APP_RELAUNCH_WAIT = 4
CONTENT_LOAD_WAIT = 6
DEVICE_REBOOT_WAIT = 180  # Max wait for device reboot
TELEMETRY_DURATION_MS = 5000
TELEMETRY_METRICS_WAIT = 30  # Max wait for telemetry metrics (seconds)
HEALTH_CHECK_INTERVAL = 5    # Seconds between health check polls

# === Reusable Helper ===
def execute_cmd_and_log(tester, device_id, topic, payload, logs = None):
    print(f"\nExecuting: {topic} with payload: {payload}")
    result_code = tester.execute_cmd(device_id, topic, payload)
    response = tester.dab_client.response()
    if logs is not None:
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

def yes_or_no(result, logs, question=""):
     positive = ['YES', 'Y']
     negative = ['NO', 'N']

     while True:
         logs.append(f"{question}(Y/N)")
         print(f"{question}(Y/N)")
         user_input=readchar().upper()
         logs.append(f"[{user_input}]")
         print(f"[{user_input}]")
         if user_input.upper() in positive:
             return True
         elif user_input.upper() in negative:
             return False
         else:
             continue

def countdown(title, count):
    while count:
        mins, secs = divmod(count, 60)
        timer = '{:02d}:{:02d}'.format(mins, secs)
        sys.stdout.write("\r" + title + " --- " + timer)
        sys.stdout.flush()
        time.sleep(1)
        count -= 1
    sys.stdout.write("\r" + title + " --- Done!\n")

def waiting_for_screensaver(result, logs, screenSaverTimeout, tips):
    while True:
        validate_state = yes_or_no(result, logs, tips)
        if validate_state:
            break
        else:
            continue
    countdown(f"Waiting for {screenSaverTimeout} seconds in idle state.", screenSaverTimeout)
def validate_response(tester, dab_topic, dab_payload, dab_response, result, logs):
    if not dab_response:
        logs.append(f"[FAIL] Request {dab_topic} '{dab_payload}' failed. No response received.")
        result.test_result = "FAILED"
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
        return False, result

    response = json.loads(dab_response)
    status = response.get("status")
    if status != 200:
        if status == 501:
            print(f"Request {dab_topic} '{dab_payload}' is NOT supported on this device.")
            logs.append(f"[OPTIONAL_FAILED] Request {topic} '{payload}' is NOT supported on this device.")
            result.test_result = "OPTIONAL_FAILED"
        else:
            print(f"Request Operation {topic} '{payload}' is FAILED on this device.")
            logs.append(f"[FAILED] Request Operation {topic} '{payload}' is FAILED on this device.")
            result.test_result = "FAILED"

        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
        return False, result

    return True, result

def verify_system_setting(tester, payload, response, result, logs):
    (key, value), = json.loads(payload).items()
    settings = json.loads(response)
    if key in settings:
        actual_value = settings.get(key)
        print(f"System settings get '{key}', Expected: {value}, Actual: {actual_value}")

        if actual_value == value:
            logs.append(f"System settings get '{key}', Expected: {value}, Actual: {actual_value}")
            return True, result
        else:
            logs.append(f"[FAIL] System settings get '{key}', Expected: {value}, Actual: {actual_value}")
            result.test_result = "FAILED"
    else:
        print(f"System settings get '{key}' is FAILED on this device.")
        logs.append(f"[FAILED] System settings get '{key}' is FAILED on this device.")
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return False, result

def get_supported_setting(tester, device_id, key, result, logs, do_list = True):
    topic = "system/settings/list"
    payload = json.dumps({})
    if EnforcementManager().check_supported_settings() == False or do_list:
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            EnforcementManager().set_supported_settings(None)
            return None, result
        EnforcementManager().set_supported_settings(json.loads(response))

    settings = EnforcementManager().get_supported_settings()
    if not settings:
        print(f"System setting list '{key}' FAILED  on this device.")
        logs.append(f"[FAILED] System settings list '{key}' FAILED on this device.")
        return None, result

    if key in settings:
        setting = settings.get(key)
        print(f"Get supported setting '{key}: {setting}'")
        return setting, result

    print(f"System setting '{key}' is unsupported on this device.")
    logs.append(f"[FAILED] System settings '{key}' is unsupported on this device.")
    result.test_result = "FAILED"
    return None, result

# === Test 1: App in FOREGROUND Validate app moves to FOREGROUND after launch ===
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


# === Test 2: App in BACKGROUND Validate app moves to BACKGROUND after pressing Home ===
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


# === Test 3: App STOPPED Validate app state is STOPPED after exit. ===
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


# === Test 4: Launch Without Content ID (Negative) Validate error is returned when contentId is missing. ===
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

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}\n({'-' * 100})")
    return result


# === Test 5: Exit App After Playing Video ===
def run_exit_after_video_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Exit After Video Playback Check")
    print("Objective: Validate that resources are released after exiting app after video playback.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    video_id = "2ZggAa6LuiM"  # Replace with actual valid YouTube video ID
    logs = []
    # Create the test result instance
    result = TestResult(test_id, device_id, "applications/exit", json.dumps({"appId": app_id}), "UNKNOWN", "", logs
    )

    try:
        # Step 1: Launch YouTube app with content parameters
        print(f"Step 1: Launching app '{app_id}' with video ID '{video_id}'.")
        launch_payload = { "appId": app_id, "parameters": [ f"v%3D{video_id}", "enableEventConsole%3Dtrue", "env_showConsole%3Dtrue"]}
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps(launch_payload), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for video playback.")
        time.sleep(APP_LAUNCH_WAIT)
        time.sleep(CONTENT_LOAD_WAIT)

        # Step 2: Exit the application
        print(f"Step 2: Exiting app '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_EXIT_WAIT} seconds for app to fully stop.")
        time.sleep(APP_EXIT_WAIT)

        # Step 3: Get the app state
        print(f"Step 3: Checking app state using 'applications/get-state'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs)
        try:
            state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        except Exception:
            state = "UNKNOWN"
            logs.append("[WARNING] Failed to parse response from get-state")

        print(f"Current app state: {state}")
        if state == "STOPPED":
            logs.append(f"[PASS] App stopped cleanly after video. State: '{state}'")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] App still active after exit. State: '{state}', expected 'STOPPED'")
            result.test_result = "FAILED"
    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} Test Outcome: {result.test_result}")
    print("-" * 100)
    return result


# === Test 6: Relaunch Stability Check ===
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

# === Test 7: Exit And Relaunch App ===
def run_exit_and_relaunch_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Exit and Relaunch App")
    print("Objective: Verify the app can exit and relaunch without issues.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Launching application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 2: Exiting application '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)
        time.sleep(APP_EXIT_WAIT)

        print(f"Step 3: Relaunching application '{app_id}' immediately after exit.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        time.sleep(APP_RELAUNCH_WAIT)

        if response:
            logs.append("[PASS] App exited and relaunched successfully without errors.")
            result.test_result = "PASS"
        else:
            logs.append("[FAIL] App did not respond correctly on relaunch.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception during test: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-'*100}")
    return result

# === Test 8: Screensaver Enable Check ===
def run_screensaver_enable_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Enable Check")
    print("Objective: Validate screensaver can be enable successfully.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": True}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Disable screensaver before the test.")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Verify screensaver is disabled.")
        topic = "system/settings/get"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state, result = verify_system_setting(tester, json.dumps({"screenSaver": False}), response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Enable screensaver.")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Verify screensaver is enabled.")
        topic = "system/settings/get"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state, result = verify_system_setting(tester, json.dumps({"screenSaver": True}), response, result, logs)
        if validate_state == False:
            return result

        print(f"Screensaver is enabled.")
        logs.append(f"[PASS] Screensaver is enabled.")
        result.test_result = "PASS"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 9: Screensaver Disable Check ===
def run_screensaver_disable_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Disable Check")
    print("Objective: Validate screensaver can be disable successfully.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": False}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Enable screensaver before the test.")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Verify screensaver is enabled.")
        topic = "system/settings/get"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state, result = verify_system_setting(tester, json.dumps({"screenSaver": True}), response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Disable screensaver.")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Verify screensaver is disabled.")
        topic = "system/settings/get"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state, result = verify_system_setting(tester, json.dumps({"screenSaver": False}), response, result, logs)
        if validate_state == False:
            return result

        print(f"Screensaver is disabled.")
        logs.append(f"[PASS] Screensaver is disabled.")
        result.test_result = "PASS"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 10: Screensaver Active Check ===
def run_screensaver_active_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Active Check")
    print("Objective: Validate that screensaver can be actived after screensaver timeout.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": True}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active?")

        if validate_state == True:
            print(f"Screensaver is active.")
            logs.append(f"[PASS] Screensaver is active after screensaver enabled.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver it not active.")
            logs.append(f"[FAILED] Screensaver is not active after screensaver enabled.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 10: Screensaver Inactive Check ===
def run_screensaver_inactive_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Inactive Check")
    print("Objective: Validate screensaver is not actived.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": False}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Disable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active?")

        if validate_state == False:
            print(f"Screensaver is not active.")
            logs.append(f"[PASS] Screen Saver is not active after screenSaver disabled.")
            result.test_result = "PASS"
        else:
            print(f"ScreenSaver is active.")
            logs.append(f"[FAILED] ScreenSaver is active after screenSaver disabled.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 11: Screensaver Active Return Check ===
def run_screensaver_active_return_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Active Return Check")
    print("Objective: Validate that screen returns previous state after screensaver active.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": True}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active?")

        if validate_state == False:
            print(f"Screensaver is not active.")
            logs.append(f"[FAILED] Screensaver is not active after screensaver enabled.")
            result.test_result = "FAILED"

        validate_state = yes_or_no(result, logs, f"Please exit screensaver, does screen return previous state?")

        if validate_state == True:
            print(f"The screen returns previous state.")
            logs.append(f"[PASS] The screen returns previous state.")
            result.test_result = "PASS"
        else:
            print(f"The screen doesn't return previous state.")
            logs.append(f"[FAILED] The screen doesn't return previous state.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 12: Screensaver Active Check After Continuous Idle ===
def run_screensaver_active_after_continuous_idle_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Active Check After Continuous Idle")
    print("Objective: Validate that screensaver can be actived only after continues idle.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": True}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Please press remote keys to simulate user activity, and then waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Finish usre activity and ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active after {screenSaverTimeout} seconds?")

        if validate_state == True:
            print(f"Screensaver is active after continuous idle.")
            logs.append(f"[PASS] Screensaver is active after continuous idle.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver is not active after continuous idle.")
            logs.append(f"[FAILED] Screensaver is not active after continuous idle.")
            result.test_result = "FAILED"
    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 13: Screensaver Inactive Check After Reboot ===
def run_screensaver_inactive_after_reboot_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Inactive Check After Reboot")
    print("Objective: Validate that screenSaver is not actived after reboot with screensaver disabled.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": False}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Disable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Reboot device.")
        print("restarting...wait...")
        execute_cmd_and_log(tester, device_id, "system/restart", json.dumps({}), logs)

        while True:
            validate_state = yes_or_no(result, logs, "Device re-started?")
            if validate_state:
                break
            else:
                continue

        print(f"Step 4: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active after {screenSaverTimeout} seconds?")

        if validate_state == False:
            print(f"Screensaver is not active after reboot with screensaver disabled.")
            logs.append(f"[PASS] Screensaver is not active after reboot with screensaver disabled.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver is active after reboot with screensaver disabled.")
            logs.append(f"[FAILED] Screensaver is active after reboot with screensaver disabled.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 14: Screensaver Timeout 300 seconds Check ===
def run_screensavertimeout_300_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Timeout Active Check")
    print("Objective: Validate that screensaver can be actived after screensaver timeout is set 300 seconds.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaverTimeout": 300}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 300
        print(f"Step 1: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active after {screenSaverTimeout} seconds?")

        if validate_state == True:
            print(f"Screensaver is active after {screenSaverTimeout} seconds.")
            logs.append(f"[PASS] Screensaver is active after {screenSaverTimeout} seconds.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver it not active after {screenSaverTimeout} seconds.")
            logs.append(f"[FAILED] Screensaver is not active after {screenSaverTimeout} seconds.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 15: Screensaver Timeout Reboot Check ===
def run_screensavertimeout_reboot_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Timeout Reboot Check")
    print(f"Objective: Validate that screensaver timeout setting persists after device restart.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaverTimeout": 30}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Reboot device.")
        print("restarting...wait...")
        execute_cmd_and_log(tester, device_id, "system/restart", json.dumps({}), logs)

        while True:
            validate_state = yes_or_no(result, logs, "Device re-started?")
            if validate_state:
                break
            else:
                continue

        print(f"Step 3: Verify screensaver timeout setting persists after device restart.")
        topic = "system/settings/get"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state, result = verify_system_setting(tester, json.dumps({"screenSaverTimeout": screenSaverTimeout}), response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 5: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active after {screenSaverTimeout} seconds?")

        if validate_state == True:
            print(f"Screensaver is active after {screenSaverTimeout} seconds after reboot.")
            logs.append(f"[PASS] Screensaver is active after {screenSaverTimeout} seconds after reboot..")
            result.test_result = "PASS"
        else:
            print(f"Screensaver is not active after {screenSaverTimeout} seconds after reboot.")
            logs.append(f"[FAILED] Screensaver is not active after {screenSaverTimeout} seconds after reboot.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 16: ScreenSaver Timeout Guest Mode Check ===
def run_screensavertimeout_guest_mode_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Timeout Check In Guest Mode")
    print("Objective: Validate that screensaver can be actived in guest mode.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaverTimeout": 30}), "UNKNOWN", "", logs)

    try:
        screenSaverTimeout = 30
        print(f"Step 1: Switch to guest mode")
        validate_state = yes_or_no(result, logs, "If device support guest mode, please switch to guest mode and then input 'Y', or 'N'")
        if validate_state == False:
            print(f"Device doesn't support guest mode.")
            logs.append(f"[OPTIONAL_FAILED] Device doesn't support guest mode.")
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
            return result

        print(f"Step 2: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Set screensaver timeout to {screenSaverTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active?")
        if validate_state == True:
            print(f"Screensaver is active in guest mode.")
            logs.append(f"[PASS] Screensaver is active in guest mode.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver it not active in guest mode.")
            logs.append(f"[FAILED] Screensaver is not active in guest mode.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 17: ScreenSaver Min Timeout Check ===
def run_screensavertimeout_minimum_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Minimum Timeout Check")
    print("Objective: Validate that screensaver can be actived after timeout is set minimum value.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/list", json.dumps({}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Get screensaver min timeout")
        screenSaverMinTimeout, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if not screenSaverMinTimeout:
            return result

        print(f"Step 2: Set screensaver timeout to {screenSaverMinTimeout} seconds")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaverTimeout": screenSaverMinTimeout})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 3: Enable screensaver")
        topic = "system/settings/set"
        payload = json.dumps({"screenSaver": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Waiting for screensaver active.")
        waiting_for_screensaver(result, logs, screenSaverMinTimeout, "Ready to wait for screensaver active?")

        validate_state = yes_or_no(result, logs, f"Screensaver is active?")
        if validate_state == True:
            print(f"Screensaver is active.")
            logs.append(f"[PASS] Screensaver is active after screensaver enabled.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver it not active.")
            logs.append(f"[FAILED] Screensaver is not active after screensaver enabled.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 18: ScreenSaver Min Timeout Reboot Check ===
def run_screensavermintimeout_reboot_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Screensaver Min Timeout After Reboot Check")
    print("Objective: Verify that the minimum screensaver timeout value is not altered after a device restart.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/list", json.dumps({}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Get screensaver minimum timeout")
        screenSaverMinTimeout, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if not screenSaverMinTimeout:
            return result

        print(f"Step 2: Reboot device.")
        print("restarting...wait...")
        execute_cmd_and_log(tester, device_id, "system/restart", json.dumps({}), logs)

        while True:
            validate_state = yes_or_no(result, logs, "Device re-started?")
            if validate_state:
                break
            else:
                continue

        print(f"Step 3: Get screensaver minimum timeout after reboot")
        screenSaverMinTimeout_reboot, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if not screenSaverMinTimeout:
            return result

        if screenSaverMinTimeout == screenSaverMinTimeout_reboot:
            print(f"Screensaver minimum timeout is not altered after a device restart.")
            logs.append(f"[PASS] Screensaver minimum timeout is not altered after a device restart.")
            result.test_result = "PASS"
        else:
            print(f"Screensaver minimum timeout is altered after a device restart.")
            logs.append(f"[FAILED] Screensaver minimum timeout is altered after a device restart.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 19: High Contrast Text Check Text Over Images ===
def run_highContrastText_text_over_images_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] High Contrast Text Check Text Over Images")
    print("Objective: Verify that enabling high contrast text adjusts text color and background for text over images.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"highContrastText": True}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Disable High Contrast Text before the test.")
        topic = "system/settings/set"
        payload = json.dumps({"highContrastText": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Navigate to a screen with text displayed over images.")
        validate_state = yes_or_no(result, logs, "Navigate to a screen with text displayed over images?")
        if validate_state == False:
            print(f"Couldn't Navigate to a screen with text displayed over images.")
            logs.append(f"[FAILED] Couldn't Navigate to a screen with text displayed over images.")
            result.test_result = "FAILED"
            return result

        print(f"Step 3: Enable High Contrast Text.")
        topic = "system/settings/set"
        payload = json.dumps({"highContrastText": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Verify text over images is clearly legible with high contrast applied")
        validate_state = yes_or_no(result, logs, f"Text over images is clearly legible with high contrast applied?")
        if validate_state == True:
            print(f"Text over images is clearly legible.")
            logs.append(f"[PASS] Text over images is clearly legible with high contrast applied.")
            result.test_result = "PASS"
        else:
            print(f"Text over images is not clearly legible.")
            logs.append(f"[FAILED] Text over images is not clearly legible with high contrast applied.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 20: High Contrast Text Check During Video Playback ===
def run_highContrastText_video_playback_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] High Contrast Text Check During Video Playback")
    print("Objective: Verify that toggling high contrast text during video playback does not interrupt video playback.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"highContrastText": True}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Disable High Contrast Text before the test.")
        topic = "system/settings/set"
        payload = json.dumps({"highContrastText": False})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 2: Play a video in any one application, e.g. YouTube, Netflix, PrimeVideo...")
        validate_state = yes_or_no(result, logs, "The video is playing?")
        if validate_state == False:
            print(f"Play video failed.")
            logs.append(f"[FAILED] Play video failed.")
            result.test_result = "FAILED"

        print(f"Step 3: Enable High Contrast Text.")
        topic = "system/settings/set"
        payload = json.dumps({"highContrastText": True})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        print(f"Step 4: Verify video playback is not affected by toggling the high contrast text setting")
        validate_state = yes_or_no(result, logs, f"Video playback is not affected by toggling the high contrast text setting?")
        if validate_state == True:
            print(f"Video playback is not affected.")
            logs.append(f"[PASS] Video playback is not affected.")
            result.test_result = "PASS"
        else:
            print(f"Text over images is affected.")
            logs.append(f"[FAILED] Text over images is affected.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 21: SetInvalidVoiceAssistant ===
def run_set_invalid_voice_assistant_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective: Validate that the system rejects unsupported voice assistant names.
    This negative test sends a 'voice/set' request with an obviously invalid
    voice assistant name ("invalid") and verifies that the system returns an
    error without performing any action.
    """

    print(f"\n[Test] Set Invalid Voice Assistant, Test name: {test_name}")
    print("Objective: Validate system rejects unsupported voice assistant names.")

    # Generate test ID
    test_id = to_test_id(f"{dab_topic}/{test_category}")

    # Use clearly invalid assistant name
    invalid_assistant = "invalid"
    request_payload = json.dumps({"voiceAssistant": invalid_assistant})

    logs = []
    result = TestResult(test_id, device_id, "voice/set", request_payload, "UNKNOWN", "", logs)

    try:
        # Step 0: Pre-check supported voice assistants
        print("Step 0: Checking supported voice assistants via 'voice/list'.")
        _, resp_list = execute_cmd_and_log(tester, device_id, "voice/list", "{}", logs)
        supported_list = []
        if resp_list:
            try:
                supported_list = json.loads(resp_list).get("voiceAssistants", [])
                print(f"Supported assistants: {supported_list}")
            except Exception as e:
                logs.append(f"[WARNING] Could not parse voice/list response: {str(e)}")

        if invalid_assistant in supported_list:
            logs.append(f"[SKIPPED] '{invalid_assistant}' is supported, skipping negative test.")
            result.test_result = "SKIPPED"
            return result

        # Step 1: Attempt to set invalid voice assistant
        print(f"Step 1: Sending 'voice/set' request with invalid assistant '{invalid_assistant}'.")
        _, response = execute_cmd_and_log(tester, device_id, "voice/set", request_payload, logs)

        # Step 2: Parse response and validate error handling
        error_detected = False
        if response:
            try:
                resp_json = json.loads(response)
                status = resp_json.get("status")
                message = resp_json.get("message", "").lower()
                print(f"Received response: {resp_json}")

                if status != 200 or "unsupported" in message or "error" in message:
                    logs.append(f"[PASS] System correctly rejected invalid assistant '{invalid_assistant}'.")
                    error_detected = True
            except Exception as e:
                logs.append(f"[ERROR] Failed to parse response: {str(e)}")

        if error_detected:
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] System accepted invalid assistant '{invalid_assistant}'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 22: Device Restart and Telemetry Validation ===
def run_device_restart_and_telemetry_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Device Restart and Telemetry Check, Test name: {test_name}")
    print("Objective: Restart device, verify health check, start telemetry, receive metrics, stop telemetry.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/restart", "{}", "UNKNOWN", "", logs)

    try:
        # === Step 1: Restart & Wait for Health ===
        print("[Step 1] Restarting device and waiting until it's healthy...")
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs)

        start_time = time.time()
        device_ready = False
        while time.time() - start_time < DEVICE_REBOOT_WAIT:
            _, resp = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs)
            if resp:
                try:
                    resp_json = json.loads(resp)
                    if resp_json.get("status") == 200 and resp_json.get("healthy", True):
                        print("Device is online and healthy.")
                        device_ready = True
                        break
                except Exception:
                    pass
            time.sleep(HEALTH_CHECK_INTERVAL)

        if not device_ready:
            logs.append("[FAIL] Device did not come back online in expected time.")
            result.test_result = "FAILED"
            return result
        # === Step 2: Start Telemetry & Wait for Metrics ===
        print("[Step 2] Starting telemetry and listening for metrics...")
        telemetry_payload = json.dumps({"duration": TELEMETRY_DURATION_MS})
        _, start_resp = execute_cmd_and_log(tester, device_id, "device-telemetry/start", telemetry_payload, logs)

        if not start_resp or json.loads(start_resp).get("status") != 200:
            logs.append("[FAIL] Failed to start telemetry session.")
            result.test_result = "FAILED"
            return result
        metrics_received = False
        telemetry_wait_start = time.time()
        while time.time() - telemetry_wait_start < TELEMETRY_METRICS_WAIT:
            try:
                if hasattr(tester.dab_client, "get_message"):
                    metric_msg = tester.dab_client.get_message(f"dab/{device_id}/device-telemetry/metrics", timeout=3)
                else:
                    metric_msg = tester.dab_client.response()

                if metric_msg:
                    print(f"Received telemetry: {metric_msg}")
                    logs.append(f"[PASS] Telemetry metrics received: {metric_msg}")
                    metrics_received = True
                    break
            except Exception:
                pass

        if not metrics_received:
            logs.append("[FAIL] No telemetry metrics received within wait time.")
            result.test_result = "FAILED"
            return result

        # === Step 3: Stop Telemetry & Mark PASS ===
        print("[Step 3] Stopping telemetry session...")
        execute_cmd_and_log(tester, device_id, "device-telemetry/stop", "{}", logs)

        logs.append("[PASS] Restart and telemetry workflow completed successfully.")
        result.test_result = "PASS"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 23: Stop App Telemetry Without Active Session (Negative) ===
def run_stop_app_telemetry_without_active_session_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective: Ensure device handles redundant app-telemetry/stop gracefully when no session is active.
    """

    print(f"\n[Test] Stop App Telemetry Without Active Session (Negative), Test name: {test_name}")
    print("Objective: Ensure device handles redundant app-telemetry/stop gracefully when no session is active.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    payload = json.dumps({"appId": app_id})
    logs = []
    result = TestResult(test_id, device_id, "app-telemetry/stop", payload, "UNKNOWN", "", logs)

    try:
        print("[Step 1] Sending app-telemetry/stop to ensure no active session...")
        _, response = execute_cmd_and_log(tester, device_id, "app-telemetry/stop", payload, logs)

        if not response:
            logs.append("[FAIL] No response received.")
            result.test_result = "FAILED"
            return result

        resp_json = json.loads(response)
        status = resp_json.get("status")
        message = str(resp_json.get("error", "")).lower()

        if status == 200:
            logs.append("[PASS] Device gracefully accepted stop request with no active session (status 200).")
            result.test_result = "PASS"
        elif status in (400, 500) and ("not started" in message or "no active session" in message):
            logs.append(f"[PASS] Device returned expected error: {message} (status: {status}).")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] Unexpected response: status={status}, message='{message}'.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Test24: Launch Video and Verify Health Check ===
def run_launch_video_and_health_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective:
        Launch YouTube with specific video content,
        wait for playback to start, then perform a
        health-check/get to confirm device is healthy.
    """

    print(f"\n[Test] Launch Video and Health Check, Test name: {test_name}")
    print("Objective: Launch video content and verify device health via health-check/get.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    video_id = "2ZggAa6LuiM"  # Replace with a valid test video ID
    logs = []

    result = TestResult(test_id, device_id, "applications/launch-with-content", json.dumps({"appId": app_id, "contentId": video_id}), "UNKNOWN", "", logs)
    try:
        # Step 1: Launch the YouTube video
        print(f"[Step 1] Launching '{app_id}' with video ID '{video_id}'.")
        payload = json.dumps({"appId": app_id, "contentId": video_id})
        _, launch_resp = execute_cmd_and_log(tester, device_id, "applications/launch-with-content", payload, logs)

        # Validate launch response
        valid, result = validate_response(tester, "applications/launch-with-content", payload, launch_resp, result, logs)
        if not valid:
            return result

        # Step 2: Wait for video playback
        print(f"[Step 2] Waiting {APP_LAUNCH_WAIT + CONTENT_LOAD_WAIT} seconds for video to start playing...")
        time.sleep(APP_LAUNCH_WAIT + CONTENT_LOAD_WAIT)

        # Step 3: Perform a health-check
        print("[Step 3] Performing health-check/get...")
        _, health_resp = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs)

        # Validate health-check response
        if not health_resp:
            logs.append("[FAIL] No response received from health-check/get.")
            result.test_result = "FAILED"
            return result

        try:
            health_data = json.loads(health_resp)
        except json.JSONDecodeError:
            logs.append("[FAIL] Invalid JSON response from health-check/get.")
            result.test_result = "FAILED"
            return result

        status = health_data.get("status")
        healthy = health_data.get("healthy", False)

        if status == 200 and healthy is True:
            logs.append("[PASS] Device is healthy after video launch.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] Device health check failed. Status: {status}, Healthy: {healthy}")
            result.test_result = "FAILED"

        # Step 4: Exit the app
        print(f"[Step 4] Exiting application '{app_id}' to clean up.")
        exit_payload = json.dumps({"appId": app_id})
        _, exit_resp = execute_cmd_and_log(tester, device_id, "applications/exit", exit_payload, logs)
        validate_response(tester, "applications/exit", exit_payload, exit_resp, result, logs)

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Test25: Voice List With No Voice Assistant Configured (Negative) ===
def run_voice_list_with_no_voice_assistant(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective:
        Validate system behavior when requesting the list of voice assistants
        on a device with no voice assistant configured.
    Expected:
        System should return an empty list OR an appropriate error message/status.
    """

    print(f"\n[Test] Voice List With No Voice Assistant, Test name: {test_name}")
    print("Objective: Ensure system gracefully handles voice/list request when no voice assistant is configured.")

    # Generate test ID
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    request_payload = "{}"  # No parameters required

    logs = []
    result = TestResult(test_id, device_id, "voice/list", request_payload, "UNKNOWN", "", logs)

    try:
        # Step 1: Send voice/list request
        print("Step 1: Sending 'voice/list' request...")
        _, response = execute_cmd_and_log(tester, device_id, "voice/list", request_payload, logs)

        if not response:
            logs.append("[FAIL] No response received for voice/list request.")
            result.test_result = "FAILED"
            return result

        # Step 2: Parse response
        try:
            resp_json = json.loads(response)
        except Exception as e:
            logs.append(f"[ERROR] Invalid JSON in response: {str(e)}")
            result.test_result = "FAILED"
            return result

        status = resp_json.get("status")
        assistants = resp_json.get("voiceAssistants", [])

        print(f"Response status: {status}")
        print(f"Voice Assistants list: {assistants}")

        # Step 3: Validate negative condition
        if status == 200 and isinstance(assistants, list) and len(assistants) == 0:
            logs.append("[PASS] No voice assistants configured, empty list returned as expected.")
            result.test_result = "PASS"
        elif status != 200:
            logs.append(f"[PASS] Received expected non-200 status for no voice assistant case: {status}")
            result.test_result = "PASS"
        else:
            logs.append("[FAIL] Voice assistants list is not empty when none expected.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    # Final result print
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}")
    print("-" * 100)
    return result

# === Test26: Exit App While Already Exiting (Negative) ===
def run_exit_app_while_exiting(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective:
        Validate the system handles redundant applications/exit requests gracefully
        when the app is already in the process of exiting.
    """

    print(f"\n[Test] Exit App While Exiting, Test name: {test_name}")
    print("Objective: Ensure system gracefully handles redundant exit requests when app is already exiting.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/exit", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        # Step 1: Launch the app to ensure it's running before exit
        print(f"Step 1: Launching application '{app_id}' to prepare for exit test.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2: Send the first exit request
        print(f"Step 2: Sending first applications/exit request for '{app_id}'.")
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)

        # Step 3: Immediately send the second exit request (redundant)
        print("Step 3: Sending second applications/exit request immediately (while app is still exiting).")
        _, second_response = execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs)

        # Step 4: Validate system response for the redundant request
        if second_response:
            try:
                resp_json = json.loads(second_response)
                status = resp_json.get("status")
                message = resp_json.get("message", "").lower()

                if status == 200 or "already exiting" in message or "not running" in message:
                    logs.append("[PASS] System gracefully handled redundant exit request.")
                    result.test_result = "PASS"
                else:
                    logs.append(f"[FAIL] Unexpected status/message for redundant exit: {resp_json}")
                    result.test_result = "FAILED"
            except Exception as e:
                logs.append(f"[ERROR] Failed to parse redundant exit response: {str(e)}")
                result.test_result = "FAILED"
        else:
            logs.append("[FAIL] No response received for redundant exit request.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred during test: {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final result
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result


def run_launch_when_uninstalled_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective:
        Validate launching an uninstalled app fails with a relevant error.
    Steps:
        1. Uninstall the removable app.
        2. Attempt to launch the app.
        3. Expect an error response (not a success).
        4. Reinstall the app from local file for cleanup.
    """

    print(f"\n[Test] Launch App When Uninstalled, Test name: {test_name}")
    print("Objective: Validate that launching an uninstalled app returns an appropriate error.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    removable_app_id = config.apps.get("removable_app", None)
    if not removable_app_id:
        print("[SKIPPED] No removable_app defined in config.apps. Cannot run this test.")
        logs = ["[SKIPPED] No removable_app defined in config.apps."]
        result = TestResult(test_id, device_id, "applications/launch", "{}", "SKIPPED", "", logs)
        return result

    logs = []
    result = TestResult(test_id, device_id, "applications/launch", json.dumps({"appId": removable_app_id}), "UNKNOWN", "", logs)

    try:
        # Step 1: Uninstall the app
        print(f"[Step 1] Uninstalling removable app '{removable_app_id}' before test...")
        uninstall_payload = json.dumps({"appId": removable_app_id})
        _, uninstall_resp = execute_cmd_and_log(tester, device_id, "applications/uninstall", uninstall_payload, logs)

        time.sleep(3)  # Wait for uninstall to complete

        # Step 2: Attempt to launch uninstalled app
        print(f"[Step 2] Attempting to launch uninstalled app '{removable_app_id}'...")
        launch_payload = json.dumps({"appId": removable_app_id})
        _, launch_resp = execute_cmd_and_log(tester, device_id, "applications/launch", launch_payload, logs)

        if launch_resp:
            try:
                resp_json = json.loads(launch_resp)
                status = resp_json.get("status", 0)
                if status != 200:
                    logs.append(f"[PASS] Launch failed as expected. Status: {status}")
                    result.test_result = "PASS"
                else:
                    logs.append(f"[FAIL] Launch succeeded unexpectedly for uninstalled app. Status: {status}")
                    result.test_result = "FAILED"
            except Exception:
                logs.append("[FAIL] Could not parse launch response JSON.")
                result.test_result = "FAILED"
        else:
            logs.append("[PASS] No response received (expected for uninstalled app).")
            result.test_result = "PASS"

        # Step 3: Reinstall the app dynamically
        print(f"[Step 3] Reinstalling '{removable_app_id}' from local file to restore state...")
        try:
            apk_path = ensure_app_available(removable_app_id)  # Dynamically resolves correct APK path
            install_payload = json.dumps({"fileLocation": f"file://{apk_path}"})
            _, install_resp = execute_cmd_and_log(tester, device_id, "applications/install", install_payload, logs)
            logs.append(f"[INFO] Reinstall response: {install_resp}")
        except Exception as e:
            logs.append(f"[WARNING] Failed to reinstall app: {str(e)}")

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Functional Test Case List ===
FUNCTIONAL_TEST_CASE = [
    ("applications/get-state", "functional", run_app_foreground_check, "AppForegroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_background_check, "AppBackgroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_stopped_check, "AppStoppedCheck", "2.0", False),
    ("applications/launch-with-content", "functional", run_launch_without_content_id, "LaunchWithoutContentID", "2.0", True),
    ("applications/exit", "functional", run_exit_after_video_check, "ExitAfterVideoCheck", "2.0", False),
    ("applications/launch", "functional", run_relaunch_stability_check, "RelaunchStabilityCheck", "2.0", False),
    ("applications/launch", "functional", run_exit_and_relaunch_check, "ExitAndRelaunchApp", "2.0", False),
    ("system/settings/set", "functional", run_screensaver_enable_check, "ScreensaverEnableCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_disable_check, "ScreensaverDisableCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_active_check, "ScreensaverActiveCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_inactive_check, "ScreensaverInactiveCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_active_return_check, "ScreensaverActiveReturnCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_active_after_continuous_idle_check, "ScreensaverActiveAfterContinuousIdleCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_inactive_after_reboot_check, "ScreensaverInactiveAfterRebootCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensavertimeout_300_check, "ScreensaverTimeout300Check", "2.1", False),
    ("system/settings/set", "functional", run_screensavertimeout_reboot_check, "ScreensaverTimeoutRebootCheck", "2.1", False),
    ("system/settings/set", "functional", run_screensavertimeout_guest_mode_check, "ScreensaverTimeoutGuestModeCheck", "2.1", False),
    ("system/settings/list", "functional", run_screensavertimeout_minimum_check, "ScreensaverMinTimeoutCheck", "2.1", False),
    ("system/settings/list", "functional", run_screensavermintimeout_reboot_check, "ScreensaverMinTimeoutRebootCheck", "2.1", False),
    ("system/settings/set", "functional", run_highContrastText_text_over_images_check, "HighContrasTextTextOverImagesCheck", "2.1", False),
    ("system/settings/set", "functional", run_highContrastText_video_playback_check, "HighContrasTextVideoPlaybackCheck", "2.1", False),
    ("voice/set", "functional", run_set_invalid_voice_assistant_check, "SetInvalidVoiceAssistant", "2.0", True),
    ("system/restart", "functional", run_device_restart_and_telemetry_check, "DeviceRestartAndTelemetryCheck", "2.0", False),
    ("app-telemetry/stop", "functional", run_stop_app_telemetry_without_active_session_check, "StopAppTelemetryWithoutActiveSession", "2.1", True),
    ("applications/launch-with-content", "functional", run_launch_video_and_health_check, "LaunchVideoAndHealthCheck", "2.1", False),
    ("voice/list", "functional", run_voice_list_with_no_voice_assistant, "VoiceListWithNoVoiceAssistant", "2.0", True),
    ("applications/exit", "functional", run_exit_app_while_exiting, "ExitAppWhileExiting", "2.0", True),
    ("applications/launch", "functional", run_launch_when_uninstalled_check, "LaunchAppNotInstalled", "2.1", True),
]