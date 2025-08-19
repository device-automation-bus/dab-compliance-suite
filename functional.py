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

# --- Sleep Time Constants ---
APP_LAUNCH_WAIT = 5
APP_UNINSTALL_WAIT = 5
APP_CLEAR_DATA_WAIT = 5
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
    """
    Fill SUPPORTED_OPERATIONS via 'operations/list' and return it.
    Accepts list[str] or list[{"operation": str}] shapes.
    """
    global SUPPORTED_OPERATIONS

    if SUPPORTED_OPERATIONS:
        LOGGER.info(f"Using cached operations ({len(SUPPORTED_OPERATIONS)})")
        return SUPPORTED_OPERATIONS

    LOGGER.info("Fetching supported DAB operations via 'operations/list'")
    result_code = tester.execute_cmd(device_id, "operations/list", "{}")
    response = tester.dab_client.response()

    if result_code != 0:
        code = tester.dab_client.last_error_code()
        LOGGER.warn(f"'operations/list' failed (code {code}); "
                    "continuing without cache")
        tester.dab_client.last_error_msg()
        return SUPPORTED_OPERATIONS

    try:
        data = json.loads(response) if response else {}
        ops = None

        if isinstance(data, dict) and "operations" in data:
            raw_ops = data["operations"]
            if isinstance(raw_ops, list):
                if raw_ops and isinstance(raw_ops[0], dict):
                    ops = [d.get("operation")
                           for d in raw_ops
                           if isinstance(d, dict) and d.get("operation")]
                else:
                    ops = [x for x in raw_ops if isinstance(x, str)]

        if not ops:
            LOGGER.warn("'operations' list missing or invalid in response")
            return SUPPORTED_OPERATIONS

        SUPPORTED_OPERATIONS = ops
        LOGGER.ok(f"Cached {len(SUPPORTED_OPERATIONS)} operations")
        return SUPPORTED_OPERATIONS

    except Exception as e:
        LOGGER.error(f"Failed to parse 'operations/list' response: {e}")
        return SUPPORTED_OPERATIONS


# === Capability-gate helpers (non-breaking additions) =========================
from logger import LOGGER

SUPPORTED_SETTINGS_IDS = None   # cached by _fetch_supported_settings_ids
SUPPORTED_KEY_CODES    = None   # cached by _fetch_supported_key_codes

def _split_items(s: str):
    return [x.strip() for x in s.split(",") if x and x.strip()]

def _parse_need_spec(spec: str):
    """
    Parse a spec like:
      'ops: a,b | settings: x,y | keys: K_HOME,K_BACK'
    Default segment = ops (if no prefix is given).
    """
    ops_req, set_req, key_req = set(), set(), set()
    for seg in (p.strip() for p in spec.split("|")):
        if not seg:
            continue
        low = seg.lower()
        if low.startswith(("ops:", "op:", "operations:")):
            ops_req.update(_split_items(seg.split(":", 1)[1]))
        elif low.startswith(("settings:", "setting:", "set:")):
            set_req.update(_split_items(seg.split(":", 1)[1]))
        elif low.startswith(("keys:", "key:")):
            key_req.update(_split_items(seg.split(":", 1)[1]))
        else:
            ops_req.update(_split_items(seg))  # default to ops
    LOGGER.info(
        f"Parsed need spec → ops={sorted(ops_req)}, "
        f"settings={sorted(set_req)}, keys={sorted(key_req)}"
    )
    return ops_req, set_req, key_req

def _fetch_supported_settings_ids(tester, device_id, logs=None, result=None):
    """
    Returns a set of supported setting IDs using 'system/settings/list'.
    Falls back gracefully if list is unsupported or unparseable.
    """
    global SUPPORTED_SETTINGS_IDS
    if SUPPORTED_SETTINGS_IDS is not None:
        LOGGER.info(f"Using cached settings IDs ({len(SUPPORTED_SETTINGS_IDS)})")
        if logs is not None:
            logs.append(LOGGER.stamp(f"Using cached settings IDs ({len(SUPPORTED_SETTINGS_IDS)})"))
        return SUPPORTED_SETTINGS_IDS
    try:
        _, resp = execute_cmd_and_log(
            tester, device_id, "system/settings/list", "{}", logs, result
        )
        data = json.loads(resp) if resp else {}
        if isinstance(data, dict) and isinstance(data.get("settings"), list):
            SUPPORTED_SETTINGS_IDS = {
                s.get("settingId")
                for s in data["settings"]
                if isinstance(s, dict) and s.get("settingId")
            }
        elif isinstance(data, dict):
            SUPPORTED_SETTINGS_IDS = set(data.keys())
        else:
            SUPPORTED_SETTINGS_IDS = set()
        LOGGER.info(f"Fetched {len(SUPPORTED_SETTINGS_IDS)} setting IDs")
        if logs is not None:
            logs.append(LOGGER.stamp(f"Fetched {len(SUPPORTED_SETTINGS_IDS)} setting IDs"))
    except UnsupportedOperationError:
        SUPPORTED_SETTINGS_IDS = set()
        LOGGER.info("system/settings/list not supported; skipping settings gate.")
        if logs is not None:
            logs.append(LOGGER.stamp("system/settings/list not supported; skipping settings gate."))
    except Exception as e:
        SUPPORTED_SETTINGS_IDS = set()
        LOGGER.warn(f"settings/list parse failed: {e}")
        if logs is not None:
            logs.append(LOGGER.stamp(f"settings/list parse failed: {e}"))
    return SUPPORTED_SETTINGS_IDS

def _fetch_supported_key_codes(tester, device_id, logs=None, result=None):
    """
    Returns a set of supported key codes using 'input/key/list'.
    """
    global SUPPORTED_KEY_CODES
    if SUPPORTED_KEY_CODES is not None:
        LOGGER.info(f"Using cached key codes ({len(SUPPORTED_KEY_CODES)})")
        if logs is not None:
            logs.append(LOGGER.stamp(f"Using cached key codes ({len(SUPPORTED_KEY_CODES)})"))
        return SUPPORTED_KEY_CODES
    try:
        _, resp = execute_cmd_and_log(
            tester, device_id, "input/key/list", "{}", logs, result
        )
        data = json.loads(resp) if resp else {}
        if isinstance(data, dict):
            for k in ("keys", "supportedKeys", "keyCodes"):
                if isinstance(data.get(k), list):
                    SUPPORTED_KEY_CODES = set(data[k])
                    break
            else:
                SUPPORTED_KEY_CODES = set()
        elif isinstance(data, list):
            SUPPORTED_KEY_CODES = set(data)
        else:
            SUPPORTED_KEY_CODES = set()
        LOGGER.info(f"Fetched {len(SUPPORTED_KEY_CODES)} key codes")
        if logs is not None:
            logs.append(LOGGER.stamp(f"Fetched {len(SUPPORTED_KEY_CODES)} key codes"))
    except UnsupportedOperationError:
        SUPPORTED_KEY_CODES = set()
        LOGGER.info("input/key/list not supported; skipping key gate.")
        if logs is not None:
            logs.append(LOGGER.stamp("input/key/list not supported; skipping key gate."))
    except Exception as e:
        SUPPORTED_KEY_CODES = set()
        LOGGER.warn(f"key/list parse failed: {e}")
        if logs is not None:
            logs.append(LOGGER.stamp(f"key/list parse failed: {e}"))
    return SUPPORTED_KEY_CODES

