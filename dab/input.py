from schema import dab_response_validator
from time import sleep
from DabTester import YesNoQuestion, Default_Validations
import jsons

class KeyList:
    key_list = []

def key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    request = jsons.loads(test_result.request)
    response  = jsons.loads(test_result.response)
    # No list available, assuming everything is required.
    if len(KeyList.key_list) <=0:
        if response.status != 200:
            return False
    else:
        if request.keyCode in KeyList.key_list:
            if response.status != 200:
                return False
        else:
            if response.status != 501:
                return False
    sleep(1)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"{test_result.request} key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def long_key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    dab_response_validator.validate_dab_response_schema(test_result.response)
    request = jsons.loads(test_result.request)
    response  = jsons.loads(test_result.response)
    # No list available, assuming everything is required.
    if len(KeyList.key_list) <=0:
        if response.status != 200:
            return False
    else:
        if request.keyCode in KeyList.key_list:
            if response.status != 200:
                return False
        else:
            if response.status != 501:
                return False

    sleep(1)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"{test_result.request} long key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def list(test_result, durationInMs=0, expectedLatencyMs=0):
    dab_response_validator.validate_key_list_schema(test_result.response)
    response  = jsons.loads(test_result.response)
    if response.status != 200:
        return False
    if len(response.keyCodes) <=0:
        return False
    KeyList.key_list = response.keyCodes
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

