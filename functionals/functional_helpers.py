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
                if logs is not None: logs.append(msg)
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Settings gate (system/settings/list) ----------
        for setting in sorted(set_req):
            # Use a dummy value; precheck only cares about the key's descriptor in the settings list
            validate_code, _ = checker.precheck(device_id, "system/settings/set", json.dumps({setting: True}))
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required setting not supported: {setting}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(msg)
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Keys gate (input/key/list) ----------
        for key in sorted(key_req):
            validate_code, _ = checker.precheck(device_id, "input/key-press", json.dumps({"keyCode": key}))
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required key not supported: {key}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(msg)
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        # ---------- Voices gate (voice/list) ----------
        for voice in sorted(voice_req):
            payload = json.dumps({"voiceSystem": {"name": voice, "enabled": True}})
            validate_code, _ = checker.precheck(device_id, "voice/set", payload)
            if validate_code != ValidateCode.SUPPORT:
                msg = f"[OPTIONAL_FAILED] Required voice assistant not supported: {voice}"
                LOGGER.warn(msg)
                if logs is not None: logs.append(msg)
                if result is not None: result.test_result = "OPTIONAL_FAILED"
                return False

        LOGGER.ok("Capability gate passed.")
        if logs is not None:
            logs.append("Capability gate passed.")
        return True

    except Exception as e:
        # Any unexpected failure in precheck is a non-enforceable optional fail
        msg = f"[OPTIONAL_FAILED] Capability precheck failed: {e}"
        LOGGER.warn(msg)
        if logs is not None:
            logs.append(msg)
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
        if logs is not None: logs.append(line)
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
    if logs is not None: logs.append(resp_line)

    # Normalize status code (never None)
    status_code = dab_status_from(resp_json, rc)
    if status_code is None:
        status_code = 500
        warn = f"[WARN] No status code found for '{topic}'; defaulting to 500."
        LOGGER.warn(warn)
        if logs is not None: logs.append(warn)

    status_line = f"[{topic}] Status: {status_code}"
    LOGGER.info(status_line)
    if logs is not None: logs.append(status_line)
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
    if logs is not None: logs.append(line0)

    for idx, value in enumerate(arr, start=1):
        line = f"*{idx}: {value}"
        LOGGER.info(line)
        if logs is not None: logs.append(line)

    # Prompt loop
    max_idx = len(arr)
    while True:
        prompt = f"Please input number (0–{max_idx}):"
        LOGGER.prompt(prompt)
        if logs is not None: logs.append(prompt)

        ch = readchar()
        echo = f"[{ch}]"
        LOGGER.result(echo)
        if logs is not None: logs.append(echo)

        if ch.isdigit():
            choice = int(ch)
            if 0 <= choice <= max_idx:
                return choice

        warn = f"[WARN] Invalid choice '{ch}'. Enter 0–{max_idx}."
        LOGGER.warn(warn)
        if logs is not None: logs.append(warn)
 

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

# === Generic result/log helpers ===
def outcome_of(result, default="UNKNOWN"):
    if result is None:
        return default
    value = getattr(result, "outcome", None)
    if value:
        return value
    return getattr(result, "test_result", default)

def set_outcome(result, outcome):
    if result is None:
        return
    # Always keep both fields aligned (prevents PASS log + FAILED summary)
    try:
        if hasattr(result, "outcome"):
            result.outcome = outcome
    except Exception:
        pass
    try:
        result.test_result = outcome
    except Exception:
        pass

def log_line(logs, tag, message=None, result=None):
    if message is None:
        if isinstance(tag, str) and tag.isupper() and len(tag) <= 10:
            message = ""
        else:
            message = tag
            tag = "INFO"

    stored = f"[{tag}] {message}".rstrip()

    # Console: avoid printing "[INFO] ..." or "[RESULT] ..." because LOGGER.result
    # already prefixes with "[RESULT] [INFO] ..."
    if tag in ("INFO", "RESULT"):
        console = (message or "").rstrip()
    else:
        console = stored

    LOGGER.result(console)
    append_log(logs, stored, result)
    return stored

def finish(result, logs, outcome, message):
    set_outcome(result, outcome)
    log_line(logs, "RESULT", f"{outcome} — {message}", result)
    return result