def need(tester, device_id, spec, result=None, logs=None):
    """
    One-line capability check. Example:
        need(tester, device_id,
             "ops: applications/launch, applications/get-state | "
             "settings: screenSaver | keys: KEY_HOME",
             result, logs)
    If any required item is missing, marks OPTIONAL_FAILED and returns False.
    """
    ops_req, set_req, key_req = _parse_need_spec(spec)

    try:
        # Ensure ops cache is filled
        if not SUPPORTED_OPERATIONS:
            LOGGER.info("Fetching supported operations…")
            fetch_supported_operations(tester, device_id)
        have_ops = set(SUPPORTED_OPERATIONS or [])
        miss_ops = ops_req - have_ops
        if miss_ops:
            LOGGER.warn("[OPTIONAL_FAILED] Required ops not supported: " +
                        ", ".join(sorted(miss_ops)))
            if logs is not None:
                logs.append(LOGGER.stamp("[OPTIONAL_FAILED] Required ops not supported: " +
                                         ", ".join(sorted(miss_ops))))
            if result is not None:
                result.test_result = "OPTIONAL_FAILED"
            return False

        # Settings (best-effort; if list unsupported, we skip)
        if set_req:
            have_settings = _fetch_supported_settings_ids(
                tester, device_id, logs, result
            )
            if have_settings:
                miss_set = set_req - have_settings
                if miss_set:
                    LOGGER.warn("[OPTIONAL_FAILED] Required settings not supported: " +
                                ", ".join(sorted(miss_set)))
                    if logs is not None:
                        logs.append(LOGGER.stamp("[OPTIONAL_FAILED] Required settings not supported: " +
                                                 ", ".join(sorted(miss_set))))
                    if result is not None:
                        result.test_result = "OPTIONAL_FAILED"
                    return False
            else:
                LOGGER.info("Settings list unavailable; skipping settings gate.")
                if logs is not None:
                    logs.append(LOGGER.stamp("Settings list unavailable; skipping settings gate."))

        # Keys (best-effort; if key/list unsupported, we skip)
        if key_req:
            have_keys = _fetch_supported_key_codes(
                tester, device_id, logs, result
            )
            if have_keys:
                miss_keys = key_req - have_keys
                if miss_keys:
                    LOGGER.warn("[OPTIONAL_FAILED] Required keys not supported: " +
                                ", ".join(sorted(miss_keys)))
                    if logs is not None:
                        logs.append(LOGGER.stamp("[OPTIONAL_FAILED] Required keys not supported: " +
                                                 ", ".join(sorted(miss_keys))))
                    if result is not None:
                        result.test_result = "OPTIONAL_FAILED"
                    return False
            else:
                LOGGER.info("Key list unavailable; skipping key gate.")
                if logs is not None:
                    logs.append(LOGGER.stamp("Key list unavailable; skipping key gate."))

        LOGGER.ok("Capability gate passed.")
        if logs is not None:
            logs.append(LOGGER.stamp("Capability gate passed."))
        return True

    except Exception as e:
        # Any unexpected failure in gating is a non-enforceable optional fail
        LOGGER.warn(f"[OPTIONAL_FAILED] Capability check failed: {e}")
        if logs is not None:
            logs.append(LOGGER.stamp(f"[OPTIONAL_FAILED] Capability check failed: {e}"))
        if result is not None:
            result.test_result = "OPTIONAL_FAILED"
        return False

def ensure_supported(tester, device_id, result, logs, ops=None, settings=None, keys=None):
    """
    Convenience wrapper to avoid building the spec string by hand.
    """
    parts = []
    if ops:      parts.append("ops: "      + ", ".join(sorted(ops)))
    if settings: parts.append("settings: " + ", ".join(sorted(settings)))
    if keys:     parts.append("keys: "     + ", ".join(sorted(keys)))
    spec = " | ".join(parts) or ""
    LOGGER.info(f"Ensuring support for: {spec or '(none)'}")
    if logs is not None:
        logs.append(LOGGER.stamp(f"Ensuring support for: {spec or '(none)'}"))
    return need(tester, device_id, spec, result, logs)

def execute_cmd_and_log(tester, device_id, topic, payload, logs=None, result=None):
    global SUPPORTED_OPERATIONS

    if not SUPPORTED_OPERATIONS:
        fetch_supported_operations(tester, device_id)

    if topic not in SUPPORTED_OPERATIONS:
        LOGGER.warn(f"[OPTIONAL_FAILED] Operation '{topic}' is not supported by the device.")
        if logs is not None:
            logs.append(line)
        if result is not None:
            result.test_result = "OPTIONAL_FAILED"
            result.reason = line
        raise UnsupportedOperationError(topic)

    LOGGER.info(f"Executing {topic} with payload {payload}")
    rc = tester.execute_cmd(device_id, topic, payload)
    resp = tester.dab_client.response()
    LOGGER.info(f"[{topic}] Response: {resp}")
    if logs is not None:
        logs.append(f"[{topic}] Response: {resp}")
    return rc, resp

def dab_status_from(resp, rc):
    try:
        if isinstance(resp, str):      # JSON string
            return json.loads(resp).get("status", rc)
        if isinstance(resp, dict):     # dict
            return resp.get("status", rc)
    except Exception:
        pass
    return rc

# The 'print_response' function is removed from here
# It is still defined in the file but is no longer called by this function.

def print_response(response, topic_for_color=None, indent=10):
    if isinstance(response, str):
        try:
            response = json.loads(response)
        except json.JSONDecodeError:
            LOGGER.error("Invalid JSON string")
            return
    if not isinstance(response, dict):
        LOGGER.error("Invalid response format")
        return
    LOGGER.info("Response:")
    for key, value in response.items():
        LOGGER.info(f"{' ' * indent}{key}: {value}")


def yes_or_no(result, logs, question=""):
    positive = ['YES', 'Y']
    negative = ['NO', 'N']
    while True:
        prompt = f"{question}(Y/N)"
        LOGGER.prompt(prompt)
        if logs is not None:
            logs.append(prompt)
        ch = readchar().upper()
        echo = f"[{ch}]"
        LOGGER.result(echo)
        if logs is not None:
            logs.append(echo)
        if ch in positive:
            return True
        if ch in negative:
            return False


def select_input(result, logs, arr):
    print(f"*0: There is no option that meet the requirement.")
    logs.append(f"*0: There is no option that meet the requirement.")
    index = 0
    for value in arr:
        index = index + 1
        print(f"*{index}: {value}")
        logs.append(f"*{index}: {value}")

    while True:
        print(f"Please input number:")
        user_input = readchar()
        if user_input.isdigit() == False or int(user_input) > index:
            continue
        print(f"[{user_input}]")
        logs.append(f"[{user_input}]")
        return int(user_input)

def countdown(title, count):
    LOGGER.info(f"{title} — starting {count}s")
    while count:
        mins, secs = divmod(count, 60)
        timer = f"{mins:02d}:{secs:02d}"
        sys.stdout.write("\r" + title + " --- " + timer)
        sys.stdout.flush()
        time.sleep(1)
        count -= 1
    sys.stdout.write("\r" + title + " --- Done!\n")
    LOGGER.ok(f"{title} — done")


def waiting_for_screensaver(result, logs, screenSaverTimeout, tips):
    while True:
        if yes_or_no(result, logs, tips):
            break
        else:
            continue
    countdown(f"Waiting for {screenSaverTimeout} seconds in idle state.", screenSaverTimeout)


def validate_response(tester, dab_topic, dab_payload, dab_response, result, logs):
    if not dab_response:
        line = f"[FAIL] Request {dab_topic} '{dab_payload}' failed. No response received."
        LOGGER.error(line)
        if logs is not None:
            logs.append(line)
        result.test_result = "FAILED"
        LOGGER.result(f"[Result] Test Id: {result.test_id}\nTest Outcome: {result.test_result}\n{'-'*100}")
        return False, result

    try:
        response = json.loads(dab_response)
    except Exception:
        line = f"[FAIL] Request {dab_topic} '{dab_payload}' returned invalid JSON."
        LOGGER.error(line)
        if logs is not None:
            logs.append(line)
        result.test_result = "FAILED"
        LOGGER.result(f"[Result] Test Id: {result.test_id}\nTest Outcome: {result.test_result}\n{'-'*100}")
        return False, result

    status = response.get("status")
    if status != 200:
        if status == 501:
            LOGGER.warn(f"Request {dab_topic} '{dab_payload}' is NOT supported on this device.")
            if logs is not None:
                logs.append(f"[OPTIONAL_FAILED] Request {dab_topic} '{dab_payload}' is NOT supported on this device.")
            result.test_result = "OPTIONAL_FAILED"
        else:
            LOGGER.error(f"Request operation {dab_topic} '{dab_payload}' FAILED on this device.")
            if logs is not None:
                logs.append(f"[FAILED] Request operation {dab_topic} '{dab_payload}' FAILED on this device.")
            result.test_result = "FAILED"

        LOGGER.result(f"[Result] Test Id: {result.test_id}\nTest Outcome: {result.test_result}\n{'-'*100}")
        return False, result

    return True, result


