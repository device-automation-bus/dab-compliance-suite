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
    return YesNoQuestion(test_result, "App started?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)

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
    return YesNoQuestion(test_result, "App started with playback?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    
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
    return YesNoQuestion(test_result, "App exited?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)

def list(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_list_applications_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    for application in response['applications']:
        EnforcementManager().add_supported_application(application['appId'])
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

def install(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_install_application_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def uninstall(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_uninstall_application_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def clear_data(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_clear_data_application_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def install_from_appstore(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_install_from_appstore_application_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)