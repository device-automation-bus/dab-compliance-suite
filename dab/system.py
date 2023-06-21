from time import sleep
from DabTester import YesNoQuestion, Default_Validations
from schema import dab_response_validator

def restart(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    print("restarting...wait 60s...",end='',flush=True)
    sleep(60)
    return YesNoQuestion(test_result, "Cobalt re-started?")

def get(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_get_system_settings_response_schema(test_result.response)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def set(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_set_system_settings_response_schema(test_result.response)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def list(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_list_system_settings_schema(test_result.response)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)