def get_numeric_setting_range(setting_name, result, logs):
    """
    Returns (min_value, max_value) for a numeric setting using EnforcementManager.

    On failure:
      - sets outcome to OPTIONAL_FAILED
      - logs a short reason
      - returns (None, None)
    """
    try:
        em = EnforcementManager()
        supported_raw = em.get_supported_settings() or {}
        supported_dict = supported_raw if isinstance(supported_raw, dict) else json.loads(supported_raw)

        settings_map = supported_dict.get("settings", supported_dict) if isinstance(supported_dict, dict) else {}
        if not isinstance(settings_map, dict):
            finish(result, logs, "OPTIONAL_FAILED", "Settings descriptor is not a map.")
            return None, None

        desc = settings_map.get(setting_name)
        if not isinstance(desc, dict):
            finish(result, logs, "OPTIONAL_FAILED", f"'{setting_name}' is missing in settings/list.")
            return None, None

        if "min" not in desc or "max" not in desc:
            finish(result, logs, "OPTIONAL_FAILED", f"'{setting_name}' does not expose min/max.")
            return None, None

        min_value = desc.get("min")
        max_value = desc.get("max")

        if not isinstance(min_value, (int, float)) or not isinstance(max_value, (int, float)):
            finish(result, logs, "OPTIONAL_FAILED", f"'{setting_name}' range is not numeric.")
            return None, None

        return min_value, max_value

    except Exception as e:
        finish(result, logs, "OPTIONAL_FAILED", f"Failed to read settings/list: {e}")
        return None, None

def is_close_numeric(actual, expected, tol=1):
    if not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        return False
    try:
        return abs(actual - expected) <= tol
    except Exception:
        return False
    
# SWAP result and logs in the definition below
def get_setting_value(tester, device_id, setting_id, logs=None, result=None):
    """
    Reads a single setting value using system/settings/get and returns the value.
    Returns None on failure (and sets result.test_result using finish()).
    """

    # Now we can pass them directly because execute_cmd_and_log expects (logs, result)
    rc, raw = execute_cmd_and_log(tester, device_id, "system/settings/get", "{}", logs, result)
    status = dab_status_from(raw, rc)

    if status != 200:
        finish(result, logs, "FAILED", f"system/settings/get returned {status}.")
        return None

    try:
        body = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception as e:
        finish(result, logs, "FAILED", f"system/settings/get invalid JSON: {e}")
        return None

    # Shape A: { "brightness": 20, ... }
    if isinstance(body, dict) and setting_id in body:
        return body.get(setting_id)

    # Shape B: { "settings": [ {"id":"brightness","value":20}, ... ] }
    settings_list = body.get("settings") if isinstance(body, dict) else None
    if isinstance(settings_list, list):
        for item in settings_list:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id") or item.get("settingId") or item.get("name")
            if item_id == setting_id:
                if "value" in item:
                    return item.get("value")
                if "currentValue" in item:
                    return item.get("currentValue")

    finish(result, logs, "FAILED", f"Setting '{setting_id}' not found in system/settings/get response.")
    return None

def set_setting_value(tester, device_id, setting_id, value, logs=None, result=None):
    """
    Sets a single system setting value.
    Returns (status_code, response_body).
    """
    # Construct payload: {"brightness": 50}
    payload = json.dumps({setting_id: value})
    
    # Execute command
    # NOTE: Ensure arguments match your definition of execute_cmd_and_log
    rc, raw_resp = execute_cmd_and_log(
        tester, device_id, "system/settings/set", payload, logs=logs, result=result
    )
    
    status = dab_status_from(raw_resp, rc)
    return status, raw_resp

def append_log(logs, message, result=None):
    """
    Safe log append:
      - if logs is a list -> append there
      - else if result has .logs list -> append there
      - else do nothing
    """
    if message is None:
        return
    try:
        if isinstance(logs, list):
            logs.append(message)
            return
    except Exception:
        pass
    try:
        if result is not None:
            arr = getattr(result, "logs", None)
            if isinstance(arr, list):
                arr.append(message)
                return
    except Exception:
        pass

def approx_equal(actual, expected, tolerance=1):
    """
    Returns True if the actual value is within the tolerance of the expected value.
    Handles type conversion safely.
    """
    try:
        return abs(float(actual) - float(expected)) <= tolerance
    except (ValueError, TypeError):
        return False

def clamp_check_min(value, min_limit, tolerance=1):
    """
    Returns True if the value has not dropped significantly below the minimum limit.
    Used to verify that setting a value < min results in a value >= min (clamped).
    """
    try:
        return float(value) >= (float(min_limit) - tolerance)
    except (ValueError, TypeError):
        return False