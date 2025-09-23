from dab_client import DabClient
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
from util.enforcement_manager import ValidateCode
from time import sleep
import json
from logger import LOGGER  # <— use the shared singleton logger

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester
        self.logger = LOGGER

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
            # print(f"\nTry to get supported DAB operation list...\n")
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

        # print(prechecker_log)
        # the caller will print/store this via its own result logger
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
            request_body = dab_request_body if isinstance(dab_request_body, dict) else json.loads(dab_request_body or "{}")
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
                accepted_info = f"{accepted_preview} (showing up to 3 of {len(desc)})"
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
            # print(f"\nTry to get system supported voice system list...\n")
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
            rechecker_log = f"\nvoice set {request_voice_system} is uncertain whether it is supported on this device. Ongoing...\n"
            return validate_code, prechecker_log
        elif validate_code == ValidateCode.UNSUPPORT:
            prechecker_log = f"\nvoice system {request_voice_system} is NOT supported on this device. Ongoing...\n"
            return validate_code, prechecker_log

        voice_assistant = EnforcementManager().get_supported_voice_assistants(request_voice_system)
        if voice_assistant["enabled"]:
            prechecker_log = f"\nvoice system {request_voice_system} is enabled on this device. Ongoing...\n"
            return validate_code, prechecker_log

        # print(f"\nvoice system {request_voice_system} is disabled on this device. Try to enable...")
        self.logger.info(f"Voice system '{request_voice_system}' is disabled. Attempting to enable it for this test.")

        dab_precheck_topic = "voice/set"
        voice_assistant["enabled"] = True
        dab_precheck_body = json.dumps({"voiceSystem": voice_assistant}, indent = 4)

        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
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

        # print(f"\nstop device telemetry on this device...\n")
        self.logger.info("Stopping any existing device telemetry so the start request can be validated cleanly.")
        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\ndevice telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_device_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "device-telemetry/start"
        dab_precheck_body = json.dumps({"duration": 1000}, indent = 4)

        # print(f"\nstart device telemetry on this device...\n")
        self.logger.info("Starting device telemetry briefly to verify the stop request behaves correctly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id)

        if not validate_result:
            # print(f"\ndevice telemetry is not started on this device.\n")
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

        # print(f"\nstop app {appId} telemetry on this device...\n")
        self.logger.info(f"Stopping any existing telemetry for app '{appId}' so the start request can be validated cleanly.")
        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\napp {appId} telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_app_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "app-telemetry/start"
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        dab_precheck_body = json.dumps({"appId": appId, "duration": 1000}, indent = 4)

        # print(f"\nstart app {appId} telemetry on this device...\n")
        self.logger.info(f"Starting telemetry for app '{appId}' briefly to verify the stop request behaves correctly.")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id, appId)

        if not validate_result:
            # print(f"\napp {appId} telemetry is not started on this device.\n")
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
            # print(f"\nTry to get supported key list...\n")
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
        request_body = json.loads(dab_request_body)
        (request_key, request_value), = request_body.items()

        validate_result = False
        actual_value = 'UNKNOWN'

        dab_response = self.__execute_cmd(device_id, dab_check_topic, dab_check_body)
        if dab_response and request_key in dab_response:
            actual_value = dab_response[request_key]
            validate_result = True if actual_value == request_value else False

        checker_log = f"\nsystem settings set {request_key} Value, Expected: {request_value}, Actual: {actual_value}\n"
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
        # print(f"\nstop device telemetry on this device...\n")
        self.logger.info("Stopping device telemetry after validation.")
        dab_response = self.__execute_cmd(device_id, 'device-telemetry/stop', '{}')
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
        # print(f"\nstop app {appId} telemetry on this device...\n")
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

        # print(f"\nstart {metrics_log} checking...\n")
        self.logger.info(f"Starting {metrics_log} check by subscribing to '{dab_check_topic}'.")
        self.dab_tester.dab_client.subscribe_metrics(device_id, dab_check_topic)
        validate_result = self.dab_tester.dab_client.last_metrics_state()

        # print(f"\nstop {metrics_log} checking...\n")
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
