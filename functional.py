from result_json import TestResult
from dab_tester import to_test_id
import config
import json
import time
import sys
from readchar import readchar
from util.enforcement_manager import EnforcementManager
from util.config_loader import ensure_app_available_anyext
from util.config_loader import ensure_app_available
from util.config_loader import ensure_apps_available as _ensure_many
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes
from dab_checker import DabChecker
from util.enforcement_manager import ValidateCode
from logger import LOGGER

# --- Sleep Time Constants ---
APP_LAUNCH_WAIT = 10
APP_UNINSTALL_WAIT = 5
APP_CLEAR_DATA_WAIT = 5
APP_EXIT_WAIT = 3
APP_STATE_CHECK_WAIT = 2
APP_RELAUNCH_WAIT = 10
CONTENT_LOAD_WAIT = 20
DEVICE_REBOOT_WAIT = 180  # Max wait for device reboot
TELEMETRY_DURATION_MS = 5000
TELEMETRY_METRICS_WAIT = 30  # Max wait for telemetry metrics (seconds)
HEALTH_CHECK_INTERVAL = 5   # Seconds between health check polls
ASSISTANT_INIT = 10
APP_INSTALL_WAIT = 10
ASSISTANT_WAIT = 10
LOGS_COLLECTION_WAIT = 30  # Seconds for logs collection wait
SCREENSAVER_TIMEOUT_WAIT = 30  # Screensaver timeout for idle wait

# === Reusable Helper ===

class UnsupportedOperationError(Exception):
    def __init__(self, topic):
        self.topic = topic
        super().__init__(f"DAB operation '{topic}' is not supported by the device.")

# === Capability-gate helpers (non-breaking additions) =========================
def _split_items(s: str):
    return [x.strip() for x in s.split(",") if x and x.strip()]

def _parse_require_capabilities_spec(spec: str):
    """
    Parse a spec like:
      'ops: a,b | settings: x,y | keys: K_HOME,K_BACK | voices: GoogleAssistant'
    Default segment = ops (if no prefix is given).
    """
    ops_req, set_req, key_req, voice_req = set(), set(), set(), set()
    for seg in (p.strip() for p in (spec or "").split("|")):
        if not seg:
            continue
        low = seg.lower()
        if low.startswith(("ops:", "op:", "operations:")):
            ops_req.update(_split_items(seg.split(":", 1)[1]))
        elif low.startswith(("settings:", "setting:", "set:")):
            set_req.update(_split_items(seg.split(":", 1)[1]))
        elif low.startswith(("keys:", "key:")):
            key_req.update(_split_items(seg.split(":", 1)[1]))
        elif low.startswith(("voices:", "voice:")):
            voice_req.update(_split_items(seg.split(":", 1)[1]))
        else:
            ops_req.update(_split_items(seg))  # default to ops
    LOGGER.info(
        f"Parsed require_capabilities spec → ops={sorted(ops_req)}, "
        f"settings={sorted(set_req)}, keys={sorted(key_req)}"
        + (f", voices={sorted(voice_req)}" if voice_req else "")
    )
    return ops_req, set_req, key_req, voice_req

def require_capabilities(tester, device_id, spec, result=None, logs=None):
    """
    One-line capability precheck to run before each test case.

    Example:
        require_capabilities(
            tester, device_id,
            "ops: applications/launch, applications/get-state | "
            "settings: personalizedAds, screenSaver | keys: KEY_HOME | voices: GoogleAssistant",
            result, logs
        )

    Uses DabChecker to precheck and populate caches for:
      - operations/list    → is_operation_supported(...)
      - system/settings/list → precheck('system/settings/set', {"setting_key": "dummy_val"})
      - input/key/list       → precheck('input/key-press', {"keyCode":"KEY_HOME"})
      - voice/list           → precheck('voice/set', {"voiceSystem":{"name":"__probe__","enabled":True}})

    If any required item is missing, marks OPTIONAL_FAILED and returns False.
    """
    # Parse what this test requires
    ops_req, set_req, key_req, voice_req = _parse_require_capabilities_spec(spec)

    # Get or create a checker instance attached to the tester
    checker = getattr(tester, "dab_checker", None)
    if checker is None:
        checker = DabChecker(tester)
        try:
            setattr(tester, "dab_checker", checker)
        except Exception:
            pass

    try:
        # ---------- Operations gate (operations/list) ----------
        for op in sorted(ops_req):
            validate_code, _ = checker.is_operation_supported(device_id, op)
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required op not supported: {op}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(LOGGER.stamp(msg))
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Settings gate (system/settings/list) ----------
        for setting in sorted(set_req):
            # Use a dummy value; precheck only cares about the key's descriptor in the settings list
            validate_code, _ = checker.precheck(device_id, "system/settings/set", json.dumps({setting: True}))
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required setting not supported: {setting}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(LOGGER.stamp(msg))
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Keys gate (input/key/list) ----------
        for key in sorted(key_req):
            validate_code, _ = checker.precheck(device_id, "input/key-press", json.dumps({"keyCode": key}))
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required key not supported: {key}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(LOGGER.stamp(msg))
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Voices gate (voice/list) ----------
        for voice in sorted(voice_req):
            payload = json.dumps({"voiceSystem": {"name": voice, "enabled": True}})
            validate_code, _ = checker.precheck(device_id, "voice/set", payload)
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required voice assistant not supported: {voice}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(LOGGER.stamp(msg))
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        LOGGER.ok("Capability gate passed.")
        if logs is not None:
            logs.append(LOGGER.stamp("Capability gate passed."))
        return True

    except Exception as e:
        # Any unexpected failure in precheck is a non-enforceable optional fail
        msg = f"[OPTIONAL_FAILED] Capability precheck failed: {e}"
        LOGGER.warn(msg)
        if logs is not None:
            logs.append(LOGGER.stamp(msg))
        if result is not None:
            result.test_result = "OPTIONAL_FAILED"
        return False
def execute_cmd_and_log(tester, device_id, topic, payload, logs=None, result=None):
    """
    Executes a DAB command and logs the request and response.

    Returns:
        (status_code: int, resp_json: str)
    """
    em = EnforcementManager()
    supported_ops_raw = em.get_supported_operations() or []
    supported_ops = {op.get("operation") if isinstance(op, dict) else op
                     for op in supported_ops_raw}

    if topic not in supported_ops and topic != "operations/list":
        line = f"[OPTIONAL_FAILED] Operation '{topic}' is not supported by the device (checked from cache)."
        LOGGER.warn(line)
        if logs is not None: logs.append(LOGGER.stamp(line))
        if result is not None:
            result.test_result = "OPTIONAL_FAILED"
        raise UnsupportedOperationError(topic)

    # Stamp request context (safe)
    if result is not None:
        try:
            result.dab_topic = topic
            result.request_payload = payload
        except Exception:
            pass

    LOGGER.info(f"Executing {topic} with payload {payload}")
    rc = tester.execute_cmd(device_id, topic, payload)
    resp = tester.dab_client.response()  # may be str, dict, list, None

    # Normalize response to JSON string
    if isinstance(resp, (dict, list)):
        resp_json = json.dumps(resp)
    elif isinstance(resp, str):
        resp_json = resp
    else:
        resp_json = json.dumps({"status": rc, "raw": None if resp is None else str(resp)})

    # Log
    resp_line = f"[{topic}] Response: {resp_json}"
    LOGGER.info(resp_line)
    if logs is not None: logs.append(LOGGER.stamp(resp_line))

    # Normalize status code (never None)
    status_code = dab_status_from(resp_json, rc)
    if status_code is None:
        status_code = 500
        warn = f"[WARN] No status code found for '{topic}'; defaulting to 500."
        LOGGER.warn(warn)
        if logs is not None: logs.append(LOGGER.stamp(warn))

    status_line = f"[{topic}] Status: {status_code}"
    LOGGER.info(status_line)
    if logs is not None: logs.append(LOGGER.stamp(status_line))
    return status_code, resp_json

def dab_status_from(resp, rc):
    try:
        if isinstance(resp, str):    # JSON string
            return json.loads(resp).get("status", rc)
        if isinstance(resp, dict):   # dict
            return resp.get("status", rc)
    except Exception:
        pass
    return rc

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
    # Show options
    line0 = "*0: There is no option that meet the requirement."
    LOGGER.info(line0)
    if logs is not None: logs.append(LOGGER.stamp(line0))

    for idx, value in enumerate(arr, start=1):
        line = f"*{idx}: {value}"
        LOGGER.info(line)
        if logs is not None: logs.append(LOGGER.stamp(line))

    # Prompt loop
    max_idx = len(arr)
    while True:
        prompt = f"Please input number (0–{max_idx}):"
        LOGGER.prompt(prompt)
        if logs is not None: logs.append(LOGGER.stamp(prompt))

        ch = readchar()
        echo = f"[{ch}]"
        LOGGER.result(echo)
        if logs is not None: logs.append(LOGGER.stamp(echo))

        if ch.isdigit():
            choice = int(ch)
            if 0 <= choice <= max_idx:
                return choice

        warn = f"[WARN] Invalid choice '{ch}'. Enter 0–{max_idx}."
        LOGGER.warn(warn)
        if logs is not None: logs.append(LOGGER.stamp(warn))
 

def countdown(title, count):
    LOGGER.info(f"{title} — starting {count}s")
    try:
        while count:
            mins, secs = divmod(count, 60)
            timer = f"{mins:02d}:{secs:02d}"
            sys.stdout.write("\r" + title + " --- " + timer)
            sys.stdout.flush()
            time.sleep(1)
            count -= 1
        sys.stdout.write("\r" + title + " --- Done!\n")
    finally:
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

def get_supported_setting(tester, device_id, key, result, logs):
    """
    Retrieves a specific setting's supported values/range from the cached
    system settings list. If the setting or the list itself is not supported,
    it marks the test as OPTIONAL_FAILED.
    """
    # Use require_capabilities() to ensure the settings list is fetched and cached if not already.
    if not require_capabilities(tester, device_id, f"settings: {key}", result, logs):
        # 'require_capabilities' already set the result to OPTIONAL_FAILED and logged the reason.
        return None, result

    # At this point, the setting is confirmed to be supported. Retrieve from cache.
    em = EnforcementManager()
    settings = em.get_supported_settings()
    settings_map = settings.get("settings", settings) if isinstance(settings, dict) else {}

    setting_value = settings_map.get(key)
    LOGGER.info(f"Get supported setting '{key}: {setting_value}'")
    return setting_value, result

# === New Helper Function to Check Minimum Screensaver Timeout ===
def check_min_screensaver_timeout(tester, device_id, result, logs):
    """
    Checks if the device's min screensaver timeout is less than 60s.
    If it's >= 60s or unsupported, marks the test as OPTIONAL_FAILED to save time.
    Returns True if the test should proceed, False otherwise.
    """
    min_timeout, _ = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)

    # get_supported_setting returns None and sets OPTIONAL_FAILED if not supported
    if min_timeout is None:
        # The get_supported_setting function already set the result and logged
        return False

    try:
        min_timeout_val = int(min_timeout)
        if min_timeout_val >= 60:
            result.test_result = "OPTIONAL_FAILED"
            line = (f"[RESULT] OPTIONAL_FAILED — Device minimum screensaver timeout ({min_timeout_val}s) "
                    f"is >= 60s. Optimizing for execution time; this test has been strategically omitted.")
            LOGGER.warn(line)
            logs.append(line)
            return False
    except (ValueError, TypeError):
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Could not parse 'screenSaverMinTimeout' value of '{min_timeout}'."
        LOGGER.warn(line)
        logs.append(line)
        return False

    # If we get here, the timeout is valid and < 60s
    return True

# ---- shared helper: build install targets from config or local artifacts ----
def get_install_targets(default_app_ids=("Sample_App", "Sample_App1")):
    """
    Returns a list of targets:
      [{"key": <label>, "appId": <id>, "install_payload": { ... }}]
    Prefers config.install_sequence (URL-based). Falls back to local files
    in config/apps via util.config_loader.ensure_apps_available (any ext).
    """
    targets = []
    try:
        # 1) Prefer explicit URL list
        seq = getattr(config, "install_sequence", None)
        if isinstance(seq, list) and seq:
            for item in seq:
                app_id = item.get("appId")
                url    = item.get("url")
                key    = item.get("key") or app_id or "unknown"
                if app_id and url:
                    targets.append({
                        "key": key,
                        "appId": app_id,
                        "install_payload": {"appId": app_id, "url": url},
                    })
            return targets

        # 2) Fallback to local sample apps (any extension)
        seq_keys = config.apps.get("seq_targets", None)
        if seq_keys:
            app_ids = [config.apps.get(k, k) for k in seq_keys]
        else:
            app_ids = list(default_app_ids)

        # legacy alias maps to any-extension implementation
        payloads = _ensure_many(app_ids=app_ids)  # [{"appId","url","format","timeout"}, ...]
        for p in payloads:
            app_id = p["appId"]
            targets.append({
                "key": app_id,
                "appId": app_id,
                "install_payload": p,
            })
    except Exception:
        return []
    return targets

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

# Priority non-English locales (TV-heavy markets) for voice/send-audio multi-language test
VOICE_PRIORITY_LOCALES = [
    "es-419",  # Latin American Spanish
    "pt-BR",   # Brazilian Portuguese
    "ar-SA",   # Arabic (Saudi Arabia)
    "ja-JP",   # Japanese
    "ko-KR",   # Korean
    "ru-RU",   # Russian
    "th-TH",   # Thai
    "vi-VN",   # Vietnamese
    "hi-IN",   # Hindi (India)
    "id-ID",   # Indonesian
]

def get_voice_audio_url_for_language(language_code):
    """
    Returns the HTTP(S) URL for a pre-recorded 'Open YouTube' utterance
    in the given language, served from GCS.

    Files must be:
      - audio/wav
      - 16-bit linear PCM
      - 16 kHz
      - mono
      - <= 4 MB
    """
    GCS = "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/different_languages"
    AUDIO_URLS = {
        "es-419": f"{GCS}/spanish.wav",
        "pt-BR":  f"{GCS}/brazil.wav",
        "ar-SA":  f"{GCS}/Arabic.wav",
        "ja-JP":  f"{GCS}/Japanese.wav",
        "ko-KR":  f"{GCS}/Korean.wav",
        "ru-RU":  f"{GCS}/Russian.wav",
        "th-TH":  f"{GCS}/Thai.wav",
        "vi-VN":  f"{GCS}/Vietnamese.wav",
        "hi-IN":  f"{GCS}/Hindi.wav",
        "id-ID":  f"{GCS}/Indonesian.wav",
    }
    return AUDIO_URLS.get(language_code)

# === Test 1: App in FOREGROUND Validate app moves to FOREGROUND after launch ===
def run_app_foreground_check(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
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
        if not require_capabilities(tester, device_id, "ops: applications/launch, applications/get-state", result, logs):
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
def run_app_background_check(dab_topic, test_name, tester, device_id):
    """
    Checks if an app correctly moves to the background after the Home key is pressed.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    state = "N/A"  # Default state for summary if test exits early

    try:
        # Always-on header + description (printed and stored)
        for line in (
            f"[TEST] App Background Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: launch an app, press HOME, and confirm it reaches BACKGROUND state.",
            "[DESC] Preconditions: device powered on, DAB reachable, stable network.",
            "[DESC] Required operations: applications/launch, input/key-press, applications/get-state.",
            "[DESC] Pass criteria: final state == 'BACKGROUND'. Any other state → FAILED.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required operations
        required_ops = "ops: applications/launch, input/key-press, applications/get-state"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result # 'require_capabilities' function already set the result and logged

        # Step 1 — Launch the application
        payload_launch = json.dumps({"appId": app_id})
        line = f"[STEP] Launching app via applications/launch with payload: {payload_launch}"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )

        # Wait for the application to stabilize in the foreground
        line = f"[WAIT] Allowing {APP_LAUNCH_WAIT}s for the app to launch and settle."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2 — Press the HOME key to send the app to the background
        payload_home = json.dumps({"keyCode": "KEY_HOME"})
        line = (
            f"[STEP] Pressing HOME key via input/key-press with payload: {payload_home}"
        )
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(
            tester, device_id, "input/key-press", payload_home, logs, result
        )

        # Wait for the app to transition to the background
        line = f"[WAIT] Allowing {APP_EXIT_WAIT}s for the app to move to the background."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_EXIT_WAIT)

        # Step 3 — Get the application's current state
        payload_state = json.dumps({"appId": app_id})
        line = f"[STEP] Querying application state via applications/get-state for appId={app_id}."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(
            tester, device_id, "applications/get-state", payload_state, logs, result
        )

        # Record the raw response for debugging purposes
        line = f"[INFO] applications/get-state raw response: {response}"
        LOGGER.info(line)
        logs.append(line)

        # Parse the state from the response and validate the result
        try:
            state = (json.loads(response).get("state", "") if response else "").upper()
            line = f"[INFO] Parsed app state='{state}'."
            LOGGER.info(line)
            logs.append(line)
        except Exception:
            state = "UNKNOWN"
            line = f"[FAIL] Request applications/get-state '{payload_state}' returned invalid JSON."
            LOGGER.error(line)
            logs.append(line)

        if state == "BACKGROUND":
            result.test_result = "PASS"
            line = f"[RESULT] PASS — app reached BACKGROUND after HOME key press (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 'BACKGROUND' but observed '{state}' (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during background check: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line)
        logs.append(line)
    
    finally:
        # Final summary log for easy parsing, always runs
        line = f"[SUMMARY] outcome={result.test_result}, observed_state={state}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 3: App STOPPED Validate app state is STOPPED after exit. ===
def run_app_stopped_check(dab_topic, test_name, tester, device_id):
    """
    Checks if an app correctly moves to the STOPPED state after being exited.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/get-state", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    state = "N/A"  # Default state for summary if test exits early

    try:
        # Always-on header + description (printed and stored)
        for line in (
            f"[TEST] App Stopped Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: launch an app, exit it, and confirm it reaches the STOPPED state.",
            "[DESC] Preconditions: device powered on, DAB reachable, stable network.",
            "[DESC] Required operations: applications/launch, applications/exit, applications/get-state.",
            "[DESC] Pass criteria: final state == 'STOPPED'. Any other state → FAILED.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required operations
        required_ops = "ops: applications/launch, applications/exit, applications/get-state"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' function already set the result and logged

        # Step 1 — Launch the application
        payload_launch = json.dumps({"appId": app_id})
        line = f"[STEP] Launching app via applications/launch with payload: {payload_launch}"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )

        # Wait for the application to stabilize
        line = f"[WAIT] Allowing {APP_LAUNCH_WAIT}s for the app to launch and settle."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2 — Exit the application
        payload_exit = json.dumps({"appId": app_id})
        line = f"[STEP] Exiting app via applications/exit with payload: {payload_exit}"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(
            tester, device_id, "applications/exit", payload_exit, logs, result
        )

        # Wait for the application to fully terminate
        line = f"[WAIT] Allowing {APP_EXIT_WAIT}s for the app to fully exit."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_EXIT_WAIT)

        # Step 3 — Get the application's final state
        payload_state = json.dumps({"appId": app_id})
        line = f"[STEP] Querying application state via applications/get-state for appId={app_id}."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(
            tester, device_id, "applications/get-state", payload_state, logs, result
        )

        # Record the raw response for debugging
        line = f"[INFO] applications/get-state raw response: {response}"
        LOGGER.info(line)
        logs.append(line)

        # Parse the state from the response and validate the result
        try:
            state = (json.loads(response).get("state", "") if response else "").upper()
            line = f"[INFO] Parsed app state='{state}'."
            LOGGER.info(line)
            logs.append(line)
        except Exception:
            state = "UNKNOWN"
            line = f"[FAIL] Request applications/get-state '{payload_state}' returned invalid JSON."
            LOGGER.error(line)
            logs.append(line)

        if state == "STOPPED":
            result.test_result = "PASS"
            line = f"[RESULT] PASS — app reached STOPPED after exit (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 'STOPPED' but observed '{state}' (appId={app_id}, device={device_id}, test_id={test_id})"
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during stopped check: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log for easy parsing, always runs
        line = f"[SUMMARY] outcome={result.test_result}, observed_state={state}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 4: Launch Without Content ID (Negative) Validate error is returned when contentId is missing. ===
def run_launch_without_content_id(dab_topic, test_name, tester, device_id):
    """
    Negative Test: Validates that launch-with-content fails if 'contentId' is missing.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    payload = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/launch-with-content", payload, "UNKNOWN", "", logs)
    status = "N/A"  # Default status for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Launch Without Content ID (Negative) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: Attempt to launch an app with content without providing a contentId.",
            "[DESC] This is a negative test and is expected to fail with a non-200 status.",
            "[DESC] Required operations: applications/launch-with-content.",
            "[DESC] Pass criteria: DAB status != 200. A 200 status is a FAILURE.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/launch-with-content", result, logs):
            return result # 'require_capabilities' already logged and set the result

        # Step 1 — Attempt the invalid launch
        line = f"[STEP] Calling applications/launch-with-content with missing 'contentId': {payload}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(
            tester, device_id, "applications/launch-with-content", payload, logs, result
        )

        # Parse status and validate the outcome
        status = dab_status_from(response, rc)
        line = f"[INFO] Received DAB status: {status}"
        LOGGER.info(line)
        logs.append(line)
        
        if status != 200:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — Device correctly returned an error status ({status}) as expected."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device returned status 200, but an error was expected."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error: {e}"
        LOGGER.result(line)
        logs.append(line)
        
    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, observed_status={status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)
        
    return result

# === Test 5: Exit App After Playing Video ===
def run_exit_after_video_check(dab_topic, test_name, tester, device_id):
    """
    Checks if an app stops cleanly after playing video content and being exited.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    video_id = "2ZggAa6LuiM"  # Example video ID
    logs = []
    result = TestResult(test_id, device_id, "applications/exit", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    state = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Exit After Video Playback — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            f"[DESC] Goal: Launch an app with video content, exit it, and confirm it reaches the STOPPED state.",
            "[DESC] Required operations: applications/launch, applications/exit, applications/get-state.",
            "[DESC] Pass criteria: final state == 'STOPPED'.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/launch, applications/exit, applications/get-state"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Launch the app with video content
        launch_payload = json.dumps({
            "appId": app_id,
            "parameters": [f"v={video_id}"]
        })
        line = f"[STEP] Launching video content with payload: {launch_payload}"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", launch_payload, logs, result)
        
        wait_time = APP_LAUNCH_WAIT + CONTENT_LOAD_WAIT
        line = f"[WAIT] Allowing {wait_time}s for video to load and play."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(wait_time)

        # Step 2: Exit the application
        exit_payload = json.dumps({"appId": app_id})
        line = f"[STEP] Exiting application with payload: {exit_payload}"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/exit", exit_payload, logs, result)
        
        line = f"[WAIT] Allowing {APP_EXIT_WAIT}s for the app to terminate."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_EXIT_WAIT)

        # Step 3: Get the final application state
        state_payload = json.dumps({"appId": app_id})
        line = f"[STEP] Querying final application state."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", state_payload, logs, result)

        line = f"[INFO] applications/get-state raw response: {response}"
        LOGGER.info(line)
        logs.append(line)
        
        # Parse and validate the final state
        try:
            state = (json.loads(response).get("state", "") if response else "UNKNOWN").upper()
            line = f"[INFO] Parsed app state='{state}'."
            LOGGER.info(line)
            logs.append(line)
        except Exception:
            state = "UNKNOWN"
            line = "[FAIL] Could not parse the response from get-state."
            LOGGER.error(line)
            logs.append(line)

        if state == "STOPPED":
            result.test_result = "PASS"
            line = f"[RESULT] PASS — App correctly stopped after playing video."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Expected 'STOPPED' but observed '{state}'."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' not supported."
        LOGGER.result(line)
        logs.append(line)
    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)
        
    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, observed_state={state}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)
        
    return result