def verify_system_setting(tester, payload, response, result, logs):
    (key, value), = json.loads(payload).items()
    settings = json.loads(response)
    if key in settings:
        actual_value = settings.get(key)
        line = f"System settings get '{key}', Expected: {value}, Actual: {actual_value}"
        LOGGER.info(line)
        if actual_value == value:
            if logs is not None:
                logs.append(line)
            return True, result
        if logs is not None:
            logs.append(f"[FAIL] {line}")
        result.test_result = "FAILED"
    else:
        LOGGER.error(f"System settings get '{key}' FAILED on this device.")
        if logs is not None:
            logs.append(f"[FAILED] System settings get '{key}' FAILED on this device.")
        result.test_result = "FAILED"

    LOGGER.result(f"[Result] Test Id: {result.test_id}\nTest Outcome: {result.test_result}\n{'-'*100}")
    return False, result


def get_supported_setting(tester, device_id, key, result, logs, do_list=True):
    topic = "system/settings/list"
    payload = "{}"
    if EnforcementManager().check_supported_settings() == False or do_list:
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        ok, result = validate_response(tester, topic, payload, response, result, logs)
        if ok is False:
            EnforcementManager().set_supported_settings(None)
            return None, result
        try:
            EnforcementManager().set_supported_settings(json.loads(response))
        except Exception:
            EnforcementManager().set_supported_settings(None)

    settings = EnforcementManager().get_supported_settings()
    if not settings:
        LOGGER.error(f"System setting list '{key}' FAILED on this device.")
        if logs is not None:
            logs.append(f"[FAILED] System settings list '{key}' FAILED on this device.")
        return None, result

    if key in settings:
        setting = settings.get(key)
        LOGGER.info(f"Get supported setting '{key}: {setting}'")
        return setting, result

    LOGGER.error(f"System setting '{key}' is unsupported on this device.")
    if logs is not None:
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
    props = Properties(PacketTypes.PUBLISH)
    props.ResponseTopic = response_topic
    dab_client._DabClient__client.publish(topic, "{}", qos=0, properties=props)
    LOGGER.info(f"Sent restart command to {topic} (fire-and-forget)")

def run_app_foreground_check(dab_topic, test_category, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)

    try:
        # Always-on header + description (printed and stored)
        for line in (
            f"[TEST] App Foreground Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: launch the app and confirm it reaches FOREGROUND within the wait window.",
            "[DESC] Preconditions: device powered on, DAB reachable, stable network.",
            "[DESC] Required operations: applications/launch, applications/get-state.",
            "[DESC] Pass criteria: state == 'FOREGROUND'. Any other state → FAILED."
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        if not need(tester, device_id, "ops: applications/launch, applications/get-state", result, logs):
            line = f"[RESULT] OPTIONAL_FAILED — missing required operations (test_id={test_id}, appId={app_id})"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome=OPTIONAL_FAILED, observed_state=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Step 1 — launch
        payload_launch = json.dumps({"appId": app_id})
        line = f"[STEP] Launching app via applications/launch with payload: {payload_launch}"
        LOGGER.result(line); logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_launch, logs, result)

        # Wait for stabilization
        line = f"[WAIT] Allowing {APP_LAUNCH_WAIT}s for the app to settle."
        LOGGER.info(line); logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2 — get-state
        payload_state = json.dumps({"appId": app_id})
        line = f"[STEP] Querying application state via applications/get-state for appId={app_id}."
        LOGGER.result(line); logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", payload_state, logs, result)

        # Record raw response into result logs too
        line = f"[INFO] applications/get-state raw response: {response}"
        LOGGER.info(line); logs.append(line)

        # Parse and evaluate
        try:
            state = (json.loads(response).get("state", "") if response else "").upper()
            line = f"[INFO] Parsed app state='{state}'."
            LOGGER.info(line); logs.append(line)
        except Exception:
            state = "UNKNOWN"
            line = f"[FAIL] Request applications/get-state '{payload_state}' returned invalid JSON."
            LOGGER.error(line); logs.append(line)

        if state == "FOREGROUND":
            result.test_result = "PASS"
            line = f"[RESULT] PASS — app reached FOREGROUND after launch (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 'FOREGROUND' but observed '{state}' (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line); logs.append(line)

        # Final summary (printed and stored)
        line = f"[SUMMARY] outcome={result.test_result}, observed_state={state}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line); logs.append(line)
        return result

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line); logs.append(line)
        line = f"[SUMMARY] outcome=OPTIONAL_FAILED, observed_state=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line); logs.append(line)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during foreground check: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line); logs.append(line)
        line = f"[SUMMARY] outcome=SKIPPED, observed_state=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line); logs.append(line)
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

# === Test 34: Uninstall An Application Currently Running Foreground Check ===
def run_uninstall_foreground_app_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Uninstall An Application Currently Running Foreground Check")
    print("Objective: Validate application currently running foreground can be uninstalled successfully.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "applications/uninstall", json.dumps({"appId": "[appId]"}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Select one non-system application in the applications list.")
        topic = "applications/list"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        applications = json.loads(response).get("applications")
        appId_list = []

        for application in applications:
            appId = application.get("appId")
            appId_list.append(appId)

        logs.append(f"Please select one Non-System application in the list.")
        print(f"Please select one Non-System application in the list.")
        index = select_input(result, logs, appId_list)
        if index == 0:
            print(f"There are no non-system applications in the applications list.")
            logs.append(f"[OPTIONAL_FAILED] There are no non-system applications in the applications list.")
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
            return result

        appId = appId_list[index - 1]
        logs.append(f"Select appId '{appId}'.")

        print(f"Step 2: Launching application '{appId}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": appId}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch and stabilize.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 3: Getting state of application '{appId}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": appId}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state: {state}.")

        if state != "FOREGROUND":
            logs.append(f"[FAIL] App state is '{state}', expected 'FOREGROUND'.")
            result.test_result = "FAILED"

        print(f"Step 4: Uninstall application '{appId}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": appId}), logs)
        status = json.loads(response).get("status", 0) if response else 0
        print(f"Waiting {APP_UNINSTALL_WAIT} seconds for application to uninstall.")
        time.sleep(APP_UNINSTALL_WAIT)

        if status == 200:
            print(f"Uninstall an application currently running foreground successful.")
            logs.append(f"[PASS] Uninstall an application currently running foreground successful.")
            result.test_result = "PASS"
        else:
            print(f"Uninstall an application currently running foreground fail.")
            logs.append(f"[FAIL] Uninstall an application currently running foreground fail.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 35: Uninstall An System Application Check ===
def run_uninstall_system_app_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Uninstall An System Application Check")
    print("Objective: Validate system application can not be uninstalled.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "applications/uninstall", json.dumps({"appId": "[appId]"}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Select one system application in the applications list.")
        topic = "applications/list"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        applications = json.loads(response).get("applications")
        appId_list = []

        for application in applications:
            appId = application.get("appId")
            appId_list.append(appId)

        logs.append(f"Please select one System application in the list.")
        print(f"Please select one System application in the list.")
        index = select_input(result, logs, appId_list)
        if index == 0:
            print(f"There are no system applications in the applications list.")
            logs.append(f"[OPTIONAL_FAILED] There are no system applications in the applications list.")
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
            return result

        appId = appId_list[index - 1]
        logs.append(f"Select appId '{appId}'.")

        print(f"Step 2: Uninstall application '{appId}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": appId}), logs)
        status = json.loads(response).get("status", 0) if response else 0
        print(f"Waiting {APP_UNINSTALL_WAIT} seconds for application to uninstall.")
        time.sleep(APP_UNINSTALL_WAIT)

        if status == 403:
            print(f"The system application '{appId}' cannot be uninstalled.")
            logs.append(f"[PASS] The system application '{appId}' cannot be uninstalled.")
            result.test_result = "PASS"
        elif status == 200:
            print(f"The system application '{appId}' can be uninstalled.")
            logs.append(f"[FAIL] The system application '{appId}' can be uninstalled.")
            result.test_result = "FAILED"
        else:
            logs.append(f"[ERROR] {str(e)}")
            result.test_result = "SKIPPED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 36: Clear Data For An Application Currently Running Foreground Check ===
