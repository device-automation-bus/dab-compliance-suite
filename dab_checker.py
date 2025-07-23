from dab_client import DabClient
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
from util.enforcement_manager import ValidateCode
from time import sleep
import json

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester

    def __execute_cmd(self, device_id, dab_topic, dab_body):
        code = self.dab_tester.execute_cmd(device_id, dab_topic, dab_body)
        dab_response = self.dab_tester.dab_client.response()
        if code == 0:
            response = json.loads(dab_response)
            return response
        else:
            return None

    def is_operation_supported(self, device_id, operation):
        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\n{operation} is uncertain whether it is supported on this device. Ongoing...\n"
        if not EnforcementManager().get_supported_operations():
            dab_precheck_topic = "operations/list"
            dab_precheck_body = "{}"
            print(f"\nTry to get supported DAB operation list...\n")
            dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
            operations = dab_response['operations'] if dab_response is not None else None
            EnforcementManager().add_supported_operations(operations)

        if not EnforcementManager().get_supported_operations():
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
            case _:
                return ValidateCode.SUPPORT, ""

    def __precheck_system_settings_set(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        (request_key, request_value), = request_body.items()
        dab_precheck_topic = "system/settings/list"
        dab_precheck_body = "{}"

        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\nsystem settings set {request_key} is uncertain whether it is supported on this device. Ongoing...\n"

        if EnforcementManager().check_supported_settings() == False:
            print(f"\nTry to get system supported settings list...\n")
            dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
            EnforcementManager().set_supported_settings(dab_response)

            if not dab_response:
                return validate_code, prechecker_log

        for setting in request_body:
            validate_code = EnforcementManager().is_setting_supported(setting)
            if validate_code == ValidateCode.SUPPORT:
                prechecker_log = f"\nsystem settings set {request_key} is supported on this device. Ongoing...\n"
            elif validate_code == ValidateCode.UNSUPPORT:
                prechecker_log = f"\nsystem settings set {request_key} is NOT supported on this device. Ongoing...\n"

        return validate_code, prechecker_log

    def __precheck_voice_set(self, device_id, dab_request_body):
        request_body = json.loads(dab_request_body)
        (request_key, request_value), = request_body.items()
        dab_precheck_topic = "voice/list"
        dab_precheck_body = "{}"

        validate_code = ValidateCode.UNCERTAIN
        prechecker_log = f"\nvoice set {request_value['name']} is uncertain whether it is supported on this device. Ongoing...\n"

        if not EnforcementManager().get_supported_voice_assistants():
            print(f"\nTry to get system supported voice system list...\n")
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

        print(f"\nvoice system {request_voice_system} is disabled on this device. Try to enable...")

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

        print(f"\nstop device telemetry on this device...\n")
        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\ndevice telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_device_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "device-telemetry/start"
        dab_precheck_body = json.dumps({"duration": 1000}, indent = 4)

        print(f"\nstart device telemetry on this device...\n")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id)

        if not validate_result:
            print(f"\ndevice telemetry is not started on this device.\n")
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

        print(f"\nstop app {appId} telemetry on this device...\n")
        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        prechecker_log = f"\napp {appId} telemetry is stopped on this device. Try to start...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_app_telemetry_stop(self, device_id, dab_request_body):
        dab_precheck_topic = "app-telemetry/start"
        request_body = json.loads(dab_request_body)
        appId = request_body['appId']
        dab_precheck_body = json.dumps({"appId": appId, "duration": 1000}, indent = 4)

        print(f"\nstart app {appId} telemetry on this device...\n")
        self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)

        validate_result = self.__check_telemetry_metrics(device_id, appId)

        if not validate_result:
            print(f"\napp {appId} telemetry is not started on this device.\n")
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
            print(f"\nTry to get supported key list...\n")
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
        print(f"\nstop device telemetry on this device...\n")
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
        print(f"\nstop app {appId} telemetry on this device...\n")
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
            dab_check_topic = "app-telemetry/metrics/" + appId.lower()
            metrics_log = f"app {appId} telemetry metrics"
        else:
            dab_check_topic = "device-telemetry/metrics"
            metrics_log = f"device telemetry metrics"

        print(f"\nstart {metrics_log} checking...\n")
        self.dab_tester.dab_client.subscribe_metrics(device_id, dab_check_topic)
        validate_result = self.dab_tester.dab_client.last_metrics_state()

        print(f"\nstop {metrics_log} checking...\n")
        self.dab_tester.dab_client.unsubscribe_metrics(device_id, dab_check_topic)

        return validate_result