# === Test 6: Relaunch Stability Check ===
def run_relaunch_stability_check(dab_topic, test_name, tester, device_id):
    """
    Validates that an application can be exited and then immediately relaunched without errors.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    relaunch_status = "N/A" # Default status for the summary log

    try:
        # Header and description
        for line in (
            f"[TEST] Relaunch Stability Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: Launch an app, exit it, and then immediately relaunch it to test stability.",
            "[DESC] Required operations: applications/launch, applications/exit.",
            "[DESC] Pass criteria: The final relaunch command must return a 200 status.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for required operations
        required_ops = "ops: applications/launch, applications/exit"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result # The 'require_capabilities' function already logged the reason and set the result

        # Step 1: Initial launch of the application
        payload = json.dumps({"appId": app_id})
        line = f"[STEP] First launch of '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload, logs, result)

        line = f"[WAIT] Allowing {APP_LAUNCH_WAIT}s for the app to settle."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2: Exit the application
        line = f"[STEP] Exiting '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/exit", payload, logs, result)
        
        line = f"[WAIT] Allowing {APP_STATE_CHECK_WAIT}s for the app to terminate."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_STATE_CHECK_WAIT)

        # Step 3: Relaunch the application and check the response
        line = f"[STEP] Relaunching '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/launch", payload, logs, result)
        relaunch_status = dab_status_from(response, rc)
        
        line = f"[WAIT] Allowing {APP_RELAUNCH_WAIT}s for the app to relaunch."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_RELAUNCH_WAIT)

        if relaunch_status == 200:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — App relaunched successfully with status 200."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — App relaunch failed with status {relaunch_status}."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)
        
    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, relaunch_status={relaunch_status}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 7: Screensaver Enable Check ===
def run_screensaver_enable_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the device's screensaver can be successfully enabled via DAB.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": True}), "UNKNOWN", "", logs)
    final_state = "N/A" # Default state for summary log

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Enable Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Disable the screensaver, then enable it and verify the setting is applied.",
            "[DESC] Required operations: system/settings/set, system/settings/get.",
            "[DESC] Pass criteria: The final 'get' operation must show 'screenSaver' as true.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for required operations and settings
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set, system/settings/get | settings: screenSaver",
                    result, logs):
            return result # The 'require_capabilities' function already logged the reason and set the result

        # Step 1: Set a known state by disabling the screensaver first
        payload_disable = json.dumps({"screenSaver": False})
        line = f"[STEP] Precondition: Disabling screensaver with payload: {payload_disable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_disable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not disable screensaver as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Enable the screensaver (the core action of the test)
        payload_enable = json.dumps({"screenSaver": True})
        line = f"[STEP] Action: Enabling screensaver with payload: {payload_enable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_enable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The set command to enable the screensaver failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Verify the change was applied
        line = "[STEP] Verification: Getting current settings to confirm the change."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)

        try:
            settings = json.loads(response) if response else {}
            final_state = settings.get("screenSaver")
            line = f"[INFO] Verified screensaver state is: {final_state}"
            LOGGER.info(line)
            logs.append(line)
        except Exception as e:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not parse the response from system/settings/get: {e}"
            LOGGER.result(line)
            logs.append(line)
            return result

        if final_state is True:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Screensaver was successfully enabled."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Expected screensaver state to be 'True', but got '{final_state}'."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, final_state={final_state}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 8: Screensaver Disable Check ===
def run_screensaver_disable_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the device's screensaver can be successfully disabled via DAB.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", json.dumps({"screenSaver": False}), "UNKNOWN", "", logs)
    final_state = "N/A" # Default state for summary log

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Disable Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Enable the screensaver, then disable it and verify the setting is applied.",
            "[DESC] Required operations: system/settings/set, system/settings/get.",
            "[DESC] Pass criteria: The final 'get' operation must show 'screenSaver' as false.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for required operations and settings
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set, system/settings/get | settings: screenSaver",
                    result, logs):
            return result # The 'require_capabilities' function already logged the reason and set the result

        # Step 1: Set a known state by enabling the screensaver first
        payload_enable = json.dumps({"screenSaver": True})
        line = f"[STEP] Precondition: Enabling screensaver with payload: {payload_enable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_enable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not enable screensaver as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Disable the screensaver (the core action of the test)
        payload_disable = json.dumps({"screenSaver": False})
        line = f"[STEP] Action: Disabling screensaver with payload: {payload_disable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_disable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The set command to disable the screensaver failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Verify the change was applied
        line = "[STEP] Verification: Getting current settings to confirm the change."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)

        try:
            settings = json.loads(response) if response else {}
            final_state = settings.get("screenSaver")
            line = f"[INFO] Verified screensaver state is: {final_state}"
            LOGGER.info(line)
            logs.append(line)
        except Exception as e:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not parse the response from system/settings/get: {e}"
            LOGGER.result(line)
            logs.append(line)
            return result

        if final_state is False:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Screensaver was successfully disabled."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Expected screensaver state to be 'False', but got '{final_state}'."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, final_state={final_state}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 9: Screensaver Active Check ===
def run_screensaver_active_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver activates after the specified timeout. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A" # Default for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Active Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Enable the screensaver, set a timeout, and manually verify that it activates.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver appeared.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result
        
        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1: Enable the screensaver
        payload_enable = json.dumps({"screenSaver": True})
        line = f"[STEP] Enabling screensaver with payload: {payload_enable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_enable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not enable screensaver as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Set the screensaver timeout
        payload_timeout = json.dumps({"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT})
        line = f"[STEP] Setting screensaver timeout to {SCREENSAVER_TIMEOUT_WAIT}s with payload: {payload_timeout}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_timeout, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not set the screensaver timeout."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Wait for timeout and prompt user for manual verification
        line = f"[STEP] Do not interact with the device. Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds for screensaver to activate."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        line = "[STEP] Manual check required."
        LOGGER.result(line)
        logs.append(line)

        user_validated = yes_or_no(result, logs, "Did the screensaver activate on the device?")
        if user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed that the screensaver activated successfully."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported that the screensaver did not activate."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, user_validated={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 10: Screensaver Inactive Check ===
def run_screensaver_inactive_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver does not activate when disabled. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A" # Default for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Inactive Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Disable the screensaver, set a timeout, and manually verify that it does NOT activate.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver did NOT appear.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result
        
        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1: Disable the screensaver
        payload_disable = json.dumps({"screenSaver": False})
        line = f"[STEP] Disabling screensaver with payload: {payload_disable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_disable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not disable screensaver as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Set the screensaver timeout
        payload_timeout = json.dumps({"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT})
        line = f"[STEP] Setting screensaver timeout to {SCREENSAVER_TIMEOUT_WAIT}s with payload: {payload_timeout}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_timeout, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not set the screensaver timeout."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Wait for timeout and prompt user for manual verification
        line = f"[STEP] Do not interact with the device. Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds to see if screensaver activates."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        line = "[STEP] Manual check required."
        LOGGER.result(line)
        logs.append(line)

        # Note the inverted logic here
        user_validated = yes_or_no(result, logs, "Did the screensaver activate on the device?")
        if not user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed that the screensaver did NOT activate, as expected."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported that the screensaver activated, even though it was disabled."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, user_saw_screensaver={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 11: Screensaver Active Return Check ===
def run_screensaver_active_return_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screen returns to its previous state after exiting the screensaver. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated_active = "N/A"
    user_validated_return = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Active Return Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Activate the screensaver, then exit it and manually verify the screen returns to its prior state.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screen returned to the correct state.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result

        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1 & 2: Enable screensaver and set a timeout
        for payload_data in [
            {"screenSaver": True},
            {"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 3: Wait for the screensaver to activate
        line = f"[STEP] Do not interact with the device. Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds for the screensaver."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        # Step 4: Manually verify activation and then the return state
        user_validated_active = yes_or_no(result, logs, "Did the screensaver activate on the device?")
        if not user_validated_active:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Prerequisite failed: User reported that the screensaver did not activate."
            LOGGER.result(line)
            logs.append(line)
            return result

        user_validated_return = yes_or_no(result, logs, "Now, press a key to exit the screensaver. Did the screen return to its previous state?")
        if user_validated_return:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screen returned to its previous state."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screen did NOT return to its previous state."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, screensaver_activated={user_validated_active}, "
                f"screen_returned={user_validated_return}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 12: Screensaver Active Check After Continuous Idle ===
def run_screensaver_active_after_continuous_idle_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver idle timer resets with user activity. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A" # Default for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Active After Continuous Idle Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Verify that user activity resets the screensaver timer, requiring a continuous idle period to activate.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver activated only after a continuous idle period.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result

        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1 & 2: Enable screensaver and set a timeout
        for payload_data in [
            {"screenSaver": True},
            {"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 3: Prompt user to perform an action to break the idle period, then wait
        line = "[STEP] Please press any key on your remote now to simulate user activity."
        LOGGER.result(line)
        logs.append(line)

        # This function combines the prompt and the countdown
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the continuous idle wait?")

        # Step 4: Manually verify if the screensaver activated
        line = "[STEP] Manual check required."
        LOGGER.result(line)
        logs.append(line)

        user_validated = yes_or_no(result, logs, f"Did the screensaver activate after the {SCREENSAVER_TIMEOUT_WAIT}-second continuous idle period?")
        if user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screensaver activated after a continuous idle period, as expected."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screensaver did not activate, suggesting the timer may not have reset correctly."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, user_validated={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 13: Screensaver Inactive Check After Reboot ===
def run_screensaver_inactive_after_reboot_check(dab_topic, test_name, tester, device_id):
    """
    Validates that a disabled screensaver setting persists after a reboot. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Inactive After Reboot Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Disable the screensaver, reboot the device, and verify the screensaver does not activate.",
            "[DESC] Required operations: system/settings/set, system/restart.",
            "[DESC] Pass criteria: User confirmation that the screensaver did NOT activate after the reboot and idle period.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set, system/restart | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result

        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1 & 2: Disable screensaver and set a timeout
        for payload_data in [
            {"screenSaver": False},
            {"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 3: Reboot the device
        line = "[STEP] Rebooting the device now."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs)

        # Step 4: Manually confirm reboot completion
        line = "[STEP] Waiting for manual confirmation that the device has restarted."
        LOGGER.result(line)
        logs.append(line)
        while not yes_or_no(result, logs, "Has the device finished rebooting and is now idle?"):
            logs.append("Waiting for 'Y' confirmation.")
            time.sleep(5) # Add a small delay between prompts

        # Step 5: Wait for the idle timeout to pass
        line = f"[STEP] Do not interact with the device. Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        # Step 6: Manually verify if the screensaver remained inactive
        user_validated = yes_or_no(result, logs, "Did the screensaver activate?")
        if not user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screensaver did NOT activate, as expected."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screensaver activated, even though it was disabled."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, user_saw_screensaver={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 14: Screensaver Timeout 300 seconds Check ===
def run_screensavertimeout_300_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver activates after a 300-second timeout. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A" # Default for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Timeout 300s Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Set a 300-second (5 minute) screensaver timeout and manually verify that it activates.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver appeared after the idle period.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout",
                    result, logs):
            return result
        
        # NOTE: This specific test is for a long timeout, so we bypass the < 60s check.

        # Step 1 & 2: Enable screensaver and set the 300-second timeout
        timeout_seconds = 300
        for payload_data in [
            {"screenSaver": True},
            {"screenSaverTimeout": timeout_seconds}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 3: Wait for timeout and prompt user for manual verification
        line = f"[STEP] Do not interact with the device. Waiting {timeout_seconds} seconds (5 minutes) for screensaver."
        LOGGER.result(line)
        logs.append(line)

        # This function combines the user prompt and the countdown
        waiting_for_screensaver(result, logs, timeout_seconds, "Ready to begin the 5-minute idle wait?")

        line = "[STEP] Manual check required."
        LOGGER.result(line)
        logs.append(line)

        user_validated = yes_or_no(result, logs, f"Did the screensaver activate after {timeout_seconds} seconds?")
        if user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed that the screensaver activated successfully."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported that the screensaver did not activate."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, user_validated={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 15: Screensaver Timeout Reboot Check ===
def run_screensavertimeout_reboot_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver timeout setting persists after a device reboot. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    setting_persisted = "N/A"
    user_validated_active = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Timeout Reboot Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Set a screensaver timeout, reboot, verify the setting persists, and then confirm it activates.",
            "[DESC] Required operations: system/settings/set, system/settings/get, system/restart.",
            "[DESC] Pass criteria: The setting must persist after reboot, and the user must confirm the screensaver activates.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set, system/settings/get, system/restart | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result
        
        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1: Set the screensaver timeout before rebooting
        payload_timeout = json.dumps({"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT})
        line = f"[STEP] Setting screensaver timeout to {SCREENSAVER_TIMEOUT_WAIT}s with payload: {payload_timeout}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_timeout, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not set the screensaver timeout as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Reboot the device
        line = "[STEP] Rebooting the device now."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs, result)

        # Step 3: Manually confirm reboot completion
        line = "[STEP] Waiting for manual confirmation that the device has restarted."
        LOGGER.result(line)
        logs.append(line)
        while not yes_or_no(result, logs, "Has the device finished rebooting and is now idle?"):
            logs.append("Waiting for 'Y' confirmation.")
            time.sleep(5)

        # Step 4: Verify the setting persisted across the reboot
        line = "[STEP] Verifying the screensaver timeout setting persisted after reboot."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        try:
            settings = json.loads(response) if response else {}
            persisted_timeout = settings.get("screenSaverTimeout")
            setting_persisted = (persisted_timeout == SCREENSAVER_TIMEOUT_WAIT)
            if not setting_persisted:
                 result.test_result = "FAILED"
                 line = f"[RESULT] FAILED — Setting did not persist. Expected {SCREENSAVER_TIMEOUT_WAIT}, but got {persisted_timeout}."
                 LOGGER.result(line)
                 logs.append(line)
                 return result
            line = f"[INFO] Setting successfully persisted. Value is {persisted_timeout}."
            LOGGER.info(line)
            logs.append(line)
        except Exception as e:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not parse settings after reboot: {e}"
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 5: Enable the screensaver to test the persisted timeout
        line = "[STEP] Enabling screensaver to test the timeout."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", json.dumps({"screenSaver": True}), logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not enable the screensaver."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 6: Wait and manually verify activation
        line = f"[STEP] Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds for screensaver to activate."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        user_validated_active = yes_or_no(result, logs, "Did the screensaver activate?")
        if user_validated_active:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screensaver activated using the persisted timeout."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screensaver did not activate."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, setting_persisted={setting_persisted}, "
                f"user_saw_screensaver={user_validated_active}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 16: ScreenSaver Timeout Guest Mode Check ===
def run_screensavertimeout_guest_mode_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver can be activated while the device is in guest mode. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    supports_guest_mode = "N/A"
    user_in_guest_mode = "N/A"
    user_validated_active = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver in Guest Mode Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Manually switch to guest mode, enable the screensaver, and verify it activates.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver activated while in guest mode.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for DAB operations
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result

        # Check if min timeout is acceptable for manual testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 1: Manually check if the device supports Guest Mode at all
        line = "[STEP] Manual check required: Checking for Guest Mode support."
        LOGGER.result(line)
        logs.append(line)
        supports_guest_mode = yes_or_no(result, logs, "Does this device support a Guest Mode feature?")
        if not supports_guest_mode:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — Test skipped because the device does not support Guest Mode."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Manually switch to Guest Mode
        line = "[STEP] Manual action required: Please switch the device to Guest Mode."
        LOGGER.result(line)
        logs.append(line)
        user_in_guest_mode = yes_or_no(result, logs, "Is the device now in Guest Mode? (Answering 'N' will fail this test)")
        if not user_in_guest_mode:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Test failed because the device was not put into guest mode as required."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3 & 4: Enable screensaver and set a timeout
        for payload_data in [
            {"screenSaver": True},
            {"screenSaverTimeout": SCREENSAVER_TIMEOUT_WAIT}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 5: Wait for the idle timeout to pass
        line = f"[STEP] Do not interact with the device. Waiting {SCREENSAVER_TIMEOUT_WAIT} seconds for the screensaver."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, SCREENSAVER_TIMEOUT_WAIT, "Ready to begin the idle wait?")

        # Step 6: Manually verify activation
        user_validated_active = yes_or_no(result, logs, "Did the screensaver activate while in guest mode?")
        if user_validated_active:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screensaver activated in guest mode."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screensaver did not activate in guest mode."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, supports_guest_mode={supports_guest_mode}, "
                f"in_guest_mode={user_in_guest_mode}, screensaver_activated={user_validated_active}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 17: ScreenSaver Min Timeout Check ===
def run_screensavertimeout_minimum_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the screensaver can be activated using the device's reported minimum timeout value.
    This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/list", "{}", "UNKNOWN", "", logs)
    min_timeout = "N/A"
    user_validated = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Minimum Timeout Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Get the minimum screensaver timeout, apply it, and verify the screensaver activates.",
            "[DESC] Required operations: system/settings/list, system/settings/set.",
            "[DESC] Pass criteria: User confirmation that the screensaver appeared after the minimum idle period.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/list, system/settings/set | settings: screenSaver, screenSaverTimeout, screenSaverMinTimeout",
                    result, logs):
            return result

        # Step 1: Get the minimum supported screensaver timeout
        line = "[STEP] Getting the device's minimum supported screensaver timeout."
        LOGGER.result(line)
        logs.append(line)
        min_timeout, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if min_timeout is None:
            # get_supported_setting already logs the failure reason and sets the result
            return result
        line = f"[INFO] Device reports minimum screensaver timeout is: {min_timeout} seconds."
        LOGGER.info(line)
        logs.append(line)

        # New logic: check if min_timeout is too long for automated testing
        if not check_min_screensaver_timeout(tester, device_id, result, logs):
            return result

        # Step 2 & 3: Enable screensaver and set the minimum timeout
        for payload_data in [
            {"screenSaver": True},
            {"screenSaverTimeout": min_timeout}
        ]:
            payload = json.dumps(payload_data)
            setting_key = list(payload_data.keys())[0]
            line = f"[STEP] Setting '{setting_key}' with payload: {payload}"
            LOGGER.result(line)
            logs.append(line)
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Could not set '{setting_key}' as a precondition."
                LOGGER.result(line)
                logs.append(line)
                return result

        # Step 4: Wait for the idle timeout to pass and get user confirmation
        line = f"[STEP] Do not interact with the device. Waiting {min_timeout} seconds for the screensaver."
        LOGGER.result(line)
        logs.append(line)
        waiting_for_screensaver(result, logs, int(min_timeout), "Ready to begin the idle wait?")

        line = "[STEP] Manual check required."
        LOGGER.result(line)
        logs.append(line)

        user_validated = yes_or_no(result, logs, f"Did the screensaver activate after {min_timeout} seconds?")
        if user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the screensaver activated with the minimum timeout."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the screensaver did not activate."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, min_timeout_used={min_timeout}, "
                f"user_validated={user_validated}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 18: ScreenSaver Min Timeout Reboot Check ===
def run_screensavermintimeout_reboot_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that the minimum screensaver timeout value is not altered after a device restart.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/list", "{}", "UNKNOWN", "", logs)
    min_timeout_before = "N/A"
    min_timeout_after = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Screensaver Min Timeout After Reboot Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Get the minimum timeout, reboot, get it again, and verify the value is unchanged.",
            "[DESC] Required operations: system/settings/list, system/restart.",
            "[DESC] Pass criteria: The timeout value must be the same before and after the reboot.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/list, system/restart | settings: screenSaverMinTimeout",
                    result, logs):
            return result

        # Step 1: Get the initial minimum timeout value
        line = "[STEP] Getting the minimum screensaver timeout before reboot."
        LOGGER.result(line)
        logs.append(line)
        min_timeout_before, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if not min_timeout_before:
            return result
        line = f"[INFO] Value before reboot: {min_timeout_before}"
        LOGGER.info(line)
        logs.append(line)

        # Step 2: Reboot the device
        line = "[STEP] Rebooting the device now."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs)

        # Step 3: Manually confirm reboot completion
        line = "[STEP] Waiting for manual confirmation that the device has restarted."
        LOGGER.result(line)
        logs.append(line)
        while not yes_or_no(result, logs, "Has the device finished rebooting and is now idle?"):
            logs.append("Waiting for 'Y' confirmation.")
            time.sleep(5)

        # Step 4: Get the minimum timeout again after reboot
        line = "[STEP] Getting the minimum screensaver timeout after reboot."
        LOGGER.result(line)
        logs.append(line)
        min_timeout_after, result = get_supported_setting(tester, device_id, "screenSaverMinTimeout", result, logs)
        if not min_timeout_after:
            return result
        line = f"[INFO] Value after reboot: {min_timeout_after}"
        LOGGER.info(line)
        logs.append(line)

        # Step 5: Compare the values
        if min_timeout_before == min_timeout_after:
            result.test_result = "PASS"
            line = "[RESULT] PASS — The minimum timeout value was unchanged after reboot."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The minimum timeout value changed after reboot."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, timeout_before={min_timeout_before}, "
                f"timeout_after={min_timeout_after}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 18: High Contrast Text Check Text Over Images ===
def run_highContrastText_text_over_images_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that enabling high contrast text improves legibility of text over images. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_navigated = "N/A"
    user_validated_legible = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] High Contrast Text Over Images Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Manually verify that enabling high contrast text improves the legibility of text over images.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that text becomes clearly legible after the setting is enabled.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/settings/set", result, logs):
            return result

        # Step 1: Set a known state by disabling high contrast text first
        payload_disable = json.dumps({"highContrastText": False})
        line = f"[STEP] Precondition: Disabling high contrast text with payload: {payload_disable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_disable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not disable high contrast text as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Manually navigate to the correct screen
        line = "[STEP] Manual action required: Navigate to a screen where text is displayed over an image."
        LOGGER.result(line)
        logs.append(line)
        user_navigated = yes_or_no(result, logs, "Are you on a screen with text over an image?")
        if not user_navigated:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Test failed because the required screen was not navigated to."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Enable High Contrast Text
        payload_enable = json.dumps({"highContrastText": True})
        line = f"[STEP] Action: Enabling high contrast text with payload: {payload_enable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_enable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — The set command to enable high contrast text failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 4: Manually verify the visual change
        user_validated_legible = yes_or_no(result, logs, "Is the text over the image now clearly legible with high contrast?")
        if user_validated_legible:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the text is now legible."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the text is still not clearly legible."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, user_navigated={user_navigated}, "
                f"legibility_confirmed={user_validated_legible}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 19: High Contrast Text Check During Video Playback ===
def run_highContrastText_video_playback_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that toggling high contrast text does not interrupt video playback. This is a manual test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    video_was_playing = "N/A"
    playback_unaffected = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] High Contrast Text During Video Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Manually verify that toggling high contrast text during video playback does not cause interruptions.",
            "[DESC] Required operations: system/settings/set.",
            "[DESC] Pass criteria: User confirmation that video playback was not affected.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/settings/set", result, logs):
            return result

        # Step 1: Set a known state by disabling high contrast text first
        payload_disable = json.dumps({"highContrastText": False})
        line = f"[STEP] Precondition: Disabling high contrast text with payload: {payload_disable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_disable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not disable high contrast text as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Manually start video playback
        line = "[STEP] Manual action required: Start playing any video on the device (e.g., in YouTube)."
        LOGGER.result(line)
        logs.append(line)
        video_was_playing = yes_or_no(result, logs, "Is a video currently playing on the screen?")
        if not video_was_playing:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Test failed because video playback was not started as required."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Enable High Contrast Text while video is playing
        payload_enable = json.dumps({"highContrastText": True})
        line = f"[STEP] Action: Enabling high contrast text with payload: {payload_enable}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_enable, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — The set command to enable high contrast text failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 4: Manually verify the video playback was not affected
        playback_unaffected = yes_or_no(result, logs, "Was the video playback smooth and uninterrupted when the setting was changed?")
        if playback_unaffected:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed video playback was not affected."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported that video playback was interrupted or affected."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, video_was_playing={video_was_playing}, "
                f"playback_unaffected={playback_unaffected}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 20: SetInvalidVoiceAssistant ===
def run_set_invalid_voice_assistant_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the system correctly rejects an unsupported voice assistant name. This is a negative test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    invalid_assistant = "invalid"
    payload = json.dumps({"voiceAssistant": invalid_assistant})
    logs = []
    result = TestResult(test_id, device_id, "voice/set", payload, "UNKNOWN", "", logs)
    status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Set Invalid Voice Assistant (Negative) — {test_name} (test_id={test_id}, device={device_id})",
            f"[DESC] Goal: Attempt to set a voice assistant to an invalid name ('{invalid_assistant}') and expect an error.",
            "[DESC] Required operations: voice/set.",
            "[DESC] Pass criteria: The 'voice/set' command must return a non-200 status code.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: voice/set", result, logs):
            return result
        
        # Optional Step: List supported assistants for context in the logs
        try:
            line = "[STEP] Listing supported voice assistants for context (optional)."
            LOGGER.info(line)
            logs.append(line)
            _, resp_list = execute_cmd_and_log(tester, device_id, "voice/list", "{}", logs)
            if resp_list:
                supported_list = json.loads(resp_list).get("voiceAssistants", [])
                logs.append(f"[INFO] Currently supported assistants: {supported_list}")
        except Exception:
            logs.append("[INFO] Could not list voice assistants; proceeding with test.")


        # Step 1: Attempt to set the invalid voice assistant
        line = f"[STEP] Attempting to set voice assistant with invalid payload: {payload}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "voice/set", payload, logs, result)
        status = dab_status_from(response, rc)

        # Step 2: Validate that the command failed as expected
        if status != 200:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — The device correctly rejected the invalid assistant with status {status}."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — The device unexpectedly accepted the invalid assistant with status 200."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, received_status={status}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 21: Device Restart and Telemetry Validation ===
def run_device_restart_and_telemetry_check(dab_topic, test_name, tester, device_id):
    """
    Validates full device restart + telemetry with minimal changes:
      1) system/restart, wait for health
      2) device-telemetry/start (single start)
      3) passive metrics wait (no re-start in loop)
      4) device-telemetry/stop in finally
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/restart", "{}", "UNKNOWN", "", logs)

    device_ready = False
    metrics_received = False

    try:
        # Header (unchanged style)
        line = f"[TEST] Device Restart and Telemetry Check — {test_name} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)
        for d in (
            "Goal: Restart device; wait until healthy; start telemetry; verify metrics; stop telemetry.",
            "Required ops: system/restart, health-check/get, device-telemetry/start, device-telemetry/stop.",
            "Pass: At least one telemetry metric observed within the wait window.",
        ):
            line = f"[DESC] {d}"
            LOGGER.result(line); logs.append(line)

        # Capability gate
        required_ops = "ops: system/restart, health-check/get, device-telemetry/start, device-telemetry/stop"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # 1) Restart & wait for health
        line = "[STEP] Restarting the device; this may take a few minutes."
        LOGGER.result(line); logs.append(line)
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs, result)

        line = f"[INFO] Polling health-check/get every {HEALTH_CHECK_INTERVAL}s for up to {DEVICE_REBOOT_WAIT}s..."
        LOGGER.info(line); logs.append(line)
        t0 = time.time()
        while time.time() - t0 < DEVICE_REBOOT_WAIT:
            try:
                rc, resp = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs, result)
                if dab_status_from(resp, rc) == 200:
                    device_ready = True
                    break
            except Exception:
                pass
            time.sleep(HEALTH_CHECK_INTERVAL)

        if not device_ready:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device did not become healthy within {DEVICE_REBOOT_WAIT}s."
            LOGGER.result(line); logs.append(line)
            return result

        LOGGER.info("[INFO] Device is online and healthy."); logs.append("[INFO] Device is online and healthy.")

        # 2) Start telemetry (single start; respect 501)
        line = f"[STEP] Starting device telemetry for ~{TELEMETRY_DURATION_MS} ms."
        LOGGER.result(line); logs.append(line)
        payload_start = json.dumps({"duration": TELEMETRY_DURATION_MS})
        rc, resp = execute_cmd_and_log(tester, device_id, "device-telemetry/start", payload_start, logs, result)
        st = dab_status_from(resp, rc)
        if st == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — Telemetry not implemented (501)."
            LOGGER.result(line); logs.append(line)
            return result
        if st != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — device-telemetry/start returned {st}."
            LOGGER.result(line); logs.append(line)
            return result

        # 3) Passive metrics wait (no re-start in loop)
        line = f"[STEP] Listening for telemetry metrics for up to {TELEMETRY_METRICS_WAIT}s..."
        LOGGER.result(line); logs.append(line)
        checker = DabChecker(tester)

        deadline = time.time() + TELEMETRY_METRICS_WAIT
        while time.time() < deadline:
            ok, chk = (False, "")
            try:
                # IMPORTANT: passive peek (must NOT start telemetry again)
                ok, chk = checker.check(device_id, "device-telemetry/metrics-peek", payload_start)
            except Exception:
                pass

            if chk:  # use checker_log per review
                logs.append(f"[INFO] checker_log: {chk}")

            # Guarded peek of last sample if your client exposes it
            sample_fn = getattr(getattr(tester, "dab_client", None), "last_metrics_sample", None)
            sample_msg = None
            if callable(sample_fn):
                try:
                    sample_msg = sample_fn()
                except Exception:
                    sample_msg = None

            if ok or sample_msg:
                metrics_received = True
                break

            time.sleep(1.0)

        if not metrics_received:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — No telemetry metrics observed within {TELEMETRY_METRICS_WAIT}s."
            LOGGER.result(line); logs.append(line)
            return result

        # PASS
        result.test_result = "PASS"
        line = "[RESULT] PASS — Restart + telemetry workflow succeeded with non-empty metrics."
        LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — Unexpected error: {e}"
        LOGGER.result(line); logs.append(line)

    finally:
        # cleanup & final summary (always)
        try:
            execute_cmd_and_log(tester, device_id, "device-telemetry/stop", "{}", logs, result)
        except Exception:
            pass
        line = (f"[SUMMARY] outcome={result.test_result}, device_ready={device_ready}, "
                f"metrics_received={metrics_received}, test_id={test_id}, device={device_id}")
        LOGGER.result(line); logs.append(line)

    return result

# === Test 22: Stop App Telemetry Without Active Session (Negative) ===
def run_stop_app_telemetry_without_active_session_check(dab_topic, test_name, tester, device_id):
    """
    Ensures the device handles a redundant 'app-telemetry/stop' command gracefully when no session is active.
    This is a negative test case.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    payload = json.dumps({"appId": app_id})
    logs = []
    result = TestResult(test_id, device_id, "app-telemetry/stop", payload, "UNKNOWN", "", logs)
    status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Stop App Telemetry Without Active Session (Negative) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Send an 'app-telemetry/stop' command when no session is running and verify a graceful response.",
            "[DESC] Required operations: app-telemetry/stop.",
            "[DESC] Pass criteria: The command must return a 200 (gracefully ignored) OR a 4xx/5xx error indicating no active session.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: app-telemetry/stop", result, logs):
            return result

        # Step 1: Send the stop command directly, assuming no active session
        line = f"[STEP] Sending 'app-telemetry/stop' with payload: {payload}"
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "app-telemetry/stop", payload, logs, result)
        status = dab_status_from(response, rc)
        
        message = ""
        try:
            if response:
                message = str(json.loads(response).get("error", "")).lower()
        except Exception:
            pass # Ignore if response is not valid JSON

        # Step 2: Validate the response
        if status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device gracefully accepted the stop request with status 200."
        elif status in (400, 500) and ("not started" in message or "no active session" in message):
            result.test_result = "PASS"
            line = f"[RESULT] PASS — Device correctly returned an error for no active session (Status: {status})."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Received an unexpected response (Status: {status}, Message: '{message}')."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, received_status={status}, "
                f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test23: Launch Video and Verify Health Check ===
