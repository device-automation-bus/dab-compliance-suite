from schema import dab_response_validator
from time import sleep
from DabTester import YesNoQuestion, Default_Validations

def key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    sleep(1)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"{test_result.request} key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def long_key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    sleep(1)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"{test_result.request} long key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def list(test_result, durationInMs=0, expectedLatencyMs=0):
    dab_response_validator.validate_key_list_schema(test_result.response)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

