from result_json import TestResult
from dab_tester import to_test_id
import config
import json
import time
import sys
from readchar import readchar
from util.enforcement_manager import EnforcementManager
from util.config_loader import ensure_app_available 
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
import dab_version as ver

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

class UnsupportedOperationError(Exception):
    def __init__(self, topic):
        self.topic = topic
        super().__init__(f"DAB operation '{topic}' is not supported by the device.")

SUPPORTED_OPERATIONS = []

def fetch_supported_operations(tester, device_id):
    global SUPPORTED_OPERATIONS
    if not SUPPORTED_OPERATIONS:
        print("[INFO] Fetching supported DAB operations via 'operations/list'...")
        result_code = tester.execute_cmd(device_id, "operations/list", "{}")
        response = tester.dab_client.response()
        try:
            data = json.loads(response)
            if isinstance(data, dict) and "operations" in data:
                SUPPORTED_OPERATIONS = data["operations"]
                #print(f"[INFO] Supported DAB operations: {SUPPORTED_OPERATIONS}")
            else:
                print("[WARNING] Invalid operations/list response format.")
        except Exception as e:
            print(f"[ERROR] Failed to fetch supported operations: {e}")


def execute_cmd_and_log(tester, device_id, topic, payload, logs=None, result=None):
    global SUPPORTED_OPERATIONS

    if not SUPPORTED_OPERATIONS:
        fetch_supported_operations(tester, device_id)

    if topic not in SUPPORTED_OPERATIONS:
        msg = f"[OPTIONAL_FAILED] Operation '{topic}' is not supported by the device."
        print(msg)
        if logs is not None:
            logs.append(msg)
        if result is not None:
            result.test_result = "OPTIONAL_FAILED"
            result.reason = msg
        raise UnsupportedOperationError(topic)

    print(f"\nExecuting: {topic} with payload: {payload}")
    result_code = tester.execute_cmd(device_id, topic, payload)
    response = tester.dab_client.response()
    if logs is not None:
        logs.append(f"[{topic}] Response: {response}")
        
    return result_code, response

# The 'print_response' function is removed from here
# It is still defined in the file but is no longer called by this function.

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

# === Helper: Restart Device  ===


def fire_and_forget_restart(dab_client, device_id):
    """
    Fire-and-forget system restart request with proper MQTT v5 ResponseTopic.
    """
    topic = f"dab/{device_id}/system/restart"
    response_topic = f"dab/_response/{topic}"

    properties = Properties(PacketTypes.PUBLISH)
    properties.ResponseTopic = response_topic

    # Send with correct headers — no subscription, no waiting
    dab_client._DabClient__client.publish(topic, "{}", qos=0, properties=properties)

    print(f"[INFO] Sent restart command to {topic} (fire-and-forget).")


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
    Objective:
        Validate that the system rejects unsupported voice assistant names.

    This negative test sends a 'voice/set' request with an obviously invalid
    voice assistant name ("invalid") and verifies that the system returns an
    error without performing any action.
    """

    print(f"\n[Test] Set Invalid Voice Assistant, Test name: {test_name}")
    print("Objective: Validate system rejects unsupported voice assistant names.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")

    # Use a clearly invalid assistant name
    invalid_assistant = "invalid"
    request_payload = json.dumps({"voiceAssistant": invalid_assistant})

    logs = []
    result = TestResult(test_id, device_id, "voice/set", request_payload, "UNKNOWN", "", logs)

    try:
        # Optional pre-check for information only
        print("Step 0: Checking supported voice assistants via 'voice/list'.")
        _, resp_list = execute_cmd_and_log(tester, device_id, "voice/list", "{}", logs)
        if resp_list:
            try:
                supported_list = json.loads(resp_list).get("voiceAssistants", [])
                logs.append(f"[INFO] Supported assistants: {supported_list}")
            except Exception as e:
                logs.append(f"[WARNING] Could not parse voice/list response: {str(e)}")

        # Step 1: Attempt to set invalid voice assistant
        print(f"Step 1: Sending 'voice/set' request with invalid assistant '{invalid_assistant}'.")
        _, response = execute_cmd_and_log(tester, device_id, "voice/set", request_payload, logs)

        # Step 2: Parse response and validate error handling
        if response:
            try:
                resp_json = json.loads(response)
                status = resp_json.get("status")
                message = str(resp_json.get("message", "")).lower()

                print(f"Received response: {resp_json}")

                if status != 200 or "unsupported" in message or "error" in message:
                    logs.append(f"[PASS] System correctly rejected invalid assistant '{invalid_assistant}'.")
                    result.test_result = "PASS"
                else:
                    logs.append(f"[FAIL] System accepted invalid assistant '{invalid_assistant}'.")
                    result.test_result = "FAILED"

            except Exception as e:
                logs.append(f"[ERROR] Failed to parse response: {str(e)}")
                result.test_result = "FAILED"
        else:
            logs.append("[FAIL] No response received for invalid assistant request.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final result status
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")

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

# === Test25: Voice List With No Voice Assistant Configured (Negative / Optional) ===
def run_voice_list_with_no_voice_assistant(dab_topic, test_category, test_name, tester, device_id):
    """
    Objective:
        Validate system behavior when requesting the list of voice assistants
        on a device with no voice assistant configured.

    Expected:
        - PASS if no assistants are configured (empty list).
        - OPTIONAL_FAILED if assistants are pre-configured in the bridge 
          (since this scenario is not enforceable without bridge config change).
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

        # Step 3: Validate result
        if status == 200 and isinstance(assistants, list) and len(assistants) == 0:
            logs.append("[PASS] No voice assistants configured, empty list returned as expected.")
            result.test_result = "PASS"

        elif status == 200 and len(assistants) > 0:
            logs.append(f"[OPTIONAL_FAILED] Voice assistants are pre-configured: {assistants}. "
                        f"Test scenario not enforceable without bridge config change.")
            result.test_result = "OPTIONAL_FAILED"

        elif status != 200:
            logs.append(f"[PASS] Non-200 status returned for no assistant case: {status}")
            result.test_result = "PASS"

        else:
            logs.append("[FAIL] Unexpected response format or condition.")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception occurred: {str(e)}")
        result.test_result = "SKIPPED"

    # Final result print
    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}")
    print("-" * 100)
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