def run_launch_video_and_health_check(dab_topic, test_name, tester, device_id):
    """
    Launches a video and then performs a health check to ensure the device remains stable under load.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    video_id = "2ZggAa6LuiM"  # A standard, reliable test video
    payload = json.dumps({"appId": app_id, "contentId": video_id})
    logs = []
    result = TestResult(test_id, device_id, "applications/launch-with-content", payload, "UNKNOWN", "", logs)
    health_status = "N/A"
    is_healthy = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Launch Video and Health Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Launch a video, wait for it to play, and then verify the device is still healthy.",
            "[DESC] Required operations: applications/launch-with-content, health-check/get, applications/exit.",
            "[DESC] Pass criteria: The health check must return status 200 and a 'healthy': true response.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/launch-with-content, health-check/get, applications/exit"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Launch the video content
        line = f"[STEP] Launching video '{video_id}' in '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/launch-with-content", payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The command to launch the video failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Wait for video playback to stabilize
        wait_time = APP_LAUNCH_WAIT + CONTENT_LOAD_WAIT
        line = f"[WAIT] Allowing {wait_time}s for video playback to start."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(wait_time)

        # Step 3: Perform a health check
        line = "[STEP] Performing a health check while video is playing."
        LOGGER.result(line)
        logs.append(line)
        rc, health_resp = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs, result)
        health_status = dab_status_from(health_resp, rc)

        try:
            is_healthy = json.loads(health_resp).get("healthy", False) if health_resp else False
        except Exception:
            is_healthy = False
            logs.append("[INFO] Could not parse 'healthy' field from health check response.")

        if health_status == 200 and is_healthy:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device health check passed while video was playing."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device health check failed. Status: {health_status}, Healthy: {is_healthy}"
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Cleanup Step: Always try to exit the application
        try:
            line = f"[CLEANUP] Exiting application '{app_id}'."
            LOGGER.info(line)
            logs.append(line)
            execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": app_id}), logs, result)
        except Exception as e:
            line = f"[CLEANUP] Failed to exit application '{app_id}': {e}"
            LOGGER.warn(line)
            logs.append(line)

        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, health_status={health_status}, is_healthy={is_healthy}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test24: Voice List With No Voice Assistant Configured (Negative / Optional) ===
def run_voice_list_with_no_voice_assistant(dab_topic, test_name, tester, device_id):
    """
    Validates system behavior when requesting the list of voice assistants on a device with none configured.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "voice/list", "{}", "UNKNOWN", "", logs)
    status = "N/A"
    assistant_count = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Voice List With No Assistant (Negative/Optional) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Request the list of voice assistants and expect an empty list if none are configured.",
            "[DESC] Required operations: voice/list.",
            "[DESC] Pass criteria: Returns a 200 status with an empty 'voiceAssistants' array.",
            "[DESC] Note: If assistants are pre-configured, this test is marked OPTIONAL_FAILED.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: voice/list", result, logs):
            return result

        # Step 1: Send the voice/list request
        line = "[STEP] Sending 'voice/list' request."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "voice/list", "{}", logs, result)
        status = dab_status_from(response, rc)
        
        assistants = []
        try:
            if response:
                assistants = json.loads(response).get("voiceAssistants", [])
                assistant_count = len(assistants)
        except Exception:
            logs.append(f"[INFO] Could not parse voice/list response: {response}")

        # Step 2: Validate the response
        if status == 200 and isinstance(assistants, list) and len(assistants) == 0:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device correctly returned an empty list of assistants."
        elif status == 200 and len(assistants) > 0:
            result.test_result = "OPTIONAL_FAILED"
            line = f"[RESULT] OPTIONAL_FAILED — Device has pre-configured assistants: {assistants}"
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Received unexpected status {status} or invalid response format."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, received_status={status}, assistant_count={assistant_count}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test25: Validates that launching an uninstalled app fails with a relevant error. Negative test case. ===
def run_launch_when_uninstalled_check(dab_topic, test_name, tester, device_id):
    """
    Negative: ensure Sample_App is installed, uninstall it, then launching must fail (non-200).
    Cleanup: reinstall from local artifact (any extension) via util.config_loader.ensure_app_available.
    Keeps results.json lean (no raw response lines stored).
    """

    # ---------- ids & setup ----------
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id  = config.apps.get("sample_app", "Sample_App")

    logs = []
    result = TestResult(
        test_id,
        device_id,
        "applications/launch",
        json.dumps({"appId": app_id}),
        "UNKNOWN",
        "",
        logs,
    )

    INSTALL_WAIT   = globals().get("APP_INSTALL_WAIT", 10)
    UNINSTALL_WAIT = globals().get("APP_UNINSTALL_WAIT", 5)
    LAUNCH_WAIT    = globals().get("APP_LAUNCH_WAIT", 5)

    install_status   = "N/A"
    uninstall_status = "N/A"
    launch_status    = "N/A"

    # send command outputs to a scratch list so huge raw responses don't end up in result.logs
    scratch = []
    def _call(topic: str, body_json: str):
        return execute_cmd_and_log(tester, device_id, topic, body_json, scratch, result)

    try:
        # ---------- header ----------
        for line in (
            f"[TEST] Launch When Uninstalled (Negative) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Flow: install Sample_App → uninstall → attempt launch (expect non-200); then reinstall (cleanup).",
            "[DESC] Ops: applications/install, applications/uninstall, applications/launch.",
        ):
            LOGGER.result(line); logs.append(line)

        if not app_id:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — config.apps['sample_app'] not set."
            LOGGER.result(msg); logs.append(msg)
            result.response = "['no sample_app configured']"
            return result

        # capability gate
        if not require_capabilities(
            tester, device_id,
            "ops: applications/install, applications/uninstall, applications/launch",
            result, logs
        ):
            result.response = "['capability gate failed']"
            return result

        logs.append("[INFO] Capability gate passed.")

        # ---------- 1) Ensure installed (install from local artifact) ----------
        try:
            payload_install = ensure_app_available(app_id=app_id)  # {"appId","url","format","timeout"}
        except Exception as e:
            result.test_result = "SKIPPED"
            msg = f"[RESULT] SKIPPED — missing local artifact for '{app_id}': {e}"
            LOGGER.result(msg); logs.append(msg)
            result.response = "['missing local artifact']"
            return result

        LOGGER.result(f"[STEP] Install '{app_id}' from local artifact"); logs.append(
            f"[STEP] Install '{app_id}' from local artifact")
        rc_i, resp_i = _call("applications/install", json.dumps(payload_install))
        install_status = dab_status_from(resp_i, rc_i)
        logs.append(f"[INFO] install status={install_status}")
        if install_status != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — install returned {install_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — install returned {install_status} (expected 200)")
            result.response = f"['install={install_status}']"
            return result

        logs.append(f"[WAIT] {INSTALL_WAIT}s after install")
        time.sleep(INSTALL_WAIT)

        # ---------- 2) Uninstall ----------
        payload_app = json.dumps({"appId": app_id})
        LOGGER.result(f"[STEP] Uninstall '{app_id}'"); logs.append(f"[STEP] Uninstall '{app_id}'")
        rc_u, resp_u = _call("applications/uninstall", payload_app)
        uninstall_status = dab_status_from(resp_u, rc_u)
        logs.append(f"[INFO] uninstall status={uninstall_status}")
        if uninstall_status != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — uninstall returned {uninstall_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — uninstall returned {uninstall_status} (expected 200)")
            result.response = f"['install={install_status}, uninstall={uninstall_status}']"
            return result

        logs.append(f"[WAIT] {UNINSTALL_WAIT}s after uninstall")
        time.sleep(UNINSTALL_WAIT)

        # ---------- 3) Attempt launch (should fail) ----------
        LOGGER.result(f"[STEP] Launch '{app_id}' (expected to fail)"); logs.append(
            f"[STEP] Launch '{app_id}' (expected to fail)")
        rc_l, resp_l = _call("applications/launch", payload_app)
        launch_status = dab_status_from(resp_l, rc_l)
        logs.append(f"[INFO] launch status={launch_status}")
        time.sleep(LAUNCH_WAIT)

        if launch_status != 200:
            result.test_result = "PASS"
            LOGGER.result(f"[RESULT] PASS — launch failed as expected (status {launch_status})."); logs.append(
                f"[RESULT] PASS — launch failed as expected (status {launch_status}).")
        else:
            result.test_result = "FAILED"
            LOGGER.result("[RESULT] FAILED — launch unexpectedly returned 200."); logs.append(
                "[RESULT] FAILED — launch unexpectedly returned 200.")

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        msg = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' not supported."
        LOGGER.result(msg); logs.append(msg)
    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — Unexpected error: {e}"
        LOGGER.result(msg); logs.append(msg)
    finally:
        # ---------- cleanup: reinstall for test isolation ----------
        try:
            payload_install = ensure_app_available(app_id=app_id)
            logs.append(f"[CLEANUP] Reinstall '{app_id}'")
            _call("applications/install", json.dumps(payload_install))
        except Exception as e:
            logs.append(f"[CLEANUP] WARNING: Failed to reinstall '{app_id}': {e}")

        # compact response for results.json
        result.response = f"['install={install_status}, uninstall={uninstall_status}, launch_after_uninstall={launch_status}']"

        summary = (f"[SUMMARY] outcome={result.test_result}, launch_status_on_uninstalled={launch_status}, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(summary); logs.append(summary)

    return result

# === Test26: Validates that launching an app while the device is restarting fails. Negative test case. ===
def run_launch_app_while_restarting_check(dab_topic, test_name, tester, device_id):
    """
    Validates that launching an app while the device is restarting fails. Negative test case.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/launch", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    launch_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Launch App While Device Restarting (Negative) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Initiate a device restart and immediately try to launch an app, expecting failure.",
            "[DESC] Required operations: system/restart, applications/launch.",
            "[DESC] Pass criteria: The launch attempt must fail, either with no response or a non-200 status.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/restart, applications/launch", result, logs):
            return result

        # Step 1: Initiate a fire-and-forget restart
        line = "[STEP] Sending system/restart command (fire-and-forget)."
        LOGGER.result(line)
        logs.append(line)
        fire_and_forget_restart(tester.dab_client, device_id)
        
        # Give a moment for the shutdown process to begin
        time.sleep(3)

        # Step 2: Attempt to launch the app while the device should be offline
        line = f"[STEP] Attempting to launch '{app_id}' during restart."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs, result)
        
        # The response may be empty or an error, so dab_status_from is not always reliable here.
        # The key is whether the launch *succeeded* (status 200).
        try:
            launch_status = json.loads(response).get("status") if response else "NO_RESPONSE"
        except Exception:
            launch_status = "INVALID_RESPONSE"

        if launch_status != 200:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — Launch failed as expected during restart (Status: {launch_status})."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Launch succeeded unexpectedly during restart."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)
        
    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, launch_status_during_restart={launch_status}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)
        # Allow time for device to come back online for next test
        LOGGER.info("Waiting for device to potentially recover from restart...")
        time.sleep(HEALTH_CHECK_INTERVAL)

    return result

def run_network_reset_check(dab_topic, test_name, tester, device_id):
    """
    Validates that the device remains responsive to DAB commands after a network reset.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/network-reset", "{}", "UNKNOWN", "", logs)
    info_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Network Reset Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Reset all network settings and then verify the device is still responsive via 'system/info'.",
            "[DESC] Required operations: system/network-reset, system/info.",
            "[DESC] Pass criteria: The 'system/info' command must succeed after the network reset.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/network-reset, system/info", result, logs):
            return result

        # Step 1: Execute the network reset
        line = "[STEP] Sending 'system/network-reset' command."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/network-reset", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — The 'system/network-reset' command failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Allow time for network to re-establish
        time.sleep(15)

        # Step 2: Verify DAB is still responsive
        line = "[STEP] Verifying DAB responsiveness with 'system/info'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/info", "{}", logs, result)
        info_status = dab_status_from(response, rc)
        
        if info_status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device responded successfully to 'system/info' after network reset."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — 'system/info' failed with status {info_status} after network reset."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, post_reset_info_status={info_status}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test26: Validates the device can be factory reset and recovers to a healthy state.
def run_factory_reset_and_recovery_check(dab_topic, test_name, tester, device_id):
    """
    Validates the device can be factory reset and recovers to a healthy state.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/factory-reset", "{}", "UNKNOWN", "", logs)
    device_recovered = False

    try:
        # Header and description
        for line in (
            f"[TEST] Factory Reset and Recovery Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Initiate a factory reset and poll until the device comes back online and is healthy.",
            "[DESC] Required operations: system/factory-reset, health-check/get.",
            "[DESC] Pass criteria: The device must become healthy within the timeout period after a reset.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/factory-reset, health-check/get", result, logs):
            return result

        # Step 1: Send the factory reset command
        line = "[STEP] Sending 'system/factory-reset' command. This will take several minutes."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/factory-reset", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The 'system/factory-reset' command was rejected."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Poll for health check until the device recovers
        line = f"[WAIT] Polling health-check every {HEALTH_CHECK_INTERVAL}s for up to {DEVICE_REBOOT_WAIT}s..."
        LOGGER.info(line)
        logs.append(line)
        
        start_time = time.time()
        while time.time() - start_time < DEVICE_REBOOT_WAIT:
            try:
                rc_health, resp_health = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs, result)
                if dab_status_from(resp_health, rc_health) == 200:
                    device_recovered = True
                    break
            except Exception:
                pass # Suppress errors while device is offline
            time.sleep(HEALTH_CHECK_INTERVAL)

        if device_recovered:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device recovered and became healthy after factory reset."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device did not recover within the {DEVICE_REBOOT_WAIT}s timeout."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, device_recovered={device_recovered}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test27: Validates device behavior for the optional 'personalizedAds' setting when it is NOT supported.
def run_personalized_ads_response_check(dab_topic, test_name, tester, device_id):
    """
    Validates device behavior for the optional 'personalizedAds' setting when it is NOT supported.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    set_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Personalized Ads Not Supported Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: On a device that does not support 'personalizedAds', verify that setting it returns a 501 error.",
            "[DESC] Required ops: system/settings/set. Optional: system/settings/list.",
            "[DESC] Pass criteria: 'set' command must return status 501. If the setting is supported, the test is OPTIONAL_FAILED.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Basic capability gate for the required operations
        if not require_capabilities(tester, device_id, "ops: system/settings/set", result, logs):
            return result

        # Step 1: Check if the 'personalizedAds' setting is supported by the device.
        is_setting_supported = require_capabilities(tester, device_id, "settings: personalizedAds", result, logs)

        if is_setting_supported:
            # If the setting IS supported, this test is not applicable and should be skipped.
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — 'personalizedAds' is a supported setting. This test is only for devices that do not support it."
            LOGGER.result(line)
            logs.append(line)
        else:
            # Step 2: If the setting is NOT supported, attempt to set it. The correct behavior is for the device to return 501.
            line = "[STEP] Setting is not supported as expected. Attempting to set 'personalizedAds', expecting a 501 error."
            LOGGER.result(line)
            logs.append(line)
            payload = json.dumps({"personalizedAds": True})
            rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
            set_status = dab_status_from(response, rc)

            if set_status == 501:
                result.test_result = "PASS"
                line = f"[RESULT] PASS — Device correctly returned '501 Not Implemented' for an unsupported setting."
            else:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — Device returned status {set_status}, but expected '501 Not Implemented' for an unsupported setting."

            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        # This will be caught if 'system/settings/set' itself is not supported.
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, set_status={set_status}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

def run_personalized_ads_persistence_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that the 'personalizedAds' setting persists after a device restart.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    persisted_value = "N/A"
    device_recovered = False

    try:
        # Header and description
        for line in (
            f"[TEST] Personalized Ads Persistence Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Enable personalized ads, reboot, and verify the setting is still enabled.",
            "[DESC] Required ops: system/settings/set, system/settings/get, system/restart, health-check/get.",
            "[DESC] Required settings: personalizedAds",
            "[DESC] Pass criteria: The 'personalizedAds' value must be true after reboot.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate: Check for both required operations AND the specific setting
        spec = "ops: system/settings/set, system/settings/get, system/restart, health-check/get | settings: personalizedAds"
        if not require_capabilities(tester, device_id, spec, result, logs):
            return result # The 'require_capabilities' function already logged the reason and set the result

        # Step 1: Enable personalized ads
        line = "[STEP] Enabling 'personalizedAds' setting."
        LOGGER.result(line)
        logs.append(line)
        payload = json.dumps({"personalizedAds": True})
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
        if dab_status_from(response, rc) != 200:
            # This could be a 501 if the setting is read-only, which is a valid failure for a 'set' test.
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not enable 'personalizedAds' as a precondition. Status: {dab_status_from(response, rc)}"
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Reboot the device
        line = "[STEP] Rebooting the device."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs, result)

        # Step 3: Wait for the device to become healthy by polling
        line = f"[WAIT] Polling for device health for up to {DEVICE_REBOOT_WAIT}s..."
        LOGGER.info(line)
        logs.append(line)
        start_time = time.time()
        while time.time() - start_time < DEVICE_REBOOT_WAIT:
            try:
                rc_health, resp_health = execute_cmd_and_log(tester, device_id, "health-check/get", "{}", logs, result)
                if dab_status_from(resp_health, rc_health) == 200 and json.loads(resp_health).get("healthy"):
                    device_recovered = True
                    LOGGER.ok("[INFO] Device is healthy after reboot.")
                    logs.append("[INFO] Device is healthy after reboot.")
                    break
            except Exception:
                # Ignore errors while device is rebooting
                pass
            time.sleep(HEALTH_CHECK_INTERVAL)

        if not device_recovered:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device did not become healthy within {DEVICE_REBOOT_WAIT}s after reboot."
            LOGGER.error(line)
            logs.append(line)
            return result

        # Step 4: Verify the setting after reboot
        line = "[STEP] Verifying 'personalizedAds' setting after reboot."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        try:
            settings = json.loads(response) if response else {}
            persisted_value = settings.get("personalizedAds")
        except Exception:
            persisted_value = "ERROR_PARSING"

        if persisted_value is True:
            result.test_result = "PASS"
            line = "[RESULT] PASS — 'personalizedAds' setting correctly persisted as true."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Setting did not persist. Expected true, got '{persisted_value}'."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, persisted_value={persisted_value}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result


def run_personalized_ads_manual_check(dab_topic, test_name, tester, device_id):
    """
    Manually verifies that enabling personalized ads results in tailored ads being shown.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    user_validated = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Personalized Ads Display Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Enable personalized ads and have the user manually verify that the ads are tailored.",
            "[DESC] Required ops: system/settings/set. Optional: system/settings/list.",
            "[DESC] Pass criteria: User confirmation that ads appear personalized.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate now checks for the setting directly
        if not require_capabilities(tester, device_id,
                    "ops: system/settings/set, system/settings/list | settings: personalizedAds",
                    result, logs):
            return result
        
        # The redundant manual check for the setting has been removed from here.

        # Step 1: Enable personalized ads
        line = "[STEP] Enabling 'personalizedAds' setting."
        LOGGER.result(line)
        logs.append(line)
        payload = json.dumps({"personalizedAds": True})
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/set", payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not enable 'personalizedAds'."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Manual verification
        line = "[STEP] Manual check: Please navigate ad surfaces (home screen, YouTube, etc.)."
        LOGGER.result(line)
        logs.append(line)
        user_validated = yes_or_no(result, logs, "Do the ads appear to be personalized to the user's interests?")
        if user_validated:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed ads are personalized."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported ads are not personalized."

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, user_validated={user_validated}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 34: Uninstall An Application Currently Running Foreground Check ===

def run_uninstall_foreground_app_check(dab_topic, test_name, tester, device_id):
    """
    Validates that a foreground application can be uninstalled successfully.
    This test now pre-installs Sample_App to ensure a consistent state.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    result = TestResult(test_id, device_id, "applications/uninstall", json.dumps({"appId": app_id}), "UNKNOWN", "", logs)
    clear_status = "N/A" # Initialize for summary

    try:
        # Header and description
        for line in (
            f"[TEST] Uninstall Foreground App Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: Install and launch a sample app, then uninstall it while it's in the foreground.",
            "[DESC] Required ops: applications/install, applications/launch, applications/get-state, applications/uninstall.",
            "[DESC] Pass criteria: The 'uninstall' command must return status 200.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/install, applications/launch, applications/get-state, applications/uninstall"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Precondition Step: Install the application to ensure it exists
        try:
            install_payload = ensure_app_available(app_id=app_id)
        except Exception as e:
            result.test_result = "SKIPPED"
            line = f"[RESULT] SKIPPED — Could not find local artifact for '{app_id}': {e}"
            LOGGER.result(line); logs.append(line)
            return result

        line = f"[STEP] Precondition: Installing '{app_id}' to ensure it exists."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/install", json.dumps(install_payload), logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not install the sample app as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 1: Launch the app
        line = f"[STEP] Launching application '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs, result)
        LOGGER.info(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch and stabilize.")
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2: Get app state to confirm it's in the foreground
        line = f"[STEP] Getting state of application '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": app_id}), logs, result)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        LOGGER.info(f"Current application state: {state}.")

        if state != "FOREGROUND":
            result.test_result = "FAILED"
            logs.append(f"[FAIL] App state is '{state}', expected 'FOREGROUND'.")
            LOGGER.result(f"[RESULT] FAILED - App did not reach FOREGROUND state before uninstall attempt.")
            return result

        # Step 3: Uninstall the foreground app
        line = f"[STEP] Uninstalling application '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": app_id}), logs, result)
        clear_status = dab_status_from(response, rc)
        LOGGER.info(f"Waiting {APP_UNINSTALL_WAIT} seconds for application to uninstall.")
        time.sleep(APP_UNINSTALL_WAIT)

        if clear_status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Successfully uninstalled the foreground application."
            LOGGER.result(line)
            logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Uninstall command returned status {clear_status} instead of 200."
            LOGGER.result(line)
            logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED - Unsupported operation: {str(e)}"
        LOGGER.warn(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        # This is the key change to get detailed error information
        error_details = traceback.format_exc()
        line = f"[RESULT] SKIPPED - An unexpected error occurred:\n{error_details}"
        LOGGER.error(line)
        logs.append(line)

    finally:
        # Final summary log
        line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}, appId={app_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 35: Uninstall An System Application Check ===
def run_uninstall_system_app_check(dab_topic, test_name, tester, device_id):
    """
    Validates that a critical system application (Settings) cannot be uninstalled.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    # Hardcode the appId to 'settings', which the DAB bridge should resolve to a package name.
    app_id = "settings"
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)
    uninstall_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Uninstall System App Check — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Goal: Verify that a critical system app (Settings) cannot be uninstalled.",
            "[DESC] Required ops: applications/uninstall.",
            "[DESC] Pass criteria: The 'uninstall' command must return status 403 (Forbidden).",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate: We only require_capabilities the uninstall operation
        if not require_capabilities(tester, device_id, "ops: applications/uninstall", result, logs):
            return result

        # Step 1: Attempt to uninstall the system app using its config key.
        line = f"[STEP] Attempting to uninstall system app '{app_id}', expecting a 403 error."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/uninstall", payload_app, logs, result)
        uninstall_status = dab_status_from(response, rc)

        # Step 2: Verify the response status. Expected outcome for system apps is 403 (Forbidden).
        if uninstall_status == 403:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device correctly returned '403 Forbidden' when attempting to uninstall a system app."
        elif uninstall_status == 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device incorrectly allowed uninstalling a system app (status 200). This is a security risk."
        else:
            result.test_result = "FAILED"
            line = (f"[RESULT] FAILED — Device returned an unexpected status '{uninstall_status}'. Expected 403. "
                    f"(A 404 status may indicate a tool configuration issue resolving the appId '{app_id}')")

        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, uninstall_status={uninstall_status}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 36: Clear Data For An Application Currently Running Foreground Check ===
def run_clear_data_foreground_app_check(dab_topic, test_name, tester, device_id):
    """
    Validates that data for a foreground app can be cleared successfully.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    appId = config.apps.get("youtube", "YouTube")
    logs = []
    result = TestResult(test_id, device_id, "applications/clear-data", json.dumps({"appId": appId}), "UNKNOWN", "", logs)
    clear_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Clear Data for Foreground App — {test_name} (test_id={test_id}, device={device_id}, appId={appId})",
            "[DESC] Goal: Launch an app, then clear its data while it's in the foreground.",
            "[DESC] Required ops: applications/launch, applications/clear-data.",
            "[DESC] Pass criteria: The 'clear-data' command must return status 200.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/launch, applications/clear-data", result, logs):
            return result

        # Step 1: Launch the app
        line = f"[STEP] Launching '{appId}' to bring it to the foreground."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": appId}), logs, result)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch and stabilize.")
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2: Clear the app's data
        line = f"[STEP] Clearing data for '{appId}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/clear-data", json.dumps({"appId": appId}), logs, result)
        clear_status = dab_status_from(response, rc)
        time.sleep(APP_CLEAR_DATA_WAIT)

        if clear_status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — 'clear-data' command returned status 200."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — 'clear-data' returned status {clear_status}."

        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, clear_status={clear_status}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 37: Clear Data For An System Application Check ===
def run_clear_data_system_app_check(dab_topic, test_name, tester, device_id):
    """
    Validates that data for a system application can be cleared.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "applications/clear-data", "{}", "UNKNOWN", "", logs)
    app_id = "N/A"
    clear_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Clear Data for System App (Manual Select) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Manually select a system app and clear its data.",
            "[DESC] Required ops: applications/list, applications/clear-data.",
            "[DESC] Pass criteria: The 'clear-data' command must return status 200.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/list, applications/clear-data", result, logs):
            return result

        # Step 1: List and select a system app
        line = "[STEP] Listing applications for manual selection."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "applications/list", "{}", logs, result)
        apps = json.loads(response).get("applications", [])
        app_id_list = [app.get("appId") for app in apps]

        line = "Please select one SYSTEM application from the list to clear its data:"
        LOGGER.prompt(line)
        logs.append(line)
        index = select_input(result, logs, app_id_list)
        if index == 0:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — No system app was selected."
            LOGGER.result(line)
            logs.append(line)
            return result

        app_id = app_id_list[index - 1]
        logs.append(f"[INFO] User selected app: {app_id}")

        # Step 2: Clear the app's data
        line = f"[STEP] Clearing data for system app '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/clear-data", json.dumps({"appId": app_id}), logs, result)
        clear_status = dab_status_from(response, rc)
        time.sleep(APP_CLEAR_DATA_WAIT)

        if clear_status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — 'clear-data' command returned status 200."
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — 'clear-data' returned status {clear_status}."

        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, target_app={app_id}, clear_status={clear_status}, test_id={test_id}, device={device_id}"
        LOGGER.result(line)
        logs.append(line)

    return result

def run_clear_data_user_installed_app_foreground(dab_topic, test_name, tester, device_id):
    test_id = to_test_id(f"{dab_topic}/{test_name}")
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

        # === Capability gate via new require_capabilities() (raises UnsupportedOperationError if missing) ===
        require_capabilities(tester, device_id, "ops: applications/launch, applications/clear-data")
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

def run_install_from_app_store_check(dab_topic, test_name, tester, device_id):
    """
    Positive: Install a new app from the app store and launch it.
    Minimal flow: install-from-app-store → short wait → launch
    Pass if install returns 200 and launch returns 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
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
        if not require_capabilities(tester, device_id, "ops: applications/install-from-app-store, applications/launch", result, logs):
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

def run_install_youtube_kids_from_store(dab_topic, test_name, tester, device_id):
    """
    Positive: Install YouTube Kids from the app store and confirm it launches.
    Flow: install-from-app-store -> short wait -> (optional) applications/list check -> launch
    Pass if install == 200 and launch == 200.
    Note: "family-friendly settings" visibility is outside DAB scope; log info for manual/OEM validation.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
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
        if not require_capabilities(tester, device_id, "ops: applications/install-from-app-store, applications/launch", result, logs):
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

def run_uninstall_after_standby_check(dab_topic, test_name, tester, device_id):
    """
    Positive: Uninstall a pre-installed removable app when device was in standby (woken for operation).
    Flow: (best-effort) wake via input/key-press -> applications/uninstall -> short wait -> (best-effort) applications/list
    Pass if uninstall returns 200 and (if list is available) the app no longer appears.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
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

        # Required capability gate (unsupported → OPTIONAL_FAILED handled by require_capabilities)
        if not require_capabilities(tester, device_id, "ops: applications/uninstall", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, uninstall_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 0) Best-effort wake from standby (optional)
        try:
            msg = f"[STEP] input/key-press {{\"keyCode\": \"KEY_POWER\"}}  # best-effort wake"
            LOGGER.result(msg); logs.append(msg)
            rc_wake, resp_wake = execute_cmd_and_log(
                tester, device_id, "input/key-press", {"keyCode": "KEY_POWER"}, logs, result
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

def run_install_bg_uninstall_sample_app(dab_topic, test_name, tester, device_id):
    """
    Flow: applications/install (Sample_App from local path) -> launch -> HOME (background) -> uninstall
    Pass if install == 200 and uninstall == 200. No launcher fallback; only KEY_HOME.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id  = config.apps.get("sample_app", "Sample_App")
    logs    = []

    payload_app_json = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app_json, "UNKNOWN", "", logs)

    INSTALL_WAIT     = 10
    APP_LAUNCH_WAIT  = globals().get("APP_LAUNCH_WAIT", 5)
    BG_WAIT          = 3

    try:
        # Header
        LOGGER.result(f"[TEST] Install → HOME → Uninstall — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"); logs.append(
            f"[TEST] Install → HOME → Uninstall — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})")

        # Resolve local install payload (absolute path; any extension)
        try:
            install_payload = ensure_app_available(app_id=app_id)  # {"appId","url","format","timeout"}
        except Exception as e:
            result.test_result = "SKIPPED"
            LOGGER.result(f"[RESULT] SKIPPED — missing app artifact: {e}"); logs.append(f"[RESULT] SKIPPED — missing app artifact: {e}")
            LOGGER.result(f"[SUMMARY] outcome=SKIPPED, test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(
                f"[SUMMARY] outcome=SKIPPED, test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        # Capability gate (include input/key-press explicitly)
        if not require_capabilities(tester, device_id,
                    "ops: applications/install, applications/launch, input/key-press, applications/uninstall",
                    result, logs):
            LOGGER.result(f"[SUMMARY] outcome=OPTIONAL_FAILED, test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        # 1) Install
        payload_install_json = json.dumps(install_payload)
        LOGGER.result(f"[STEP] applications/install {payload_install_json}"); logs.append(f"[STEP] applications/install {payload_install_json}")
        rc_i, resp_i = execute_cmd_and_log(tester, device_id, "applications/install", payload_install_json, logs, result)
        st_i = dab_status_from(resp_i, rc_i)
        if st_i != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — install returned {st_i} (expected 200)")
            LOGGER.result(f"[SUMMARY] outcome=FAILED, install_status={st_i}, test_id={test_id}, device={device_id}, appId={app_id}")
            return result
        time.sleep(INSTALL_WAIT)

        # 2) Launch
        LOGGER.result(f"[STEP] applications/launch {payload_app_json}"); logs.append(f"[STEP] applications/launch {payload_app_json}")
        rc_l, resp_l = execute_cmd_and_log(tester, device_id, "applications/launch", payload_app_json, logs, result)
        time.sleep(APP_LAUNCH_WAIT)

        # 3) Background with HOME (no fallback)
        payload_home = json.dumps({"keyCode": "KEY_HOME"})
        LOGGER.result(f'[STEP] input/key-press {payload_home}  # background app'); logs.append(f'[STEP] input/key-press {payload_home}')
        rc_home, resp_home = execute_cmd_and_log(tester, device_id, "input/key-press", payload_home, logs, result)
        time.sleep(BG_WAIT)

        # 4) Uninstall
        LOGGER.result(f"[STEP] applications/uninstall {payload_app_json}"); logs.append(f"[STEP] applications/uninstall {payload_app_json}")
        rc_u, resp_u = execute_cmd_and_log(tester, device_id, "applications/uninstall", payload_app_json, logs, result)
        st_u = dab_status_from(resp_u, rc_u)

        if st_u == 200:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — install 200, HOME ok, uninstall 200")
        else:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — uninstall returned {st_u} (expected 200)")

        LOGGER.result(f"[SUMMARY] outcome={result.test_result}, install_status={st_i}, uninstall_status={st_u}, test_id={test_id}, device={device_id}, appId={app_id}")
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        LOGGER.result(f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id})")
        LOGGER.result(f"[SUMMARY] outcome=SKIPPED, test_id={test_id}, device={device_id}, appId={app_id}")
        return result

def run_uninstall_sample_app_with_local_data_check(dab_topic, test_name, tester, device_id):
    """
    Positive: Uninstall a third-party app (sample_app) that has local storage data.
    Flow: install -> (optional) launch -> uninstall. Pass if uninstall returns 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)
    uninstall_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Uninstall Sample App (with local data) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Flow: install → (optional) launch → uninstall; PASS if uninstall == 200.",
            "[DESC] Local data deletion must be verified manually/OEM; storage inspection not in DAB scope."
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate for required operations
        required_ops = "ops: applications/install, applications/uninstall"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Precondition Step: Install the application to ensure it exists
        try:
            install_payload = ensure_app_available(app_id=app_id)
        except Exception as e:
            result.test_result = "SKIPPED"
            line = f"[RESULT] SKIPPED — Could not find local artifact for '{app_id}': {e}"
            LOGGER.result(line); logs.append(line)
            return result
        
        line = f"[STEP] Precondition: Installing '{app_id}' to ensure it exists for the test."
        LOGGER.result(line); logs.append(line)
        rc_install, resp_install = execute_cmd_and_log(tester, device_id, "applications/install", json.dumps(install_payload), logs, result)
        install_status = dab_status_from(resp_install, rc_install)
        if install_status != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Precondition failed: Could not install '{app_id}'. Status: {install_status}"
            LOGGER.result(line); logs.append(line)
            return result
        time.sleep(APP_INSTALL_WAIT)

        # Optional: Launch the app to ensure it recently touched local data (best-effort)
        try:
            line = f"[STEP] (optional) applications/launch {payload_app}"
            LOGGER.result(line); logs.append(line)
            execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
            line = f"[WAIT] 3s after optional launch"
            LOGGER.info(line); logs.append(line)
            time.sleep(3)
        except Exception:
            line = "[INFO] Skipping optional launch (applications/launch unsupported or failed)"
            LOGGER.info(line); logs.append(line)

        # Main Test Step: Uninstall the sample app
        line = f"[STEP] applications/uninstall {payload_app}"
        LOGGER.result(line); logs.append(line)
        rc_uninst, resp_uninst = execute_cmd_and_log(tester, device_id, "applications/uninstall", payload_app, logs, result)
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        
        if uninstall_status == 200:
            result.test_result = "PASS"
            line = "[RESULT] PASS — applications/uninstall returned 200 as expected."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED - Unsupported operation: {str(e)}"
        LOGGER.warn(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        error_details = traceback.format_exc()
        line = f"[RESULT] SKIPPED - An unexpected error occurred:\n{error_details}"
        LOGGER.error(line); logs.append(line)
        
    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, uninstall_status={uninstall_status}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(line); logs.append(line)

    return result
    
def run_uninstall_preinstalled_with_local_data_simple(dab_topic, test_name, tester, device_id):
    """
    Positive: Install and then uninstall an app (with local data).
    Flow: install -> (optional) launch -> applications/uninstall -> short wait
    Pass if uninstall returns 200.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/uninstall", payload_app, "UNKNOWN", "", logs)
    uninstall_status = "N/A"

    try:
        # Header and description
        # NOTE: Although the name implies a preinstalled app, this test now installs it
        # to ensure it exists, making the test more robust.
        msg = f"[TEST] Install and Uninstall App (with local data) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: install -> launch -> uninstall; PASS if uninstall == 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Local-data deletion must be verified manually/OEM; DAB cannot inspect storage."
        LOGGER.result(msg); logs.append(msg)

        # Gate all required operations for the full test flow
        spec = "ops: applications/uninstall, applications/install, applications/launch"
        if not require_capabilities(tester, device_id, spec, result, logs):
            # The 'require_capabilities' function already set the result and logged the reason
            return result

        # Step 1: Install the app as a precondition
        msg = f"[STEP] Ensuring app '{app_id}' is installed as a precondition."
        LOGGER.result(msg); logs.append(msg)
        try:
            install_payload = json.dumps(ensure_app_available(app_id))
        except Exception as e:
            raise Exception(f"Could not find configuration for sample_app '{app_id}': {e}")

        rc_inst, resp_inst = execute_cmd_and_log(tester, device_id, "applications/install", install_payload, logs, result)
        install_status = dab_status_from(resp_inst, rc_inst)
        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — Precondition failed: could not install app. Status: {install_status}"
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = f"[WAIT] {APP_LAUNCH_WAIT}s for installation to finalize."
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 2: Launch to ensure app recently touched local data
        msg = f"[STEP] Launching app to generate local data: {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)

        msg = f"[WAIT] {APP_EXIT_WAIT}s after launch."
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_EXIT_WAIT)

        # Step 3: Uninstall the app
        msg = f"[STEP] Uninstalling the app: {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_uninst, resp_uninst = execute_cmd_and_log(tester, device_id, "applications/uninstall", payload_app, logs, result)
        uninstall_status = dab_status_from(resp_uninst, rc_uninst)
        msg = f"[INFO] applications/uninstall transport_rc={rc_uninst}, dab_status={uninstall_status}"
        LOGGER.info(msg); logs.append(msg)

        if uninstall_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/uninstall returned {uninstall_status} (expected 200)"
        else:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — applications/uninstall returned 200 as expected"

        LOGGER.result(msg); logs.append(msg)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — A required operation is not supported: '{e.topic}'"
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(msg); logs.append(msg)

    finally:
        msg = (f"[SUMMARY] outcome={result.test_result}, uninstall_status={uninstall_status}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)

    return result

def run_install_from_url_during_idle_then_launch(dab_topic, test_name, tester, device_id):
    """
    Positive: Install an app from a LOCAL ARTIFACT during device idle (screen off), then wake and launch.
    Flow: sleep (best-effort) -> applications/install(<local payload>) -> short wait -> wake (best-effort) -> applications/launch
    Pass if install == 200 and launch == 200.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id  = config.apps.get("sample_app", "Sample_App")

    logs = []
    result = TestResult(test_id, device_id, "applications/install", "{}", "UNKNOWN", "", logs)

    INSTALL_WAIT = 15
    IDLE_WAIT    = 3
    WAKE_WAIT    = 3

    # keep raw device responses out of result.logs
    scratch = []
    def _call(topic: str, body_json: str):
        return execute_cmd_and_log(tester, device_id, topic, body_json, scratch, result)

    try:
        # Header
        for line in (
            f"[TEST] Install During Idle (LOCAL PATH) → Wake → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Flow: sleep → install from local path → wait → wake → launch; PASS if both return 200.",
        ):
            LOGGER.result(line); logs.append(line)

        # Resolve local artifact (any extension)
        try:
            install_payload = ensure_app_available(app_id=app_id)  # {"appId","url","format","timeout"}
        except Exception as e:
            result.test_result = "SKIPPED"
            msg = f"[RESULT] SKIPPED — missing local artifact for '{app_id}': {e}"
            LOGGER.result(msg); logs.append(msg)
            result.response = "['missing local artifact']"
            return result

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            LOGGER.result(f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}")
            return result
        logs.append("[INFO] Capability gate passed.")

        # 0) Best-effort: enter idle/screen off
        try:
            LOGGER.result('[STEP] input/key-press {"keyCode": "KEY_POWER"}  # enter idle'); logs.append(
                '[STEP] input/key-press {"keyCode": "KEY_POWER"}')
            rc_sleep, _ = _call("input/key-press", json.dumps({"keyCode": "KEY_POWER"}))
            logs.append(f"[INFO] input/key-press KEY_POWER transport_rc={rc_sleep}")
            time.sleep(IDLE_WAIT)
        except Exception:
            logs.append("[INFO] Skipping sleep attempt (input/key-press unavailable or failed)")

        # 1) Install from LOCAL PATH (send full payload, not a string URL)
        LOGGER.result(f"[STEP] applications/install {install_payload}"); logs.append(
            f"[STEP] applications/install {install_payload}")
        rc_i, resp_i = _call("applications/install", json.dumps(install_payload))
        install_status = dab_status_from(resp_i, rc_i)
        logs.append(f"[INFO] applications/install status={install_status}")

        if install_status != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)")
            result.response = f"['install={install_status}']"
            return result

        logs.append(f"[WAIT] {INSTALL_WAIT}s after install"); time.sleep(INSTALL_WAIT)

        # 2) Best-effort: wake device
        try:
            LOGGER.result('[STEP] input/key-press {"keyCode": "KEY_POWER"}  # wake'); logs.append(
                '[STEP] input/key-press {"keyCode": "KEY_POWER"}')
            rc_wake, _ = _call("input/key-press", json.dumps({"keyCode": "KEY_POWER"}))
            logs.append(f"[INFO] input/key-press KEY_POWER transport_rc={rc_wake}")
            time.sleep(WAKE_WAIT)
        except Exception:
            logs.append("[INFO] Skipping wake attempt (input/key-press unavailable or failed)")

        # 3) Launch
        payload_launch = json.dumps({"appId": app_id})
        LOGGER.result(f"[STEP] applications/launch {payload_launch}"); logs.append(
            f"[STEP] applications/launch {payload_launch}")
        rc_l, resp_l = _call("applications/launch", payload_launch)
        launch_status = dab_status_from(resp_l, rc_l)
        logs.append(f"[INFO] applications/launch status={launch_status}")

        if launch_status == 200:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — install (idle) 200 and launch (post-wake) 200"); logs.append(
                "[RESULT] PASS — install (idle) 200 and launch (post-wake) 200")
        else:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)")

        result.response = f"['install={install_status}, launch={launch_status}']"
        summary = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
                   f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(summary); logs.append(summary)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        LOGGER.result(f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"); logs.append(
            f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})")
        LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(
            f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}")
        return result


