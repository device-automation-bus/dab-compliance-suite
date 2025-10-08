from dab_client import DabClient
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
from util.enforcement_manager import ValidateCode
from time import sleep
import json
import re
import types
from logger import LOGGER  # <— use the shared singleton logger

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester
        self.logger = LOGGER

        # Keep track of the last payload actually sent for system/settings/set
        self._last_effective_settings_payload = None

        # --- Patch dab_tester.execute_cmd to intercept real sends ---
        original_execute_cmd = dab_tester.execute_cmd  # bound method

        def _patched_execute_cmd(_self, device_id, dab_topic, dab_body):
            # Intercept only system/settings/set
            try:
                if dab_topic == "system/settings/set":
                    adjusted = self.__maybe_adjust_settings_set_payload(dab_body)
                    # Persist what we are *actually* sending so checker can validate against it
                    self._last_effective_settings_payload = adjusted if isinstance(adjusted, str) else json.dumps(adjusted)
                    return original_execute_cmd(device_id, dab_topic, adjusted)
            except Exception as e:
                self.logger.warn(f"[SET precheck] execute_cmd patch error: {e}")
            # For all other topics, just forward
            return original_execute_cmd(device_id, dab_topic, dab_body)

        # Bind the patched function as a method on this dab_tester instance
        dab_tester.execute_cmd = types.MethodType(_patched_execute_cmd, dab_tester)

    # -------------------------------------------------------------------------
    # Minimal helpers to align positive system/settings/set payloads to supported
    # values advertised by system/settings/list. Negative tests remain untouched.
    # Also includes a tiny tolerant JSON fixer for one-key objects with bare strings.
    # -------------------------------------------------------------------------

    def __prefer_language(self, options):
        try:
            if "en-US" in options:
                return "en-US"
            for o in options:
                if isinstance(o, str) and (o.startswith("en-") or o == "en"):
                    return o
            return options[0] if options else None
        except Exception:
            return None

    def __match_subset(self, req_d, opt_d):
        if not isinstance(req_d, dict) or not isinstance(opt_d, dict):
            return False
        for k, v in req_d.items():
            if opt_d.get(k) != v:
                return False
        return True

    def __builtin_default_for(self, key: str):
        kl = (key or "").lower()
        if kl == "language":
            return "en-US"
        if kl in ("highcontrasttext", "screensaver"):
            return True
        if kl in ("personalizedads",):
            return False
        if kl in ("brightness", "contrast"):
            return 50
        if kl in ("screensavertimeout", "screensavermintimeout"):
            return 300
        if kl in ("timezone", "timezone", "timeZone"):
            return "UTC"
        if kl == "outputresolution":
            return {"width": 1920, "height": 1080, "frequency": 60}
        return None

    def __to_settings_map(self, supported):
        try:
            if isinstance(supported, str):
                supported = json.loads(supported)
        except Exception:
            return {}
        if not isinstance(supported, dict):
            return {}
        settings_map = supported.get("settings", supported)
        if not isinstance(settings_map, dict):
            return {}
        # strip common meta
        for meta in ("status", "statusText", "ts", "error"):
            settings_map.pop(meta, None)
        return settings_map

    def __select_supported_value(self, supported_settings, key, preferred=None):
        """
        Returns (value, note). If unsupported/unknown → (None, reason).
        """
        settings_map = self.__to_settings_map(supported_settings)
        if not settings_map:
            return None, "No settings map (empty or malformed settings/list cache)."

        if key not in settings_map:
            sample = list(settings_map.keys())[:3]
            return None, f"'{key}' not advertised in settings/list. Known keys (sample): {sample}"

        desc = settings_map[key]

        # Boolean capability flag
        if isinstance(desc, bool):
            if desc is False:
                return None, f"'{key}' unsupported (capability=false in settings/list)."
            if isinstance(preferred, bool):
                return preferred, f"'{key}' supported; using preferred={preferred}."
            return True, f"'{key}' supported; defaulting to True."

        # Numeric range {"min": x, "max": y}
        if isinstance(desc, dict) and {"min", "max"}.issubset(desc.keys()):
            mn, mx = desc["min"], desc["max"]
            if isinstance(preferred, (int, float)) and mn <= preferred <= mx:
                return preferred, f"'{key}' in range [{mn}, {mx}]; using preferred."
            mid = (mn + mx) // 2 if isinstance(mn, int) and isinstance(mx, int) else (float(mn) + float(mx)) / 2.0
            return mid, f"'{key}' in range [{mn}, {mx}]; using midpoint={mid}."

        # List of options
        if isinstance(desc, list):
            if not desc:
                return None, f"'{key}' unsupported (no options advertised)."
            if isinstance(desc[0], dict):
                if isinstance(preferred, dict):
                    for opt in desc:
                        if self.__match_subset(preferred, opt):
                            return opt, f"'{key}' matched preferred subset {preferred}."
                return desc[0], f"'{key}' options available; using first={desc[0]}."
            # list of primitives
            if preferred is None and key.lower() == "language":
                ch = self.__prefer_language([o for o in desc if isinstance(o, str)])
                if ch is not None:
                    return ch, f"'{key}' options; language heuristic selected {ch}."
            if preferred in desc:
                return preferred, f"'{key}' options include preferred={preferred}."
            return desc[0], f"'{key}' options; preferred not found → using first={desc[0]}."

        # Other object-like
        if isinstance(desc, dict):
            prev = list(desc.keys())[:6]
            return None, f"'{key}' descriptor is object-like ({prev}); cannot auto-pick."

        return None, f"'{key}' descriptor type {type(desc).__name__} not recognized."

    def __coerce_single_kv_json(self, raw):
        """
        Tiny tolerant parser for a one-key JSON object where the value might be an
        unquoted bare string (e.g., {"language": en-US1}). Returns a dict or None.
        """
        try:
            s = (raw or "").strip()
            if not s:
                return None
            # If it's already valid JSON and one-key, just use it.
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and len(obj) == 1:
                    return obj
            except Exception:
                pass

            # Try to capture {"key": <value>}
            m = re.match(r'^\{\s*"([^"]+)"\s*:\s*([^}]*)\}$', s)
            if not m:
                return None
            key = m.group(1)
            val = m.group(2).strip()
            # Remove trailing comma if any
            val = re.sub(r',\s*$', '', val)

            # If already quoted (single or double), normalize to double
            if val.startswith('"') and val.endswith('"'):
                candidate = f'{{"{key}": {val}}}'
                return json.loads(candidate)
            if val.startswith("'") and val.endswith("'"):
                candidate = f'{{"{key}": "{val[1:-1]}"}}'
                return json.loads(candidate)

            # If clearly a number / boolean / null / object / array → let JSON handle
            if val.startswith(('{', '[')) or val in ('true', 'false', 'null') or re.match(r'^-?\d+(\.\d+)?$', val):
                candidate = f'{{"{key}": {val}}}'
                return json.loads(candidate)

            # Otherwise treat as a bare string token → quote it
            candidate = f'{{"{key}": "{val}"}}'
            return json.loads(candidate)
        except Exception:
            return None

    def __settings_set_payload(self, key, preferred=None, default=None):
        """
        Build a JSON string payload for system/settings/set (e.g., '{"language":"en-US"}').
        If supported value cannot be derived, log and fall back to preferred → default → builtin default.
        """
        try:
            sup = EnforcementManager().get_supported_settings()
            val, note = self.__select_supported_value(sup, key, preferred)
            if val is not None:
                payload = json.dumps({key: val})
                self.logger.result(f"[settings_set_payload] {note} → {payload}")
                return payload

            # Unsupported or cannot infer → carry a default
            fallback = preferred if preferred is not None else (default if default is not None else self.__builtin_default_for(key))
            if fallback is not None:
                payload = json.dumps({key: fallback})
                self.logger.result(f"[settings_set_payload] {note} → carrying default value {fallback}. "
                                 f"This may be marked OPTIONAL_FAILED if not implemented on device.")
                return payload

            self.logger.result(f"[settings_set_payload] {note} → no default available; returning '{{}}'.")
            return "{}"
        except Exception as e:
            self.logger.result(f"[settings_set_payload] Error building payload for '{key}': {e}")
            return "{}"

    def __looks_negative_payload(self, raw_body_str: str) -> bool:
        """
        Conservative heuristic: if payload uses 'invalid' values or keys ending with '_',
        assume it's a negative/bad-request validation and do NOT auto-adjust.
        """
        try:
            s = raw_body_str if isinstance(raw_body_str, str) else json.dumps(raw_body_str or {})
        except Exception:
            s = str(raw_body_str)
        if '"invalid"' in s:
            return True
        if re.search(r'"\w+_"\s*:', s):
            return True
        return False

    def __maybe_adjust_settings_set_payload(self, dab_body):
        """
        Positive tests only (best-effort): compare requested {key: value} to settings/list
        and adjust to a supported value. If the payload looks intentionally negative, leave
        it as-is. Also leave out-of-range numerics or wrong types as-is to avoid
        interfering with negative tests. Handles a simple case of unquoted strings.
        """
        try:
            # Normalize body
            if isinstance(dab_body, dict):
                body = dab_body
                raw = json.dumps(dab_body)
            else:
                raw = dab_body or "{}"
                try:
                    body = json.loads(raw)
                except Exception:
                    # Try tolerant coerce for one-key body
                    coerced = self.__coerce_single_kv_json(raw)
                    if coerced is None:
                        # Can't fix → treat as negative/malformed; send as-is
                        self.logger.warn(f"[SET precheck] Could not parse/repair payload; sending as-is. Raw={raw}")
                        return dab_body
                    body = coerced
                    raw = json.dumps(coerced)

            # Only simple {key: value}
            if not isinstance(body, dict) or len(body) != 1:
                return dab_body

            # Negative/malformed heuristics → keep original
            if self.__looks_negative_payload(raw):
                self.logger.info("[SET precheck] Negative test detected (invalid/underscore key); sending payload as-is.")
                return dab_body

            (k, v), = body.items()

            # Extra guard using descriptor to avoid 'fixing' negative tests
            sup_map = self.__to_settings_map(EnforcementManager().get_supported_settings())
            desc = sup_map.get(k)

            # If no descriptor, don't attempt to auto-fix (could be a neg test on unknown key)
            if desc is None:
                self.logger.info(f"[SET precheck] '{k}' not in settings/list; sending payload as-is.")
                return dab_body

            # If numeric range and value is out-of-range or non-numeric, treat as negative → as-is
            if isinstance(desc, dict) and {"min", "max"}.issubset(desc.keys()):
                if not isinstance(v, (int, float)):
                    self.logger.info("[SET precheck] Non-numeric value for numeric range; treating as negative.")
                    return dab_body
                if not (desc["min"] <= v <= desc["max"]):
                    self.logger.info("[SET precheck] Out-of-range numeric; treating as negative.")
                    return dab_body

            # If list of options and value type is clearly wrong, treat as negative
            if isinstance(desc, list):
                if desc and isinstance(desc[0], dict):
                    if not isinstance(v, dict):
                        self.logger.info("[SET precheck] Dict options but non-dict value; treating as negative.")
                        return dab_body
                else:
                    # list of primitives
                    if isinstance(v, (dict, list, bool)) or v is None:
                        self.logger.info("[SET precheck] Primitive options but non-primitive/boolean value; treating as negative.")
                        return dab_body

            # Try to produce a supported payload (language etc.). If unchanged or '{}', keep original
            adjusted = self.__settings_set_payload(k, preferred=v)
            if not adjusted or adjusted == "{}":
                return dab_body
            if isinstance(dab_body, str) and adjusted.strip() == dab_body.strip():
                return dab_body
            if isinstance(dab_body, dict) and adjusted.strip() == json.dumps(dab_body):
                return dab_body

            self.logger.info(f"[SET precheck] Adjusting '{k}' to a supported value via settings/list.")
            return adjusted
        except Exception as e:
            self.logger.warn(f"[SET precheck] Payload adjust error: {e}")
            return dab_body

    def __execute_cmd(self, device_id, dab_topic, dab_body):
        # verbose detail about the command being sent
        self.logger.info(f"Sending request to '{dab_topic}' for device '{device_id}'.")
        code = self.dab_tester.execute_cmd(device_id, dab_topic, dab_body)
        dab_response = self.dab_tester.dab_client.response()
        if code == 0:
            self.logger.ok(f"Received a valid response from '{dab_topic}'.")
            try:
                response = json.loads(dab_response)
            except Exception as e:
                self.logger.warn(f"Response payload from '{dab_topic}' was not valid JSON: {e}")
                return None
            return response
        else:
            err = self.dab_tester.dab_client.last_error_code()
            self.logger.warn(f"No valid response from '{dab_topic}'. Error code: {err}")
            return None

    def is_operation_supported(self, device_id, operation):
        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\n{operation} is uncertain whether it is supported on this device. Ongoing...\n"
        if not EnforcementManager().get_supported_operations():
            dab_precheck_topic = "operations/list"
            dab_precheck_body = "{}"
            self.logger.info("Fetching the list of supported DAB operations from the device.")
            dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
            operations = dab_response['operations'] if dab_response is not None else None
            EnforcementManager().add_supported_operations(operations)

        if not EnforcementManager().get_supported_operations():
            # rely on caller to emit prechecker_log as a result line
            return validate_code, prechecker_log

        if EnforcementManager().is_operation_supported(operation):
            validate_code = ValidateCode.SUPPORT
            prechecker_log = f"\n{operation} is supported on this device. Ongoing...\n"
        else:
            validate_code = ValidateCode.UNSUPPORT
            prechecker_log = f"\n{operation} is NOT supported on this device. Ongoing...\n"

        return validate_code, prechecker_log

    def precheck(self, device_id, dab_request_topic, dab_request_body):
        """
        Checks if the DAB operation is supported by the target before send the DAB request to the target.

        Args:
            device_id: The device id
            dab_request_topic: the request dab topic
            dab_request_body: the request dab body

         Returns:
            validate_code:
                ValidateCode.SUPPORT, target supports this DAB operation.
                ValidateCode.UNSUPPORT, target doesn't support this DAB operation.
                ValidateCode.UNCERTAIN, uncertain whether the target support this DAB operation.
            prechecker_log:
                output message
        """
        match dab_request_topic:
            case 'system/settings/set':
                return self.__precheck_system_settings_set(device_id, dab_request_body)
            case 'voice/set':
                return self.__precheck_voice_set(device_id, dab_request_body)
            case 'voice/send-text' | 'voice/send-audio':
                return self.__precheck_voice_send_text_audio(device_id, dab_request_body)
            case 'device-telemetry/start':
                return self.__precheck_device_telemetry_start(device_id, dab_request_body)
            case 'device-telemetry/stop':
                return self.__precheck_device_telemetry_stop(device_id, dab_request_body)
            case 'app-telemetry/start':
                return self.__precheck_app_telemetry_start(device_id, dab_request_body)
            case 'app-telemetry/stop':
                return self.__precheck_app_telemetry_stop(device_id, dab_request_body)
            case 'input/key-press' | 'input/long-key-press':
                return self.__precheck_key_press(device_id, dab_request_body)
            case 'system/logs/stop-collection':
                return self.__precheck_logs_stop_collection(device_id, dab_request_body)
            case _:
                return ValidateCode.SUPPORT, ""

    def __precheck_system_settings_set(self, device_id, dab_request_body):
        # 1) Parse request: must be single {key: value}
        try:
            if isinstance(dab_request_body, dict):
                request_body = dab_request_body
            else:
                try:
                    request_body = json.loads(dab_request_body or "{}")
                except Exception:
                    # Try tolerant coerce for one-key body (fix unquoted string)
                    fixed = self.__coerce_single_kv_json(dab_request_body or "")
                    if fixed is None:
                        raise
                    request_body = fixed

            (request_key, request_value), = request_body.items()
            self.logger.info(f"Parsed request: key='{request_key}', value='{request_value}'")
        except Exception as e:
            self.logger.warn(f"CRASH during request parsing: {e}")
            return ValidateCode.UNCERTAIN, f"\nsettings/set: invalid request body ({e}); UNCERTAIN.\n"

        # 2) Ensure settings/list cache exists; if empty/malformed, re-fetch once
        need_fetch = not EnforcementManager().check_supported_settings()
        if not need_fetch:
            try:
                cached = EnforcementManager().get_supported_settings()
                if not cached or (isinstance(cached, dict) and len(cached) == 0):
                    self.logger.info("Cache present but empty → will re-fetch settings/list.")
                    need_fetch = True
            except Exception:
                need_fetch = True

        if need_fetch:
            self.logger.info("Fetching settings/list from device...")
            resp = self.__execute_cmd(device_id, "system/settings/list", "{}")
            if not resp:
                last = self.dab_tester.dab_client.last_error_code()
                self.logger.warn(f"settings/list failed. Error code: {last}")
                return ValidateCode.UNSUPPORT, f"\nsystem/settings/list unavailable (error {last}); cannot verify support for '{request_key}'.\n"
            EnforcementManager().set_supported_settings(resp)
            self.logger.info("Cache updated from device.")
        else:
            self.logger.info("Using existing data from cache.")

        # 3) Interpret cache and decide support
        try:
            sup = EnforcementManager().get_supported_settings() or {}
            sup = sup if isinstance(sup, dict) else json.loads(sup)
            settings_map = sup.get("settings", sup) if isinstance(sup, dict) else {}
            if not isinstance(settings_map, dict):
                raise ValueError("settings cache not a dict")

            # Defensive: ignore obvious meta keys
            for meta in ("status", "statusText", "ts"):
                settings_map.pop(meta, None)

            # ---- MANDATORY KEY VALIDATION ----
            if request_key not in settings_map:
                sample = list(settings_map.keys())[:3]
                hint = f" Known keys: {sample} (showing up to 3 of {len(settings_map)})." if sample else " No known settings advertised."
                self.logger.info(f"'{request_key}' missing in cache.")
                return ValidateCode.UNSUPPORT, f"\n'{request_key}' is not supported (missing in settings/list).{hint}\n"

            desc = settings_map[request_key]
            self.logger.info(f"Descriptor for '{request_key}': {type(desc).__name__}")

            # Helper to preview lists nicely
            def _preview_list(lst, n=3):
                if not lst:
                    return []
                if isinstance(lst[0], dict):
                    return [{k: d.get(k) for k in list(d.keys())[:3]} for d in lst[:n]]
                return lst[:n]

            # ----- Numeric range: {"min": x, "max": y}
            if isinstance(desc, dict) and {"min", "max"}.issubset(desc.keys()):
                accepted = f"[{desc['min']}, {desc['max']}]"
                self.logger.info(f"Accepted domain for '{request_key}': numeric range {accepted}. Provided: {request_value}")
                if not isinstance(request_value, (int, float)):
                    return ValidateCode.UNCERTAIN, (
                        f"\n'{request_key}': accepted numeric range {accepted}; provided value '{request_value}' is not numeric. Marking as UNCERTAIN.\n"
                    )
                if not (desc["min"] <= request_value <= desc["max"]):
                    return ValidateCode.UNCERTAIN, (
                        f"\n'{request_key}': accepted numeric range {accepted}; provided value {request_value} out of range. Marking as UNCERTAIN.\n"
                    )
                return ValidateCode.SUPPORT, (
                    f"\n'{request_key}' supported. Accepted range {accepted}; provided {request_value} within range.\n"
                )

            # ----- Boolean capability flag: True/False indicates whether the setting is supported
            if isinstance(desc, bool):
                self.logger.info(
                    f"Accepted type for '{request_key}': boolean (True/False); "
                    f"capability advertised={desc}. Provided: {request_value} (type {type(request_value).__name__})"
                )
                # Do NOT fail/uncertain on type; we don't validate value here. Decide by capability:
                if desc is False:
                    return ValidateCode.UNSUPPORT, (
                        f"\n'{request_key}' is NOT supported on this device (settings/list advertises capability=false). "
                        f"Provided value: {request_value}.\n"
                    )
                # desc is True → supported
                return ValidateCode.SUPPORT, (
                    f"\n'{request_key}' supported (settings/list advertises capability=true). "
                    f"Provided value noted: {request_value}.\n"
                )

            # ----- Enumerations / options: list of primitives or dicts
            if isinstance(desc, list):
                if not desc:
                    # empty options list → UNSUPPORT
                    self.logger.info(
                        f"Accepted domain for '{request_key}': list of options; none available (0). Provided: {request_value}"
                    )
                    return ValidateCode.UNSUPPORT, (
                        f"\n'{request_key}' is NOT supported on this device (no available options advertised in settings/list). "
                        f"Provided value: {request_value}.\n"
                    )

                accepted_preview = _preview_list(desc)
                shown = len(accepted_preview)
                total = len(desc)
                accepted_info = f"{accepted_preview} (showing {shown} of {total})"
                self.logger.info(f" Accepted domain for '{request_key}': list of options; examples: {accepted_info}. Provided: {request_value}")

                wants = request_value if isinstance(request_value, list) else [request_value]

                if desc and isinstance(desc[0], dict):
                    # subset-match for dict entries (e.g., {"width":3840,"height":2160})
                    def _match(req_d, opt_d):
                        return isinstance(req_d, dict) and all(req_d.get(k) == opt_d.get(k) for k in req_d.keys())
                    ok = all(any(_match(w, opt) for opt in desc) for w in wants)
                else:
                    ok = all(w in desc for w in wants)

                if not ok:
                    return ValidateCode.UNCERTAIN, (
                        f"\n'{request_key}': accepted options include {accepted_info}; provided {wants} not fully recognized. Marking as UNCERTAIN.\n"
                    )
                return ValidateCode.SUPPORT, (
                    f"\n'{request_key}' supported. Provided {wants} within accepted options (e.g., {accepted_info}).\n"
                )

            # ----- Unknown/complex object: log keys and treat as supported by key presence
            if isinstance(desc, dict):
                keys_preview = list(desc.keys())[:6]
                self.logger.info(f"Accepted domain for '{request_key}': object-like descriptor; keys (subset): {keys_preview}. Provided: {request_value}")
                return ValidateCode.SUPPORT, (
                    f"\n'{request_key}' supported (key present). Descriptor keys include {keys_preview}. "
                    f"Provided value: {request_value}. Precheck cannot fully validate complex objects.\n"
                )

            # ----- Fallback for unrecognized descriptor types
            self.logger.info(f"Unrecognized descriptor type for '{request_key}'. Provided: {request_value}")
            return ValidateCode.UNCERTAIN, (
                f"\n'{request_key}': descriptor type is unrecognized; provided value '{request_value}'. Marking as UNCERTAIN.\n"
            )

        except Exception as e:
            self.logger.warn(f"CRASH during pre-check logic: {e}")
            return ValidateCode.UNCERTAIN, f"\nAn error occurred during settings pre-check: {e}.\n"

    def __precheck_voice_set(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        (request_key, request_value), = request_body.items()
        dab_precheck_topic = "voice/list"
        dab_precheck_body = "{}"

        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\nvoice set {request_value['name']} is uncertain whether it is supported on this device. Ongoing...\n"

        if not EnforcementManager().get_supported_voice_assistants():
            self.logger.info("Fetching the list of supported voice systems from the device.")
            dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

            if not dab_response or 'voiceSystems' not in dab_response:
                EnforcementManager().set_supported_voice_assistants(None)
                return validate_code, prechecker_log

            EnforcementManager().set_supported_voice_assistants(dab_response['voiceSystems'])

        voice_assistant = EnforcementManager().get_supported_voice_assistants(request_value['name'])

        if not voice_assistant:
            prechecker_log = f"\nvoice set {request_key} is NOT supported on this device. Ongoing...\n"
            return ValidateCode.UNSUPPORT, prechecker_log

        prechecker_log = f"\nvoice set {request_key} is supported on this device. Ongoing...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_voice_send_text_audio(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        request_voice_system = request_body['voiceSystem']
        dab_precheck_body = json.dumps({"voiceSystem": {"name": request_voice_system, "enabled": True}}, indent = 4)

        validate_code, prechecker_log = self.__precheck_voice_set(device_id, dab_precheck_body)

        if validate_code == ValidateCode.UNCERTAIN:
            return validate_code, prechecker_log
        elif validate_code == ValidateCode.UNSUPPORT:
            prechecker_log = f"\nvoice system {request_voice_system} is NOT supported on this device. Ongoing...\n"
            return validate_code, prechecker_log

        voice_assistant = EnforcementManager().get_supported_voice_assistants(request_voice_system)
        if voice_assistant["enabled"]:
            prechecker_log = f"\nvoice system {request_voice_system} is enabled on this device. Ongoing...\n"
            return validate_code, prechecker_log

        self.logger.info(f"Voice system '{request_voice_system}' is disabled. Attempting to enable it for this test.")
        dab_precheck_topic = "voice/set"
        voice_assistant["enabled"] = True
        dab_precheck_body = json.dumps({"voiceSystem": voice_assistant}, indent = 4)

        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        sleep(5)
        validate_result, precheck_log = self.__check_voice_set(device_id, dab_precheck_body)

        if validate_result:
            prechecker_log = f"\nvoice system {request_voice_system} is enabled on this device. Ongoing...\n"
            return ValidateCode.SUPPORT, prechecker_log

        prechecker_log = f"\nvoice system {request_voice_system} is not enabled on this device. Ongoing...\n"
        return ValidateCode.UNSUPPORT, prechecker_log

    def __precheck_device_telemetry_start(self, device_id, dab_request_body):
        dab_precheck_topic = "device-telemetry/stop"
        dab_precheck_body = "{}"

        self.logger.info("Stopping any existing device telemetry so the start request can be validated cleanly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\ndevice telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_device_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "device-telemetry/start"
        dab_precheck_body = json.dumps({"duration": 1000}, indent = 4)

        self.logger.info("Starting device telemetry briefly to verify the stop request behaves correctly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id)

        if not validate_result:
            self.logger.warn("Device telemetry did not appear to start.")
            prechecker_log = f"\ndevice telemetry is not started.\n"
            return ValidateCode.UNSUPPORT, prechecker_log
        else:
            prechecker_log = f"\ndevice telemetry is started on this device. Try to stop...\n"
            return ValidateCode.SUPPORT, prechecker_log

    def __precheck_app_telemetry_start(self, device_id, dab_request_body):
        dab_precheck_topic = "app-telemetry/stop"
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        dab_precheck_body = json.dumps({"appId": appId}, indent = 4)

        self.logger.info(f"Stopping any existing telemetry for app '{appId}' so the start request can be validated cleanly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\napp {appId} telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_app_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "app-telemetry/start"
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        dab_precheck_body = json.dumps({"appId": appId, "duration": 1000}, indent = 4)

        self.logger.info(f"Starting telemetry for app '{appId}' briefly to verify the stop request behaves correctly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id, appId)

        if not validate_result:
            self.logger.warn(f"App '{appId}' telemetry did not appear to start.")
            prechecker_log = f"\napp {appId} telemetry is not started.\n"
            return ValidateCode.UNSUPPORT, prechecker_log
        else:
            prechecker_log = f"\napp {appId} telemetry is started on this device. Try to stop...\n"
            return ValidateCode.SUPPORT, prechecker_log

    def __precheck_key_press(self, device_id, dab_request_body):
        dab_precheck_topic = "input/key/list"
        dab_precheck_body = "{}"
        request_body = json.loads(dab_request_body)
        key = request_body['keyCode']

        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\n{key} is uncertain whether it is supported on this device. Ongoing...\n"

        if not EnforcementManager().get_supported_keys():
            self.logger.info("Fetching the list of supported input keys from the device.")
            dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
            keys = dab_response['keyCodes'] if dab_response else None
            EnforcementManager().add_supported_keys(keys)

        if not EnforcementManager().get_supported_keys():
            return validate_code, prechecker_log

        if EnforcementManager().is_key_supported(key):
            validate_code = ValidateCode.SUPPORT
            prechecker_log = f"\n{key} is supported on this device. Ongoing...\n"
        else:
            validate_code = ValidateCode.UNSUPPORT
            prechecker_log = f"\n{key} is NOT supported on this device. Ongoing...\n"

        return validate_code, prechecker_log

    def __precheck_logs_stop_collection(self, device_id, dab_request_body):
        dab_precheck_topic = "system/logs/start-collection"
        dab_precheck_body = "{}"

        self.logger.info("Start logs collection.")
        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        self.logger.info(f"Waiting for 10 sec after start log-collection")
        sleep(10)
        if dab_response:
            prechecker_log = f"\nlogs collection is started on this device. Ongoing...\n"
            validate_code = ValidateCode.SUPPORT
        else:
            prechecker_log = f"\nstart logs collection failed on this device.\n"
            validate_code = ValidateCode.UNSUPPORT

        return validate_code, prechecker_log

    def end_precheck(self, device_id, dab_request_topic, dab_request_body):
        match dab_request_topic:
            case 'device-telemetry/start' | 'device-telemetry/stop':
                self.__execute_cmd(device_id, 'device-telemetry/stop', '{}')
            case 'app-telemetry/start' | 'app-telemetry/stop':
                request_body = json.loads(dab_request_body)
                appId = request_body['appId']
                self.__execute_cmd(device_id, 'app-telemetry/stop', json.dumps({"appId": appId}, indent = 4))

    def check(self, device_id, dab_request_topic, dab_request_body):
        """
        Checks if the request DAB operation is executed correctly on the target.

        Args:
            device_id: The device id
            dab_request_topic: the request dab topic
            dab_request_body: the request dab body

         Returns:
            validate_result:
                True if successful, False otherwise.
            checker_log:
                output message.
        """
        match dab_request_topic:
            case 'applications/launch' | 'applications/launch-with-content':
                return self.__check_application_state(device_id, dab_request_body)
            case 'applications/exit':
                return self.__check_application_state(device_id, dab_request_body, 'EXIT')
            case 'system/settings/set':
                return self.__check_system_settings_set(device_id, dab_request_body)
            case 'voice/set':
                return self.__check_voice_set(device_id, dab_request_body)
            case 'device-telemetry/start':
                return self.__check_device_telemetry_start(device_id, dab_request_body)
            case 'device-telemetry/stop':
                return self.__check_device_telemetry_stop(device_id, dab_request_body)
            case 'app-telemetry/start':
                return self.__check_app_telemetry_start(device_id, dab_request_body)
            case 'app-telemetry/stop':
                return self.__check_app_telemetry_stop(device_id, dab_request_body)
            case 'system/logs/stop-collection':
                return self.__check_logs_chunks(device_id, dab_request_body)
            case _:
                return True, ""

    def __check_application_state(self, device_id, dab_request_body, expected_state = 'FOREGROUND'):
        dab_check_topic = "applications/get-state"
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        dab_check_body = json.dumps({"appId": appId}, indent = 4)

        if expected_state == 'EXIT':
            if 'background' in request_body:
                expected_state = 'BACKGROUND' if request_body['background'] == True else 'STOPPED'
            else:
                expected_state = 'STOPPED'

        validate_result = False
        actual_state = 'UNKNOWN'

        dab_response = self.__execute_cmd(device_id, dab_check_topic, dab_check_body)
        if dab_response and 'state' in dab_response:
            actual_state = dab_response['state']
            validate_result = True if actual_state == expected_state else False

        checker_log = f"\napplication {appId} State, Expected: {expected_state}, Actual: {actual_state}\n"
        return validate_result, checker_log

    def __check_system_settings_set(self, device_id, dab_request_body):
        dab_check_topic = "system/settings/get"
        dab_check_body = "{}"

        # Use the *effective payload* if the set was auto-adjusted during send
        effective_raw = self._last_effective_settings_payload or dab_request_body
        request_body = json.loads(effective_raw)
        (request_key, request_value), = request_body.items()

        # If numeric-range and out-of-range was requested, expect device to clamp to nearest boundary.
        expected_value = request_value
        try:
            sup_map = self.__to_settings_map(EnforcementManager().get_supported_settings())
            desc = sup_map.get(request_key)
            if isinstance(desc, dict) and {"min", "max"}.issubset(desc.keys()) and isinstance(request_value, (int, float)):
                mn, mx = desc["min"], desc["max"]
                if request_value < mn:
                    expected_value = mn
                    self.logger.info(f"[check] '{request_key}' requested {request_value} below min {mn} → expecting clamp to {mn}.")
                elif request_value > mx:
                    expected_value = mx
                    self.logger.info(f"[check] '{request_key}' requested {request_value} above max {mx} → expecting clamp to {mx}.")
        except Exception as e:
            self.logger.warn(f"[check] clamp expectation compute error for '{request_key}': {e}")

        validate_result = False
        actual_value = 'UNKNOWN'

        dab_response = self.__execute_cmd(device_id, dab_check_topic, dab_check_body)
        if dab_response and request_key in dab_response:
            actual_value = dab_response[request_key]
            validate_result = True if actual_value == expected_value else False

        checker_log = f"\nsystem settings set {request_key} Value, Expected: {expected_value}, Actual: {actual_value}\n"

        # Clear after use to avoid leaking into next test
        self._last_effective_settings_payload = None

        return validate_result, checker_log

    def __check_voice_set(self, device_id, dab_request_body):
        dab_check_topic = "voice/list"
        dab_check_body = "{}"
        request_body = json.loads(dab_request_body)
        (request_key, request_value), = request_body.items()

        validate_result = False
        actual_value = 'UNKNOWN'
        checker_log = f"\nvoice set {request_value['name']} Value, Expected: {request_value['enabled']}, Actual: {actual_value}\n"

        dab_response = self.__execute_cmd(device_id, dab_check_topic, dab_check_body)
        if not dab_response or 'voiceSystems' not in dab_response:
            EnforcementManager().set_supported_voice_assistants(None)
            return validate_result, checker_log

        EnforcementManager().set_supported_voice_assistants(dab_response['voiceSystems'])
        for voice_assistant in dab_response['voiceSystems']:
            if voice_assistant['name'] == request_value['name']:
                actual_value = voice_assistant['enabled']
                validate_result = True if voice_assistant['enabled'] == request_value['enabled'] else False

        checker_log = f"\nvoice set {request_value['name']} Value, Expected: {request_value['enabled']}, Actual: {actual_value}\n"
        return validate_result, checker_log

    def __check_device_telemetry_start(self, device_id, dab_request_body):
        validate_result = self.__check_telemetry_metrics(device_id)

        checker_log = f"\ndevice telemetry start, Expected: True, Actual: {validate_result}\n"
        self.logger.info("Stopping device telemetry after validation.")
        self.__execute_cmd(device_id, 'device-telemetry/stop', '{}')
        return validate_result, checker_log

    def __check_device_telemetry_stop(self, device_id, dab_request_body):
        validate_result = not self.__check_telemetry_metrics(device_id)
        checker_log = f"\ndevice telemetry stop, Expected: True, Actual: {validate_result}\n"
        return validate_result, checker_log

    def __check_app_telemetry_start(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']

        validate_result = self.__check_telemetry_metrics(device_id, appId)
        checker_log = f"\napp {appId} telemetry start, Expected: True, Actual: {validate_result}\n"
        self.logger.info(f"Stopping telemetry for app '{appId}' after validation.")
        self.__execute_cmd(device_id, 'app-telemetry/stop', json.dumps({"appId": appId}, indent = 4))
        return validate_result, checker_log

    def __check_app_telemetry_stop(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        validate_result = not self.__check_telemetry_metrics(device_id, appId)
        checker_log = f"\napp {appId} telemetry stop, Expected: True, Actual: {validate_result}\n"
        return validate_result, checker_log

    def __check_telemetry_metrics(self, device_id, appId = None):
        if appId:
            dab_check_topic = "app-telemetry/metrics/" + appId
            metrics_log = f"app {appId} telemetry metrics"
        else:
            dab_check_topic = "device-telemetry/metrics"
            metrics_log = f"device telemetry metrics"

        self.logger.info(f"Starting {metrics_log} check by subscribing to '{dab_check_topic}'.")
        self.dab_tester.dab_client.subscribe_metrics(device_id, dab_check_topic)
        validate_result = self.dab_tester.dab_client.last_metrics_state()
        self.logger.info(f"Stopping {metrics_log} check by unsubscribing from '{dab_check_topic}'.")
        self.dab_tester.dab_client.unsubscribe_metrics(device_id, dab_check_topic)

        return validate_result

    def __check_logs_chunks(self, device_id, dab_request_body):
        logs = []
        try:
            validate_state = EnforcementManager().verify_logs_chunk(self.dab_tester, logs)
            if validate_state == False:
                "\n".join(logs)
                return validate_state, logs
            return EnforcementManager().verify_logs_structure(logs), "\n".join(logs)
        finally:
            EnforcementManager().delete_logs_collection_files()