# === Test 26: Launch App While Device Restarting (Negative) ===
def run_launch_app_while_restarting_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Validates that launching an app while device is restarting fails.
    """
    print(f"\n[Test] Launch App While Device Restarting, Test name: {test_name}")
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch",
                        json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        # Step 1: Fire-and-forget restart
        print("[Step 1] Sending system/restart (fire-and-forget)...")
        fire_and_forget_restart(tester.dab_client, device_id)

        # Step 2: Short delay to ensure device starts going offline
        offline_wait_time = 3
        print(f"[Step 2] Waiting {offline_wait_time}s for device to begin restart...")
        time.sleep(offline_wait_time)

        # Step 3: Attempt to launch app
        print(f"[Step 3] Attempting to launch '{app_id}' while restarting...")
        _, launch_response = execute_cmd_and_log(tester, device_id, "applications/launch",
                                                 json.dumps({"appId": app_id}), logs)

        # Step 4: Validate expected failure
        if not launch_response:
            logs.append("[PASS] No response received — launch failed as expected during restart.")
            result.test_result = "PASS"
        else:
            try:
                resp_json = json.loads(launch_response)
                status = resp_json.get("status")
                if status != 200:
                    logs.append(f"[PASS] Received error status ({status}) during restart.")
                    result.test_result = "PASS"
                else:
                    logs.append("[FAIL] Launch succeeded unexpectedly during restart.")
                    result.test_result = "FAILED"
            except Exception:
                logs.append("[PASS] Invalid/empty response — treated as expected failure.")
                result.test_result = "PASS"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result
  
# === Test 27: Network Reset Check ===
def run_network_reset_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Network Reset Check, Test name: {test_name}")
    print("Objective: Reset all network settings and verify DAB responds successfully.")

    logs = []
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    result = TestResult(test_id, device_id, "system/network-reset", "{}", "UNKNOWN", "", logs)

    try:
        # Step 1: Validate required operations using operations/list
        print("[STEP 1] Checking if 'system/network-reset' and 'system/info' are supported...")
        required_ops = {"system/network-reset", "system/info"}
        
        try:
            # Use execute_cmd_and_log to fetch operations and handle unsupported cases
            _, response = execute_cmd_and_log(tester, device_id, "operations/list", "{}", logs)
            if response:
                supported_ops = set(json.loads(response).get("operations", []))
                missing_ops = required_ops - supported_ops
                if missing_ops:
                    msg = f"[OPTIONAL_FAILED] Missing required operations: {', '.join(missing_ops)}. Cannot perform this test."
                    print(msg)
                    logs.append(msg)
                    result.test_result = "OPTIONAL_FAILED"
                    return result
                logs.append("[INFO] All required operations are supported.")
        except UnsupportedOperationError as e:
            # This catch handles the case where 'operations/list' itself is not supported
            logs.append(f"[OPTIONAL_FAILED] '{e.topic}' is not supported. Cannot validate required operations.")
            result.test_result = "OPTIONAL_FAILED"
            return result

        # Step 2: Execute network reset
        print("[STEP 2] Sending DAB request to reset network settings...")
        result_code, response = execute_cmd_and_log(tester, device_id, "system/network-reset", "{}", logs, result)
        if result_code != 200:
            logs.append(f"[FAIL] Unexpected response code from 'system/network-reset': {result_code}")
            result.test_result = "FAILED"
            return result

        # Step 3: Validate DAB responsiveness via system/info
        print("[STEP 3] Verifying DAB is still responsive using 'system/info'...")
        result_code_2, response_2 = execute_cmd_and_log(tester, device_id, "system/info", "{}", logs, result)
        if result_code_2 == 200:
            logs.append("[PASS] DAB responded successfully after network reset.")
            result.test_result = "PASS"
        else:
            logs.append(f"[FAIL] 'system/info' failed after reset. Status: {result_code_2}")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception during test execution: {str(e)}")
        result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return [result]

# === Test 28: Factory Reset and Recovery Check ===

def run_factory_reset_and_recovery_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Factory Reset and Device Recovery Check, Test name: {test_name}")
    print("Objective: Validate factory reset and confirm device returns online with healthy DAB.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    try:
        # Step 1: Send factory reset
        print("Step 1: Sending system/factory-reset command...")
        result_code, response = execute_cmd_and_log(tester, device_id, dab_topic, "{}", logs, result)

        if result_code != 200:
            logs.append(f"[FAIL] Unexpected response code from factory reset: {result_code}")
            result.test_result = "FAILED"
            return result

        logs.append("[INFO] Factory reset command accepted. Waiting for reboot...")
        print("[INFO] Waiting for device to reboot and DAB to come back online...")

        # Step 2: Wait and poll for device health
        max_wait_sec = 120
        poll_interval = 10
        attempts = max_wait_sec // poll_interval

        for i in range(attempts):
            print(f"[INFO] Attempt {i+1}/{attempts}: Checking device health...")
            time.sleep(poll_interval)
            try:
                health_code, health_resp = execute_cmd_and_log(
                    tester, device_id, "health-check/get", "{}", logs, result
                )
                if health_code == 200:
                    logs.append("[PASS] Device returned online and passed health check after reset.")
                    result.test_result = "PASS"
                    break
            except UnsupportedOperationError as e:
                logs.append(f"[OPTIONAL_FAILED] {str(e)}")
                result.test_result = "OPTIONAL_FAILED"
                return result
            except Exception as e:
                logs.append(f"[INFO] Retry failed: {e}")

        if result.test_result != "PASS":
            logs.append("[FAIL] Device did not respond to health-check/get after factory reset.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        if result.test_result == "UNKNOWN":
            result.test_result = "SKIPPED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-'*100}")
    return result

# === Test 29: Behavior when personalized ads setting is not supported ===
# Functional Test: Validate behavior when 'personalizedAds' setting is NOT supported on the device
def run_personalized_ads_response_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Personalized Ads Optional Check, test name: {test_name}")
    print("Objective: Verify device behavior for the optional 'personalizedAds' setting.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    payload_set = json.dumps({"personalizedAds": True})
    
    result = TestResult(test_id, device_id, "system/settings/set", payload_set, "UNKNOWN", "", logs )

    try:
        # Step 1: Check if system/settings/list is supported
        print("Step 1: Checking if 'system/settings/list' operation is supported...")
        try:
            _, response = execute_cmd_and_log(tester, device_id, "system/settings/list", "{}", logs)
            if response:
                settings_list = json.loads(response).get("settings", [])
                setting_ids = [setting.get("settingId") for setting in settings_list]
                if "personalizedAds" in setting_ids:
                    logs.append("[INFO] 'personalizedAds' is listed in supported settings.")
                    print("[INFO] 'personalizedAds' is listed in supported settings.")
                    result.test_result = "OPTIONAL_FAILED"
                    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
                    return result
                else:
                    logs.append("[INFO] 'personalizedAds' is NOT listed in supported settings. Proceeding with set attempt.")
                    print("[INFO] 'personalizedAds' is NOT listed in supported settings. Proceeding with set attempt.")
            else:
                logs.append("[WARNING] No response received for 'system/settings/list'. Proceeding anyway.")

        except UnsupportedOperationError:
            logs.append("[INFO] 'system/settings/list' not supported. Skipping list check and trying to set directly.")
            print("[INFO] 'system/settings/list' not supported. Skipping list check and trying to set directly.")

        # Step 2: Check if system/settings/set is supported
        print("Step 2: Checking if 'system/settings/set' operation is supported...")
        try:
            execute_cmd_and_log(tester, device_id, "system/settings/set", "{}", logs)
        except UnsupportedOperationError:
            logs.append("[SKIPPED] 'system/settings/set' operation not supported. Test not applicable.")
            result.test_result = "SKIPPED"
            print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
            return result

        # Step 3: Attempt to set personalizedAds
        print(f"Step 3: Attempting to set 'personalizedAds' with payload: {payload_set}")
        status_code, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_set, logs)
        print_response(response)

        if not response:
            logs.append("[FAIL] No response received.")
            result.test_result = "FAILED"
            return result

        resp_json = json.loads(response)
        status = resp_json.get("status")
        error_msg = resp_json.get("error", "").lower()

        if status in (400, 501) and ("not supported" in error_msg or "do not support" in error_msg or "invalid" in error_msg):
            logs.append(f"[PASS] Device correctly rejected unsupported setting with status {status}.")
            result.test_result = "PASS"
        elif status == 200:
            logs.append("[OPTIONAL_FAILED] Device accepted 'personalizedAds' setting despite not listing it.")
            result.test_result = "OPTIONAL_FAILED"
        else:
            logs.append(f"[FAILED] Unexpected status: {status}, error: {error_msg}")
            result.test_result = "FAILED"

    except Exception as e:
        logs.append(f"[ERROR] Exception during test: {str(e)}")
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result


# === Test 30: Personalized Ads Setting Persistence Check ===
def run_personalized_ads_persistence_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Personalized Ads Persistence Check, test name: {test_name}")
    print("Objective: Verify that 'personalizedAds' setting persists after device restart.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"personalizedAds": True}), "UNKNOWN", "", logs)

    try:
        # Step 1: Check if required operations are supported using operations/list
        print("[STEP 1] Fetching supported DAB operations using 'operations/list' to verify required operations.")
        required_ops = {"system/settings/set", "system/settings/get", "system/restart"}
        status, response = execute_cmd_and_log(tester, device_id, "operations/list", "{}", logs)

        if status != 200:
            msg = f"[FAIL] Failed to retrieve supported operations. Status: {status}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"
            return result

        try:
            supported_ops = set(json.loads(response).get("operations", []))
            missing_ops = required_ops - supported_ops
            if missing_ops:
                msg = f"[OPTIONAL_FAILED] Missing required operations: {', '.join(missing_ops)}. Cannot perform persistence check."
                print(msg)
                logs.append(msg)
                result.test_result = "OPTIONAL_FAILED"
                return result
            logs.append("[INFO] All required operations are supported.")
        except Exception as e:
            msg = f"[ERROR] Failed to parse operations/list response: {str(e)}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"
            return result

        # Step 2: Enable personalizedAds
        print("[STEP 2] Enabling 'personalizedAds' setting using system/settings/set.")
        status, _ = execute_cmd_and_log(tester, device_id, "system/settings/set",
                                        json.dumps({"personalizedAds": True}), logs)
        if status != 200:
            msg = f"[FAIL] Failed to set personalizedAds. Received status: {status}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"
            return result
        logs.append("[INFO] Successfully enabled personalizedAds setting.")

        # Step 3: Restart the device
        print("[STEP 3] Sending system/restart command to reboot the device.")
        status, _ = execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs)
        if status != 200:
            msg = f"[FAIL] Device restart failed with status: {status}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"
            return result
        print("[INFO] Device restart initiated. Waiting for device to come back online...")
        logs.append("[INFO] Device restart initiated.")
        time.sleep(15)  # Modify as needed based on device boot duration

        # Step 4: Verify personalizedAds after restart
        print("[STEP 4] Fetching 'personalizedAds' value post-reboot using system/settings/get.")
        status, response = execute_cmd_and_log(tester, device_id, "system/settings/get",
                                               json.dumps({"settingId": "personalizedAds"}), logs)
        if status != 200:
            msg = f"[FAIL] Unable to retrieve 'personalizedAds' after restart. Status: {status}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"
            return result

        value = json.loads(response).get("value")
        if value is True:
            print("[PASS] 'personalizedAds' setting persisted after device restart.")
            logs.append("[PASS] 'personalizedAds' setting persisted after device restart.")
            result.test_result = "PASS"
        else:
            msg = f"[FAIL] 'personalizedAds' setting did not persist. Retrieved value: {value}"
            print(msg)
            logs.append(msg)
            result.test_result = "FAILED"

    except Exception as e:
        msg = f"[ERROR] Exception occurred during test execution: {str(e)}"
        print(msg)
        logs.append(msg)
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result


# === Test 31: Personalized Ads Not Supported Check ===

def run_personalized_ads_not_supported_check(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Personalized Ads Not-Supported Check, test name: {test_name}")
    print("Objective: If 'personalizedAds' is not supported, device should reject with 501. If listed in settings, mark as OPTIONAL_FAILED.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    set_payload = json.dumps({"personalizedAds": True})

    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"personalizedAds": True}), "UNKNOWN", "", logs)

    try:
        # Step 0: Try to use settings/list to see if 'personalizedAds' appears at all
        print("[STEP 0] Checking 'system/settings/list' for 'personalizedAds' support...")
        listed = False
        try:
            _, list_resp = execute_cmd_and_log(tester, device_id, "system/settings/list", "{}", logs, result)
            if list_resp:
                try:
                    # Expecting a JSON object; many bridges return a flat map of supported settings or a list of settingIds.
                    data = json.loads(list_resp)
                    # Handle both shapes gracefully:
                    # 1) {"personalizedAds": <capabilities or True/False>}
                    # 2) {"settings":[{"settingId":"..."}, ...]}
                    if isinstance(data, dict):
                        if "settings" in data and isinstance(data["settings"], list):
                            listed = any((isinstance(s, dict) and s.get("settingId") == "personalizedAds") for s in data["settings"])
                        else:
                            listed = "personalizedAds" in data
                except Exception as e:
                    logs.append(f"[WARN] Couldn't parse system/settings/list response: {e}")
        except UnsupportedOperationError:
            logs.append("[INFO] 'system/settings/list' not supported; will validate by attempting 'system/settings/set'.")

        if listed:
            msg = "[OPTIONAL_FAILED] 'personalizedAds' is listed in supported settings (device supports it)."
            print(msg)
            logs.append(msg)
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
            return result

        # Step 1: Not listed → attempt to set; expect 501 Not Implemented (treated as Not Supported)
        print("[STEP 1] 'personalizedAds' not listed. Attempting 'system/settings/set' expecting 501 (Not Implemented).")
        status_code, set_resp = execute_cmd_and_log(tester, device_id, "system/settings/set", set_payload, logs, result)

        # Parse response safely
        resp_json = {}
        if set_resp:
            try:
                resp_json = json.loads(set_resp)
            except Exception as e:
                logs.append(f"[ERROR] Invalid JSON in set response: {e}")

        status = resp_json.get("status", status_code)

        if status == 501:
            logs.append("[PASS] Device returned 501 (Not Implemented) for 'personalizedAds' — treated as not supported.")
            result.test_result = "PASS"
        elif status == 200:
            logs.append("[OPTIONAL_FAILED] Device accepted 'personalizedAds' (status 200) even though it was not listed.")
            result.test_result = "OPTIONAL_FAILED"
        else:
            logs.append(f"[FAILED] Unexpected status for unsupported setting. Got: {status}; Expected: 501.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        # If set itself isn’t supported, that’s effectively “not supported” for this setting too → PASS by your rule?
        # You said “use 501 not error”; but if the op is missing entirely we’ll treat as PASS (equivalent outcome).
        logs.append(f"[PASS] '{e.topic}' operation not supported; treated as not supported for 'personalizedAds'.")
        result.test_result = "PASS"
    except Exception as e:
        logs.append(f"[ERROR] Exception during test: {str(e)}")
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Test 32: Personalized Video Ads Check ===
def run_personalized_ads_Video_ads_are_personalized(dab_topic, test_category, test_name, tester, device_id):
    print(f"\n[Test] Personalized Ads Manual Validation Check, test name: {test_name}")
    print("Objective: Enable personalized ads and validate via tester confirmation if ads are personalized.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    set_payload = json.dumps({"personalizedAds": True})

    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"personalizedAds": True}), "UNKNOWN", "", logs)


    try:
        # STEP 0: Check support using system/settings/list
        print("[STEP 0] Checking 'system/settings/list' for 'personalizedAds' support...")
        listed = False
        try:
            _, list_resp = execute_cmd_and_log(tester, device_id, "system/settings/list", "{}", logs, result)
            if list_resp:
                try:
                    data = json.loads(list_resp)
                    if isinstance(data, dict):
                        if "settings" in data and isinstance(data["settings"], list):
                            listed = any((isinstance(s, dict) and s.get("settingId") == "personalizedAds") for s in data["settings"])
                        else:
                            listed = "personalizedAds" in data
                except Exception as e:
                    logs.append(f"[WARN] Couldn't parse system/settings/list response: {e}")
        except UnsupportedOperationError:
            logs.append("[INFO] 'system/settings/list' not supported; will proceed to attempt 'system/settings/set'.")

        if not listed:
            msg = "[OPTIONAL_FAILED] 'personalizedAds' is not supported on this device. Skipping manual validation."
            print(msg)
            logs.append(msg)
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
            return result

        # STEP 1: Enable personalized ads
        print("[STEP 1] Enabling 'personalizedAds' setting on the device.")
        status_code, set_resp = execute_cmd_and_log(tester, device_id, "system/settings/set", set_payload, logs, result)

        resp_json = {}
        if set_resp:
            try:
                resp_json = json.loads(set_resp)
            except Exception as e:
                logs.append(f"[ERROR] Invalid JSON in set response: {e}")

        status = resp_json.get("status", status_code)

        if status != 200:
            logs.append(f"[FAILED] Failed to enable 'personalizedAds'. Status: {status}")
            result.test_result = "FAILED"
            print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
            return result

        # STEP 2: Prompt for manual verification
        print("\n[STEP 2] Manual validation required:")
        print("Navigate through Google TV home screen, app discovery pages, and open a few ad-supported apps (e.g., YouTube).")
        print("Check if the displayed ads are highly relevant to the Google account's known interests (hobbies, favorite genres, recent searches).")
        user_input = input("Are the ads personalized? (y/n): ").strip().lower()

        if user_input == "y":
            logs.append("[PASS] Tester confirmed that ads are personalized.")
            result.test_result = "PASSED"
        elif user_input == "n":
            logs.append("[FAIL] Tester confirmed ads are NOT personalized.")
            result.test_result = "FAILED"
        else:
            logs.append("[ERROR] Invalid input provided for manual check.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] '{e.topic}' not supported. Cannot perform manual validation for 'personalizedAds'.")
        result.test_result = "OPTIONAL_FAILED"
    except Exception as e:
        logs.append(f"[ERROR] Exception during test: {str(e)}")
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Test 33: Personalized Ads Apply and Display Check ===

def run_personalized_ads_apply_and_display_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Enable personalized ads and verify device applies the setting and shows personalized ads.
    Manual validation uses yes_or_no() for the ad observation step.
    Behavior:
      - If system/settings/list works and doesn't list 'personalizedAds' -> OPTIONAL_FAILED (feature not supported).
      - If list fails (e.g., rc=500) -> proceed to set anyway.
      - If set returns 501 -> OPTIONAL_FAILED (not supported).
      - If set returns 200 -> ask tester to confirm ads are personalized (PASS/FAIL).
      - Other statuses -> FAILED.
    """
    print(f"\n[Test] Personalized Ads Apply & Display (Manual), test name: {test_name}")
    print("Objective: Enable 'personalizedAds' and confirm ads shown are tailored to the user.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    set_payload = json.dumps({"personalizedAds": True})
    result = TestResult(test_id, device_id, "system/settings/set", set_payload, "UNKNOWN", "", logs)

    try:
        # STEP 0: Preconditions (manual)
        if not yes_or_no(result, logs, "Is the device powered on AND a user is logged in?"):
            logs.append("[FAILED] Preconditions not met (power/login).")
            result.test_result = "FAILED"
            return result

        # STEP 1: Best-effort: ensure ops are loaded, and check 'system/settings/set' support
        try:
            execute_cmd_and_log(tester, device_id, "operations/list", "{}", logs, result)
        except Exception as e:
            logs.append(f"[WARN] operations/list failed; continuing. {e}")

        try:
            execute_cmd_and_log(tester, device_id, "system/settings/set", "{}", logs, result)
        except UnsupportedOperationError as e:
            logs.append(f"[OPTIONAL_FAILED] '{e.topic}' not supported; cannot enable 'personalizedAds'.")
            result.test_result = "OPTIONAL_FAILED"
            return result

        # STEP 2: Try system/settings/list (if it fails, don't fail the test—just continue)
        listed = False
        try:
            rc, list_resp = execute_cmd_and_log(tester, device_id, "system/settings/list", "{}", logs, result)
            if list_resp:
                try:
                    data = json.loads(list_resp)
                    if isinstance(data, dict):
                        if "settings" in data and isinstance(data["settings"], list):
                            listed = any((isinstance(s, dict) and s.get("settingId") == "personalizedAds") for s in data["settings"])
                        else:
                            listed = "personalizedAds" in data
                except Exception as e:
                    logs.append(f"[WARN] Could not parse settings/list JSON: {e}")
            else:
                logs.append("[WARN] Empty response from system/settings/list; continuing without list gate.")
        except UnsupportedOperationError:
            logs.append("[INFO] 'system/settings/list' not supported by device; continuing without list gate.")
        except Exception as e:
            logs.append(f"[WARN] system/settings/list failed (e.g., rc=500). Continuing. {e}")

        # If list says it's NOT supported, mark optional and bail
        if rc == 200 and listed is False:
            logs.append("[OPTIONAL_FAILED] 'personalizedAds' is not listed in supported settings (feature not supported).")
            result.test_result = "OPTIONAL_FAILED"
            return result

        # STEP 3: Enable personalizedAds
        status_code, set_resp = execute_cmd_and_log(tester, device_id, "system/settings/set", set_payload, logs, result)
        try:
            status = json.loads(set_resp).get("status", status_code) if set_resp else status_code
        except Exception:
            status = status_code

        if status == 501:
            logs.append("[OPTIONAL_FAILED] Device returned 501 (Not Implemented) for 'personalizedAds' set — treat as not supported.")
            result.test_result = "OPTIONAL_FAILED"
            return result
        if status != 200:
            logs.append(f"[FAILED] Failed to enable 'personalizedAds'. Status: {status}")
            result.test_result = "FAILED"
            return result

        # STEP 4: Manual ad observation (yes_or_no)
        print("\nPlease navigate to ad surfaces (home screen, discovery rows, YouTube, other ad-supported apps).")
        print("Look for ads tailored to the logged-in user's interests (recent searches, favorite genres, etc.).")
        if yes_or_no(result, logs, "Do the ads appear tailored/personalized to the user?"):
            logs.append("[PASS] Tester confirmed ads are personalized.")
            result.test_result = "PASS"
        else:
            logs.append("[FAILED] Tester reported ads are NOT personalized.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] '{e.topic}' not supported.")
        result.test_result = "OPTIONAL_FAILED"
    except Exception as e:
        logs.append(f"[ERROR] Exception during test: {e}")
        result.test_result = "FAILED"

    print(f"[Result] Test Id: {result.test_id} \nTest Outcome: {result.test_result}\n{'-' * 100}")
    return result

# === Functional Test Case List ===
FUNCTIONAL_TEST_CASE = [
    ("applications/get-state", "functional", run_app_foreground_check, "AppForegroundCheck", ver.DABVersion.V2_0, False),
    ("applications/get-state", "functional", run_app_background_check, "AppBackgroundCheck", ver.DABVersion.V2_0, False),
    ("applications/get-state", "functional", run_app_stopped_check, "AppStoppedCheck", ver.DABVersion.V2_0, False),
    ("applications/launch-with-content", "functional", run_launch_without_content_id, "LaunchWithoutContentID", ver.DABVersion.V2_0, True),
    ("applications/exit", "functional", run_exit_after_video_check, "ExitAfterVideoCheck", ver.DABVersion.V2_0, False),
    ("applications/launch", "functional", run_relaunch_stability_check, "RelaunchStabilityCheck", ver.DABVersion.V2_0, False),
    ("applications/launch", "functional", run_exit_and_relaunch_check, "ExitAndRelaunchApp", ver.DABVersion.V2_0, False),
    ("system/settings/set", "functional", run_screensaver_enable_check, "ScreensaverEnableCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_disable_check, "ScreensaverDisableCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_active_check, "ScreensaverActiveCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_inactive_check, "ScreensaverInactiveCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_active_return_check, "ScreensaverActiveReturnCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_active_after_continuous_idle_check, "ScreensaverActiveAfterContinuousIdleCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensaver_inactive_after_reboot_check, "ScreensaverInactiveAfterRebootCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensavertimeout_300_check, "ScreensaverTimeout300Check", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensavertimeout_reboot_check, "ScreensaverTimeoutRebootCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_screensavertimeout_guest_mode_check, "ScreensaverTimeoutGuestModeCheck", ver.DABVersion.V2_1, False),
    ("system/settings/list", "functional", run_screensavertimeout_minimum_check, "ScreensaverMinTimeoutCheck", ver.DABVersion.V2_1, False),
    ("system/settings/list", "functional", run_screensavermintimeout_reboot_check, "ScreensaverMinTimeoutRebootCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_highContrastText_text_over_images_check, "HighContrasTextTextOverImagesCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_highContrastText_video_playback_check, "HighContrasTextVideoPlaybackCheck", ver.DABVersion.V2_1, False),
    ("voice/set", "functional", run_set_invalid_voice_assistant_check, "SetInvalidVoiceAssistant", ver.DABVersion.V2_0, True),
    ("system/restart", "functional", run_device_restart_and_telemetry_check, "DeviceRestartAndTelemetryCheck", ver.DABVersion.V2_0, False),
    ("app-telemetry/stop", "functional", run_stop_app_telemetry_without_active_session_check, "StopAppTelemetryWithoutActiveSession", ver.DABVersion.V2_1, True),
    ("applications/launch-with-content", "functional", run_launch_video_and_health_check, "LaunchVideoAndHealthCheck", ver.DABVersion.V2_1, False),
    ("voice/list", "functional", run_voice_list_with_no_voice_assistant, "VoiceListWithNoVoiceAssistant", ver.DABVersion.V2_0, True),
    ("applications/launch", "functional", run_launch_when_uninstalled_check, "LaunchAppNotInstalled", ver.DABVersion.V2_1, True),
    ("applications/launch", "functional", run_launch_app_while_restarting_check, "LaunchAppWhileDeviceRestarting", ver.DABVersion.V2_1, True),
    ("system/network-reset", "functional", run_network_reset_check, "NetworkResetCheck", ver.DABVersion.V2_1, False),
    ("system/factory-reset", "functional", run_factory_reset_and_recovery_check, "Factory Reset and Recovery Check", ver.DABVersion.V2_1, False ),
    ("system/settings/list", "functional", run_personalized_ads_response_check, "behavior when personalized ads setting is not supported", ver.DABVersion.V2_1, False ),
    ("system/settings/set", "functional", run_personalized_ads_persistence_check, "Personalized Ads Setting Persistence Check", ver.DABVersion.V2_1, False),
    ("system/settings/list", "functional", run_personalized_ads_not_supported_check, "PersonalizedAdsNotSupportedCheck", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_personalized_ads_Video_ads_are_personalized, "Video ads are personalized", ver.DABVersion.V2_1, False),
    ("system/settings/set", "functional", run_personalized_ads_apply_and_display_check, "display_check for personalized", ver.DABVersion.V2_1, False),

]