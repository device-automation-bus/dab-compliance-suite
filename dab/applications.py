from time import sleep
from schema import dab_response_validator
from dab_tester import YesNoQuestion, Default_Validations
from util.enforcement_manager import EnforcementManager
import jsons

def launch(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt started?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)

def launch_with_content(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt started with playback?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    
def exit(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_exit_application_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(5)
    return YesNoQuestion(test_result, "Cobalt exited?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)

def list(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_list_applications_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    EnforcementManager().add_supported_application(response.applications)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def get_state(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_get_application_state_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)