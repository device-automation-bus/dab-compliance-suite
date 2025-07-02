from dab_client import DabClient
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
from util.enforcement_manager import ValidateCode
from time import sleep
import jsons

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester

    def __execute_cmd(self, device_id, dab_topic, dab_body):
        code = self.dab_tester.execute_cmd(device_id, dab_topic, dab_body)
        dab_response = self.dab_tester.dab_client.response()
        if code == 0:
            response = jsons.loads(dab_response)
            #print(response)
            return response
        else:
            return None

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
            case _:
                return ValidateCode.SUPPORT, ""

    def __precheck_system_settings_set(self, device_id, dab_request_body):
        request_body = jsons.loads(dab_request_body)
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
                prechecker_log = f"\nsystem settings set {request_key} is NOT supported on this device. Skip the test...\n"

        return validate_code, prechecker_log

    def __precheck_voice_set(self, device_id, dab_request_body):
        request_body = jsons.loads(dab_request_body)
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
            prechecker_log = f"\nvoice set {request_key} is NOT supported on this device. Skip the test...\n"
            return ValidateCode.UNSUPPORT, prechecker_log

        prechecker_log = f"\nvoice set {request_key} is supported on this device. Ongoing...\n"
        return ValidateCode.SUPPORT, prechecker_log

    def __precheck_voice_send_text_audio(self, device_id, dab_request_body):
        request_body = jsons.loads(dab_request_body)
        request_voice_system = request_body['voiceSystem']
        dab_precheck_body = jsons.dumps({"voiceSystem": {"name": request_voice_system, "enabled": True}}, indent = 4)

        validate_code, prechecker_log = self.__precheck_voice_set(device_id, dab_precheck_body)

        if validate_code == ValidateCode.UNCERTAIN:
            rechecker_log = f"\nvoice set {request_voice_system} is uncertain whether it is supported on this device. Ongoing...\n"
            return validate_code, prechecker_log
        elif validate_code == ValidateCode.UNSUPPORT:
            prechecker_log = f"\nvoice system {request_voice_system} is NOT supported on this device. Skip the test...\n"
            return validate_code, prechecker_log

        voice_assistant = EnforcementManager().get_supported_voice_assistants(request_voice_system)
        if voice_assistant["enabled"]:
            prechecker_log = f"\nvoice system {request_voice_system} is enabled on this device. Ongoing...\n"
            return validate_code, prechecker_log

        print(f"\nvoice system {request_voice_system} is disabled on this device. Try to enable...")

        dab_precheck_topic = "voice/set"
        voice_assistant["enabled"] = True
        dab_precheck_body = jsons.dumps({"voiceSystem": voice_assistant}, indent = 4)

        dab_response = self.__execute_cmd(device_id, dab_precheck_topic, dab_precheck_body)
        sleep(5)
        validate_result, precheck_log = self.__check_voice_set(device_id, dab_precheck_body)

        if validate_result:
            prechecker_log = f"\nvoice system {request_voice_system} is enabled on this device. Ongoing...\n"
            return ValidateCode.SUPPORT, prechecker_log

        prechecker_log = f"\nvoice system {request_voice_system} is not enabled on this device. Fail the test...\n"
        return ValidateCode.FAIL, prechecker_log

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
            case _:
                return True, ""

    def __check_application_state(self, device_id, dab_request_body, expected_state = 'FOREGROUND'):
        dab_check_topic = "applications/get-state"
        request_body = jsons.loads(dab_request_body)
        appId = request_body['appId']
        dab_check_body = jsons.dumps({"appId": appId}, indent = 4)

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
        request_body = jsons.loads(dab_request_body)
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
        request_body = jsons.loads(dab_request_body)
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
