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
        """
        Returns (ValidateCode, reason_string) for system/settings/set using system/settings/list.
        Features: 501 handling, EM caching, flat/legacy schemas, value support check, compact previews (max 3).
        """
        import json
        try:
            req = json.loads(dab_request_body); (sid, val), = req.items(); sid = str(sid).strip()
        except Exception as e:
            return ValidateCode.UNCERTAIN, f"system/settings/set {dab_request_body} ⇒ cannot parse payload ({e})."

        pv = lambda x, n=3: (f"{x[:n]!r}, … +{len(x)-n} more" if isinstance(x, list) and len(x) > n else
                            f"{ {k: x[k] for k in list(x)[:n]}!r}, … +{len(x)-n} more" if isinstance(x, dict) and len(x) > n else
                            repr(x))
        why = lambda m: f"system/settings/set {req} ⇒ {m}"

        em = EnforcementManager()
        if em.check_supported_settings() is False:
            resp = self.__execute_cmd(device_id, "system/settings/list", "{}")
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except Exception: resp = None
            if resp is None:
                last = getattr(self.dab_tester.dab_client, "last_error_code", lambda: None)()
                if last == 501:
                    em.set_supported_settings({}); return ValidateCode.UNSUPPORT, why("system/settings/list not implemented (501); settings API optional.")
                em.set_supported_settings({}); return ValidateCode.UNCERTAIN, why("could not fetch system/settings/list; cannot infer support.")
            sup = {}
            if isinstance(resp, dict) and "settings" not in resp:
                for k, v in resp.items():
                    k = str(k).strip()
                    if not k: continue
                    if isinstance(v, bool): sup[k] = v
                    elif isinstance(v, list): sup[k] = v
                    elif isinstance(v, dict) and v.get("min") is not None and v.get("max") is not None: sup[k] = {"min": v["min"], "max": v["max"]}
                    else: sup[k] = False
            elif isinstance(resp, dict) and isinstance(resp.get("settings"), list):
                for s in resp["settings"]:
                    if not isinstance(s, dict): continue
                    k = (s.get("id") or s.get("settingId") or "").strip(); t = (s.get("type") or "").strip().lower()
                    if not k: continue
                    if t in ("boolean", "bool", "toggle"): sup[k] = bool(s.get("supported", True))
                    elif t in ("list", "enum", "array", "multi-select"): sup[k] = s.get("values") or s.get("options") or []
                    elif t in ("integer", "int", "number", "range"):
                        r = s.get("range") or {"min": s.get("min"), "max": s.get("max")}
                        sup[k] = r if isinstance(r, dict) and r.get("min") is not None and r.get("max") is not None else False
                    else: sup[k] = False
            else:
                em.set_supported_settings({}); return ValidateCode.UNCERTAIN, why("unexpected system/settings/list schema; cannot infer support.")
            em.set_supported_settings(sup)

        sm = em.get_supported_settings() or {}
        if sid not in sm:
            return ValidateCode.UNSUPPORT, why("key (Settings Operation) not present in system/settings/list (omitted ⇒ unsupported).")

        desc = sm[sid]
        if isinstance(desc, bool): detail = "boolean=True (supported)" if desc else "boolean=False (unsupported)"
        elif isinstance(desc, list): detail = f"enum values(sample)=[{pv(desc)}]" if desc else "enum has no allowed values [] (unsupported)"
        elif isinstance(desc, dict) and "min" in desc and "max" in desc: detail = f"numeric range=[{desc['min']}, {desc['max']}]"
        else: detail = "descriptor indicates unsupported"

        code = em.is_setting_supported(sid, val)
        if code == ValidateCode.SUPPORT:   return ValidateCode.SUPPORT,   why(f"supported by device; {detail}.")
        if code == ValidateCode.UNSUPPORT: return ValidateCode.UNSUPPORT, why(f"value not supported by device; {detail}.")
        return ValidateCode.UNCERTAIN,      why(f"could not determine conclusively; {detail}.")

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
        """
        Precheck for input/key-press:
        - Fetch & cache supported keys from input/key/list (once)
        - Handle 501 as OPTIONAL (UNSUPPORT)
        - Normalize various response shapes
        - Return (ValidateCode, concise reason with 3-item sample)
        """
        import json
        req = json.loads(dab_request_body or "{}")
        key = (req.get("keyCode") or req.get("code") or "").strip()
        if not key:
            return ValidateCode.UNCERTAIN, "input/key-press payload missing 'keyCode'."

        pv = lambda xs: (f"{xs[:3]!r}, … +{len(xs)-3} more" if isinstance(xs, list) and len(xs) > 3 else repr(xs))
        EM = EnforcementManager()

        if not EM.get_supported_keys():
            self.logger.info("Fetching the list of supported input keys from the device.")
            resp = self.__execute_cmd(device_id, "input/key/list", "{}")
            if isinstance(resp, str):
                try: resp = json.loads(resp)
                except Exception: resp = None
            if resp is None:
                last = getattr(self.dab_tester.dab_client, "last_error_code", lambda: None)()
                if last == 501:
                    EM.add_supported_keys([])
                    return ValidateCode.UNSUPPORT, "input/key/list not implemented (501); key API optional."
                return ValidateCode.UNCERTAIN, "Could not fetch input/key/list; unable to infer support."

            # Normalize keys from common shapes
            raw = resp.get("keyCodes") if isinstance(resp, dict) else resp
            if isinstance(resp, dict) and not raw:
                raw = resp.get("keys") or resp.get("supportedKeys") or []
            keys = []
            for k in (raw if isinstance(raw, list) else []):
                if isinstance(k, str):
                    s = k.strip()
                    if s: keys.append(s)
                elif isinstance(k, dict):
                    v = (k.get("keyCode") or k.get("code") or k.get("id") or "").strip()
                    if v: keys.append(v)
            EM.add_supported_keys(keys or [])

        supported = EM.get_supported_keys() or []
        if not supported:
            return ValidateCode.UNCERTAIN, "No supported keys advertised; cannot determine support."

        if EM.is_key_supported(key):
            return ValidateCode.SUPPORT, f"input/key-press {key} supported. sample={pv(supported)}"
        return ValidateCode.UNSUPPORT, f"input/key-press {key} NOT supported. sample={pv(supported)}"


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
