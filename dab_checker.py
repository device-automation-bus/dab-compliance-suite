from dab_client import DabClient
import jsons

class DabChecker:
    def __init__(self, dab_tester):
        self.dab_tester = dab_tester

    def check(self, device_id, dab_request_topic, dab_request_body):
        match dab_request_topic:
            case 'applications/launch' | 'applications/launch-with-content':
                return self.__check_application_state(device_id, dab_request_body)
            case 'applications/exit':
                return self.__check_application_state(device_id, dab_request_body, 'EXIT')
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

        if validate_result == False:
            checker_log = checker_log + f"\napplication {appId} state is not expected state.\n"

        return validate_result, checker_log