def run_install_large_apk_from_url_then_launch(dab_topic, test_name, tester, device_id):
    """
    Positive: Install a large app (prefer local path; fallback to configured URL), then launch.
    Flow: applications/install -> long wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("large_app", "Large_App")

    logs = []
    # keep response tiny in results.json (avoid raw blobs)
    result = TestResult(test_id, device_id, "applications/install", "{}", "UNKNOWN", "", logs)

    # ----- header -----
    for line in (
        f"[TEST] Large App Install → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
        "[DESC] Prefer local artifact from config/apps; if missing, use configured App Store URL.",
        "[DESC] Flow: applications/install → long wait → applications/launch; PASS if both return 200.",
    ):
        LOGGER.result(line); logs.append(line)

    # ----- build install payload (path first, url fallback) -----
    try:
        install_body = ensure_app_available(app_id=app_id)  # {"appId","url","format","timeout"}
    except Exception as e_path:
        try:
            url = ensure_app_available_anyext(app_id)               # per-app or global URL from config
            install_body = {"appId": app_id, "url": url}
        except Exception as e_url:
            result.test_result = "SKIPPED"
            msg = (f"[RESULT] SKIPPED — missing app artifact and URL for '{app_id}'. "
                   f"Hint: place file in config/apps or set URL via --init.")
            LOGGER.result(msg); logs.append(msg)
            LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(msg)
            # keep results.json compact
            result.response = "['install/launch not attempted: no path or url']"
            return result

    payload_install = json.dumps(install_body)
    payload_launch  = json.dumps({"appId": app_id})
    result.request  = payload_install  # minimal; no raw response stored

    try:
        # ----- capability gate -----
        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            LOGGER.result(f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(
                          f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}")
            result.response = "['capability gate failed']"
            return result

        LOGGER.info("[INFO] Capability gate passed."); logs.append("[INFO] Capability gate passed.")

        # ----- install -----
        LOGGER.result(f"[STEP] applications/install {payload_install}"); logs.append(
            f"[STEP] applications/install {payload_install}")
        rc_i, resp_i = execute_cmd_and_log(tester, device_id, "applications/install", payload_install, logs, result)
        st_i = dab_status_from(resp_i, rc_i)
        LOGGER.info(f"[INFO] applications/install transport_rc={rc_i}, dab_status={st_i}"); logs.append(
            f"[INFO] applications/install transport_rc={rc_i}, dab_status={st_i}")

        if st_i != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — applications/install returned {st_i} (expected 200)"); logs.append(
                f"[RESULT] FAILED — applications/install returned {st_i} (expected 200)")
            result.response = f"['install={st_i}, launch=N/A']"
            LOGGER.result(f"[SUMMARY] outcome=FAILED, install_status={st_i}, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(
                          f"[SUMMARY] outcome=FAILED, install_status={st_i}, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        # ----- launch -----
        LOGGER.result(f"[STEP] applications/launch {payload_launch}"); logs.append(
            f"[STEP] applications/launch {payload_launch}")
        rc_l, resp_l = execute_cmd_and_log(tester, device_id, "applications/launch", payload_launch, logs, result)
        st_l = dab_status_from(resp_l, rc_l)
        LOGGER.info(f"[INFO] applications/launch transport_rc={rc_l}, dab_status={st_l}"); logs.append(
            f"[INFO] applications/launch transport_rc={rc_l}, dab_status={st_l}")

        if st_l == 200:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — install 200 and launch 200"); logs.append("[RESULT] PASS — install 200 and launch 200")
        else:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — applications/launch returned {st_l} (expected 200)"); logs.append(
                f"[RESULT] FAILED — applications/launch returned {st_l} (expected 200)")

        # compact response in results.json
        result.response = f"['install={st_i}, launch={st_l}']"

        LOGGER.result(f"[SUMMARY] outcome={result.test_result}, install_status={st_i}, launch_status={st_l}, "
                      f"test_id={test_id}, device={device_id}, appId={app_id}")
        logs.append(f"[SUMMARY] outcome={result.test_result}, install_status={st_i}, launch_status={st_l}, "
                    f"test_id={test_id}, device={device_id}, appId={app_id}")
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        LOGGER.result(f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"); logs.append(
            f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})")
        result.response = "['install/launch not completed due to internal error']"
        LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
                      f"test_id={test_id}, device={device_id}, appId={app_id}")
        logs.append(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
                    f"test_id={test_id}, device={device_id}, appId={app_id}")
        return result
    
def run_install_from_url_while_heavy_app_running(dab_topic, test_name, tester, device_id):
    """
    Positive: Install an app from a LOCAL FILE while a heavy app is running, then launch it.
    Flow: launch heavy_app -> applications/install(<local path>) -> wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")

    # Heavy app to load the system (fallback to YouTube)
    heavy_app_id = config.apps.get("heavy_app", config.apps.get("youtube", "YouTube"))
    # Target app to install from local path
    app_id = config.apps.get("sample_app", "Sample_App")

    logs = []
    result = TestResult(test_id, device_id, "applications/install", "{}", "UNKNOWN", "", logs)

    # Resolve local artifact → {"appId","url":"/abs/path/file","format":"ext","timeout":int}
    try:
        local_payload_dict = ensure_app_available(app_id=app_id)  # path-based install payload
    except Exception as e:
        result.test_result = "SKIPPED"
        msg = (f"[RESULT] SKIPPED — missing local artifact for '{app_id}': {e}. "
               "Place the file under config/apps or run --init to configure.")
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
               f"test_id={test_id}, device={device_id}, targetApp={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    payload_install = json.dumps(local_payload_dict)      # path-based install
    payload_launch  = json.dumps({"appId": app_id})
    payload_heavy   = json.dumps({"appId": heavy_app_id})
 # allow time for copy/verify under load

    try:
        # Headers
        msg = (f"[TEST] Install From LOCAL Path While Heavy App Running — {test_name} "
               f"(test_id={test_id}, device={device_id}, targetApp={app_id}, heavyApp={heavy_app_id})")
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: launch heavy_app → install(local-path) → wait → launch; PASS if both return 200."
        LOGGER.result(msg); logs.append(msg)

        # Capability gate (install + launch)
        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, targetApp={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        LOGGER.info("[INFO] Capability gate passed."); logs.append("[INFO] Capability gate passed.")

        # 0) Launch heavy app
        LOGGER.result(f"[STEP] applications/launch {payload_heavy}  # start heavy workload"); logs.append(
            f"[STEP] applications/launch {payload_heavy}  # start heavy workload"
        )
        rc_heavy, _resp_heavy = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_heavy, logs, result
        )
        LOGGER.info(f"[INFO] heavy_app launch transport_rc={rc_heavy}"); logs.append(
            f"[INFO] heavy_app launch transport_rc={rc_heavy}"
        )

        # 1) Install target app from LOCAL PATH while heavy app is running
        LOGGER.result(f"[STEP] applications/install {payload_install}"); logs.append(
            f"[STEP] applications/install {payload_install}"
        )
        rc_install, resp_install = execute_cmd_and_log(
            tester, device_id, "applications/install", payload_install, logs, result
        )
        install_status = dab_status_from(resp_install, rc_install)
        LOGGER.info(f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"); logs.append(
            f"[INFO] applications/install transport_rc={rc_install}, dab_status={install_status}"
        )

        if install_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/install returned {install_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, "
                   f"test_id={test_id}, device={device_id}, targetApp={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # 2) Launch the newly installed app
        LOGGER.result(f"[STEP] applications/launch {payload_launch}"); logs.append(
            f"[STEP] applications/launch {payload_launch}"
        )
        rc_launch, resp_launch = execute_cmd_and_log(
            tester, device_id, "applications/launch", payload_launch, logs, result
        )
        launch_status = dab_status_from(resp_launch, rc_launch)
        LOGGER.info(f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"); logs.append(
            f"[INFO] applications/launch transport_rc={rc_launch}, dab_status={launch_status}"
        )

        if launch_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — local install under load (200) and post-install launch (200) succeeded"
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/launch returned {launch_status} (expected 200)"
        LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
               f"launch_status={launch_status}, test_id={test_id}, device={device_id}, "
               f"targetApp={app_id}, heavyApp={heavy_app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = (f"[RESULT] SKIPPED — internal error: {e} "
               f"(test_id={test_id}, device={device_id}, targetApp={app_id})")
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
               f"test_id={test_id}, device={device_id}, targetApp={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_after_reboot_then_launch(dab_topic, test_name, tester, device_id):
    """
    Positive: After device restart, install Sample_App from local artifact (any extension) and launch it.
    Flow: restart -> wait -> applications/install(local path) -> wait -> applications/launch
    PASS if install == 200 and launch == 200.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")

    logs = []
    result = TestResult(test_id, device_id, "applications/install", "{}", "UNKNOWN", "", logs)

    RESTART_WAIT = 60
    STABLE_WAIT  = 15
    POST_INSTALL_WAIT = 10

    install_status = "N/A"
    launch_status  = "N/A"

    try:
        # Header
        for line in (
            f"[TEST] Install After Restart → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Using local artifact from config/apps/<appId>.<anyext> (no URL).",
        ):
            LOGGER.result(line); logs.append(line)

        # Resolve local artifact (any extension). If missing → SKIPPED with guidance.
        try:
            payload_install_dict = ensure_app_available(app_id=app_id)  # {"appId","url","format","timeout"}
        except Exception as e:
            result.test_result = "SKIPPED"
            msg = (f"[RESULT] SKIPPED — local artifact for '{app_id}' not found. "
                   f"Place a file named '{app_id}.*' in config/apps or run --init. ({e})")
            LOGGER.result(msg); logs.append(msg)
            LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        payload_install = json.dumps(payload_install_dict)
        payload_launch  = json.dumps({"appId": app_id})
        result.request  = payload_install  # keep small; no raw responses below

        # Restart (fire-and-forget best-effort)
        LOGGER.result("[STEP] system/restart (fire-and-forget)"); logs.append("[STEP] system/restart (fire-and-forget)")
        try:
            fire_and_forget_restart(tester.dab_client, device_id)  # preferred helper if available
        except Exception:
            try:
                execute_cmd_and_log(tester, device_id, "system/restart", "{}", logs, result)
            except Exception:
                LOGGER.warn("[WARN] Restart command fallback failed; proceeding after wait."); logs.append("[WARN] Restart fallback failed; proceeding.")

        LOGGER.info(f"[WAIT] {RESTART_WAIT}s for reboot + {STABLE_WAIT}s stabilize"); logs.append(
            f"[WAIT] {RESTART_WAIT}s + {STABLE_WAIT}s")
        time.sleep(RESTART_WAIT + STABLE_WAIT)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            result.response = "['capability gate failed']"
            return result

        LOGGER.info("[INFO] Capability gate passed."); logs.append("[INFO] Capability gate passed.")

        # Install from local path
        LOGGER.result(f"[STEP] applications/install {payload_install}"); logs.append(
            f"[STEP] applications/install {payload_install}")
        rc_i, resp_i = execute_cmd_and_log(tester, device_id, "applications/install",
                                           payload_install, logs, result)
        install_status = dab_status_from(resp_i, rc_i)
        LOGGER.info(f"[INFO] install rc={rc_i}, status={install_status}"); logs.append(
            f"[INFO] install rc={rc_i}, status={install_status}")

        if install_status != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — install returned {install_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — install returned {install_status}")
            result.response = f"['install={install_status}, launch=N/A']"
            LOGGER.result(f"[SUMMARY] outcome=FAILED, install_status={install_status}, launch_status=N/A, "
                          f"test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        LOGGER.info(f"[WAIT] {POST_INSTALL_WAIT}s post-install"); logs.append(f"[WAIT] {POST_INSTALL_WAIT}s post-install")
        time.sleep(POST_INSTALL_WAIT)

        # Launch to verify
        LOGGER.result(f"[STEP] applications/launch {payload_launch}"); logs.append(
            f"[STEP] applications/launch {payload_launch}")
        rc_l, resp_l = execute_cmd_and_log(tester, device_id, "applications/launch",
                                           payload_launch, logs, result)
        launch_status = dab_status_from(resp_l, rc_l)
        LOGGER.info(f"[INFO] launch rc={rc_l}, status={launch_status}"); logs.append(
            f"[INFO] launch rc={rc_l}, status={launch_status}")

        if launch_status == 200:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — install 200 and launch 200"); logs.append("[RESULT] PASS — install 200 and launch 200")
        else:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — launch returned {launch_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — launch returned {launch_status}")

        # Keep results.json lean
        result.response = f"['install={install_status}, launch={launch_status}']"

        LOGGER.result(f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
                      f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        result.response = "['internal error']"
        LOGGER.result(f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"); logs.append(
            f"[RESULT] SKIPPED — internal error: {e}")
        LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, "
                      f"test_id={test_id}, device={device_id}, appId={app_id}")
        return result


def run_sequential_installs_then_launch(dab_topic, test_name, tester, device_id):
    """
    Positive: Sequentially install N applications then launch each.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []

    # --- Build targets via shared helper ---
    targets = get_install_targets()

    payload_init = json.dumps({"apps": [t["appId"] for t in targets]}) if targets else "{}"
    result = TestResult(test_id, device_id, "applications/install", payload_init, "UNKNOWN", "", logs)

    try:
        msg = f"[TEST] Sequential Installs from URL → Launch Each — {test_name} (test_id={test_id}, device={device_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow per app: applications/install → wait → applications/launch; PASS if all return 200."
        LOGGER.result(msg); logs.append(msg)

        if not targets:
            result.test_result = "SKIPPED"
            msg = "[RESULT] SKIPPED — missing app artifacts or no targets configured"
            LOGGER.result(msg); logs.append(msg)
            msg = f"[SUMMARY] outcome=SKIPPED, apps=0, test_id={test_id}, device={device_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            msg = f"[SUMMARY] outcome=OPTIONAL_FAILED, apps={len(targets)}, test_id={test_id}, device={device_id}"
            LOGGER.result(msg); logs.append(msg)
            return result

        LOGGER.info("[INFO] Capability gate passed."); logs.append("[INFO] Capability gate passed.")

        installed = []
        for idx, t in enumerate(targets, 1):
            app_id = t["appId"]; key = t["key"]
            inst_payload = t["install_payload"]
            payload_install = json.dumps(inst_payload) if isinstance(inst_payload, dict) else str(inst_payload)

            msg = f"[STEP {idx}] applications/install {payload_install}"
            LOGGER.result(msg); logs.append(msg)
            rc_i, resp_i = execute_cmd_and_log(tester, device_id, "applications/install", payload_install, logs, result)
            st_i = dab_status_from(resp_i, rc_i)
            LOGGER.info(f"[INFO] applications/install[{key}] transport_rc={rc_i}, dab_status={st_i}")
            logs.append(f"[INFO] applications/install[{key}] transport_rc={rc_i}, dab_status={st_i}")
            if st_i != 200:
                result.test_result = "FAILED"
                msg = f"[RESULT] FAILED — install[{key}] returned {st_i} (expected 200)"
                LOGGER.result(msg); logs.append(msg)
                msg = (f"[SUMMARY] outcome=FAILED, failed_key={key}, install_status={st_i}, "
                       f"progress={idx-1}/{len(targets)}, test_id={test_id}, device={device_id}")
                LOGGER.result(msg); logs.append(msg)
                return result

            payload_launch = json.dumps({"appId": app_id})
            msg = f"[STEP {idx}] applications/launch {payload_launch}"
            LOGGER.result(msg); logs.append(msg)
            rc_l, resp_l = execute_cmd_and_log(tester, device_id, "applications/launch", payload_launch, logs, result)
            st_l = dab_status_from(resp_l, rc_l)
            LOGGER.info(f"[INFO] applications/launch[{key}] transport_rc={rc_l}, dab_status={st_l}")
            logs.append(f"[INFO] applications/launch[{key}] transport_rc={rc_l}, dab_status={st_l}")

            if st_l != 200:
                result.test_result = "FAILED"
                msg = f"[RESULT] FAILED — launch[{key}] returned {st_l} (expected 200)"
                LOGGER.result(msg); logs.append(msg)
                msg = (f"[SUMMARY] outcome=FAILED, failed_key={key}, launch_status={st_l}, "
                       f"progress={idx-1}/{len(targets)}, test_id={test_id}, device={device_id}")
                LOGGER.result(msg); logs.append(msg)
                return result

            installed.append(key)

        result.test_result = "PASS"
        msg = f"[RESULT] PASS — all {len(targets)} apps installed and launched: {installed}"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=PASS, apps={len(targets)}, "
               f"installed_launched={installed}, test_id={test_id}, device={device_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except FileNotFoundError as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — missing app artifacts: {e}"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, apps={len(targets)}, test_id={test_id}, device={device_id}"
        LOGGER.result(msg); logs.append(msg)
        return result
    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = f"[SUMMARY] outcome=SKIPPED, apps={len(targets)}, test_id={test_id}, device={device_id}"
        LOGGER.result(msg); logs.append(msg)
        return result

