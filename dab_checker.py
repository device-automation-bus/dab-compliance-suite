from dab_client import DabClient
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
import jsons

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester

    def precheck(self, device_id, dab_request_topic, dab_request_body):
        """
        Checks if the DAB operation is supported by the target before send the DAB request to the target.

        Args:
            device_id: The device id
            dab_request_topic: the request dab topic
            dab_request_body: the request dab body

         Returns:
            validate_code:
                0, target supports this DAB operation.
                1, target doesn't support this DAB operation.
                2, uncertain whether the target support this DAB operation.
            prechecker_log:
                output message
        """
        match dab_request_topic:
            case 'system/settings/set':
                return self.__precheck_system_settings_set(device_id, dab_request_body)
            case _:
                return 0, ""

    def __precheck_system_settings_set(self, device_id, dab_request_body):
        dab_precheck_topic = "system/settings/list"
        request_body = jsons.loads(dab_request_body)
        (request_key, request_value), = request_body.items()

        validate_code = 2
        prechecker_log = f"\nsystem settings set {request_key} is uncertain whether it is supported on this device. Ongoing...\n"

        if EnforcementManager().check_supported_settings() == False:
            print(f"\nTry to get system supported settings list...\n")
            code = self.dab_tester.execute_cmd(device_id, dab_precheck_topic)
            check_response = self.dab_tester.dab_client.response()
            if code == 0:
                try:
                    dab_response_validator.validate_list_system_settings_schema(check_response)
                except Exception as error:
                    print("Schema error:", error)
                    print(check_response)
                    EnforcementManager().set_supported_settings(None)
                    return validate_code, prechecker_log
                response = jsons.loads(check_response)
                EnforcementManager().set_supported_settings(response)
            else:
                EnforcementManager().set_supported_settings(None)
                return validate_code, prechecker_log

        for setting in request_body:
            validate_code = EnforcementManager().is_setting_supported(setting)
            if validate_code == 0:
                prechecker_log = f"\nsystem settings set {request_key} is supported on this device. Ongoing...\n"
            elif validate_code == 1:
                prechecker_log = f"\nsystem settings set {request_key} is NOT supported on this device. Skip the test...\n"

        return validate_code, prechecker_log

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

        code = self.dab_tester.execute_cmd(device_id, dab_check_topic, dab_check_body)

        validate_result = False
        actual_state = 'UNKNOWN'
        check_response = self.dab_tester.dab_client.response()

        if code == 0:
            try:
                response = jsons.loads(check_response)
                if response['status'] != 200:
                    validate_result = False
                else:
                    actual_state = response['state']
                    validate_result = True if actual_state == expected_state else False

            except Exception as e:
                validate_result = False

        checker_log = f"\napplication {appId} State, Expected: {expected_state}, Actual: {actual_state}\n"

        #if validate_result == False:
        #    checker_log = checker_log + f"\napplication {appId} state is not expected state.\n"

        return validate_result, checker_log

    def __check_system_settings_set(self, device_id, dab_request_body):
        dab_check_topic = "system/settings/get"
        request_body = jsons.loads(dab_request_body)
        (request_key, request_value), = request_body.items()

        code = self.dab_tester.execute_cmd(device_id, dab_check_topic)

        validate_result = False
        actual_value = 'UNKNOWN'
        check_response = self.dab_tester.dab_client.response()

        if code == 0:
            try:
                response = jsons.loads(check_response)
                if response['status'] != 200:
                    validate_result = False
                else:
                    actual_value = response[request_key]
                    validate_result = True if actual_value == request_value else False

            except Exception as e:
                validate_result = False

        checker_log = f"\nsystem settings set {request_key} Value, Expected: {request_value}, Actual: {actual_value}\n"

        #if validate_result == False:
        #    checker_log = checker_log + f"\nsystem settings set {request_key} value is not expected value.\n"

        return validate_result, checker_log