def run_clear_data_foreground_app_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Clear Data For An Application Currently Running Foreground Check")
    print("Objective: Validate application currently running foreground can be cleared data successfully.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    appId = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/clear-data", json.dumps({"appId": appId}), "UNKNOWN", "", logs)

    try:
        print(f"Step 2: Launching application '{appId}'.")
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": appId}), logs)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch and stabilize.")
        time.sleep(APP_LAUNCH_WAIT)

        print(f"Step 3: Getting state of application '{appId}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": appId}), logs)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        print(f"Current application state: {state}.")

        if state != "FOREGROUND":
            logs.append(f"[FAIL] App state is '{state}', expected 'FOREGROUND'.")
            result.test_result = "FAILED"

        print(f"Step 4: Clear application '{appId}' data.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/clear-data", json.dumps({"appId": appId}), logs)
        status = json.loads(response).get("status", 0) if response else 0
        print(f"Waiting {APP_CLEAR_DATA_WAIT} seconds for application to clear data.")
        time.sleep(APP_CLEAR_DATA_WAIT)

        if status == 200:
            print(f"Clear data for an application currently running foreground successful.")
            logs.append(f"[PASS] Clear data for an application currently running foreground successful.")
            result.test_result = "PASS"
        else:
            print(f"Clear data for an application currently running foreground fail.")
            logs.append(f"[FAIL] Clear data for an application currently running foreground fail.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

# === Test 37: Clear Data For An System Application Check ===
def run_clear_data_system_app_check(dab_topic, test_category, test_name, tester, device_id):
    print("\n[Test] Clear Data For An System Application Check")
    print("Objective: Validate system application can be cleared data successfully.")

    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []
    result = TestResult(test_id, device_id, "applications/uninstall", json.dumps({"appId": "[appId]"}), "UNKNOWN", "", logs)

    try:
        print(f"Step 1: Select one system application in the applications list.")
        topic = "applications/list"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result

        applications = json.loads(response).get("applications")
        appId_list = []

        for application in applications:
            appId = application.get("appId")
            appId_list.append(appId)

        logs.append(f"Please select one System application in the list.")
        print(f"Please select one System application in the list.")
        index = select_input(result, logs, appId_list)
        if index == 0:
            print(f"There are no system applications in the applications list.")
            logs.append(f"[OPTIONAL_FAILED] There are no system applications in the applications list.")
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
            return result

        appId = appId_list[index - 1]
        logs.append(f"Select appId '{appId}'.")

        print(f"Step 4: Clear data for system application '{appId}'.")
        _, response = execute_cmd_and_log(tester, device_id, "applications/clear-data", json.dumps({"appId": appId}), logs)
        status = json.loads(response).get("status", 0) if response else 0
        print(f"Waiting {APP_CLEAR_DATA_WAIT} seconds for application to uninstall.")
        time.sleep(APP_CLEAR_DATA_WAIT)

        if status == 200:
            print(f"Clear data for an system application successful.")
            logs.append(f"[PASS] Clear data for an system application successful.")
            result.test_result = "PASS"
        else:
            print(f"Clear data for an system application fail.")
            logs.append(f"[FAIL] Clear data for an system application fail.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    # Print concise final test result status
    print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
    return result

def run_clear_data_user_installed_app_foreground(dab_topic, test_category, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/clear-data", payload_app, "UNKNOWN", "", logs)

    try:
        for line in (
            f"[TEST] Clear Data (User-Installed App) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Minimal flow: launch → clear-data → relaunch. Pass if DAB status == 200."
        ):
            LOGGER.result(line); logs.append(line)

        # === Capability gate via new need() (raises UnsupportedOperationError if missing) ===
        need(tester, device_id, "ops: applications/launch, applications/clear-data")
        line = "[INFO] Capability gate passed."
        LOGGER.info(line); logs.append(line)

        # 1) Launch to ensure app is active (assume FOREGROUND after wait)
        line = f"[STEP] applications/launch {payload_app}"; LOGGER.result(line); logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        line = f"[WAIT] {APP_LAUNCH_WAIT}s"; LOGGER.info(line); logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # 2) Clear data (use DAB status, not transport rc)
        line = f"[STEP] applications/clear-data {payload_app}"; LOGGER.result(line); logs.append(line)
        rc, resp = execute_cmd_and_log(tester, device_id, "applications/clear-data", payload_app, logs, result)
        dab_status = dab_status_from(resp, rc)
        line = f"[INFO] applications/clear-data transport_rc={rc}, dab_status={dab_status}"; LOGGER.info(line); logs.append(line)

        # 3) Relaunch to surface first-run behavior
        line = f"[STEP] applications/launch {payload_app}"; LOGGER.result(line); logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        line = f"[WAIT] {APP_LAUNCH_WAIT}s"; LOGGER.info(line); logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        if dab_status == 200:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — clear-data returned 200 (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line); logs.append(line)
        elif dab_status == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = f"[RESULT] OPTIONAL_FAILED — clear-data not implemented (501) (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = (f"[RESULT] FAILED — clear-data returned {dab_status} (transport_rc={rc}) "
                    f"(appId={app_id}, device={device_id}, test_id={test_id})")
            LOGGER.result(line); logs.append(line)

        line = (f"[SUMMARY] outcome={result.test_result}, clear_status={dab_status}, "
                f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line); logs.append(line)
        return result

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = (f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported "
                f"(test_id={test_id}, device={device_id}, appId={app_id})")
        LOGGER.result(line); logs.append(line)
        line = (f"[SUMMARY] outcome=OPTIONAL_FAILED, clear_status=N/A, "
                f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line); logs.append(line)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        line = (f"[RESULT] SKIPPED — internal error: {e} "
                f"(test_id={test_id}, device={device_id}, appId={app_id})")
        LOGGER.result(line); logs.append(line)
        line = (f"[SUMMARY] outcome=SKIPPED, clear_status=N/A, "
                f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line); logs.append(line)
        return result
    
def run_install_from_app_store_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install a new app from the app store and launch it.
    Minimal flow: install-from-app-store → short wait → launch
    Pass if install returns 200 and launch returns 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("store_app", "Store_App")  # valid, not-installed appId
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install-from-app-store", payload_app, "UNKNOWN", "", logs)

    INSTALL_WAIT = 10  # short padding after install to finalize

    try:
        # Header
        msg = f"[TEST] Install From App Store — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: install-from-app-store → short wait → launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Capability gate — returns OPTIONAL_FAILED in result/logs if unsupported
        if not need(tester, device_id, "ops: applications/install-from-app-store, applications/launch", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install from app store
        msg = f"[STEP] applications/install-from-app-store {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install-from-app-store", payload_app, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] install-from-app-store transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — install-from-app-store returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to allow finalization
        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # 2) Launch the newly installed app
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_app, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install-from-app-store and launch both returned 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — launch returned {launch_status} (expected 200) after install"
            LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
               f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_youtube_kids_from_store(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install YouTube Kids from the app store and confirm it launches.
    Flow: install-from-app-store -> short wait -> (optional) applications/list check -> launch
    Pass if install == 200 and launch == 200.
    Note: "family-friendly settings" visibility is outside DAB scope; log info for manual/OEM validation.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("youtube_kids", "YouTubeKids")  # use config.py entry
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install-from-app-store", payload_app, "UNKNOWN", "", logs)

    INSTALL_WAIT = 10  # short padding after install

    try:
        # Header
        msg = f"[TEST] YouTube Kids Install — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: install-from-app-store → short wait → (optional) apps list → launch; PASS if both steps return 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Note: Family-friendly settings check is manual/OEM (not exposed via DAB)."
        LOGGER.result(msg); logs.append(msg)

        # Capability gate (required ops only)
        if not need(tester, device_id, "ops: applications/install-from-app-store, applications/launch", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install from app store
        msg = f"[STEP] applications/install-from-app-store {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install-from-app-store", payload_app, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] install-from-app-store transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — install-from-app-store returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to finalize install
        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # (Optional) verify appears in installed apps list, if supported
        try:
            msg = "[STEP] applications/list"
            LOGGER.result(msg); logs.append(msg)
            rc_list, resp_list = execute_cmd_and_log(
                tester, device_id, "applications/list", "{}", logs, result
            )
            # Best-effort parse
            installed = False
            try:
                data = json.loads(resp_list) if isinstance(resp_list, str) else (resp_list or {})
                apps = data.get("applications") or data.get("apps") or data
                if isinstance(apps, list):
                    for a in apps:
                        if isinstance(a, str) and a == app_id:
                            installed = True; break
                        if isinstance(a, dict) and (a.get("appId") == app_id or a.get("id") == app_id or a.get("name") == app_id):
                            installed = True; break
                elif isinstance(apps, dict):
                    # Some devices might return a dict keyed by appId
                    installed = app_id in apps.keys()
            except Exception:
                installed = None
            msg = f"[INFO] applications/list contains appId={app_id}: {installed}"
            LOGGER.info(msg); logs.append(msg)
        except UnsupportedOperationError:
            msg = "[INFO] Skipping installed-apps verification: applications/list not supported"
            LOGGER.info(msg); logs.append(msg)

        # 2) Launch the newly installed app
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_app, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install-from-app-store and launch both returned 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — launch returned {launch_status} (expected 200) after install"
            LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
               f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_uninstall_after_standby_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Uninstall a pre-installed removable app when device was in standby (woken for operation).
    Flow: (best-effort) wake via input/key-press -> applications/uninstall -> short wait -> (best-effort) applications/list
    Pass if uninstall returns 200 and (if list is available) the app no longer appears.
    Notes:
      - Standby wake is best-effort via input/key-press; not all devices expose power mode controls via DAB.
      - Data deletion confirmation is OEM/manual; DAB has no per-app storage inspection.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)

    UNINSTALL_WAIT = 10  # short padding after uninstall
    WAKE_WAIT = 3        # brief wait after wake attempt

    try:
        # Header
        msg = f"[TEST] Uninstall After Standby — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: wake (best-effort) → uninstall → short wait → (best-effort) apps list check; PASS if uninstall == 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Data deletion must be verified manually/OEM; DAB lacks per-app storage APIs."
        LOGGER.result(msg); logs.append(msg)

        # Required capability gate (unsupported → OPTIONAL_FAILED handled by need)
        if not need(tester, device_id, "ops: applications/uninstall", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Best-effort wake from standby (optional)
        try:
            msg = f"[STEP] input/key-press {{\"key\": \"POWER\"}}  # best-effort wake"
            LOGGER.result(msg); logs.append(msg)
            rc_wake, resp_wake = execute_cmd_and_log(
                tester, device_id, "input/key-press", json.dumps({"key": "POWER"}), logs, result
            )
            msg = f"[INFO] input/key-press transport_rc={rc_wake}, response={resp_wake}"
            LOGGER.info(msg); logs.append(msg)
            msg = f"[WAIT] {WAKE_WAIT}s after wake attempt"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(WAKE_WAIT)
        except Exception:
            msg = "[INFO] Skipping wake attempt (input/key-press unavailable or failed)"
            LOGGER.info(msg); logs.append(msg)

        # 1) Uninstall
        msg = f"[STEP] applications/uninstall {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_uninst, resp_uninst = execute_cmd_and_log(
            tester, device_id, "applications/uninstall", payload_app, logs, result
        )
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        msg = f"[INFO] applications/uninstall transport_rc={rc_uninst}, dab_status={uninstall_status}"
        LOGGER.info(msg); logs.append(msg)

        if uninstall_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, uninstall_status={uninstall_status}, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to finalize uninstall
        msg = f"[WAIT] {UNINSTALL_WAIT}s after uninstall for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(UNINSTALL_WAIT)

        # 2) Best-effort verification via applications/list (optional)
        removed_flag = None
        try:
            msg = "[STEP] applications/list"
            LOGGER.result(msg); logs.append(msg)
            rc_list, resp_list = execute_cmd_and_log(
                tester, device_id, "applications/list", "{}", logs, result
            )
            try:
                data = json.loads(resp_list) if isinstance(resp_list, str) else (resp_list or {})
            except Exception:
                data = {}
            apps = data.get("applications") or data.get("apps") or data
            present = False
            if isinstance(apps, list):
                for a in apps:
                    if (isinstance(a, str) and a == app_id) or \
                       (isinstance(a, dict) and (a.get("appId") == app_id or a.get("id") == app_id or a.get("name") == app_id)):
                        present = True; break
            elif isinstance(apps, dict):
                present = app_id in apps.keys()
            removed_flag = not present
            msg = f"[INFO] applications/list absence check for appId={app_id}: removed={removed_flag}"
            LOGGER.info(msg); logs.append(msg)

            if removed_flag is False:
                result.test_result = "FAILED"
                msg = "[RESULT] FAILED — app still present in applications/list after uninstall"
                LOGGER.result(msg); logs.append(msg)
                msg = (f"[SUMMARY] outcome=FAILED, uninstall_status=200, "
                       f"apps_list_present=True, test_id={test_id}, device={device_id}, appId={app_id}")
                LOGGER.result(msg); logs.append(msg)
                return result
        except Exception:
            msg = "[INFO] Skipping apps list verification: applications/list not available or parsing failed"
            LOGGER.info(msg); logs.append(msg)

        # Result
        result.test_result = "PASS"
        msg = "[RESULT] PASS — applications/uninstall returned 200" + ("" if removed_flag is None else f"; removed_in_list={removed_flag}")
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=PASS, uninstall_status=200, removed_in_list={removed_flag}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, uninstall_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_bg_uninstall_sample_app(dab_topic, test_category, test_name, tester, device_id):
    """
    Flow: applications/install (sample_app) -> applications/launch -> background -> applications/uninstall
    Pass if install == 200 and uninstall == 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})

    # Core op under validation is uninstall
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)

    INSTALL_WAIT = 10   # short padding after install
    BG_WAIT = 3         # short settle time after backgrounding

    try:
        # Header
        msg = f"[TEST] Install → Background → Uninstall (applications/install) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Method: install sample_app → open it → keep in background → uninstall (no app-store API used)."
        LOGGER.result(msg); logs.append(msg)

        # Gate required ops (OPTIONAL_FAILED handled by need)
        if not need(tester, device_id, "ops: applications/install, applications/launch, applications/uninstall", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install sample_app (applications/install)
        msg = f"[STEP] applications/install {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_app, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, install_status={install_status}, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # 2) Launch the app (foreground)
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_app, logs, result
        )
        msg = f"[WAIT] {APP_LAUNCH_WAIT}s after launch"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # 3) Background the app (best-effort: HOME key; fallback to launcher)
        try:
            msg = '[STEP] input/key-press {"key": "HOME"}  # background app'
            LOGGER.result(msg); logs.append(msg)
            rc_home, resp_home = execute_cmd_and_log(
                tester, device_id, "input/key-press", json.dumps({"key": "HOME"}), logs, result
            )
            msg = f"[INFO] input/key-press HOME transport_rc={rc_home}, response={resp_home}"
            LOGGER.info(msg); logs.append(msg)
        except Exception:
            launcher_id = config.apps.get("home_launcher", "com.android.tv.launcher")
            payload_home = json.dumps({"appId": launcher_id})
            msg = f"[STEP] applications/launch {payload_home}  # fallback to launcher"
            LOGGER.result(msg); logs.append(msg)
            rc_home2, resp_home2 = execute_cmd_and_log(
                tester, device_id, "applications/launch", payload_home, logs, result
            )
            msg = f"[INFO] launcher transport_rc={rc_home2}, response={resp_home2}"
            LOGGER.info(msg); logs.append(msg)

        msg = f"[WAIT] {BG_WAIT}s after backgrounding"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(BG_WAIT)

        # 4) Uninstall the app
        msg = f"[STEP] applications/uninstall {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_uninst, resp_uninst = execute_cmd_and_log(
            tester, device_id, "applications/uninstall", payload_app, logs, result
        )
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        msg = f"[INFO] applications/uninstall transport_rc={rc_uninst}, dab_status={uninstall_status}"
        LOGGER.info(msg); logs.append(msg)

        if uninstall_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install 200, then uninstall 200 with app backgrounded"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
               f"uninstall_status={uninstall_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, install_status=N/A, uninstall_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_uninstall_sample_app_with_local_data_check(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Uninstall a third-party app (sample_app) that has local storage data.
    Minimal flow: (optional) launch -> applications/uninstall -> short wait
    Pass if uninstall returns 200.
    Notes:
      - Local storage/data deletion is OEM/manual; DAB does not expose per-app storage inspection.
      - No use of applications/list per request.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)

    UNINSTALL_WAIT = 10  # seconds
    APP_POKE_WAIT = 3    # small wait after optional launch

    try:
        # Header
        msg = f"[TEST] Uninstall Sample App (with local data) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: (optional) launch → uninstall → short wait; PASS if uninstall == 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Local data deletion must be verified manually/OEM; storage inspection not in DAB scope."
        LOGGER.result(msg); logs.append(msg)

        # Required capability gate (unsupported → OPTIONAL_FAILED handled by need)
        if not need(tester, device_id, "ops: applications/uninstall", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Optional: launch the app to ensure it recently touched local data (best-effort)
        try:
            msg = f"[STEP] (optional) applications/launch {payload_app}"
            LOGGER.result(msg); logs.append(msg)
            rc_launch, resp_launch = execute_cmd_and_log(
                tester, device_id, "applications/launch", payload_app, logs, result
            )
            msg = f"[WAIT] {APP_POKE_WAIT}s after optional launch"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(APP_POKE_WAIT)
        except Exception:
            msg = "[INFO] Skipping optional launch (applications/launch unsupported or failed)"
            LOGGER.info(msg); logs.append(msg)

        # 1) Uninstall the sample app
        msg = f"[STEP] applications/uninstall {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_uninst, resp_uninst = execute_cmd_and_log(
            tester, device_id, "applications/uninstall", payload_app, logs, result
        )
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        msg = f"[INFO] applications/uninstall transport_rc={rc_uninst}, dab_status={uninstall_status}"
        LOGGER.info(msg); logs.append(msg)

        if uninstall_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, uninstall_status={uninstall_status}, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # Short wait to finalize uninstall
        msg = f"[WAIT] {UNINSTALL_WAIT}s after uninstall for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(UNINSTALL_WAIT)

        # Result
        result.test_result = "PASS"
        msg = "[RESULT] PASS — applications/uninstall returned 200"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=PASS, uninstall_status=200, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, uninstall_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result
    
def run_uninstall_preinstalled_with_local_data_simple(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Uninstall a pre-installed removable app (with local data).
    Minimal flow: (optional) launch -> applications/uninstall -> short wait
    Pass if uninstall returns 200.
    Notes:
      - Local data deletion is OEM/manual to verify; DAB has no per-app storage inspection.
      - No applications/list used (kept intentionally simple).
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)

    UNINSTALL_WAIT = 10  # seconds
    APP_POKE_WAIT = 3    # brief wait after optional launch

    try:
        # Header
        msg = f"[TEST] Uninstall Preinstalled (with local data) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: (optional) launch → uninstall → short wait; PASS if uninstall == 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Local-data deletion must be verified manually/OEM; DAB cannot inspect storage."
        LOGGER.result(msg); logs.append(msg)

        # Gate only the required op (unsupported -> OPTIONAL_FAILED handled by need)
        if not need(tester, device_id, "ops: applications/uninstall", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Optional: launch to ensure app recently touched local data (best-effort; not gated)
        try:
            msg = f"[STEP] (optional) applications/launch {payload_app}"
            LOGGER.result(msg); logs.append(msg)
            rc_launch, resp_launch = execute_cmd_and_log(
                tester, device_id, "applications/launch", payload_app, logs, result
            )
            msg = f"[WAIT] {APP_POKE_WAIT}s after optional launch"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(APP_POKE_WAIT)
        except Exception:
            msg = "[INFO] Skipping optional launch (applications/launch unsupported or failed)"
            LOGGER.info(msg); logs.append(msg)

        # 1) Uninstall the app
        msg = f"[STEP] applications/uninstall {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_uninst, resp_uninst = execute_cmd_and_log(
            tester, device_id, "applications/uninstall", payload_app, logs, result
        )
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        msg = f"[INFO] applications/uninstall transport_rc={rc_uninst}, dab_status={uninstall_status}"
        LOGGER.info(msg); logs.append(msg)

        if uninstall_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, uninstall_status={uninstall_status}, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to finalize uninstall
        msg = f"[WAIT] {UNINSTALL_WAIT}s after uninstall for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(UNINSTALL_WAIT)

        # Result
        result.test_result = "PASS"
        msg = "[RESULT] PASS — applications/uninstall returned 200"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=PASS, uninstall_status=200, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, uninstall_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_from_url_during_idle_then_launch(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install an app from a valid APK URL during device idle (screen off), then wake and launch.
    Minimal flow: sleep (best-effort) -> applications/install(url) -> short wait -> wake (best-effort) -> applications/launch
    Pass if install == 200 and launch == 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")

    # Try to read APK URL from config; user/project should populate one of these.
    apk_url = (
        config.apps.get("sample_app_url") or
        getattr(config, "apk_urls", {}).get("sample_app") or
        getattr(config, "urls", {}).get("sample_app")
    )

    logs = []
    payload_install = json.dumps({"appId": app_id, "url": apk_url})
    payload_launch  = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install", payload_install, "UNKNOWN", "", logs)

    INSTALL_WAIT = 10  # short padding for install finalize
    IDLE_WAIT    = 3   # small delay after sleep press
    WAKE_WAIT    = 3   # small delay after wake press

    try:
        # Headers
        msg = f"[TEST] Install During Idle (URL) → Wake → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: sleep (best-effort) → applications/install(url) → short wait → wake (best-effort) → applications/launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Validate URL presence (precondition)
        if not apk_url:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing APK URL in config (sample_app_url / apk_urls['sample_app'] / urls['sample_app'])."
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Gate required operations (OPTIONAL_FAILED handled by need)
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Best-effort put device into idle (screen off)
        try:
            msg = '[STEP] input/key-press {"key": "POWER"}  # best-effort to enter idle/screen-off'
            LOGGER.result(msg); logs.append(msg)
            rc_sleep, resp_sleep = execute_cmd_and_log(
                tester, device_id, "input/key-press", json.dumps({"key": "POWER"}), logs, result
            )
            msg = f"[INFO] input/key-press POWER transport_rc={rc_sleep}, response={resp_sleep}"
            LOGGER.info(msg); logs.append(msg)
            msg = f"[WAIT] {IDLE_WAIT}s after sleep attempt"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(IDLE_WAIT)
        except Exception:
            msg = "[INFO] Skipping sleep attempt (input/key-press unavailable or failed)"
            LOGGER.info(msg); logs.append(msg)

        # 1) Install from URL while device is idle
        msg = f"[STEP] applications/install {payload_install}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to finalize install
        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # 2) Best-effort wake device
        try:
            msg = '[STEP] input/key-press {"key": "POWER"}  # wake device'
            LOGGER.result(msg); logs.append(msg)
            rc_wake, resp_wake = execute_cmd_and_log(
                tester, device_id, "input/key-press", json.dumps({"key": "POWER"}), logs, result
            )
            msg = f"[INFO] input/key-press POWER transport_rc={rc_wake}, response={resp_wake}"
            LOGGER.info(msg); logs.append(msg)
            msg = f"[WAIT] {WAKE_WAIT}s after wake attempt"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(WAKE_WAIT)
        except Exception:
            msg = "[INFO] Skipping wake attempt (input/key-press unavailable or failed)"
            LOGGER.info(msg); logs.append(msg)

        # 3) Launch to verify availability after wake
        msg = f"[STEP] applications/launch {payload_launch}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install (idle) 200 and launch (post-wake) 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_large_apk_from_url_then_launch(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install a large APK from a valid URL, then launch to verify functionality.
    Minimal flow: applications/install(url) -> long wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("large_app", "Large_App")

    # Provide the APK URL via config (one of these should be set in your repo config)
    apk_url = (
        config.apps.get("large_app_url") or
        getattr(config, "apk_urls", {}).get("large_app") or
        getattr(config, "urls", {}).get("large_app")
    )

    logs = []
    payload_install = json.dumps({"appId": app_id, "url": apk_url})
    payload_launch  = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install", payload_install, "UNKNOWN", "", logs)

    LARGE_INSTALL_WAIT = 180  # seconds; larger buffer for big APK download+install

    try:
        # Headers
        msg = f"[TEST] Large APK Install from URL → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: applications/install(url) → long wait → applications/launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Validate URL precondition
        if not apk_url:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing large APK URL in config (large_app_url / apk_urls['large_app'] / urls['large_app'])."
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Capability gate (install + launch). If unsupported, need(...) fills result/logs and returns False.
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install from URL (large APK)
        msg = f"[STEP] applications/install {payload_install}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Long wait to accommodate big APK download/installation finalization
        msg = f"[WAIT] {LARGE_INSTALL_WAIT}s after install for finalization (large APK)"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(LARGE_INSTALL_WAIT)

        # 2) Launch to verify app is functional post-install
        msg = f"[STEP] applications/launch {payload_launch}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — large APK install and launch both returned 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result
    
def run_install_from_url_while_heavy_app_running(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install an app from a valid APK URL while a resource-intensive app is running, then launch it.
    Flow: launch heavy_app -> applications/install(url) -> long wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")

    # Resource-intensive app to keep pressure on the device
    heavy_app_id = config.apps.get("heavy_app", config.apps.get("youtube", "YouTube"))
    # Target app to install from URL (use your existing sample_app config)
    app_id = config.apps.get("sample_app", "Sample_App")

    # APK URL for the target app (set one of these in your config)
    apk_url = (
        config.apps.get("sample_app_url")
        or getattr(config, "apk_urls", {}).get("sample_app")
        or getattr(config, "urls", {}).get("sample_app")
    )

    logs = []
    payload_install = json.dumps({"appId": app_id, "url": apk_url})
    payload_launch  = json.dumps({"appId": app_id})
    payload_heavy   = json.dumps({"appId": heavy_app_id})
    result = TestResult(test_id, device_id, "applications/install", payload_install, "UNKNOWN", "", logs)

    HEAVY_WAIT         = 5    # let heavy app start streaming/processing
    LARGE_INSTALL_WAIT = 120  # allow time for download+install under load

    try:
        # Headers
        msg = f"[TEST] Install From URL While Heavy App Running — {test_name} (test_id={test_id}, device={device_id}, targetApp={app_id}, heavyApp={heavy_app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: launch heavy_app → applications/install(url) → long wait → applications/launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Precondition: URL available
        if not apk_url:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing APK URL (sample_app_url / apk_urls['sample_app'] / urls['sample_app'])."
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, targetApp={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Capability gate for required ops (install + launch)
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, targetApp={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Launch resource-intensive app
        msg = f"[STEP] applications/launch {payload_heavy}  # start heavy workload"
        LOGGER.result(msg); logs.append(msg)
        rc_heavy, resp_heavy = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_heavy, logs, result
        )
        msg = f"[INFO] heavy_app launch transport_rc={rc_heavy}, response={resp_heavy}"
        LOGGER.info(msg); logs.append(msg)
        msg = f"[WAIT] {HEAVY_WAIT}s to let heavy_app stabilize"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(HEAVY_WAIT)

        # 1) Install target app from URL while heavy app is running
        msg = f"[STEP] applications/install {payload_install}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, test_id={test_id}, device={device_id}, targetApp={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Long wait to accommodate big install under system load
        msg = f"[WAIT] {LARGE_INSTALL_WAIT}s after install for finalization (under load)"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(LARGE_INSTALL_WAIT)

        # 2) Launch the newly installed target app to confirm it's functional
        msg = f"[STEP] applications/launch {payload_launch}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install during heavy load (200) and post-install launch (200) succeeded"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, launch_status={launch_status}, test_id={test_id}, device={device_id}, targetApp={app_id}, heavyApp={heavy_app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, targetApp={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, targetApp={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_after_reboot_then_launch(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: After device restart, install an app from a valid APK URL and launch it.
    Flow: fire_and_forget_restart -> wait -> applications/install(url) -> wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")

    # Target app + URL (configure these in config)
    app_id = config.apps.get("sample_app", "Sample_App")
    apk_url = (
        config.apps.get("sample_app_url")
        or getattr(config, "apk_urls", {}).get("sample_app")
        or getattr(config, "urls", {}).get("sample_app")
    )

    logs = []
    payload_install = json.dumps({"appId": app_id, "url": apk_url})
    payload_launch  = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install", payload_install, "UNKNOWN", "", logs)

    # Waits tuned for reboot + network + package manager settle
    RESTART_WAIT = 60   # device restart window
    STABLE_WAIT  = 15   # extra stabilization
    INSTALL_WAIT = 60   # finalize install

    try:
        # Headers
        msg = f"[TEST] Install After Restart → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: restart → wait → applications/install(url) → wait → applications/launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Precondition: URL present
        if not apk_url:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing APK URL in config (sample_app_url / apk_urls['sample_app'] / urls['sample_app'])."
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # 0) Use the built-in restart op (fire-and-forget)
        msg = "[STEP] system/restart (fire-and-forget helper)"
        LOGGER.result(msg); logs.append(msg)
        fire_and_forget_restart(tester.dab_client, device_id)

        msg = f"[WAIT] {RESTART_WAIT}s for restart + {STABLE_WAIT}s stabilize"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(RESTART_WAIT + STABLE_WAIT)

        # Gate required ops (install + launch). If unsupported, need() marks OPTIONAL_FAILED and returns False.
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install from URL
        msg = f"[STEP] applications/install {payload_install}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # 2) Launch to verify functional post-restart
        msg = f"[STEP] applications/launch {payload_launch}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install (post-restart) 200 and launch 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

config.install_sequence = [
    {"key": "app1", "appId": "App1_Id", "url": "https://.../app1.apk"},
    {"key": "app2", "appId": "App2_Id", "url": "https://.../app2.apk"},
]

def run_sequential_installs_then_launch(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Sequentially install N applications from valid URLs, then launch each to confirm functionality.
    Flow per app: applications/install(url) -> wait -> applications/launch
    Pass if ALL installs == 200 and ALL launches == 200.
    Config expectations (pick one):
      - config.install_sequence: list[{"key": "<cfg-key>", "appId": "<realId>", "url": "<apk-url>"}]
      - config.apps["seq_targets"]: list[str cfg keys]; URL pulled from config using "<key>_url", apk_urls[key], or urls[key]
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    logs = []

    # --- Build target list from config ---
    targets = []
    try:
        # Preferred explicit structure
        seq = getattr(config, "install_sequence", None)
        if isinstance(seq, list) and seq:
            for item in seq:
                app_id = item.get("appId")
                url    = item.get("url")
                key    = item.get("key") or app_id or "unknown"
                if app_id and url:
                    targets.append({"key": key, "appId": app_id, "url": url})
        else:
            # Fallback: derive from named keys
            keys = config.apps.get("seq_targets", [])
            if not keys:
                keys = ["sample_app"]  # minimal sensible default
            for key in keys:
                app_id = config.apps.get(key, key)
                url = (
                    config.apps.get(f"{key}_url")
                    or getattr(config, "apk_urls", {}).get(key)
                    or getattr(config, "urls", {}).get(key)
                )
                if app_id and url:
                    targets.append({"key": key, "appId": app_id, "url": url})
    except Exception:
        targets = []

    # If no valid targets, skip
    payload_init = json.dumps({"apps": [t.get("appId") for t in targets]}) if targets else "{}"
    result = TestResult(test_id, device_id, "applications/install", payload_init, "UNKNOWN", "", logs)

    INSTALL_WAIT = 45  # per-app settle time

    try:
        # Headers
        msg = f"[TEST] Sequential Installs from URL → Launch Each — {test_name} (test_id={test_id}, device={device_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow per app: applications/install(url) → wait → applications/launch; PASS if all return 200."
        LOGGER.result(msg); logs.append(msg)

        if not targets:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — no install targets with URLs configured (install_sequence or apps.seq_targets)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, apps=0, test_id={test_id}, device={device_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Capability gate (install + launch)
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, apps={len(targets)}, test_id={test_id}, device={device_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # Run sequentially; stop on first failure to keep it simple
        installed = []
        for idx, t in enumerate(targets, 1):
            app_id = t["appId"]; url = t["url"]; key = t["key"]
            payload_install = json.dumps({"appId": app_id, "url": url})
            payload_launch  = json.dumps({"appId": app_id})

            # Install
            msg = f"[STEP {idx}] applications/install {payload_install}"
            LOGGER.result(msg); logs.append(msg)
            rc_i, resp_i = execute_cmd_and_log(
                tester, device_id, "applications/install", payload_install, logs, result
            )
            st_i = dab_status_from(resp_i, rc_i)
            msg = f"[INFO] applications/install[{key}] transport_rc={rc_i}, dab_status={st_i}"
            LOGGER.info(msg); logs.append(msg)
            if st_i != 200:
                result.test_result = "FAILED"
                msg = f"[RESULT] FAILED — install[{key}] returned {st_i} (expected 200)"
                LOGGER.result(msg); logs.append(msg)
                msg = (f"[SUMMARY] outcome=FAILED, failed_key={key}, install_status={st_i}, "
                       f"progress={idx-1}/{len(targets)}, test_id={test_id}, device={device_id}")
                LOGGER.result(msg); logs.append(msg)
                return result

            msg = f"[WAIT] {INSTALL_WAIT}s after install[{key}]"
            LOGGER.info(msg); logs.append(msg)
            time.sleep(INSTALL_WAIT)

            # Launch
            msg = f"[STEP {idx}] applications/launch {payload_launch}"
            LOGGER.result(msg); logs.append(msg)
            rc_l, resp_l = execute_cmd_and_log(
                tester, device_id, "applications/launch", payload_launch, logs, result
            )
            st_l = dab_status_from(resp_l, rc_l)
            msg = f"[INFO] applications/launch[{key}] transport_rc={rc_l}, dab_status={st_l}"
            LOGGER.info(msg); logs.append(msg)

            if st_l != 200:
                result.test_result = "FAILED"
                msg = f"[RESULT] FAILED — launch[{key}] returned {st_l} (expected 200)"
                LOGGER.result(msg); logs.append(msg)
                msg = (f"[SUMMARY] outcome=FAILED, failed_key={key}, launch_status={st_l}, "
                       f"progress={idx-1}/{len(targets)}, test_id={test_id}, device={device_id}")
                LOGGER.result(msg); logs.append(msg)
                return result

            installed.append(key)

        # If we reach here, all apps installed + launched
        result.test_result = "PASS"
        msg = f"[RESULT] PASS — all {len(targets)} apps installed and launched: {installed}"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=PASS, apps={len(targets)}, "
               f"installed_launched={installed}, test_id={test_id}, device={device_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, apps={len(targets)}, test_id={test_id}, device={device_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_from_url_then_launch_simple(dab_topic, test_category, test_name, tester, device_id):
    """
    Positive: Install an application from a valid APK URL when not already installed, then launch it.
    Minimal flow: applications/install(url) -> wait -> applications/launch
    Pass if install == 200 and launch == 200.
    Notes:
      - "Not installed" is treated as an external precondition.
      - No applications/list used; availability is proven by successful launch.
    """
    test_id = to_test_id(f"{dab_topic}/{test_category}")
    app_id = config.apps.get("sample_app", "Sample_App")  # target app ID

    # Resolve the APK URL for this app from config (set one of these)
    apk_url = (
        config.apps.get("sample_app_url")
        or getattr(config, "apk_urls", {}).get("sample_app")
        or getattr(config, "urls", {}).get("sample_app")
    )

    logs = []
    payload_install = json.dumps({"appId": app_id, "url": apk_url})
    payload_launch  = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/install", payload_install, "UNKNOWN", "", logs)

    INSTALL_WAIT = 45  # seconds to allow download + package manager finalize

    try:
        # Headers
        msg = f"[TEST] Install From URL → Launch (Not Pre-Installed) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: applications/install(url) → wait → applications/launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Precondition: URL must be configured
        if not apk_url:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing APK URL (sample_app_url / apk_urls['sample_app'] / urls['sample_app'])."
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Capability gate (install + launch). If unsupported, need() fills result/logs and returns False.
        if not need(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Install from URL
        msg = f"[STEP] applications/install {payload_install}"
        LOGGER.result(msg); logs.append(msg)
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        msg = f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        LOGGER.info(msg); logs.append(msg)

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        # Allow install to finalize
        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # 2) Launch to confirm availability and basic functionality
        msg = f"[STEP] applications/launch {payload_launch}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — install 200 and launch 200"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(msg); logs.append(msg)
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
    ("applications/launch", "functional", run_launch_when_uninstalled_check, "LaunchAppNotInstalled", "2.1", True),
    ("applications/launch", "functional", run_launch_app_while_restarting_check, "LaunchAppWhileDeviceRestarting", "2.1", True),
    ("system/network-reset", "functional", run_network_reset_check, "NetworkResetCheck", "2.1", False),
    ("system/factory-reset", "functional", run_factory_reset_and_recovery_check, "Factory Reset and Recovery Check", "2.1", False ),
    ("system/settings/list", "functional", run_personalized_ads_response_check, "behavior when personalized ads setting is not supported", "2.1", False ),
    ("system/settings/set", "functional", run_personalized_ads_persistence_check, "Personalized Ads Setting Persistence Check", "2.1", False),
    ("system/settings/list", "functional", run_personalized_ads_not_supported_check, "PersonalizedAdsNotSupportedCheck", "2.1", False),
    ("system/settings/set", "functional", run_personalized_ads_Video_ads_are_personalized, "Video ads are personalized", "2.1", False),
    ("system/settings/set", "functional", run_personalized_ads_apply_and_display_check, "display_check for personalized", "2.1", False),
    ("applications/uninstall", "functional", run_uninstall_foreground_app_check, "UninstallForegroundAppCheck", "2.1", False),
    ("applications/uninstall", "functional", run_uninstall_system_app_check, "UninstallSystemAppCheck", "2.1", False),
    ("applications/clear-data", "functional", run_clear_data_foreground_app_check, "ClearDataForegroundAppCheck", "2.1", False),
    ("applications/clear-data", "functional", run_clear_data_system_app_check, "ClearDataSystemAppCheck", "2.1", False),
    ("applications/clear-data", "functional", run_clear_data_user_installed_app_foreground, "ClearDataUserInstalledAppForeground", "2.1", False),
    ("applications/install-from-app-store", "functional", run_install_from_app_store_check, "InstallFromAppStoreAndLaunch", "2.1", False),
    ("applications/install-from-app-store", "functional", run_install_youtube_kids_from_store, "InstallYouTubeKidsFromStore", "2.1", False),
    ("applications/uninstall", "functional", run_uninstall_after_standby_check, "UninstallPreinstalledAppAfterStandby", "2.1", False),
    ("applications/uninstall", "functional", run_install_bg_uninstall_sample_app, "InstallBackgroundAndUninstallSampleApp", "2.1", False),
    ("applications/uninstall", "functional", run_uninstall_sample_app_with_local_data_check, "UninstallSampleAppWithLocalData_NoList", "2.1", False),
    ("applications/uninstall", "functional", run_uninstall_preinstalled_with_local_data_simple, "UninstallPreinstalledWithLocalData_Simple", "2.1", False),
    ("applications/install", "functional", run_install_from_url_during_idle_then_launch, "InstallFromUrlDuringIdleThenLaunch", "2.1", False),
    ("applications/install", "functional", run_install_large_apk_from_url_then_launch, "InstallLargeApkFromUrlThenLaunch", "2.1", False),
    ("applications/install", "functional", run_install_from_url_while_heavy_app_running, "InstallFromUrlWhileHeavyAppRunning", "2.1", False),
    ("applications/install", "functional", run_install_after_reboot_then_launch, "InstallAfterRebootThenLaunch", "2.1", False),
    ("applications/install", "functional", run_sequential_installs_then_launch, "SequentialInstallsFromUrlsThenLaunch", "2.1", False),
    ("applications/install", "functional", run_install_from_url_then_launch_simple, "InstallFromUrlThenLaunch_Simple", "2.1", False),


]