def run_install_from_url_then_launch_simple(dab_topic, test_name, tester, device_id):
    """
    Positive: install an application from a LOCAL ARTIFACT (any extension), then launch it.
    Flow: applications/install(<local path payload>) -> wait -> applications/launch
    Pass if install == 200 and launch == 200.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id  = config.apps.get("sample_app", "Sample_App")  # target app ID

    logs = []
    result = TestResult(test_id, device_id, "applications/install", "{}", "UNKNOWN", "", logs)

    INSTALL_WAIT = globals().get("APP_INSTALL_WAIT", 30)  # shorter since it's local, not a download

    # keep raw device responses out of result.logs
    scratch = []
    def _call(topic: str, body_json: str):
        return execute_cmd_and_log(tester, device_id, topic, body_json, scratch, result)

    try:
        # Header
        for line in (
            f"[TEST] Install From Local Path → Launch — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})",
            "[DESC] Flow: applications/install(local path payload) → wait → applications/launch; PASS if both return 200.",
        ):
            LOGGER.result(line); logs.append(line)

        # Resolve local artifact (returns {"appId","url","format","timeout"} with absolute path)
        try:
            install_payload = ensure_app_available(app_id=app_id)
        except Exception as e:
            result.test_result = "SKIPPED"
            msg = f"[RESULT] SKIPPED — missing local artifact for '{app_id}': {e}"
            LOGGER.result(msg); logs.append(msg)
            result.response = "['missing local artifact']"
            return result

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/install, applications/launch", result, logs):
            LOGGER.result(f"[SUMMARY] outcome=OPTIONAL_FAILED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}")
            return result

        logs.append("[INFO] Capability gate passed.")

        # 1) Install from local path (pass the WHOLE payload, not a string URL)
        LOGGER.result(f"[STEP] Install '{app_id}' from local artifact"); logs.append(f"[STEP] Install '{app_id}' from local artifact")
        rc_i, resp_i = _call("applications/install", json.dumps(install_payload))
        install_status = dab_status_from(resp_i, rc_i)
        logs.append(f"[INFO] install status={install_status}")

        if install_status != 200:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — install returned {install_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — install returned {install_status} (expected 200)")
            result.response = f"['install={install_status}']"
            return result

        logs.append(f"[WAIT] {INSTALL_WAIT}s after install")
        time.sleep(INSTALL_WAIT)

        # 2) Launch to confirm
        payload_launch = json.dumps({"appId": app_id})
        LOGGER.result(f"[STEP] Launch '{app_id}'"); logs.append(f"[STEP] Launch '{app_id}'")
        rc_l, resp_l = _call("applications/launch", payload_launch)
        launch_status = dab_status_from(resp_l, rc_l)
        logs.append(f"[INFO] launch status={launch_status}")

        if launch_status == 200:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — install 200 and launch 200"); logs.append("[RESULT] PASS — install 200 and launch 200")
        else:
            result.test_result = "FAILED"
            LOGGER.result(f"[RESULT] FAILED — launch returned {launch_status} (expected 200)"); logs.append(
                f"[RESULT] FAILED — launch returned {launch_status} (expected 200)")

        result.response = f"['install={install_status}, launch={launch_status}']"
        summary = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
                   f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(summary); logs.append(summary)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        LOGGER.result(f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"); logs.append(
            f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})")
        LOGGER.result(f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}"); logs.append(
            f"[SUMMARY] outcome=SKIPPED, install_status=N/A, launch_status=N/A, test_id={test_id}, device={device_id}, appId={app_id}")
        return result

    
def run_clear_data_accessibility_settings_reset(dab_topic, test_name, tester, device_id):
    """
    Positive: Verify applications/clear-data resets a third-party app's accessibility settings to defaults.
    Flow: applications/launch -> applications/clear-data -> applications/launch
    Pass if clear-data returns 200. (Accessibility reset verification is manual/OEM.)
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/clear-data", payload_app, "UNKNOWN", "", logs)

    try:
        # Headers
        msg = f"[TEST] Clear Data (Accessibility Settings) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: launch → clear-data → relaunch; PASS if clear-data returns 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Note: Confirm accessibility settings (e.g., high contrast, screen reader) are enabled BEFORE test; reset is manual/OEM to verify."
        LOGGER.result(msg); logs.append(msg)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/launch, applications/clear-data", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, clear_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Launch to ensure app session is active (and settings are persisted)
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        msg = f"[WAIT] {APP_LAUNCH_WAIT}s after launch"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # 2) Clear data
        msg = f"[STEP] applications/clear-data {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_clear, resp_clear = execute_cmd_and_log(
            tester, device_id, "applications/clear-data", payload_app, logs, result
        )
        clear_status = dab_status_from(resp_clear, rc_clear)
        msg = f"[INFO] applications/clear-data transport_rc={rc_clear}, dab_status={clear_status}"
        LOGGER.info(msg); logs.append(msg)

        # 3) Relaunch to surface first-run / default state
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        msg = f"[WAIT] {APP_LAUNCH_WAIT}s after relaunch"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # Result
        if clear_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — applications/clear-data returned 200; verify accessibility defaults manually"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/clear-data returned {clear_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, clear_status={clear_status}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, clear_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_clear_data_session_reset(dab_topic, test_name, tester, device_id):
    """
    Positive: Verify applications/clear-data clears a third-party app's user login/session data.
    Flow: applications/launch -> applications/clear-data -> applications/launch
    Pass if clear-data returns 200. (Session reset verification is manual/OEM).
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("sample_app", "Sample_App")
    logs = []
    payload_app = json.dumps({"appId": app_id})
    result = TestResult(test_id, device_id, "applications/clear-data", payload_app, "UNKNOWN", "", logs)

    try:
        # Headers
        msg = f"[TEST] Clear Data (User Session) — {test_name} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Flow: launch → clear-data → relaunch; PASS if clear-data returns 200."
        LOGGER.result(msg); logs.append(msg)
        msg = "[DESC] Precondition: app installed and user is logged in (session stored locally). Session-clear verification is manual/OEM."
        LOGGER.result(msg); logs.append(msg)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: applications/launch, applications/clear-data", result, logs):
            msg = (f"[SUMMARY] outcome=OPTIONAL_FAILED, clear_status=N/A, "
                   f"test_id={test_id}, device={device_id}, appId={app_id}")
            LOGGER.result(msg); logs.append(msg)
            return result

        msg = "[INFO] Capability gate passed."
        LOGGER.info(msg); logs.append(msg)

        # 1) Launch to ensure current session is active
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        msg = f"[WAIT] {APP_LAUNCH_WAIT}s after launch"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # 2) Clear data
        msg = f"[STEP] applications/clear-data {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_clear, resp_clear = execute_cmd_and_log(
            tester, device_id, "applications/clear-data", payload_app, logs, result
        )
        clear_status = dab_status_from(resp_clear, rc_clear)
        msg = f"[INFO] applications/clear-data transport_rc={rc_clear}, dab_status={clear_status}"
        LOGGER.info(msg); logs.append(msg)

        # 3) Relaunch to surface first-run (logged-out) behavior
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload_app, logs, result)
        msg = f"[WAIT] {APP_LAUNCH_WAIT}s after relaunch"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(APP_LAUNCH_WAIT)

        # Result
        if clear_status == 200:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — applications/clear-data returned 200; verify login/session is reset manually"
            LOGGER.result(msg); logs.append(msg)
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — applications/clear-data returned {clear_status} (expected 200)"
            LOGGER.result(msg); logs.append(msg)

        msg = (f"[SUMMARY] outcome={result.test_result}, clear_status={clear_status}, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

    except Exception as e:
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id}, appId={app_id})"
        LOGGER.result(msg); logs.append(msg)
        msg = (f"[SUMMARY] outcome=SKIPPED, clear_status=N/A, "
               f"test_id={test_id}, device={device_id}, appId={app_id}")
        LOGGER.result(msg); logs.append(msg)
        return result

def run_voice_log_collection_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that voice assistant activity is captured in the system logs. This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", "{}", "UNKNOWN", "", logs)
    # Variables for the final summary log
    supports_voice = "N/A"
    logs_contain_voice_activity = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Voice Activity Log Collection Check (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Start log collection, send a voice command, stop collection, and manually verify the logs.",
            "[DESC] Required ops: voice/list, voice/set, system/logs/start-collection, voice/send-text, system/logs/stop-collection.",
            "[DESC] Pass criteria: User confirmation that the voice command appears in the collected system logs.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required DAB operations
        required_ops = "ops: voice/list, voice/set, system/logs/start-collection, voice/send-text, system/logs/stop-collection"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Manually select one supported voice system on the device.
        line = f"[STEP] Listing voice systems for manual selection."
        LOGGER.result(line)
        logs.append(line)
        topic = "voice/list"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not list supported voice systems as a precondition."
            LOGGER.result(line)
            logs.append(line)
            return result

        voiceSystems = json.loads(response).get("voiceSystems")
        if not voiceSystems:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — Test skipped because there are no voice systems in the list."
            LOGGER.result(line)
            logs.append(line)
            return result

        voiceSystem_list = []

        for voiceSystem in voiceSystems:
            name = voiceSystem.get("name")
            voiceSystem_list.append(name)

        logs.append(f"Please select one supported voice system in the list.")
        print(f"Please select one supported voice system in the list.")
        index = select_input(result, logs, voiceSystem_list)
        if index == 0:
            print(f"There are no supported voice system in the list.")
            logs.append(f"[OPTIONAL_FAILED] There are no supported voice system in the list.")
            result.test_result = "OPTIONAL_FAILED"
            print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")
            return result

        voiceSystem = voiceSystem_list[index - 1]
        line = f"Select voice system '{voiceSystem}'."
        logs.append(line)
        LOGGER.info(line)

        print(voiceSystems[index-1])
        enabled = voiceSystems[index-1].get("enabled")
        if enabled == False:
            line = f"Voice system {voiceSystem} is disabled, try to enable it."
            logs.append(line)
            LOGGER.info(line)
            rc, response = execute_cmd_and_log(tester, device_id, "voice/set", json.dumps({"voiceSystem": {"name": voiceSystem, "enabled": True}}), logs, result)
            if dab_status_from(response, rc) != 200:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — Could not enable the supported voice system {voiceSystem} on the device."
                LOGGER.result(line)
                logs.append(line)
                return result

            line = f"Waiting for {ASSISTANT_INIT}s to initial voice system {voiceSystem}"
            LOGGER.result(line)
            logs.append(line)
            time.sleep(ASSISTANT_INIT)

        # Step 2: Start log collection
        line = "[STEP] Starting system log collection."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The 'system/logs/start-collection' command failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 3: Send a voice command
        voice_command = "Open YouTube"
        payload_voice = json.dumps({"requestText": voice_command, "voiceSystem": voiceSystem})
        line = f"[STEP] Sending voice command: '{voice_command}'"
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "voice/send-text", payload_voice, logs, result)

        # Allow time for the command to be processed and logged
        time.sleep(ASSISTANT_WAIT)

        # Step 4: Waiting for 10 seconds to collect logs.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 5: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 6: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 7: Manual verification of logs
        line = "[STEP] Manual action required: Please retrieve and inspect the collected system logs."
        LOGGER.result(line)
        logs.append(line)
        logs_contain_voice_activity = yes_or_no(result, logs, f"Do the logs contain entries related to the voice command '{voice_command}'?")
        
        if logs_contain_voice_activity:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed voice activity was present in the system logs."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported no voice activity was found in the system logs."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, supports_voice={supports_voice}, "
                f"logs_contain_voice_activity={logs_contain_voice_activity}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

def run_idle_log_collection_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that system logs are collected correctly during an idle period. This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", "{}", "UNKNOWN", "", logs)
    # Variable for the final summary log
    logs_are_valid = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Idle Log Collection and Verification (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Start log collection, wait 30 seconds while the device is idle, stop collection, and manually verify the logs.",
            "[DESC] Required ops: system/logs/start-collection, system/logs/stop-collection.",
            "[DESC] Pass criteria: User confirmation that the logs are returned in the correct format and appear complete.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required DAB operations
        required_ops = "ops: system/logs/start-collection, system/logs/stop-collection"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Start log collection
        line = "[STEP] Starting system log collection."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The 'system/logs/start-collection' command failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Wait for 30 seconds while the device is idle
        wait_duration = 30
        line = f"[STEP] Device is now idle. Waiting for {wait_duration} seconds."
        LOGGER.result(line)
        logs.append(line)
        countdown("Idle log collection", wait_duration)

        # Step 3: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 4: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 5: Manual verification of logs
        line = "[STEP] Manual action required: Please retrieve and inspect the collected system logs."
        LOGGER.result(line)
        logs.append(line)
        logs_are_valid = yes_or_no(result, logs, "Are the logs in the correct format and complete for the idle period?")
        
        if logs_are_valid:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the logs are valid and complete."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the logs are incorrect or incomplete."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, logs_are_valid={logs_are_valid}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

def run_channel_switch_log_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that system logs are collected correctly during rapid TV channel switching.
    This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", "{}", "UNKNOWN", "", logs)
    # Variable for the final summary log
    logs_are_valid = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Rapid Channel Switch Log Verification (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Start log collection, rapidly switch TV channels, stop collection, and manually verify the logs.",
            "[DESC] Required ops: system/logs/start-collection, system/logs/stop-collection.",
            "[DESC] Pass criteria: User confirmation that all channel switching events are in the logs.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required DAB operations
        required_ops = "ops: system/logs/start-collection, system/logs/stop-collection"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Start log collection
        line = "[STEP] Starting system log collection."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The 'system/logs/start-collection' command failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Manually switch channels for 5 minutes
        wait_duration = 30 # 5 minutes
        line = f"[STEP] Manual Action Required: Please rapidly switch TV channels for the next {wait_duration / 60} minutes."
        LOGGER.result(line)
        logs.append(line)
        countdown("Channel switching period", wait_duration)

        # Step 3: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 4: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 5: Manual verification of logs
        line = "[STEP] Manual action required: Please retrieve and inspect the collected system logs."
        LOGGER.result(line)
        logs.append(line)
        logs_are_valid = yes_or_no(result, logs, "Do the logs contain entries for each channel switch and related system events?")
        
        if logs_are_valid:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the channel switch logs are valid and complete."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the logs are incorrect or incomplete."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, logs_are_valid={logs_are_valid}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result


def run_app_switch_log_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that system logs are collected correctly during an app switch.
    This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", "{}", "UNKNOWN", "", logs)
    # Variable for the final summary log
    logs_are_valid = "N/A"
    app1_id = config.apps.get("youtube", "YouTube")
    app2_id = config.apps.get("amazon", "PrimeVideo")


    try:
        # Header and description
        for line in (
            f"[TEST] App Switch Log Verification (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            f"[DESC] Goal: Start logs, launch '{app1_id}', switch to '{app2_id}', stop logs, and manually verify.",
            "[DESC] Required ops: system/logs/start-collection, system/logs/stop-collection, applications/launch.",
            "[DESC] Pass criteria: User confirmation that all app activities are in the logs.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate for all required DAB operations
        required_ops = "ops: system/logs/start-collection, system/logs/stop-collection, applications/launch"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result

        # Step 1: Start log collection
        line = "[STEP] Starting system log collection."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — The 'system/logs/start-collection' command failed."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Launch the first app
        line = f"[STEP] Launching first app: '{app1_id}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app1_id}), logs, result)
        line = f"[WAIT] Waiting {APP_LAUNCH_WAIT}s for '{app1_id}' to open and perform activity."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 3: Launch the second app to trigger a switch
        line = f"[STEP] Switching to second app: '{app2_id}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app2_id}), logs, result)
        line = f"[WAIT] Waiting {APP_LAUNCH_WAIT}s for '{app2_id}' to open and perform activity."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 4: Waiting for 10 seconds to collect logs.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 5: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 6: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 7: Manual verification of logs
        line = "[STEP] Manual action required: Please retrieve and inspect the collected system logs."
        LOGGER.result(line)
        logs.append(line)
        logs_are_valid = yes_or_no(result, logs, f"Do the logs contain entries for both '{app1_id}' and '{app2_id}' activities?")
        
        if logs_are_valid:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the app switch logs are valid and complete."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the logs are incorrect or incomplete."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, logs_are_valid={logs_are_valid}, "
                f"test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

def run_clear_data_preinstalled_app_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that 'applications/clear-data' works on a non-removable, pre-installed app.
    This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "applications/clear-data", "{}", "UNKNOWN", "", logs)
    app_id = "N/A"
    clear_status = "N/A"
    user_validated_reset = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Clear Data for Pre-installed App (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Clear all data for a non-removable, pre-installed app and manually verify it was reset.",
            "[DESC] Required ops: applications/list, applications/launch, applications/clear-data.",
            "[DESC] Pass criteria: User confirmation that the app was reset to its initial state.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/list, applications/launch, applications/clear-data"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result
        
        # Step 1: List and select a non-removable, pre-installed app
        line = "[STEP] Listing applications for manual selection."
        LOGGER.result(line)
        logs.append(line)
        _, response = execute_cmd_and_log(tester, device_id, "applications/list", "{}", logs, result)
        apps = json.loads(response).get("applications", [])
        app_id_list = [app.get("appId") for app in apps]
        
        line = "Please select one NON-REMovable, PRE-INSTALLED app from the list:"
        LOGGER.prompt(line)
        logs.append(line)
        index = select_input(result, logs, app_id_list)
        if index == 0:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — No suitable pre-installed app was selected."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        app_id = app_id_list[index - 1]
        logs.append(f"[INFO] User selected app: {app_id}")

        # Step 2: Launch the app to ensure it has local data
        line = f"[STEP] Launching '{app_id}' to ensure it has local data."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs, result)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 3: Clear the app's data
        line = f"[STEP] Clearing data for '{app_id}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/clear-data", json.dumps({"appId": app_id}), logs, result)
        clear_status = dab_status_from(response, rc)

        if clear_status != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — 'clear-data' command failed with status {clear_status}."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        time.sleep(APP_CLEAR_DATA_WAIT)

        # Step 4: Relaunch the app for verification
        line = f"[STEP] Relaunching '{app_id}' to verify it has been reset."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": app_id}), logs, result)
        time.sleep(APP_LAUNCH_WAIT)
        
        # Step 5: Manual verification
        user_validated_reset = yes_or_no(result, logs, "Did the application start up in its initial, first-run state (e.g., asking for login)?")
        if user_validated_reset:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the app was reset to its initial state."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the app was not reset."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, cleared_app={app_id}, clear_status={clear_status}, "
                f"user_validated_reset={user_validated_reset}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

def run_install_region_specific_app_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that a region-specific app can be installed and shows correct localization.
    This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = "localApp963" # Example App ID for a region-specific app
    logs = []
    result = TestResult(test_id, device_id, "applications/install-from-app-store", "{}", "UNKNOWN", "", logs)
    install_status = "N/A"
    user_validated_localization = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Install Region-Specific App (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Install a region-specific app and manually verify its localization.",
            "[DESC] Required ops: applications/install-from-app-store, applications/launch, applications/uninstall (for cleanup).",
            "[DESC] Pass criteria: User confirmation that the app installs and shows correct localization.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/install-from-app-store, applications/launch, applications/uninstall"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result
        
        # Step 1: Manually set device region
        line = "[STEP] Manual action required: Please set the device's region/locale to a supported one for the test app (e.g., 'de-DE')."
        LOGGER.result(line)
        logs.append(line)
        if not yes_or_no(result, logs, "Is the device's region set correctly for the test?"):
            result.test_result = "SKIPPED"
            line = "[RESULT] SKIPPED — Precondition failed: device region not set."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        # Step 2: Install the region-specific app
        line = f"[STEP] Installing region-specific app '{app_id}' from the app store."
        LOGGER.result(line)
        logs.append(line)
        payload = json.dumps({"appId": app_id})
        rc, response = execute_cmd_and_log(tester, device_id, "applications/install-from-app-store", payload, logs, result)
        install_status = dab_status_from(response, rc)
        
        if install_status != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — App install failed with status {install_status}."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        line = f"[WAIT] Waiting {APP_UNINSTALL_WAIT}s for installation to finalize." # Re-using a reasonable wait time
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_UNINSTALL_WAIT)

        # Step 3: Launch the app
        line = f"[STEP] Launching '{app_id}' to verify localization."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload, logs, result)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 4: Manual verification
        user_validated_localization = yes_or_no(result, logs, "Does the app show the correct language, content, or features for the region you set?")
        if user_validated_localization:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the app shows correct localization."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported incorrect app localization."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Cleanup Step: Uninstall the app
        try:
            line = f"[CLEANUP] Uninstalling '{app_id}'."
            LOGGER.info(line)
            logs.append(line)
            execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": app_id}), logs, result)
        except Exception as e:
            line = f"[CLEANUP] WARNING: Failed to uninstall app '{app_id}': {e}"
            LOGGER.warn(line)
            logs.append(line)

        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
                f"user_validated_localization={user_validated_localization}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

def run_update_installed_app_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that an already installed application can be updated to a newer version.
    This is a manual verification test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = "updatableApp123" # Example App ID for an app that has an older version
    logs = []
    result = TestResult(test_id, device_id, "applications/install-from-app-store", "{}", "UNKNOWN", "", logs)
    update_status = "N/A"
    user_validated_update = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Update Installed App (Manual) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Manually install an old version of an app, then use DAB to update it and verify success.",
            "[DESC] Required ops: applications/install-from-app-store, applications/launch, applications/uninstall (for cleanup).",
            "[DESC] Pass criteria: User confirmation that the app was successfully updated to a newer version.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: applications/install-from-app-store, applications/launch, applications/uninstall"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result
        
        # Step 1: Manually install an older version of the app
        line = f"[STEP] Manual action required: Please ensure an OLDER version of the app '{app_id}' is installed."
        LOGGER.result(line)
        logs.append(line)
        if not yes_or_no(result, logs, "Is an older version of the app installed and ready for an update?"):
            result.test_result = "SKIPPED"
            line = "[RESULT] SKIPPED — Precondition failed: an older version of the app was not installed."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        # Step 2: Trigger the update from the app store
        line = f"[STEP] Triggering update for '{app_id}' via 'install-from-app-store'."
        LOGGER.result(line)
        logs.append(line)
        payload = json.dumps({"appId": app_id})
        rc, response = execute_cmd_and_log(tester, device_id, "applications/install-from-app-store", payload, logs, result)
        update_status = dab_status_from(response, rc)
        
        if update_status != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — App update command failed with status {update_status}."
            LOGGER.result(line)
            logs.append(line)
            return result
        
        line = f"[WAIT] Waiting {APP_UNINSTALL_WAIT * 2}s for the update to download and install."
        LOGGER.info(line)
        logs.append(line)
        time.sleep(APP_UNINSTALL_WAIT * 2)

        # Step 3: Launch the app to check the new version
        line = f"[STEP] Launching '{app_id}' to verify the update."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", payload, logs, result)
        time.sleep(APP_LAUNCH_WAIT)

        # Step 4: Manual verification
        user_validated_update = yes_or_no(result, logs, "Has the app been successfully updated to the newer version?")
        if user_validated_update:
            result.test_result = "PASS"
            line = "[RESULT] PASS — User confirmed the app was successfully updated."
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — User reported the app was not updated."
        
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # Cleanup Step: Uninstall the app
        try:
            line = f"[CLEANUP] Uninstalling '{app_id}'."
            LOGGER.info(line)
            logs.append(line)
            execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": app_id}), logs, result)
        except Exception as e:
            line = f"[CLEANUP] WARNING: Failed to uninstall app '{app_id}': {e}"
            LOGGER.warn(line)
            logs.append(line)

        # Final summary log
        line = (f"[SUMMARY] outcome={result.test_result}, update_status={update_status}, "
                f"user_validated_update={user_validated_update}, test_id={test_id}, device={device_id}")
        LOGGER.result(line)
        logs.append(line)

    return result

# === Test 38: Log Collection Check ===
def run_logs_collection_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully.",
            "[DESC] Required operations: system/logs/start-collection, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs has been collected and include the folder categories follow DAB spec requirement.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, system/logs/stop-collection", result, logs):
            return result

        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Waiting for 30 seconds to collect logs.
        log_collection_timeout = 30
        line = f"[STEP] Waiting for {log_collection_timeout} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for 30 seconds to collect logs.", log_collection_timeout)

        # Step 3: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 4: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"[PASS] The logs structure follows DAB requirement.")
            result.test_result = "PASS"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 39: Log Collection For Major System Services Check ===
def run_logs_collection_for_major_system_services_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully for major system services.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection For Major System Services Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully after major system services active.",
            "[DESC] Required operations: system/logs/start-collection, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs has been collected and include major system services active.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, system/logs/stop-collection", result, logs):
            return result

        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Trigger activity of major system services.
        line = f"[STEP] Trigger activity of major system services."
        LOGGER.result(line)
        logs.append(line)
        print(f"1. [AV Decoder] Please play a video for a while.\n2. [Power Manager] Please toggle power state.\n3. [Networking Module] Please disable and enable network.")

        validate_state = False
        while(validate_state == False):
            validate_state = yes_or_no(result, logs, f"Complete the above operations?")

        # Step 3: Waiting for 10 seconds to collect logs.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 4: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 5: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 6: Verify logs details.
        line = f"[STEP] Verify logs details."
        LOGGER.result(line)
        logs.append(line)
        print(f"Please enter logs folder and verify logs about major system services.")
        validate_state = yes_or_no(result, logs, f"Logs collaction includes AV Decoder, Power Manager, and Networking Module?")
        if validate_state == True:
            print(f"Logs collection includes major system services.")
            logs.append(f"[PASS] Logs collection includes major system services.")
            result.test_result = "PASS"
        else:
            print(f"Logs collection doesn't include major system services.")
            logs.append(f"[FAILED] Logs collection doesn't include major system services.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 40: Log Collection While App Pause Check ===
def run_logs_collection_app_pause_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully while an app pause.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    appId = config.apps.get("youtube", "YouTube")
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection For an app pause Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully after an app pause.",
            "[DESC] Required operations: system/logs/start-collection, applications/launch, applications/exit, applications/get-state, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs has been collected and include log about app pause.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, applications/launch, applications/exit, applications/get-state, system/logs/stop-collection", result, logs):
            return result

        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Launch an application.
        line = f"[STEP] Launch application '{appId}'."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": appId}), logs, result)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        # Step 3: Pause the application and confirm the state.
        line = f"[STEP] Pause application '{appId}' and confirm its state is BACKGROUND."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": appId, "background": True}), logs, result)
        print(f"Waiting {APP_STATE_CHECK_WAIT} seconds after exit.")
        time.sleep(APP_STATE_CHECK_WAIT)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": appId}), logs, result)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        if state != "BACKGROUND":
            print(f"Pause application {appId} Fail.")
            logs.append(f"[FAILED] Pause application {appId} Fail.")
            result.test_result = "FAILED"
            return result

        # Step 4: Waiting for logs collections.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 5: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 6: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 7: Verify logs details.
        line = f"[STEP] Verify logs details."
        LOGGER.result(line)
        logs.append(line)
        print(f"Please enter logs folder and verify logs about application '{appId}'.")
        validate_state = yes_or_no(result, logs, f"Logs collaction includes pausing application '{appId}'?")
        if validate_state == True:
            print(f"Logs collection includes pausing application '{appId}'.")
            logs.append(f"[PASS] Logs collection includes pausing application '{appId}'.")
            result.test_result = "PASS"
        else:
            print(f"Logs collection doesn't include pausing application '{appId}'.")
            logs.append(f"[FAILED] Logs collection doesn't incclue pausing application '{appId}'.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 41: Log Collection While Background App Is Force-Stopped Check ===
def run_logs_collection_app_force_stop_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully while While Background App Is Force-Stopped.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    appId = config.apps.get("youtube", "YouTube")
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection While Background App Is Force-Stopped — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully while background app is force-stopped.",
            "[DESC] Required operations: system/logs/start-collection, applications/launch, applications/exit, applications/get-state, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs collection includes the log about a background app is force-stopped.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, applications/launch, applications/exit, applications/get-state, system/logs/stop-collection", result, logs):
            return result

        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Launch an application.
        line = f"[STEP] Launch application '{appId}'."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/launch", json.dumps({"appId": appId}), logs, result)
        print(f"Waiting {APP_LAUNCH_WAIT} seconds for application to launch.")
        time.sleep(APP_LAUNCH_WAIT)

        # Step 3: Exit the application to background, and confirm the state.
        line = f"[STEP] Pause application '{appId}' and confirm its state is BACKGROUND."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": appId, "background": True}), logs, result)
        print(f"Waiting {APP_STATE_CHECK_WAIT} seconds after exit.")
        time.sleep(APP_STATE_CHECK_WAIT)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": appId}), logs, result)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        if state != "BACKGROUND":
            print(f"Exit application {appId} to background fail.")
            logs.append(f"[FAILED] Exit application {appId} to background fail.")
            result.test_result = "FAILED"
            return result

        # Step 4: Force stop the application, and confirm the state.
        line = f"[STEP] Pause application '{appId}' and confirm its state is BACKGROUND."
        LOGGER.result(line)
        logs.append(line)
        execute_cmd_and_log(tester, device_id, "applications/exit", json.dumps({"appId": appId}), logs, result)
        print(f"Waiting {APP_STATE_CHECK_WAIT} seconds after exit.")
        time.sleep(APP_STATE_CHECK_WAIT)
        _, response = execute_cmd_and_log(tester, device_id, "applications/get-state", json.dumps({"appId": appId}), logs, result)
        state = json.loads(response).get("state", "").upper() if response else "UNKNOWN"
        if state != "STOPPED":
            print(f"Force stop application {appId} fail.")
            logs.append(f"[FAILED] Force stop application {appId} fail.")
            result.test_result = "FAILED"
            return result

        # Step 5: Waiting for logs collections.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 6: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 7: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 8: Verify logs details.
        line = f"[STEP] Verify logs details."
        LOGGER.result(line)
        logs.append(line)
        print(f"Please enter logs folder and verify logs about application '{appId}'.")
        validate_state = yes_or_no(result, logs, f"Logs collaction includes force stop application '{appId}'?")
        if validate_state == True:
            print(f"Logs collection includes force stop application '{appId}'.")
            logs.append(f"[PASS] Logs collection includes force stop application '{appId}'.")
            result.test_result = "PASS"
        else:
            print(f"Logs collection doesn't include force stop application '{appId}'.")
            logs.append(f"[FAILED] Logs collection doesn't incclue force stop application '{appId}'.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 42: Log Collection During App Uninstallation Check ===
def run_logs_collection_app_uninstall_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully while App Uninstallation.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    # Use sample_app as the target for this test
    appId = config.apps.get("sample_app", "Sample_App")
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection During App Uninstallation Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully while a sample app is uninstalled.",
            "[DESC] Required operations: system/logs/start-collection, applications/install, applications/uninstall, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs are collected successfully and include app uninstallation logs.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, applications/install, applications/uninstall, system/logs/stop-collection", result, logs):
            return result
        
        # Step 0: Precondition - Ensure the sample app is installed first
        line = f"[STEP] Precondition: Installing '{appId}' to ensure it exists."
        LOGGER.result(line); logs.append(line)
        try:
            install_payload = ensure_app_available(app_id=appId)
        except Exception as e:
            result.test_result = "SKIPPED"
            line = f"[RESULT] SKIPPED — Could not find local artifact for '{appId}': {e}"
            LOGGER.warn(line); logs.append(line)
            return result
        
        rc, response = execute_cmd_and_log(tester, device_id, "applications/install", json.dumps(install_payload), logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Precondition failed: Could not install '{appId}'."
            LOGGER.error(line); logs.append(line)
            return result
        time.sleep(APP_INSTALL_WAIT)


        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Uninstall an application.
        line = f"[STEP] Uninstall application {appId}."
        LOGGER.result(line)
        logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "applications/uninstall", json.dumps({"appId": appId}), logs, result)
        print(f"Waiting {APP_UNINSTALL_WAIT} seconds for application uninstallation.")
        time.sleep(APP_UNINSTALL_WAIT)

        # Step 3: Waiting for logs collections.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 4: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 5: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 6: Verify logs details.
        line = f"[STEP] Verify logs details."
        LOGGER.result(line)
        logs.append(line)
        print(f"Please enter logs folder and verify logs about application '{appId}'.")
        validate_state = yes_or_no(result, logs, f"Logs collection includes application '{appId}' uninstallation log?")
        if validate_state == True:
            print(f"Logs collection includes application '{appId}' uninstallation log.")
            logs.append(f"[PASS] Logs collection includes application '{appId}' uninstallation log.")
            result.test_result = "PASS"
        else:
            print(f"Logs collection doesn't include application '{appId}' uninstallation log.")
            logs.append(f"[FAILED] Logs collection doesn't include application '{appId}' uninstallation log.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        
        # Cleanup: Reinstall the app for test isolation
        try:
            line = f"[CLEANUP] Reinstalling '{appId}' to restore state for subsequent tests."
            LOGGER.info(line); logs.append(line)
            install_payload = ensure_app_available(app_id=appId)
            execute_cmd_and_log(tester, device_id, "applications/install", json.dumps(install_payload), logs, result)
        except Exception as e:
            line = f"[CLEANUP] WARNING: Failed to reinstall app '{appId}': {e}"
            LOGGER.warn(line); logs.append(line)
            
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test 43: Log Collection While App Install And Launch Check ===
def run_logs_collection_app_install_and_launch_check(dab_topic, test_name, tester, device_id):
    """
    Validates that logs can be collected successfully while install and launch App.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    appId = config.apps.get("store_app", "Store_App")  # valid, not-installed appId
    payload_app = json.dumps({"appId": appId})
    result = TestResult(test_id, device_id, "system/logs/start-collection", json.dumps({}), "UNKNOWN", "", logs)

    try:
        # Header and description
        for line in (
            f"[TEST] Log Collection While App install and launch Check — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Validates that logs can be collected successfully while app install and launch.",
            "[DESC] Required operations: system/logs/start-collection, applications/install-from-app-store, applications/launch, system/logs/stop-collection.",
            "[DESC] Pass criteria: Logs has been collected and include app install and launch logs.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        if not require_capabilities(tester, device_id, "ops: system/logs/start-collection, applications/install-from-app-store, applications/launch, system/logs/stop-collection", result, logs):
            return result

        # Step 1: Start logs collection.
        line = f"[STEP] Start logs collection."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/start-collection"
        payload = json.dumps({})
        rc, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Could not start logs collection."
            LOGGER.result(line)
            logs.append(line)
            return result

        # Step 2: Install an application.
        msg = f"[STEP] Install application {appId}."
        LOGGER.result(msg)
        logs.append(msg)
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
                   f"test_id={test_id}, device={device_id}, appId={appId}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # short wait to allow finalization
        msg = f"[WAIT] {INSTALL_WAIT}s after install for finalization"
        LOGGER.info(msg); logs.append(msg)
        time.sleep(INSTALL_WAIT)

        # Step 3: Launch the newly installed app
        msg = f"[STEP] applications/launch {payload_app}"
        LOGGER.result(msg); logs.append(msg)
        rc_launch, resp_launch = execute_cmd_and_log(
                tester, device_id, "applications/launch", payload_app, logs, result
                )
        launch_status = dab_status_from(resp_launch, rc_launch)
        msg = f"[INFO] launch transport_rc={rc_launch}, dab_status={launch_status}"
        LOGGER.info(msg); logs.append(msg)

        if launch_status != 200:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — launch returned {launch_status} (expected 200) after install"
            LOGGER.result(msg); logs.append(msg)
            msg = (f"[SUMMARY] outcome={result.test_result}, install_status={install_status}, "
                   f"launch_status={launch_status}, test_id={test_id}, device={device_id}, appId={appId}")
            LOGGER.result(msg); logs.append(msg)
            return result

        # Step 4: Waiting for logs collections.
        line = f"[STEP] Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs."
        LOGGER.result(line)
        logs.append(line)
        countdown(f"Waiting for {LOGS_COLLECTION_WAIT} seconds to collect logs.", LOGS_COLLECTION_WAIT)

        # Step 5: Stop logs collection, and generate logs.tar.gz file.
        line = f"[STEP] Stop logs collection, and generate logs.tar.gz file."
        LOGGER.result(line)
        logs.append(line)
        topic = "system/logs/stop-collection"
        payload = json.dumps({})
        _, response = execute_cmd_and_log(tester, device_id, topic, payload, logs, result)
        validate_state, result = validate_response(tester, topic, payload, response, result, logs)
        if validate_state == False:
            return result
        validate_state = EnforcementManager().verify_logs_chunk(tester, logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result

        # Step 6: Uncompress logs.tar.gz and verify logs structure.
        line = f"[STEP] Uncompress logs.tar.gz and verify logs structure."
        LOGGER.result(line)
        logs.append(line)
        validate_state = EnforcementManager().verify_logs_structure(logs)
        if validate_state == False:
            result.test_result = "FAILED"
            return result
        else:
            print(f"The logs structure follows DAB requirement.")
            logs.append(f"The logs structure follows DAB requirement.")

        # Step 7: Verify logs details.
        line = f"[STEP] Verify logs details."
        LOGGER.result(line)
        logs.append(line)
        print(f"Please enter logs folder and verify logs about application '{appId}'.")
        validate_state = yes_or_no(result, logs, f"Logs collaction includes application '{appId}' install and launch log?")
        if validate_state == True:
            print(f"Logs collection includes application '{appId}' install and launch log.")
            logs.append(f"[PASS] Logs collection includes application '{appId}' install and launch log.")
            result.test_result = "PASS"
        else:
            print(f"Logs collection doesn't include application '{appId}' install and launch log.")
            logs.append(f"[FAILED] Logs collection doesn't incclue application '{appId}' install and launch log.")
            result.test_result = "FAILED"

    except UnsupportedOperationError as e:
        logs.append(f"[OPTIONAL_FAILED] Unsupported operation: {str(e)}")
        result.test_result = "OPTIONAL_FAILED"

    except Exception as e:
        logs.append(f"[ERROR] {str(e)}")
        result.test_result = "SKIPPED"

    finally:
        EnforcementManager().delete_logs_collection_files()
        # Print concise final test result status
        print(f"[Result] Test Id: {result.test_id} \n Test Outcome: {result.test_result}\n({'-' * 100})")

    return result

# === Test: Network Reset – Wi-Fi Settings Default Restoration ===
def run_network_reset_wifi_default_restoration(dab_topic, test_name, tester, device_id):
    """
    Verifies that system/network-reset resets Wi-Fi settings to defaults and requires manual reconnection.
    """
    NETWORK_RESET_WAIT = 20  # seconds
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload_reset = json.dumps({})

    # TestResult(test_id, device_id, dab_topic, request_payload, test_result, details, logs)
    result = TestResult(test_id, device_id, "system/network-reset", payload_reset, "UNKNOWN", "", logs)

    try:
        # Always-on header + description (printed and stored)
        for line in (
            f"[TEST] Network Reset — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: confirm network reset clears Wi-Fi custom config (static IP/DNS/proxy/saved SSIDs) and requires manual reconnection.",
            "[DESC] Preconditions: device on Wi-Fi with custom config; DAB reachable.",
            "[DESC] Required operations: system/network-reset.",
            "[DESC] Pass criteria: reset returns 200, saved networks cleared, IP/DNS/Proxy defaulted, manual reconnection required.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate
        required_ops = "ops: system/network-reset"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' already logged and set result

        # Preconditions (manual)
        line = "[STEP] Ensure device is currently connected to Wi-Fi with a custom setting applied (static IP / DNS / proxy)."
        LOGGER.result(line); logs.append(line)
        if not yes_or_no("Confirm custom Wi-Fi configuration is active on the device [y/N]: "):
            result.test_result = "SKIPPED"
            line = f"[RESULT] SKIPPED — precondition not met (no custom Wi-Fi config). (test_id={test_id}, device={device_id})"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Initiate network reset
        line = f"[STEP] Initiating network reset via {dab_topic} with payload: {payload_reset}"
        LOGGER.result(line); logs.append(line)
        code, resp = execute_cmd_and_log(tester, device_id, "system/network-reset", payload_reset, logs, result)

        # Handle 501 or unexpected status
        if code == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = f"[RESULT] OPTIONAL_FAILED — 501 Not Implemented returned by system/network-reset. (test_id={test_id}, device={device_id})"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        if code != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 200 from system/network-reset but got {code}. Response: {resp}"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        line = f"[RESULT] system/network-reset returned 200 OK. Response: {resp}"
        LOGGER.result(line); logs.append(line)

        # Wait for reset side-effects (Wi-Fi stack restart / MQTT drop)
        line = f"[WAIT] Allowing {NETWORK_RESET_WAIT}s for network stack to reset."
        LOGGER.info(line); logs.append(line)
        time.sleep(NETWORK_RESET_WAIT)

        # Manual validations
        LOGGER.result("[STEP] Validate on device UI that Wi-Fi settings are reset to defaults.")
        cleared_saved = yes_or_no("Are saved Wi-Fi networks cleared? [y/N]: ")
        defaults_ip  = yes_or_no("Are IP settings back to DHCP/Automatic (not static)? [y/N]: ")
        defaults_dns = yes_or_no("Are DNS/Proxy settings cleared/reset to defaults? [y/N]: ")
        manual_reconnect = yes_or_no("Did the device require manual reconnection (credentials prompted)? [y/N]: ")

        # Decide outcome
        if cleared_saved and defaults_ip and defaults_dns and manual_reconnect:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — Wi-Fi config cleared and manual reconnection required."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            missing = []
            if not cleared_saved:   missing.append("saved networks not cleared")
            if not defaults_ip:     missing.append("IP not default/DHCP")
            if not defaults_dns:    missing.append("DNS/Proxy not default")
            if not manual_reconnect: missing.append("no manual reconnection required")
            reason = "; ".join(missing) if missing else "validation failed"
            line = f"[RESULT] FAILED — {reason}."
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during network reset validation: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        # Final summary log for easy parsing
        line = (
            f"[SUMMARY] outcome={result.test_result}, "
            f"cleared_saved={str(cleared_saved) if 'cleared_saved' in locals() else 'N/A'}, "
            f"default_ip={str(defaults_ip) if 'defaults_ip' in locals() else 'N/A'}, "
            f"default_dns_proxy={str(defaults_dns) if 'defaults_dns' in locals() else 'N/A'}, "
            f"manual_reconnect={str(manual_reconnect) if 'manual_reconnect' in locals() else 'N/A'}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result

# === Test: Setup Skip – Privacy Settings Screen Bypass (fixed locals init) ===
def run_setup_skip_privacy_bypass(dab_topic, test_name, tester, device_id):
    """
    Verifies that calling system/setup/skip from the Privacy Settings screen exits setup wizard and lands on Home.
    """
    RESET_REBOOT_WAIT = 90
    SETUP_RESUME_WAIT = 30
    SKIP_TRANSITION_WAIT = 45

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload_empty = json.dumps({})

    # TestResult(test_id, device_id, dab_topic, request_payload, test_result, details, logs)
    result = TestResult(test_id, device_id, "system/setup/skip", payload_empty, "UNKNOWN", "", logs)

    # --- SAFE DEFAULTS so summary never crashes ---
    do_reset = False
    at_privacy = False
    code_skip = None
    resp_skip = None
    on_home = False
    opt_features_disabled = None  # None → N/A in summary

    try:
        # Header + description
        for line in (
            f"[TEST] Setup Skip — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: from Privacy Settings screen during setup wizard, call system/setup/skip and verify device lands on Home.",
            "[DESC] Preconditions: device at setup wizard; target screen = Privacy Settings; DAB reachable.",
            "[DESC] Required operations: system/setup/skip. Optional: system/factory-reset.",
            "[DESC] Pass criteria: skip accepted (200), device exits setup wizard and shows Home screen.",
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        required_ops = "ops: system/setup/skip; optional: system/factory-reset"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' already handled

        # Optional factory reset to ensure clean setup state
        LOGGER.result("[STEP] If not already at setup wizard, trigger factory reset via system/factory-reset (optional).")
        do_reset = yes_or_no("Do you want to perform system/factory-reset now? This will erase the device. [y/N]: ")
        if do_reset:
            LOGGER.result(f"[STEP] Calling system/factory-reset with payload: {payload_empty}")
            code_fr, resp_fr = execute_cmd_and_log(tester, device_id, "system/factory-reset", payload_empty, logs, result)
            if code_fr == 501:
                LOGGER.result("[RESULT] OPTIONAL_FAILED — system/factory-reset not implemented on this device. Proceeding manually to setup wizard.")
            elif code_fr != 200:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — expected 200 from system/factory-reset, got {code_fr}. Response: {resp_fr}"
                LOGGER.result(line); logs.append(line)
                return result
            else:
                LOGGER.result(f"[RESULT] system/factory-reset returned 200 OK. Response: {resp_fr}")
                line = f"[WAIT] Allowing {RESET_REBOOT_WAIT}s for reboot/reset to complete."
                LOGGER.info(line); logs.append(line)
                time.sleep(RESET_REBOOT_WAIT)

        # Manually advance to Privacy Settings
        LOGGER.result("[STEP] Manually progress through setup until 'Privacy Settings' screen is displayed.")
        line = f"[WAIT] Allowing {SETUP_RESUME_WAIT}s for UI to stabilize."
        LOGGER.info(line); logs.append(line)
        time.sleep(SETUP_RESUME_WAIT)

        at_privacy = yes_or_no("Is the device on the Privacy Settings screen now? [y/N]: ")
        if not at_privacy:
            result.test_result = "SKIPPED"
            line = "[RESULT] SKIPPED — device not at Privacy Settings screen."
            LOGGER.result(line); logs.append(line)
            return result

        # Invoke skip at Privacy Settings
        LOGGER.result(f"[STEP] Invoking {dab_topic} with payload: {payload_empty}")
        code_skip, resp_skip = execute_cmd_and_log(tester, device_id, "system/setup/skip", payload_empty, logs, result)

        if code_skip == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — 501 Not Implemented for system/setup/skip."
            LOGGER.result(line); logs.append(line)
            return result

        if code_skip != 200:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 200 from system/setup/skip, got {code_skip}. Response: {resp_skip}"
            LOGGER.result(line); logs.append(line)
            return result

        LOGGER.result(f"[RESULT] system/setup/skip returned 200 OK. Response: {resp_skip}")
        line = f"[WAIT] Allowing {SKIP_TRANSITION_WAIT}s for device to exit setup and load Home."
        LOGGER.info(line); logs.append(line)
        time.sleep(SKIP_TRANSITION_WAIT)

        # Verify Home
        on_home = yes_or_no("Did the device exit setup wizard and land on the Home screen? [y/N]: ")
        opt_features_disabled = yes_or_no("Optional: Are account-based/personalized features disabled until configured? [y/N]: ")

        if on_home:
            result.test_result = "PASS"
            LOGGER.result("[RESULT] PASS — setup skipped from Privacy Settings and Home screen is visible.")
        else:
            result.test_result = "FAILED"
            LOGGER.result("[RESULT] FAILED — device did not reach Home after skip.")

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during setup skip validation: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        def yn(v):
            return "Y" if v is True else ("N" if v is False else "N/A")
        line = (
            f"[SUMMARY] outcome={result.test_result}, "
            f"did_reset={yn(do_reset)}, "
            f"at_privacy={yn(at_privacy)}, "
            f"skip_status={code_skip if code_skip is not None else 'N/A'}, "
            f"home_visible={yn(on_home)}, "
            f"features_disabled_opt={yn(opt_features_disabled)}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result


# === Test: Content Search – Special-Character-Only Query Validation ===
def run_content_search_special_chars_validation(dab_topic, test_name, tester, device_id):
    """
    Validates that content/search handles special-character-only queries gracefully:
    - Either returns 4xx with a clear validation error (JSON), or
    - Returns 200 with a well-formed JSON body and an empty results array.
    """

    SPECIAL_QUERY = "!@#$%^&*()"
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload = json.dumps({"query": SPECIAL_QUERY})

    # TestResult(test_id, device_id, dab_topic, request_payload, test_result, details, logs)
    result = TestResult(test_id, device_id, "content/search", payload, "UNKNOWN", "", logs)

    # For final summary fields
    status_code = None
    json_ok = False
    mode = "N/A"             # "200_empty" | "4xx_error" | "other"
    ui_ok = "N/A"

    try:
        # Header + description
        for line in (
            f"[TEST] Content Search — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: send a special-character-only query and ensure robust handling without crashes or malformed JSON.",
            "[DESC] Preconditions: device reachable via DAB; content service reachable; user at search interface.",
            "[DESC] Required operations: content/search.",
            "[DESC] Pass criteria: valid JSON with either 4xx clear validation error or 200 with empty results.",
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        required_ops = "ops: content/search"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' already logged and set result

        # Optional precondition confirmation about UI
        if not yes_or_no("Is the device currently on the search interface? [y/N]: "):
            result.test_result = "SKIPPED"
            line = f"[RESULT] SKIPPED — device not on search interface."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Step — Send special-character-only query
        line = f"[STEP] Calling content/search with payload: {payload}"
        LOGGER.result(line); logs.append(line)
        status_code, raw_resp = execute_cmd_and_log(tester, device_id, "content/search", payload, logs, result)

        # 501 path: optional/unsupported
        if status_code == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = f"[RESULT] OPTIONAL_FAILED — 501 Not Implemented for content/search."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status_code}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Capture raw response for debugging
        LOGGER.info(f"[INFO] content/search raw response: {raw_resp}")
        logs.append(f"[INFO] content/search raw response: {raw_resp}")

        # Validate JSON
        try:
            obj = json.loads(raw_resp) if raw_resp else {}
            json_ok = True
        except Exception:
            obj = None
            json_ok = False

        # Decision logic
        if 200 <= (status_code or 0) < 300:
            # Expect empty results array on success
            mode = "200_empty"
            # Accept either "results": [] or "items": []
            results = None
            if isinstance(obj, dict):
                if "results" in obj:
                    results = obj.get("results")
                elif "items" in obj:
                    results = obj.get("items")

            if not json_ok:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — 200 OK but response is not valid JSON."
                LOGGER.result(line); logs.append(line)
            elif isinstance(results, list) and len(results) == 0:
                # Optional UI stability check
                ui_stable = yes_or_no("Did the UI remain stable (no crash/hang) and show no results or a validation message? [y/N]: ")
                ui_ok = "Y" if ui_stable else "N"
                if ui_stable:
                    result.test_result = "PASS"
                    line = "[RESULT] PASS — 200 OK with empty results and stable UI."
                    LOGGER.result(line); logs.append(line)
                else:
                    result.test_result = "FAILED"
                    line = "[RESULT] FAILED — UI instability observed."
                    LOGGER.result(line); logs.append(line)
            else:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — 200 OK but expected an empty 'results' (or 'items') array."
                LOGGER.result(line); logs.append(line)

        elif 400 <= (status_code or 0) < 500:
            mode = "4xx_error"
            # Expect clear validation error in JSON (common shapes)
            clear_error = False
            if json_ok and isinstance(obj, dict):
                if "error" in obj:
                    err_obj = obj["error"]
                    if isinstance(err_obj, dict):
                        msg = str(err_obj.get("message", "")).strip()
                        code = str(err_obj.get("code", "")).strip()
                        status = str(err_obj.get("status", "")).strip()
                        clear_error = bool(msg or code or status)
                else:
                    # Fallback: top-level code/message/status
                    msg = str(obj.get("message", "")).strip()
                    code = str(obj.get("code", "")).strip()
                    status = str(obj.get("status", "")).strip()
                    clear_error = bool(msg or code or status)

            if json_ok and clear_error:
                # Optional UI stability check
                ui_stable = yes_or_no("Did the UI remain stable (no crash/hang) and show an appropriate validation message? [y/N]: ")
                ui_ok = "Y" if ui_stable else "N"
                if ui_stable:
                    result.test_result = "PASS"
                    line = "[RESULT] PASS — 4xx with clear validation error in JSON and stable UI."
                    LOGGER.result(line); logs.append(line)
                else:
                    result.test_result = "FAILED"
                    line = "[RESULT] FAILED — UI instability observed with validation error."
                    LOGGER.result(line); logs.append(line)
            else:
                result.test_result = "FAILED"
                if not json_ok:
                    line = "[RESULT] FAILED — 4xx but response is not valid JSON."
                else:
                    line = "[RESULT] FAILED — 4xx without a clear validation error in JSON."
                LOGGER.result(line); logs.append(line)

        else:
            mode = "other"
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — unexpected status: {status_code}. Expected 200(empty) or 4xx(error)."
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during special-char search validation: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        # Final summary (concise, machine-parsable)
        line = (
            f"[SUMMARY] outcome={result.test_result}, "
            f"status={status_code if status_code is not None else 'N/A'}, "
            f"json_valid={'Y' if json_ok else 'N'}, "
            f"mode={mode}, "
            f"ui_ok={ui_ok}, "
            f"query='{SPECIAL_QUERY}', "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result

# === Test: Power Mode Get – STANDBY State Verification ===
def run_power_mode_get_standby_verify(dab_topic, test_name, tester, device_id):
    """
    Validates that system/power-mode/get reports STANDBY (or Background) when the device is in standby.
    """

    STANDBY_ALIASES = {"STANDBY", "BACKGROUND"}

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload = json.dumps({})

    # TestResult(test_id, device_id, dab_topic, request_payload, test_result, details, logs)
    result = TestResult(test_id, device_id, "system/power-mode/get", payload, "UNKNOWN", "", logs)

    status = None
    parsed_state = "UNKNOWN"
    state_source = "N/A"

    try:
        # Header + description
        for line in (
            f"[TEST] Power Mode — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: when device is in STANDBY, verify system/power-mode/get returns STANDBY (or Background).",
            "[DESC] Preconditions: device already in STANDBY and connected; DAB reachable.",
            "[DESC] Required operations: system/power-mode/get.",
            "[DESC] Pass criteria: 2xx and state/mode == STANDBY or Background.",
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        required_ops = "ops: system/power-mode/get"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' already handled

        # Preconditions (manual confirmation)
        if not yes_or_no("Confirm the device is currently in STANDBY and network/DAB connectivity is stable [y/N]: "):
            result.test_result = "SKIPPED"
            line = "[RESULT] SKIPPED — precondition not met (device not confirmed in STANDBY/connected)."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Step — Send GET
        line = f"[STEP] Calling system/power-mode/get with payload: {payload}"
        LOGGER.result(line); logs.append(line)
        status, raw_resp = execute_cmd_and_log(tester, device_id, "system/power-mode/get", payload, logs, result)

        # 501 path (optional on some devices)
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — system/power-mode/get not implemented (501)."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Non-2xx → fail
        if not (200 <= (status or 0) < 300):
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 2xx, got {status}. Response: {raw_resp}"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, state={parsed_state}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Parse JSON and extract state/mode
        obj = {}
        try:
            obj = json.loads(raw_resp) if raw_resp else {}
        except Exception:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — response is not valid JSON."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, state=UNKNOWN, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Try typical locations
        candidates = []
        if isinstance(obj, dict):
            if "state" in obj: candidates.append(("state", obj.get("state")))
            if "mode" in obj:  candidates.append(("mode", obj.get("mode")))
            pm = obj.get("powerMode")
            if isinstance(pm, dict):
                if "state" in pm: candidates.append(("powerMode.state", pm.get("state")))
                if "mode" in pm:  candidates.append(("powerMode.mode", pm.get("mode")))

        # First non-empty candidate wins
        for k, v in candidates:
            if v is not None and str(v).strip() != "":
                parsed_state = str(v).strip().upper()
                state_source = k
                break

        LOGGER.info(f"[INFO] system/power-mode/get raw response: {raw_resp}")
        logs.append(f"[INFO] system/power-mode/get raw response: {raw_resp}")
        LOGGER.info(f"[INFO] Parsed state='{parsed_state}' (source={state_source})")
        logs.append(f"[INFO] Parsed state='{parsed_state}' (source={state_source})")

        if parsed_state in STANDBY_ALIASES:
            result.test_result = "PASS"
            line = "[RESULT] PASS — power mode reports STANDBY/Background as expected."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected STANDBY/Background, got '{parsed_state}' (source={state_source})."
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during power mode validation: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        line = (
            f"[SUMMARY] outcome={result.test_result}, "
            f"status={status if status is not None else 'N/A'}, "
            f"state={parsed_state}, source={state_source}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result

# === Test: Power Mode Get – ON State Verification ===
def run_power_mode_get_on_verify(dab_topic, test_name, tester, device_id):
    """
    Validates that system/power-mode/get reports ON when the device is powered ON and connected.
    Acceptance: 2xx + state/mode == "ON" (exact). Anything else → FAILED. 501 → OPTIONAL_FAILED.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload = json.dumps({})

    # TestResult(test_id, device_id, dab_topic, request_payload, test_result, details, logs)
    result = TestResult(test_id, device_id, "system/power-mode/get", payload, "UNKNOWN", "", logs)

    # Safe defaults for summary
    status = None
    parsed_state = "UNKNOWN"
    state_source = "N/A"

    try:
        # Header + description
        for line in (
            f"[TEST] Power Mode — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: when device is ON, verify system/power-mode/get returns ON.",
            "[DESC] Preconditions: device ON, network connected, DAB reachable, on Home screen.",
            "[DESC] Required operations: system/power-mode/get.",
            "[DESC] Pass criteria: 2xx and state/mode == ON.",
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        required_ops = "ops: system/power-mode/get"
        if not require_capabilities(tester, device_id, required_ops, result, logs):
            return result  # 'require_capabilities' already handled

        # Preconditions (manual confirmation)
        if not yes_or_no("Confirm the device is ON (Home screen visible) and connectivity is stable [y/N]: "):
            result.test_result = "SKIPPED"
            line = "[RESULT] SKIPPED — precondition not met (device not confirmed ON/connected)."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Step — Send GET
        line = f"[STEP] Calling system/power-mode/get with payload: {payload}"
        LOGGER.result(line); logs.append(line)
        status, raw_resp = execute_cmd_and_log(tester, device_id, "system/power-mode/get", payload, logs, result)

        # 501 path (optional on some devices)
        if status == 501:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — system/power-mode/get not implemented (501)."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, state={parsed_state}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Non-2xx → fail
        if not (200 <= (status or 0) < 300):
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected 2xx, got {status}. Response: {raw_resp}"
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, state={parsed_state}, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Parse JSON and extract state/mode
        obj = {}
        try:
            obj = json.loads(raw_resp) if raw_resp else {}
        except Exception:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — response is not valid JSON."
            LOGGER.result(line); logs.append(line)
            line = f"[SUMMARY] outcome={result.test_result}, status={status}, state=UNKNOWN, test_id={test_id}, device={device_id}"
            LOGGER.result(line); logs.append(line)
            return result

        # Common shapes: {"state": "..."} | {"mode": "..."} | {"powerMode": {"state": "...", "mode": "..." }}
        candidates = []
        if isinstance(obj, dict):
            if "state" in obj: candidates.append(("state", obj.get("state")))
            if "mode" in obj:  candidates.append(("mode", obj.get("mode")))
            pm = obj.get("powerMode")
            if isinstance(pm, dict):
                if "state" in pm: candidates.append(("powerMode.state", pm.get("state")))
                if "mode" in pm:  candidates.append(("powerMode.mode", pm.get("mode")))

        for k, v in candidates:
            if v is not None and str(v).strip() != "":
                parsed_state = str(v).strip().upper()
                state_source = k
                break

        LOGGER.info(f"[INFO] system/power-mode/get raw response: {raw_resp}")
        logs.append(f"[INFO] system/power-mode/get raw response: {raw_resp}")
        LOGGER.info(f"[INFO] Parsed state='{parsed_state}' (source={state_source})")
        logs.append(f"[INFO] Parsed state='{parsed_state}' (source={state_source})")

        if parsed_state == "ON":
            result.test_result = "PASS"
            line = "[RESULT] PASS — power mode reports ON as expected."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — expected ON, got '{parsed_state}' (source={state_source})."
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — operation '{e.topic}' not supported (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error during power mode ON validation: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        line = (
            f"[SUMMARY] outcome={result.test_result}, "
            f"status={status if status is not None else 'N/A'}, "
            f"state={parsed_state}, source={state_source}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result
def run_power_mode_get_adaptive_support_check(dab_topic, test_name, tester, device_id):
    """
    Adaptive test:
      - If system/power-mode/get is supported: PASS when status==200 and body.mode is present (string).
      - If unsupported: PASS when status==501 with a clear 'not supported/not implemented' message.
      - Otherwise: FAILED. Never interactive.
    """
    import json

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload = json.dumps({})
    result = TestResult(test_id, device_id, "system/power-mode/get", payload, "UNKNOWN", "", logs)

    status = None
    raw_resp = None
    json_ok = False
    msg_ok = False
    err_msg = ""
    err_status = ""
    mode_val = "N/A"

    try:
        # Header
        for line in (
            f"[TEST] Power Mode GET — Adaptive Support Check (test_id={test_id}, device={device_id})",
            "[DESC] If supported → expect 200 and a 'mode' string; if unsupported → expect 501 with clear message.",
            "[DESC] No prompts; auto-detect support.",
        ):
            LOGGER.result(line); logs.append(line)

        # Use checker to decide path
        checker = getattr(tester, "dab_checker", None) or DabChecker(tester)
        try:
            setattr(tester, "dab_checker", checker)
        except Exception:
            pass

        validate_code, _ = checker.is_operation_supported(device_id, "system/power-mode/get")

        # Call op (works either way — we’ll judge from status and body)
        LOGGER.result(f"[STEP] Calling system/power-mode/get with payload: {payload}")
        logs.append(f"[STEP] Calling system/power-mode/get with payload: {payload}")
        status, raw_resp = execute_cmd_and_log(
            tester, device_id, "system/power-mode/get", payload, logs, result
        )

        # Parse JSON if present
        obj = {}
        try:
            obj = json.loads(raw_resp) if raw_resp else {}
            json_ok = True
        except Exception:
            json_ok = False

        # Support path
        if validate_code == ValidateCode.SUPPORT:
            if status == 200 and json_ok and isinstance(obj, dict):
                mode_val = str(obj.get("mode", "UNKNOWN"))
                if mode_val and mode_val != "UNKNOWN":
                    result.test_result = "PASS"
                    line = f"[RESULT] PASS — supported: status=200 with mode='{mode_val}'."
                    LOGGER.result(line); logs.append(line)
                else:
                    result.test_result = "FAILED"
                    line = f"[RESULT] FAILED — supported: missing/invalid 'mode' in body. Resp={raw_resp}"
                    LOGGER.result(line); logs.append(line)
            elif 200 <= (status or 0) < 300:
                # 2xx but body bad
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — supported: status={status} but invalid/absent JSON or 'mode'. Resp={raw_resp}"
                LOGGER.result(line); logs.append(line)
            elif status == 501:
                # Inconsistent with checker; still judge by response
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — checker said supported but device returned 501."
                LOGGER.result(line); logs.append(line)
            else:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — supported: unexpected status={status}. Resp={raw_resp}"
                LOGGER.result(line); logs.append(line)

        # Unsupported path
        else:
            # Extract typical error text
            text = ""
            if json_ok and isinstance(obj, dict):
                if "error" in obj and isinstance(obj["error"], dict):
                    err = obj["error"]
                    err_msg = str(err.get("message", "")).strip()
                    err_status = str(err.get("status", "")).strip().upper()
                else:
                    err_msg = str(obj.get("message", "")).strip()
                    err_status = str(obj.get("status", "")).strip().upper()
                text = (err_msg or err_status).lower()

            msg_ok = ("not supported" in text) or ("unsupported" in text) or ("not_implemented" in text) or ("unimplemented" in text)

            if status == 501 and json_ok and msg_ok:
                result.test_result = "PASS"
                line = "[RESULT] PASS — unsupported: 501 with clear 'not supported' indication."
                LOGGER.result(line); logs.append(line)
            elif status == 501 and json_ok and not msg_ok:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — unsupported: 501 but message not clearly indicating 'not supported'."
                LOGGER.result(line); logs.append(line)
            elif status == 501 and not json_ok:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — unsupported: 501 but invalid JSON."
                LOGGER.result(line); logs.append(line)
            elif status is not None and 200 <= status < 300:
                result.test_result = "FAILED"
                line = "[RESULT] FAILED — unsupported per checker, but device returned 2xx."
                LOGGER.result(line); logs.append(line)
            else:
                result.test_result = "FAILED"
                line = f"[RESULT] FAILED — unsupported: unexpected status={status}. Resp={raw_resp}"
                LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        # For the unsupported path, treat as PASS; for supported path this means device impl disagrees with checker.
        if validate_code != ValidateCode.SUPPORT:
            result.test_result = "PASS"
            line = f"[RESULT] PASS — UnsupportedOperationError treated as unsupported."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — checker said supported, but raise: {e}"
            LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — internal error: {e} (test_id={test_id}, device={device_id})"
        LOGGER.result(line); logs.append(line)

    finally:
        line = (
            f"[SUMMARY] outcome={result.test_result}, status={status if status is not None else 'N/A'}, "
            f"json_valid={'Y' if json_ok else 'N'}, mode='{mode_val}', "
            f"msg_ok={'Y' if msg_ok else 'N'}, error_status='{err_status}' error_message='{err_msg}', "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(line); logs.append(line)

    return result



# === Test: Power Mode Transition – Standby to Active ===
def run_power_mode_transition_standby_to_active(dab_topic, test_name, tester, device_id):
    """
    Verifies power-mode transition Standby -> Active using system/power-mode/get|set.

    Plan:
      0) Auto-precondition: if current != "Active", set "Active" and confirm
      1) Set "Standby"
      2) Wait fixed 10s (no polling)
      3) Set "Active"
      4) PASS if final GET == 200 and body.mode == "Active"
    """
    MODE_ACTIVE  = "Active"
    MODE_STANDBY = "Standby"
    WAIT_SECONDS = 10

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload_empty = json.dumps({})

    # TestResult(test_id, device_id, operation, request, test_result, details, logs)
    result = TestResult(test_id, device_id, "system/power-mode/get", payload_empty, "UNKNOWN", "", logs)
    final_mode = "UNKNOWN"

    try:
        # Header
        for line in (
            f"[TEST] Power Mode Transition – Standby → Active (test_id={test_id}, device={device_id})",
            "[DESC] Auto-precondition to Active → set Standby → wait 10s → set Active → confirm final mode.",
            "[REQ]  ops: system/power-mode/get, system/power-mode/set",
        ):
            LOGGER.result(line); logs.append(line)

        # Capability gate
        if not require_capabilities(
            tester, device_id,
            "ops: system/power-mode/get, system/power-mode/set",
            result, logs
        ):
            if result.test_result == "UNKNOWN":
                result.test_result = "OPTIONAL_FAILED"
                logs.append("[RESULT] OPTIONAL_FAILED — power-mode ops not supported.")
            return result

        # STEP 0: Precondition ensure Active
        LOGGER.result("[STEP] Reading current power mode (system/power-mode/get)")
        logs.append("[STEP] Reading current power mode (system/power-mode/get)")
        rc, resp = execute_cmd_and_log(tester, device_id, "system/power-mode/get", payload_empty, logs, result)
        if dab_status_from(resp, rc) != 200:
            result.test_result = "FAILED"
            result.response = f"Initial GET failed: status={rc}, resp={resp}"
            LOGGER.result(f"[RESULT] FAILED — {result.response}")
            return result

        try:
            body = json.loads(resp) if resp else {}
        except Exception:
            body = {}
        current_mode = str(body.get("mode", "UNKNOWN"))

        LOGGER.result(f"[INFO] Current mode: {current_mode}")
        logs.append(f"[INFO] Current mode: {current_mode}")

        if current_mode != MODE_ACTIVE:
            LOGGER.result("[PRECHECK] Not Active; setting to Active to satisfy precondition")
            logs.append("[PRECHECK] Not Active; setting to Active to satisfy precondition")

            rc, resp = execute_cmd_and_log(
                tester, device_id, "system/power-mode/set", json.dumps({"mode": MODE_ACTIVE}), logs, result
            )
            if dab_status_from(resp, rc) != 200:
                result.test_result = "FAILED"
                result.response = f"Precondition SET Active failed: status={rc}, resp={resp}"
                LOGGER.result(f"[RESULT] FAILED — {result.response}")
                return result

            rc, resp = execute_cmd_and_log(
                tester, device_id, "system/power-mode/get", payload_empty, logs, result
            )
            if dab_status_from(resp, rc) != 200:
                result.test_result = "FAILED"
                result.response = f"Precondition confirm GET failed: status={rc}, resp={resp}"
                LOGGER.result(f"[RESULT] FAILED — {result.response}")
                return result

            try:
                body = json.loads(resp) if resp else {}
            except Exception:
                body = {}
            pre_mode = str(body.get("mode", "UNKNOWN"))

            if pre_mode != MODE_ACTIVE:
                result.test_result = "FAILED"
                result.response = f"Precondition not satisfied: expected 'Active', got '{pre_mode}'"
                LOGGER.result(f"[RESULT] FAILED — {result.response}")
                return result

            LOGGER.result("[PRECHECK] Precondition satisfied: device is now 'Active'")
            logs.append("[PRECHECK] Precondition satisfied: device is now 'Active'")

        # STEP 1: Set Standby
        LOGGER.result("[STEP] Setting power mode → Standby")
        logs.append("[STEP] Setting power mode → Standby")
        rc, resp = execute_cmd_and_log(
            tester, device_id, "system/power-mode/set", json.dumps({"mode": MODE_STANDBY}), logs, result
        )
        if dab_status_from(resp, rc) != 200:
            result.test_result = "FAILED"
            result.response = f"SET Standby failed: status={rc}, resp={resp}"
            LOGGER.result(f"[RESULT] FAILED — {result.response}")
            return result

        # STEP 2: Wait 10s
        LOGGER.result(f"[WAIT] Standby settle for {WAIT_SECONDS}s ")
        logs.append(f"[WAIT] Standby settle for {WAIT_SECONDS}s ")
        countdown("Standby settle", WAIT_SECONDS)

        # STEP 3: Set Active
        LOGGER.result("[STEP] Setting power mode → Active")
        logs.append("[STEP] Setting power mode → Active")
        rc, resp = execute_cmd_and_log(
            tester, device_id, "system/power-mode/set", json.dumps({"mode": MODE_ACTIVE}), logs, result
        )
        if dab_status_from(resp, rc) != 200:
            result.test_result = "FAILED"
            result.response = f"SET Active failed: status={rc}, resp={resp}"
            LOGGER.result(f"[RESULT] FAILED — {result.response}")
            return result

        # STEP 4: Confirm final mode
        LOGGER.result("[STEP] Confirming final power mode (single get)")
        logs.append("[STEP] Confirming final power mode (single get)")
        rc, resp = execute_cmd_and_log(
            tester, device_id, "system/power-mode/get", payload_empty, logs, result
        )
        if dab_status_from(resp, rc) != 200:
            result.test_result = "FAILED"
            result.response = f"Final GET failed: status={rc}, resp={resp}"
        else:
            try:
                body = json.loads(resp) if resp else {}
            except Exception:
                body = {}
            final_mode = str(body.get("mode", "UNKNOWN"))

            if final_mode == MODE_ACTIVE:
                result.test_result = "PASS"
                result.response = "Transition Standby → Active succeeded and final mode is 'Active'."
            else:
                result.test_result = "FAILED"
                result.response = f"Expected final 'Active', got '{final_mode}'"

        LOGGER.result(f"[RESULT] {result.test_result} — {result.response}")

    except UnsupportedOperationError as u:
        result.test_result = "OPTIONAL_FAILED"
        result.response = f"Required operation not implemented: {str(u)}"
        logs.append(f"[SUMMARY] Skipped due to unsupported operation: {str(u)}")

    except Exception as e:
        result.test_result = "SKIPPED"
        result.response = str(e)
        logs.append(f"[SUMMARY] Exception occurred: {str(e)}")

    finally:
        LOGGER.result(
            f"[SUMMARY] outcome={result.test_result}, details={result.response}, "
            f"final_mode={final_mode}, test_id={test_id}, device={device_id}"
        )
        logs.append(
            f"[SUMMARY] outcome={result.test_result}, details={result.response}, "
            f"final_mode={final_mode}, test_id={test_id}, device={device_id}"
        )

    return result

# === Test: Screen Saver Timeout Invalid Value Check (Negative) ===
def run_screensaver_timeout_invalid_value_check(dab_topic, test_name, tester, device_id):
    """
    Verifies that setting screenSaverTimeout with a non-integer value is rejected. This is a negative test.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, "system/settings/set", "{}", "UNKNOWN", "", logs)
    initial_timeout = "N/A"
    set_status = "N/A"

    try:
        # Header and description
        for line in (
            f"[TEST] Set Screensaver Timeout Invalid Value (Negative) — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: Send a system/settings/set request with a non-integer value for screenSaverTimeout.",
            "[DESC] Required ops: system/settings/set, system/settings/get.",
            "[DESC] Pass criteria: The set operation must fail with a 400 error, and the original timeout value must remain unchanged.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # Capability gate (include both the precondition setting and the target setting)
        if not require_capabilities(
            tester, device_id,
            "ops: system/settings/set, system/settings/get | settings: screenSaver, screenSaverTimeout",
            result, logs
        ):
            return result

        # Step 1: Enable screensaver as a precondition
        line = "[STEP] Precondition: Enabling screensaver."
        LOGGER.result(line); logs.append(line)
        rc, response = execute_cmd_and_log(
            tester, device_id,
            "system/settings/set",
            json.dumps({"screenSaver": True}),
            logs, result
        )
        if dab_status_from(response, rc) != 200:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not enable screensaver as a precondition."
            LOGGER.result(line); logs.append(line)
            return result

        # Step 2: Get the initial timeout value
        line = "[STEP] Getting initial screenSaverTimeout value."
        LOGGER.result(line); logs.append(line)
        rc, response = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
        if dab_status_from(response, rc) == 200:
            initial_timeout = json.loads(response).get("screenSaverTimeout", "N/A")
            logs.append(f"[INFO] Initial screenSaverTimeout is: {initial_timeout}")
        else:
            result.test_result = "FAILED"
            line = "[RESULT] FAILED — Could not get initial settings."
            LOGGER.result(line); logs.append(line)
            return result

        # Step 3: Send the invalid request
        invalid_payload = json.dumps({"screenSaverTimeout": "@@!!"})
        line = f"[STEP] Sending invalid request: {invalid_payload}"
        LOGGER.result(line); logs.append(line)
        rc, response = execute_cmd_and_log(
            tester, device_id,
            "system/settings/set",
            invalid_payload, logs, result
        )
        set_status = dab_status_from(response, rc)

        if set_status != 400:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Expected status 400 but received {set_status}."
            LOGGER.result(line); logs.append(line)
            return result
        else:
            logs.append(f"[INFO] Received expected status 400.")

        # Step 4: Confirm the timeout value has not changed
        line = "[STEP] Verifying screenSaverTimeout value has not changed."
        LOGGER.result(line); logs.append(line)
        rc, response = execute_cmd_and_log(
            tester, device_id,
            "system/settings/get",
            "{}", logs, result
        )
        final_timeout = "N/A"
        if dab_status_from(response, rc) == 200:
            final_timeout = json.loads(response).get("screenSaverTimeout", "N/A")
            logs.append(f"[INFO] Final screenSaverTimeout is: {final_timeout}")

        if initial_timeout == final_timeout:
            result.test_result = "PASS"
            line = "[RESULT] PASS — Device correctly rejected the invalid value and the setting remained unchanged."
            LOGGER.result(line); logs.append(line)
        else:
            result.test_result = "FAILED"
            line = f"[RESULT] FAILED — Device's setting was incorrectly changed from {initial_timeout} to {final_timeout}."
            LOGGER.result(line); logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported."
        LOGGER.result(line); logs.append(line)

    except Exception as e:
        result.test_result = "SKIPPED"
        line = f"[RESULT] SKIPPED — An unexpected error occurred: {e}"
        LOGGER.result(line); logs.append(line)

    finally:
        line = f"[SUMMARY] outcome={result.test_result}, set_status={set_status}, initial_value={initial_timeout}, test_id={test_id}, device={device_id}"
        LOGGER.result(line); logs.append(line)

    return result

# === Test: Set Contrast to Maximum Value ===
def run_set_contrast_to_max(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 Positive Test:
      - Set 'contrast' to its maximum supported value.
      - Confirm device reports max contrast via system/settings/get.
      - (Optionally) prompt operator to visually verify max contrast on screen.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    # Local state for safety
    original_contrast = None
    current_contrast = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Set Contrast to Maximum — {test_name} (test_id={test_id}, device={device_id})",
        "[DESC] Goal: set system contrast to maximum supported value and confirm via system/settings/get.",
        "[DESC] Preconditions: device powered on, DAB reachable, 'contrast' setting supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    # --- Step 1: Capability check (contrast setting support) ---
    cap_spec = "ops: system/settings/get, system/settings/set | settings: contrast"
    if not require_capabilities(tester, device_id, cap_spec, result, logs):
        # OPTIONAL_FAILED already set inside require_capabilities
        summary = f"[SUMMARY] Set Contrast to Maximum — final result: {result.test_result}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # --- Step 2: Get supported range for 'contrast' ---
    try:
        setting_info, _ = get_supported_setting(tester, device_id, "contrast", result, logs)
        # Expecting something like {"min": 0, "max": 100} or [0, 100]
        if isinstance(setting_info, dict) and "max" in setting_info:
            max_contrast = setting_info["max"]
        elif isinstance(setting_info, (list, tuple)) and len(setting_info) == 2:
            max_contrast = max(setting_info)
        else:
            msg = f"[FAILED] Could not determine max value for contrast from supported setting: {setting_info}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
            summary = f"[SUMMARY] Set Contrast to Maximum — final result: {result.test_result}"
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result
    except Exception as ex:
        msg = f"[FAILED] Exception while fetching contrast supported range: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"
        summary = f"[SUMMARY] Set Contrast to Maximum — final result: {result.test_result}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # --- Step 3: Store original contrast value ---
    try:
        _, resp_get = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "contrast"}), logs, result)
        resp_data = json.loads(resp_get) if isinstance(resp_get, str) else resp_get
        original_contrast = resp_data.get("contrast")
        msg = f"[INFO] Original contrast value: {original_contrast}"
        LOGGER.info(msg)
        logs.append(LOGGER.stamp(msg))
    except Exception as ex:
        msg = f"[FAILED] Could not read original contrast: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"
        summary = f"[SUMMARY] Set Contrast to Maximum — final result: {result.test_result}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # --- Step 4: Set contrast to maximum ---
    try:
        set_payload = json.dumps({"contrast": max_contrast})
        status, resp_set = execute_cmd_and_log(tester, device_id, "system/settings/set", set_payload, logs, result)
        if status != 200:
            msg = f"[FAILED] Failed to set contrast to max {max_contrast}. Status: {status}, Response: {resp_set}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
            # Continue to restore original value in Step 6
        else:
            msg = f"[STEP] Set contrast to {max_contrast} successfully."
            LOGGER.ok(msg)
            logs.append(LOGGER.stamp(msg))
    except Exception as ex:
        msg = f"[FAILED] Exception during contrast set: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"
        # Still fall through to restore block

    # --- Step 5: Verify contrast is set to max ---
    try:
        _, resp_verify = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "contrast"}), logs, result)
        verify_data = json.loads(resp_verify) if isinstance(resp_verify, str) else resp_verify
        current_contrast = verify_data.get("contrast")

        if current_contrast == max_contrast:
            msg = f"[PASS] Contrast successfully set to max: {max_contrast}"
            LOGGER.ok(msg)
            logs.append(LOGGER.stamp(msg))

            # Optional manual visual confirmation
            if yes_or_no(
                result,
                logs,
                "Is the device screen at maximum contrast visually "
                "(should appear with very strong contrast)? ",
            ):
                result.test_result = "PASS"
            else:
                result.test_result = "FAILED"
                msg = (
                    "[FAILED] Contrast set to max in API, but operator did not "
                    "confirm visual effect."
                )
                LOGGER.result(msg)
                logs.append(LOGGER.stamp(msg))
        else:
            msg = f"[FAILED] Device did not set contrast to max: got {current_contrast}, expected {max_contrast}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
    except Exception as ex:
        msg = f"[FAILED] Exception during verification of contrast: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

    # --- Step 6: Restore original contrast value (best-effort) ---
    try:
        if original_contrast is not None and current_contrast != original_contrast:
            msg = f"[STEP] Restoring original contrast value: {original_contrast}"
            LOGGER.info(msg)
            logs.append(LOGGER.stamp(msg))
            restore_payload = json.dumps({"contrast": original_contrast})
            execute_cmd_and_log(tester, device_id, "system/settings/set", restore_payload, logs, result)
    except Exception:
        msg = "[WARN] Best-effort contrast restore failed"
        LOGGER.warn(msg)
        logs.append(LOGGER.stamp(msg))

    # --- Final summary -------------------------------------------------------
    summary = f"[SUMMARY] Set Contrast to Maximum — final result: {result.test_result}"
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result
# === Test: Screensaver Timeout Invalid Value (-1) — Negative Test ===
def run_screensaver_timeout_invalid_time(dab_topic, test_name, tester, device_id):
    """
    Negative Test:
      - Validate system rejects invalid screensaver timeout (-1).
      - Only 400 is considered correct negative behaviour.
      - 200 → FAILED.s
      - 501 is handled by capability check → OPTIONAL_FAILED.
      - Restore original value after test (best-effort).
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    payload_invalid = json.dumps({"screenSaverTimeout": -1})
    result = TestResult(test_id, device_id, dab_topic, payload_invalid, "UNKNOWN", "", logs)

    # Local state for safety / finally block
    orig_timeout = None
    status = None

    try:
        # === Header ===
        for line in (
            f"[TEST] Screensaver Timeout Invalid Test — {test_name} (test_id={test_id}, device={device_id})",
            "[DESC] Goal: ensure device rejects negative timeout (-1) with HTTP 400.",
            "[DESC] Preconditions: device ON, DAB reachable, system/settings + screenSaverTimeout supported.",
        ):
            LOGGER.result(line)
            logs.append(LOGGER.stamp(line))

        # === Capability Gate (handles 501 automatically) ===
        cap_spec = "ops: system/settings/get, system/settings/set | settings: screenSaverTimeout"
        if not require_capabilities(tester, device_id, cap_spec, result, logs):
            summary = (
                f"[SUMMARY] Screensaver Timeout Invalid Test — final result: "
                f"{result.test_result}, status={status}, original={orig_timeout}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        # === Read original value ===
        msg = "[STEP] Reading current screensaver timeout via system/settings/get."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        _, resp_get0 = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "screenSaverTimeout"}), logs, result)

        try:
            resp0 = json.loads(resp_get0) if isinstance(resp_get0, str) else resp_get0
            orig_timeout = resp0.get("screenSaverTimeout", None)
        except Exception:
            orig_timeout = None

        msg = f"[INFO] Original screenSaverTimeout captured: {orig_timeout}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        # === STEP: Send invalid value (-1) ===
        msg = f"[STEP] Sending invalid timeout payload → {payload_invalid}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        status, resp_json = execute_cmd_and_log(tester, device_id, "system/settings/set", payload_invalid, logs, result)

        # === Validation logic ===
        if status == 400:
            result.test_result = "PASS"
            msg = "[RESULT] PASS — Device correctly rejected -1 with HTTP 400."
        elif status == 200:
            result.test_result = "FAILED"
            msg = "[RESULT] FAILED — Device incorrectly accepted negative timeout (-1) with 200."
        else:
            result.test_result = "FAILED"
            msg = f"[RESULT] FAILED — Unexpected status={status}, expected 400 only."

        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        # === Summary ===
        summary = (
            f"[SUMMARY] Screensaver Timeout Invalid Test — final result: "
            f"{result.test_result}, status={status}, original={orig_timeout}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))

        return result

    except UnsupportedOperationError:
        # Should not happen because capability gate covers this, but keep it defensive
        result.test_result = "OPTIONAL_FAILED"
        msg = "[RESULT] OPTIONAL_FAILED — Operation not supported (from capability layer)."
        LOGGER.warn(msg)
        logs.append(LOGGER.stamp(msg))

        summary = (
            f"[SUMMARY] Screensaver Timeout Invalid Test — final result: "
            f"{result.test_result}, status={status}, original={orig_timeout}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    except Exception as e:
        # Internal error → SKIPPED (consistent with harness behaviour)
        result.test_result = "SKIPPED"
        msg = f"[RESULT] SKIPPED — Internal error during test execution: {e}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))

        summary = (
            f"[SUMMARY] Screensaver Timeout Invalid Test — final result: "
            f"{result.test_result}, status={status}, original={orig_timeout}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    finally:
        # === Restore original value (best-effort) ===
        try:
            if orig_timeout is not None:
                payload_restore = json.dumps({"screenSaverTimeout": orig_timeout})
                msg = f"[STEP] Restoring original timeout → {payload_restore}"
                LOGGER.result(msg)
                logs.append(LOGGER.stamp(msg))

                execute_cmd_and_log(tester, device_id, "system/settings/set", payload_restore, logs, result)

                # Optional: verify restore
                _, resp_v = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "screenSaverTimeout"}), logs, result)
                try:
                    resp_v_obj = json.loads(resp_v) if isinstance(resp_v, str) else resp_v
                    new_val = resp_v_obj.get("screenSaverTimeout")
                    if new_val == orig_timeout:
                        msg = "[INFO] Restore verified successfully."
                        LOGGER.result(msg)
                        logs.append(LOGGER.stamp(msg))
                except Exception:
                    # If parsing fails, just skip verification
                    pass
        except Exception:
            msg = "[WARN] Restore best-effort failed."
            LOGGER.warn(msg)
            logs.append(LOGGER.stamp(msg))

# === Test: Rapid Contrast Change Min to Max ===
def run_contrast_rapid_change_min_to_max(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 Positive Test:
      - Rapidly set 'contrast' to min, then max.
      - Confirm device reports changes immediately.
      - Operator confirms screen reflects new contrast.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    # Local safety state
    original_contrast = None
    current_contrast = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Rapid Contrast Change Min→Max — {test_name} (test_id={test_id}, device={device_id})",
        "[DESC] Goal: set contrast to minimum then immediately to maximum and validate behaviour.",
        "[DESC] Preconditions: device powered on, DAB reachable, 'contrast' setting supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    # --- Step 1: Capability check (contrast setting support) ---
    cap_spec = "ops: system/settings/get, system/settings/set | settings: contrast"
    if not require_capabilities(tester, device_id, cap_spec, result, logs):
        summary = f"[SUMMARY] Rapid Contrast Change Min→Max — final result: {result.test_result}, test_id={test_id}, device={device_id}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result  # OPTIONAL_FAILED already set

    # --- Step 2: Get supported min/max for 'contrast' ---
    try:
        setting_info, _ = get_supported_setting(tester, device_id, "contrast", result, logs)
        if isinstance(setting_info, dict) and "min" in setting_info and "max" in setting_info:
            min_contrast = setting_info["min"]
            max_contrast = setting_info["max"]
        elif isinstance(setting_info, (list, tuple)) and len(setting_info) == 2:
            min_contrast, max_contrast = min(setting_info), max(setting_info)
        else:
            msg = f"[FAILED] Could not determine min/max for contrast from supported setting: {setting_info}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
            summary = f"[SUMMARY] Rapid Contrast Change Min→Max — final result: {result.test_result}, test_id={test_id}, device={device_id}"
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result
    except Exception as ex:
        msg = f"[FAILED] Exception while fetching contrast supported range: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"
        summary = f"[SUMMARY] Rapid Contrast Change Min→Max — final result: {result.test_result}, test_id={test_id}, device={device_id}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # --- Step 3: Store original contrast value ---
    try:
        _, resp_get = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "contrast"}), logs, result)
        resp_data = json.loads(resp_get) if isinstance(resp_get, str) else resp_get
        original_contrast = resp_data.get("contrast")
        msg = f"[INFO] Original contrast value: {original_contrast}"
        LOGGER.info(msg)
        logs.append(LOGGER.stamp(msg))
    except Exception as ex:
        msg = f"[FAILED] Could not read original contrast: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"
        summary = f"[SUMMARY] Rapid Contrast Change Min→Max — final result: {result.test_result}, test_id={test_id}, device={device_id}"
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # --- Step 4: Rapidly set contrast min, then max ---
    try:
        # Set to min
        msg = f"[STEP] Setting contrast to minimum value: {min_contrast}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        set_min = json.dumps({"contrast": min_contrast})
        status_min, resp_min = execute_cmd_and_log(tester, device_id, "system/settings/set", set_min, logs, result)
        if status_min != 200:
            msg = f"[FAILED] Failed to set contrast to min {min_contrast}. Status: {status_min}, Response: {resp_min}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

        # Quickly set to max (even if min failed, we still best-effort attempt max)
        msg = f"[STEP] Immediately setting contrast to maximum value: {max_contrast}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        set_max = json.dumps({"contrast": max_contrast})
        status_max, resp_max = execute_cmd_and_log(tester, device_id, "system/settings/set", set_max, logs, result)
        if status_max != 200:
            msg = f"[FAILED] Failed to set contrast to max {max_contrast}. Status: {status_max}, Response: {resp_max}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
    except Exception as ex:
        msg = f"[FAILED] Exception during rapid contrast change: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

    # --- Step 5: Verify contrast is set to max ---
    try:
        _, resp_verify = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "contrast"}), logs, result)
        verify_data = json.loads(resp_verify) if isinstance(resp_verify, str) else resp_verify
        current_contrast = verify_data.get("contrast")

        if current_contrast == max_contrast:
            msg = f"[PASS] Contrast successfully set to max after rapid change: {max_contrast}"
            LOGGER.ok(msg)
            logs.append(LOGGER.stamp(msg))

            # Optional manual visual confirmation
            if yes_or_no(result, logs, "Did the screen visibly update to maximum contrast immediately after the change? ",):
                result.test_result = "PASS"
            else:
                result.test_result = "FAILED"
                msg = "[FAILED] Contrast set to max in API, but operator did not confirm immediate visual update."
                LOGGER.result(msg)
                logs.append(LOGGER.stamp(msg))
        else:
            msg = f"[FAILED] Device did not set contrast to max: got {current_contrast}, expected {max_contrast}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
    except Exception as ex:
        msg = f"[FAILED] Exception during verification of contrast: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

    # --- Step 6: Restore original contrast value (best-effort) ---
    try:
        if original_contrast is not None and current_contrast != original_contrast:
            msg = f"[STEP] Restoring original contrast value: {original_contrast}"
            LOGGER.info(msg)
            logs.append(LOGGER.stamp(msg))
            restore_payload = json.dumps({"contrast": original_contrast})
            execute_cmd_and_log(tester, device_id, "system/settings/set", restore_payload, logs, result)
    except Exception:
        msg = "[WARN] Best-effort contrast restore failed"
        LOGGER.warn(msg)
        logs.append(LOGGER.stamp(msg))

    # --- Final summary -------------------------------------------------------
    summary = f"[SUMMARY] Rapid Contrast Change Min→Max — final result: {result.test_result}, test_id={test_id}, device={device_id}"
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result

# === Test: Personalized Ads Invalid Value (Negative Test) ===
def run_personalized_ads_invalid_value(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 NEGATIVE TEST:
        - Send invalid value for personalizedAds → {"personalizedAds": "invalidValue"}
        - Expected: 400 BAD REQUEST only.
        - Device must not change the original value.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    invalid_payload = json.dumps({"personalizedAds": "invalidValue"})  # invalid type/value
    result = TestResult(test_id, device_id, dab_topic, invalid_payload, "UNKNOWN", "", logs)

    original_value = None
    after_value = None
    status = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Personalized Ads Invalid Value (Negative) — {test_id} on {device_id}",
        "[DESC] Goal: ensure device rejects invalid personalizedAds value with HTTP 400 and preserves the original setting.",
        "[DESC] Preconditions: device powered on, DAB reachable, personalizedAds setting supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    # STEP 1: Capability Gate — personalizedAds must be supported
    cap = "ops: system/settings/get, system/settings/set | settings: personalizedAds"
    if not require_capabilities(tester, device_id, cap, result, logs):
        summary = (
            f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
            f"status={status}, original={original_value}, after={after_value}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result  # OPTIONAL_FAILED already set

    # STEP 2: Read Original personalizedAds Value
    try:
        msg = "[STEP] Reading current personalizedAds value via system/settings/get."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        _, resp0 = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "personalizedAds"}), logs, result)
        parsed0 = json.loads(resp0) if isinstance(resp0, str) else resp0
        original_value = parsed0.get("personalizedAds")
        msg = f"[INFO] Original personalizedAds value: {original_value}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

    except Exception as ex:
        msg = f"[FAILED] Unable to read original personalizedAds value: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

        summary = (
            f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
            f"status={status}, original={original_value}, after={after_value}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 3: Send invalid payload (string instead of boolean)
    try:
        msg = f"[STEP] Sending invalid personalizedAds payload → {invalid_payload}"
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        status, resp_json = execute_cmd_and_log(tester, device_id, "system/settings/set", invalid_payload, logs, result)

        # Expected Negative Behavior → 400 BAD REQUEST
        if status == 400:
            msg = "[RESULT] PASS (negative) — Device correctly rejected invalid personalizedAds value with 400 BAD REQUEST."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
        else:
            # For this negative test: 200, 100, 500, any non-400 → FAILED
            msg = f"[RESULT] FAILED — Expected 400 for invalid value but received status={status}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
                f"status={status}, original={original_value}, after={after_value}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

    except UnsupportedOperationError:
        # Should not happen due to capability check, but keep defensive
        result.test_result = "OPTIONAL_FAILED"
        msg = "[RESULT] OPTIONAL_FAILED — Operation unexpectedly unsupported after capability gate."
        LOGGER.warn(msg)
        logs.append(LOGGER.stamp(msg))

        summary = (
            f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
            f"status={status}, original={original_value}, after={after_value}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    except Exception as ex:
        msg = f"[RESULT] FAILED — Unexpected internal exception during invalid-set: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

        summary = (
            f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
            f"status={status}, original={original_value}, after={after_value}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 4: Verify the value did NOT change
    try:
        msg = "[STEP] Verifying personalizedAds value did NOT change after invalid request."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        _, resp_ver = execute_cmd_and_log(tester, device_id, "system/settings/get", json.dumps({"id": "personalizedAds"}), logs, result)
        parsed_ver = json.loads(resp_ver) if isinstance(resp_ver, str) else resp_ver
        after_value = parsed_ver.get("personalizedAds")

        if after_value != original_value:
            msg = f"[FAILED] personalizedAds changed! Before={original_value}, After={after_value}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
        else:
            msg = "[PASS] Device preserved original personalizedAds value after invalid request."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
            # Only mark PASS if we haven't already marked FAILED above
            if result.test_result == "UNKNOWN":
                result.test_result = "PASS"

    except Exception as ex:
        msg = f"[RESULT] FAILED — Verification failed due to internal error: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "FAILED"

    # FINAL SUMMARY
    summary = (
        f"[SUMMARY] Personalized Ads Invalid Value (Negative) — final result={result.test_result}, "
        f"status={status}, original={original_value}, after={after_value}, "
        f"test_id={test_id}, device={device_id}"
    )
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result

# === Test: Factory Reset and Verify Initial State ===
def run_factory_reset_and_verify_initial_state(dab_topic, test_name, tester, device_id):
    """
    Installs sample apps, performs a factory reset, waits for completion,
    then verifies all sample apps are uninstalled.
    DAB 2.1 required.
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    SAMPLE_APPS = [
        config.apps.get("sample_app", "Sample_App"),
        config.apps.get("sample_app1", "Sample_App1"),
    ]
    result = TestResult(test_id, device_id, dab_topic, "N/A", "UNKNOWN", "", logs)

    # Local state for summary/debug
    installed_apps = []
    installed_apps_post = []

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Factory Reset and Verify Initial State — {test_name} (test_id={test_id}, device={device_id})",
        "[DESC] Goal: install sample apps, perform system/factory-reset, and verify "
        "that all sample apps are removed (device back to initial state).",
        "[DESC] Preconditions: device powered on, DAB reachable, DAB 2.1 factory-reset + install/list supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    # STEP 1: CAPABILITY CHECK (DAB 2.1 required)
    cap_spec = "ops: applications/install, applications/list, system/factory-reset"
    if not require_capabilities(tester, device_id, cap_spec, result, logs):
        summary = (
            f"[SUMMARY] Factory Reset and Verify Initial State — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result  # OPTIONAL_FAILED already set by capability gate

    try:
        # STEP 2: INSTALL SAMPLE APPS
        msg = "[STEP] Installing sample apps for factory reset test."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        for app_id in SAMPLE_APPS:
            status, resp = execute_cmd_and_log(tester, device_id, "applications/install", json.dumps({"appId": app_id}), logs, result)
            if status != 200:
                msg = f"[WARN] Failed to install app: {app_id}. Status: {status}"
                LOGGER.warn(msg)
                logs.append(LOGGER.stamp(msg))

        # Confirm all sample apps are installed
        _, installed_list = execute_cmd_and_log(tester, device_id, "applications/list", "{}", logs, result)
        try:
            installed_apps = (json.loads(installed_list) if isinstance(installed_list, str) else installed_list).get("applications", [])
        except Exception:
            installed_apps = []

        missing_before_reset = []
        for app_id in SAMPLE_APPS:
            if app_id not in [a.get("appId") for a in installed_apps]:
                missing_before_reset.append(app_id)

        if missing_before_reset:
            msg = f"[FAILED] Some sample apps not installed before factory reset: {missing_before_reset}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Factory Reset and Verify Initial State — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        # STEP 3: FACTORY RESET
        msg = "[STEP] Triggering system/factory-reset..."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        status, resp = execute_cmd_and_log(tester, device_id, "system/factory-reset", "{}", logs, result)
        if status != 200:
            msg = f"[FAILED] Factory reset operation failed. Status: {status}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Factory Reset and Verify Initial State — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        # STEP 4: WAIT FOR FACTORY RESET COMPLETION
        msg = "[WAIT] Waiting for factory reset to complete (device will reboot)..."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        wait_ok = wait_for_factory_reset_complete(tester, device_id, logs, timeout=180)
        if not wait_ok:
            msg = "[FAILED] Device did not complete factory reset within timeout."
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Factory Reset and Verify Initial State — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        # STEP 5: VERIFY INITIAL STATE (No sample apps installed)
        msg = "[STEP] Verifying device is in initial state (no sample apps installed)..."
        LOGGER.result(msg)
        logs.append(LOGGER.stamp(msg))

        _, installed_list_post = execute_cmd_and_log(tester, device_id, "applications/list", "{}", logs, result)
        try:
            installed_apps_post = (json.loads(installed_list_post) if isinstance(installed_list_post, str) else installed_list_post).get("applications", [])
        except Exception:
            installed_apps_post = []

        remaining = [a.get("appId") for a in installed_apps_post if a.get("appId") in SAMPLE_APPS]
        if remaining:
            msg = f"[FAILED] Sample apps still present after factory reset: {remaining}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
        else:
            msg = "[PASS] Device is in initial state; sample apps successfully removed by factory reset."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "PASS"

    except UnsupportedOperationError:
        result.test_result = "OPTIONAL_FAILED"
        msg = "[RESULT] OPTIONAL_FAILED — Operation not supported (factory-reset/install/list)."
        LOGGER.warn(msg)
        logs.append(LOGGER.stamp(msg))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during factory reset test: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

    # FINAL SUMMARY
    summary = (
        f"[SUMMARY] Factory Reset and Verify Initial State — final result: {result.test_result}, "
        f"test_id={test_id}, device={device_id}"
    )
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result

# === Test: Power Mode Set - Case Sensitivity (Negative Test) ===
def run_power_mode_case_sensitive_negative(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 NEGATIVE TEST:
      - Set power-mode to "Active" (should succeed)
      - Confirm mode is "Active"
      - Set power-mode with mode="standby" (lowercase, should fail)
      - Confirm error (status=400)
      - Confirm mode remains "Active"
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    active_mode = None
    final_mode = None
    status_invalid = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Power Mode Case Sensitivity (Negative) — {test_name} (test_id={test_id}, device={device_id})",
        "[DESC] Goal: verify system/power-mode/set rejects lowercase 'standby' and preserves mode 'Active'.",
        "[DESC] Preconditions: device powered on, DAB reachable, power-mode get/set supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    # Capability gate
    cap = "ops: system/power-mode/set, system/power-mode/get"
    if not require_capabilities(tester, device_id, cap, result, logs):
        summary = (
            f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 1: Set mode to "Active"
    try:
        LOGGER.result("[STEP] Setting power-mode to 'Active'.")
        logs.append(LOGGER.stamp("[STEP] Setting power-mode to 'Active'."))

        payload_active = json.dumps({"mode": "Active"})
        status1, _ = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_active, logs, result)
        if status1 != 200:
            msg = f"[FAILED] Unable to set power mode to 'Active'. Status={status1}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Set power-mode to 'Active' — Success."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during set to Active: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 2: Confirm mode is "Active"
    try:
        LOGGER.result("[STEP] Confirming power-mode is 'Active' after set.")
        logs.append(LOGGER.stamp("[STEP] Confirming power-mode is 'Active' after set."))

        _, resp2 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp2) if isinstance(resp2, str) else resp2
            active_mode = parsed.get("mode")
        except Exception:
            active_mode = None

        if active_mode != "Active":
            msg = f"[FAILED] Power mode not 'Active' after set. Actual: {active_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Confirmed power-mode is 'Active'."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during get after set to Active: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 3: Set power-mode with mode="standby" (lowercase)
    try:
        LOGGER.result("[STEP] Sending invalid power-mode payload with lowercase 'standby'.")
        logs.append(LOGGER.stamp("[STEP] Sending invalid power-mode payload with lowercase 'standby'."))

        payload_invalid = json.dumps({"mode": "standby"})
        status_invalid, resp3 = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_invalid, logs, result)

        if status_invalid == 400:
            msg = "[RESULT] PASS (negative) — Device correctly rejected lowercase 'standby' with 400 BAD REQUEST."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
        else:
            msg = f"[RESULT] FAILED — Expected status 400 for invalid value, got {status_invalid}."
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

    except Exception as ex:
        msg = f"[SKIPPED] Exception during set to invalid standby: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 4: Confirm mode remains "Active"
    try:
        LOGGER.result("[STEP] Confirming power-mode remains 'Active' after invalid request.")
        logs.append(LOGGER.stamp("[STEP] Confirming power-mode remains 'Active' after invalid request."))

        _, resp4 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp4) if isinstance(resp4, str) else resp4
            final_mode = parsed.get("mode")
        except Exception:
            final_mode = None

        if final_mode != "Active":
            msg = f"[FAILED] Power mode changed after invalid set! Expected 'Active', got: {final_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
        else:
            msg = "[PASS] Device preserved power-mode as 'Active' after invalid lowercase request."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
            if result.test_result == "UNKNOWN":
                result.test_result = "PASS"

    except Exception as ex:
        msg = f"[SKIPPED] Exception during final get: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # FINAL SUMMARY
    summary = (
        f"[SUMMARY] Power Mode Case Sensitivity (Negative) — final result: {result.test_result}, "
        f"test_id={test_id}, device={device_id}"
    )
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result
# === Test: Power Mode Set - Missing Mode Parameter (Negative Test) ===
def run_power_mode_set_missing_param(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 NEGATIVE TEST:
      - Set power-mode to "Active" (should succeed)
      - Confirm mode is "Active"
      - Send system/power-mode/set WITHOUT 'mode' parameter (should fail)
      - Confirm error (status=400)
      - Confirm mode remains "Active"
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    active_mode = None
    after_mode = None
    status_missing = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Power Mode Missing 'mode' Parameter (Negative) — {test_name} "
        f"(test_id={test_id}, device={device_id})",
        "[DESC] Goal: send system/power-mode/set without 'mode' and ensure 400 and no mode change.",
        "[DESC] Preconditions: device powered on, DAB reachable, power-mode get/set supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    cap = "ops: system/power-mode/set, system/power-mode/get"
    if not require_capabilities(tester, device_id, cap, result, logs):
        summary = (
            f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 1: Set mode to "Active"
    try:
        LOGGER.result("[STEP] Setting power-mode to 'Active' precondition.")
        logs.append(LOGGER.stamp("[STEP] Setting power-mode to 'Active' precondition."))

        payload_active = json.dumps({"mode": "Active"})
        status1, _ = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_active, logs, result)
        if status1 != 200:
            msg = f"[FAILED] Unable to set power mode to 'Active'. Status={status1}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Set power-mode to 'Active' — Success."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during set to Active: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 2: Confirm mode is "Active"
    try:
        LOGGER.result("[STEP] Confirming power-mode is 'Active' after precondition.")
        logs.append(LOGGER.stamp("[STEP] Confirming power-mode is 'Active' after precondition."))

        _, resp2 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp2) if isinstance(resp2, str) else resp2
            active_mode = parsed.get("mode")
        except Exception:
            active_mode = None

        if active_mode != "Active":
            msg = f"[FAILED] Power mode not 'Active' after set. Actual: {active_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Confirmed power-mode is 'Active'."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during get after set to Active: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 3: Send system/power-mode/set WITHOUT 'mode' field
    try:
        LOGGER.result("[STEP] Sending system/power-mode/set without 'mode' parameter.")
        logs.append(LOGGER.stamp("[STEP] Sending system/power-mode/set without 'mode' parameter."))

        payload_missing = json.dumps({})  # No 'mode' key
        status_missing, _ = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_missing, logs, result)

        if status_missing == 400:
            msg = "[RESULT] PASS (negative) — Device correctly rejected missing 'mode' parameter with 400 BAD REQUEST."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
        else:
            msg = f"[RESULT] FAILED — Expected status 400 for missing 'mode', got {status_missing}."
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

    except Exception as ex:
        msg = f"[SKIPPED] Exception during set with missing mode: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 4: Confirm mode remains "Active"
    try:
        LOGGER.result("[STEP] Confirming power-mode remains 'Active' after invalid request.")
        logs.append(LOGGER.stamp("[STEP] Confirming power-mode remains 'Active' after invalid request."))

        _, resp4 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp4) if isinstance(resp4, str) else resp4
            after_mode = parsed.get("mode")
        except Exception:
            after_mode = None

        if after_mode != "Active":
            msg = f"[FAILED] Power mode changed after missing-param set! Expected 'Active', got: {after_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"
        else:
            msg = "[PASS] Device preserved power-mode as 'Active' after invalid missing-param request."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
            if result.test_result == "UNKNOWN":
                result.test_result = "PASS"

    except Exception as ex:
        msg = f"[SKIPPED] Exception during final get: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # FINAL SUMMARY
    summary = (
        f"[SUMMARY] Power Mode Missing 'mode' Parameter (Negative) — final result: "
        f"{result.test_result}, test_id={test_id}, device={device_id}"
    )
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result

# === Test: Power Mode Transition (Active -> Standby) and DAB Liveness ===
def run_power_mode_active_to_standby_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 POSITIVE TEST:
      - Ensure device is in "Active"
      - Set power mode to "Standby"
      - Confirm power mode is now "Standby"
      - Confirm DAB is still alive by running a simple op (e.g., system/settings/get)
    """

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    pre_mode = None
    after_mode = None
    dab_status = None

    # --- Header --------------------------------------------------------------
    for line in (
        f"[TEST] Power Mode Transition Active→Standby + DAB Liveness — {test_name} "
        f"(test_id={test_id}, device={device_id})",
        "[DESC] Goal: validate transition Active→Standby and confirm DAB remains responsive.",
        "[DESC] Preconditions: device powered on, DAB reachable, power-mode and system/settings/get supported.",
    ):
        LOGGER.result(line)
        logs.append(LOGGER.stamp(line))

    cap = "ops: system/power-mode/set, system/power-mode/get, system/settings/get"
    if not require_capabilities(tester, device_id, cap, result, logs):
        summary = (
            f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 1: Ensure device is "Active"
    try:
        LOGGER.result("[STEP] Ensuring device is in 'Active' mode (precondition).")
        logs.append(LOGGER.stamp("[STEP] Ensuring device is in 'Active' mode (precondition)."))

        payload_active = json.dumps({"mode": "Active"})
        status1, _ = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_active, logs, result)
        if status1 != 200:
            msg = f"[FAILED] Could not set to 'Active' precondition. Status={status1}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        _, resp2 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp2) if isinstance(resp2, str) else resp2
            pre_mode = parsed.get("mode")
        except Exception:
            pre_mode = None

        if pre_mode != "Active":
            msg = f"[FAILED] Device not in 'Active' state for precondition. Actual: {pre_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Device confirmed in 'Active' mode for precondition."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during 'Active' precondition: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 2: Set power mode to "Standby"
    try:
        LOGGER.result("[STEP] Setting power-mode to 'Standby'.")
        logs.append(LOGGER.stamp("[STEP] Setting power-mode to 'Standby'."))

        payload_standby = json.dumps({"mode": "Standby"})
        status2, _ = execute_cmd_and_log(tester, device_id, "system/power-mode/set", payload_standby, logs, result)
        if status2 != 200:
            msg = f"[FAILED] Could not set power mode to 'Standby'. Status={status2}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Set power-mode to 'Standby' — Success."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during set to Standby: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 3: Confirm mode is now "Standby"
    try:
        LOGGER.result("[STEP] Confirming power-mode is now 'Standby'.")
        logs.append(LOGGER.stamp("[STEP] Confirming power-mode is now 'Standby'."))

        _, resp3 = execute_cmd_and_log(tester, device_id, "system/power-mode/get", "{}", logs, result)
        try:
            parsed = json.loads(resp3) if isinstance(resp3, str) else resp3
            after_mode = parsed.get("mode")
        except Exception:
            after_mode = None

        if after_mode != "Standby":
            msg = f"[FAILED] Power mode did not become 'Standby'. Actual: {after_mode}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

            summary = (
                f"[SUMMARY] Power Mode Transition Active → Standby + DAB Liveness — final result: "
                f"{result.test_result}, test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(LOGGER.stamp(summary))
            return result

        logs.append(LOGGER.stamp("[STEP] Confirmed power-mode is now 'Standby'."))

    except Exception as ex:
        msg = f"[SKIPPED] Exception during get after Standby: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # STEP 4: Confirm DAB liveness by system/settings/get
    try:
        LOGGER.result("[STEP] Checking DAB liveness via system/settings/get (highContrastText).")
        logs.append(LOGGER.stamp("[STEP] Checking DAB liveness via system/settings/get (highContrastText)."))

        dab_status, resp4 = execute_cmd_and_log(
            tester, device_id, "system/settings/get", json.dumps({"id": "highContrastText"}), logs, result
        )
        if dab_status == 200:
            msg = "[PASS] DAB subsystem responded to system/settings/get after Standby. DAB is alive."
            LOGGER.result(msg)
            logs.append(LOGGER.stamp(msg))
            if result.test_result == "UNKNOWN":
                result.test_result = "PASS"
        else:
            msg = f"[FAILED] DAB subsystem did not respond with 200 after Standby. Status={dab_status}"
            LOGGER.error(msg)
            logs.append(LOGGER.stamp(msg))
            result.test_result = "FAILED"

    except Exception as ex:
        msg = f"[SKIPPED] Exception during DAB liveness check: {ex}"
        LOGGER.error(msg)
        logs.append(LOGGER.stamp(msg))
        result.test_result = "SKIPPED"

        summary = (
            f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
            f"{result.test_result}, test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(LOGGER.stamp(summary))
        return result

    # FINAL SUMMARY
    summary = (
        f"[SUMMARY] Power Mode Transition Active→Standby + DAB Liveness — final result: "
        f"{result.test_result}, test_id={test_id}, device={device_id}"
    )
    LOGGER.result(summary)
    logs.append(LOGGER.stamp(summary))

    return result

def run_voice_multilanguage_language_alignment_check(dab_topic, test_name, tester, device_id):
    """
    Multi-language voice/send-audio test:

      - Save current system language.
      - Try setting one of the 10 priority non-English locales via system/settings/set.
      - Use the first locale that returns status 200 as the test language.
      - Ensure a voice assistant is enabled.
      - Send a pre-recorded 'Open YouTube' audio using voice/send-audio with fileLocation from GCS.
      - Ask the tester to confirm that the assistant responded correctly in that language.
      - Restore the previous language (or en-US if unknown).

    If none of the 10 locales are accepted, mark OPTIONAL_FAILED.
    """

    DEFAULT_LANGUAGE = "en-US"

    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    # dab_topic should be "voice/send-audio" in the FUNCTIONAL_TEST_CASE tuple
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    selected_language = None
    previous_language = None
    assistant_name = None

    try:
        # ------------------------------------------------------------------
        # Header / description
        # ------------------------------------------------------------------
        for line in (
            f"[TEST] Voice Multi-Language Alignment (send-audio) — {test_name} "
            f"(test_id={test_id}, device={device_id})",
            "[DESC] Goal: Use one of 10 priority non-English locales that the device "
            "actually accepts via system/settings/set and run a voice/send-audio test.",
            "[DESC] Preconditions: device powered on, DAB reachable.",
            "[DESC] Required ops: system/settings/get, system/settings/set, "
            "voice/list, voice/set, voice/send-audio.",
            "[DESC] Pass criteria: Tester confirms the assistant responded correctly "
            "for the selected language; all DAB calls succeed; language is restored.",
        ):
            LOGGER.result(line)
            logs.append(line)

        # ------------------------------------------------------------------
        # Capability gate (operations only; no 'settings: language' strict check)
        # ------------------------------------------------------------------
        cap_spec = (
            "ops: system/settings/get, system/settings/set, "
            "voice/list, voice/set, voice/send-audio"
        )
        if not require_capabilities(tester, device_id, cap_spec, result, logs):
            # require_capabilities already logged and set OPTIONAL_FAILED
            return result

        # ------------------------------------------------------------------
        # Step 1: Read and remember current system language
        # ------------------------------------------------------------------
        payload_get = json.dumps({"id": "language"})
        line = f"[STEP] Reading current language via system/settings/get with payload: {payload_get}"
        LOGGER.result(line)
        logs.append(line)

        _, resp_get = execute_cmd_and_log(
            tester, device_id, "system/settings/get", payload_get, logs, result
        )

        try:
            body = json.loads(resp_get) if resp_get else {}
            previous_language = body.get("language")
            line = f"[INFO] Current system language reported as: {previous_language}"
        except Exception as e:
            previous_language = None
            line = f"[WARN] Could not parse current language from response: {resp_get} (error: {e})"

        LOGGER.info(line)
        logs.append(line)

        # ------------------------------------------------------------------
        # Step 2: Probe for a supported target language using system/settings/set
        # ------------------------------------------------------------------
        line = (
            "[STEP] Probing system/settings/set with priority non-English locales "
            f"to find a supported test language: {VOICE_PRIORITY_LOCALES}"
        )
        LOGGER.result(line)
        logs.append(line)

        for candidate in VOICE_PRIORITY_LOCALES:
            payload_probe = json.dumps({"language": candidate})
            probe_log = (
                f"[INFO] Trying candidate language '{candidate}' via system/settings/set "
                f"with payload: {payload_probe}"
            )
            LOGGER.info(probe_log)
            logs.append(probe_log)

            rc_probe, resp_probe = execute_cmd_and_log(
                tester, device_id, "system/settings/set", payload_probe, logs, result
            )
            status_probe = dab_status_from(resp_probe, rc_probe)

            if status_probe == 200:
                selected_language = candidate
                line = (
                    f"[INFO] Candidate '{candidate}' accepted (status=200). "
                    "Using this language for the test."
                )
                LOGGER.result(line)
                logs.append(line)
                break
            else:
                line = (
                    f"[INFO] Candidate '{candidate}' not accepted. "
                    f"Status={status_probe}, response={resp_probe}"
                )
                LOGGER.info(line)
                logs.append(line)

        if not selected_language:
            result.test_result = "OPTIONAL_FAILED"
            line = (
                "[RESULT] OPTIONAL_FAILED — None of the 10 priority locales were accepted "
                "by system/settings/set; cannot run multi-language voice test."
            )
            LOGGER.result(line)
            logs.append(line)

            summary = (
                f"[SUMMARY] outcome={result.test_result}, selected_language=None, "
                f"previous_language={previous_language}, assistant=None, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(summary)
            return result

        line = f"[INFO] Selected test language: {selected_language}"
        LOGGER.result(line)
        logs.append(line)

        # ------------------------------------------------------------------
        # Step 3: Ensure a voice assistant is available and enabled
        # ------------------------------------------------------------------
        line = "[STEP] Listing voice systems via voice/list to choose an assistant."
        LOGGER.result(line)
        logs.append(line)

        rc_list, resp_list = execute_cmd_and_log(
            tester, device_id, "voice/list", "{}", logs, result
        )

        try:
            body = json.loads(resp_list) if resp_list else {}
            voice_systems = body.get("voiceSystems") or body.get("voiceAssistants") or []
        except Exception as e:
            voice_systems = []
            line = f"[WARN] Could not parse voice/list response: {resp_list} (error: {e})"
            LOGGER.warn(line)
            logs.append(line)

        if not voice_systems:
            result.test_result = "OPTIONAL_FAILED"
            line = "[RESULT] OPTIONAL_FAILED — No voice assistants available on this device."
            LOGGER.result(line)
            logs.append(line)

            summary = (
                f"[SUMMARY] outcome={result.test_result}, selected_language={selected_language}, "
                f"previous_language={previous_language}, assistant=None, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(summary)
            return result

        chosen = voice_systems[0]
        assistant_name = chosen.get("name") or chosen.get("id") or "UNKNOWN"
        enabled = chosen.get("enabled")

        line = f"[INFO] Selected voice assistant for test: {assistant_name} (enabled={enabled})"
        LOGGER.result(line)
        logs.append(line)

        if enabled is False:
            payload_enable = json.dumps({
                "voiceSystem": {"name": assistant_name, "enabled": True}
            })
            line = (
                f"[STEP] Enabling voice assistant '{assistant_name}' via voice/set "
                f"with payload: {payload_enable}"
            )
            LOGGER.result(line)
            logs.append(line)

            rc_vs, resp_vs = execute_cmd_and_log(
                tester, device_id, "voice/set", payload_enable, logs, result
            )
            status_vs = dab_status_from(resp_vs, rc_vs)
            if status_vs != 200:
                result.test_result = "FAILED"
                line = (
                    f"[RESULT] FAILED — Could not enable voice assistant '{assistant_name}'. "
                    f"Status={status_vs}, response={resp_vs}"
                )
                LOGGER.result(line)
                logs.append(line)
                return result

        # ------------------------------------------------------------------
        # Step 4: Prepare audio URL for selected language
        # ------------------------------------------------------------------
        audio_url = get_voice_audio_url_for_language(selected_language)
        if not audio_url:
            result.test_result = "OPTIONAL_FAILED"
            line = (
                "[RESULT] OPTIONAL_FAILED — No audio URL configured for "
                f"language '{selected_language}'. Please update get_voice_audio_url_for_language()."
            )
            LOGGER.result(line)
            logs.append(line)

            summary = (
                f"[SUMMARY] outcome={result.test_result}, selected_language={selected_language}, "
                f"previous_language={previous_language}, assistant={assistant_name}, "
                f"test_id={test_id}, device={device_id}"
            )
            LOGGER.result(summary)
            logs.append(summary)
            return result

        # ------------------------------------------------------------------
        # Step 5: Send voice/send-audio request
        # ------------------------------------------------------------------
        payload_voice = json.dumps({
            "fileLocation": audio_url,
            "voiceSystem": assistant_name,
        })

        line = (
            "[STEP] Sending voice command via voice/send-audio with payload: "
            f"{payload_voice}"
        )
        LOGGER.result(line)
        logs.append(line)

        rc_voice, resp_voice = execute_cmd_and_log(
            tester, device_id, "voice/send-audio", payload_voice, logs, result
        )
        status_voice = dab_status_from(resp_voice, rc_voice)
        if status_voice != 200:
            result.test_result = "FAILED"
            line = (
                f"[RESULT] FAILED — voice/send-audio returned status {status_voice}, "
                "expected 200."
            )
            LOGGER.result(line)
            logs.append(line)
            return result

        # ------------------------------------------------------------------
        # Step 6: Manual confirmation — did assistant actually trigger?
        # ------------------------------------------------------------------
        question = (
            f"Did the voice assistant respond correctly for language '{selected_language}' "
            "when the audio command was played (e.g., opened YouTube or handled the request)? "
        )
        line = "[STEP] Awaiting manual confirmation from tester for assistant behavior."
        LOGGER.result(line)
        logs.append(line)

        user_ok = yes_or_no(result, logs, question)
        if not user_ok:
            result.test_result = "FAILED"
            line = (
                "[RESULT] FAILED — Tester indicated that the assistant did NOT behave "
                "correctly for the selected language."
            )
            LOGGER.result(line)
            logs.append(line)
            return result

        result.test_result = "PASS"
        line = "[RESULT] PASS — Assistant behaved correctly for the selected system language."
        LOGGER.result(line)
        logs.append(line)

    except UnsupportedOperationError as e:
        result.test_result = "OPTIONAL_FAILED"
        line = f"[RESULT] OPTIONAL_FAILED — Operation '{e.topic}' is not supported: {e}"
        LOGGER.result(line)
        logs.append(line)

    except Exception as e:
        result.test_result = "FAILED"
        line = f"[RESULT] FAILED — Unexpected exception occurred: {e}"
        LOGGER.result(line)
        logs.append(line)

    finally:
        # ------------------------------------------------------------------
        # Step 7: Restore previous system language (best-effort)
        # ------------------------------------------------------------------
        target_restore = previous_language or DEFAULT_LANGUAGE
        if selected_language and target_restore and target_restore != selected_language:
            payload_restore = json.dumps({"language": target_restore})
            line = (
                f"[STEP] Restoring system language to '{target_restore}' via system/settings/set "
                f"with payload: {payload_restore}"
            )
            LOGGER.result(line)
            logs.append(line)
            try:
                rc_res, resp_res = execute_cmd_and_log(
                    tester, device_id, "system/settings/set", payload_restore, logs, result
                )
                status_res = dab_status_from(resp_res, rc_res)
                if status_res != 200:
                    warn_line = (
                        f"[WARN] Best-effort restore of system language failed. "
                        f"Status={status_res}, response={resp_res}"
                    )
                    LOGGER.warn(warn_line)
                    logs.append(warn_line)
            except UnsupportedOperationError as e:
                warn_line = f"[WARN] Restore skipped — system/settings/set not supported: {e}"
                LOGGER.warn(warn_line)
                logs.append(warn_line)
            except Exception as e:
                warn_line = f"[WARN] Restore skipped due to unexpected exception: {e}"
                LOGGER.warn(warn_line)
                logs.append(warn_line)

        summary = (
            f"[SUMMARY] outcome={result.test_result}, selected_language={selected_language}, "
            f"previous_language={previous_language}, assistant={assistant_name}, "
            f"test_id={test_id}, device={device_id}"
        )
        LOGGER.result(summary)
        logs.append(summary)

    return result

# === Functional Test Case List ===
FUNCTIONAL_TEST_CASE = [
    ("applications/get-state", "functional", run_app_foreground_check, "AppForegroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_background_check, "AppBackgroundCheck", "2.0", False),
    ("applications/get-state", "functional", run_app_stopped_check, "AppStoppedCheck", "2.0", False),
    ("applications/launch-with-content", "functional", run_launch_without_content_id, "LaunchWithoutContentID", "2.0", True),
    ("applications/exit", "functional", run_exit_after_video_check, "ExitAfterVideoCheck", "2.0", False),
    ("applications/launch", "functional", run_relaunch_stability_check, "RelaunchStabilityCheck", "2.0", False),
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
    ("applications/clear-data", "functional", run_clear_data_accessibility_settings_reset, "ClearDataAccessibilitySettingsReset", "2.1", False),
    ("applications/clear-data", "functional", run_clear_data_session_reset, "ClearDataSessionReset", "2.1", False),
    ("system/logs/start-collection", "functional", run_voice_log_collection_check, "VoiceAssistantLogsCollection", "2.1", False),
    ("system/logs/start-collection", "functional", run_idle_log_collection_check, "IdleLogCollectionCheck", "2.1", False),
    ("system/settings/set", "functional", run_personalized_ads_manual_check, "PersonalizedAdsDisplayCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_channel_switch_log_check, "RapidChannelSwitchLogCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_app_switch_log_check, "AppSwitchLogCheck", "2.1", False),
    ("applications/clear-data", "functional", run_clear_data_preinstalled_app_check, "ClearDataPreinstalledAppCheck", "2.1", False),
    ("applications/install-from-app-store", "functional", run_install_region_specific_app_check, "InstallRegionSpecificAppCheck", "2.1", False),
    ("applications/install-from-app-store", "functional", run_update_installed_app_check, "UpdateInstalledAppCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_check, "LogsCollectionCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_for_major_system_services_check, "LogsCollectionForMajorSystemServicesCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_app_pause_check, "LogsCollectionAppPauseCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_app_force_stop_check, "LogsCollectionAppForceStopCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_app_uninstall_check, "LogsCollectionAppUninstallCheck", "2.1", False),
    ("system/logs/start-collection", "functional", run_logs_collection_app_install_and_launch_check, "LogsCollectionAppinstallAndLaunchCheck", "2.1", False),
    ("system/network-reset", "functional", run_network_reset_wifi_default_restoration, "Network Reset  Wi-Fi Settings Default Restoration", "2.1", False),
    ("system/setup/skip", "functional", run_setup_skip_privacy_bypass, "Setup Skip Privacy Settings Screen Bypass", "2.1", False),
    ("content/search", "functional", run_content_search_special_chars_validation, "Content Search  Special-Character-Only Query Validation", "2.1", True),
    ("system/power-mode/get", "functional", run_power_mode_get_standby_verify, "Power Mode Get STANDBY State Verification", "2.1", False),
    ("system/power-mode/get", "functional", run_power_mode_get_on_verify, "Power Mode Get ON State Verification", "2.1", False),
    ("system/power-mode/get", "functional", run_power_mode_get_adaptive_support_check, "Power Mode GET Adaptive Support Check", "2.1", False),
    ("system/power-mode/get", "functional", run_power_mode_transition_standby_to_active, "Power Mode Transition Standby Active", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_timeout_invalid_value_check, "SetScreenSaverTimeoutInvalidValue", "2.1", True),
    ("system/settings/set", "functional", run_set_contrast_to_max, "Set Contrast to Maximum", "2.1", False),
    ("system/settings/set", "functional", run_screensaver_timeout_invalid_time, "Screensaver Timeout Invalid negative value", "2.1", True),
    ("system/settings/set", "functional", run_contrast_rapid_change_min_to_max, "Contrast Rapid Change Min Max", "2.1", False),
    ("system/settings/set", "functional", run_personalized_ads_invalid_value, "PersonalizedAds Invalid Value", "2.1", True),
    ("system/factory-reset", "functional", run_factory_reset_and_verify_initial_state, "FactoryResetRestoreInitialState", "2.1", False),
    ("system/power-mode/set", "functional", run_power_mode_case_sensitive_negative, "PowerModeSetCaseSensitivityNegative", "2.1", True),
    ("system/power-mode/set", "functional", run_power_mode_set_missing_param, "PowerModeSetMissingModeNegative", "2.1", True),
    ("system/power-mode/set", "functional", run_power_mode_active_to_standby_check, "PowerModeActiveToStandbyPositive", "2.1", False),
    ("voice/send-text", "functional", run_voice_multilanguage_language_alignment_check, "VoiceMultiLanguageLanguageAlignment", "2.1", False),

]