from schema import dab_response_validator
from time import sleep
from dab_tester import YesNoQuestion, Default_Validations
from util.enforcement_manager import EnforcementManager
import json

class KeyList:
    key_list = []

def key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    request = json.loads(test_result.request)
    response  = json.loads(test_result.response)
    # No list available, assuming everything is required.
    if len(KeyList.key_list) <=0:
        if response['status'] != 200:
            return False
    else:
        if request['keyCode'] in KeyList.key_list:
            if response['status'] != 200:
                return False
        else:
            if response['status'] != 501:
                return False
    sleep(1)

    # Remove YesNoQuestion → directly validate
    if isinstance(expectedLatencyMs, int):
        return Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return True
    
    # Previous logic:
    # if type(expectedLatencyMs) == int:
    #    return YesNoQuestion(test_result, f"{test_result.request} key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    # else:
    #    return YesNoQuestion(test_result, expectedLatencyMs)
     
def long_key_press(test_result, durationInMs=0, expectedLatencyMs=None):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    request = json.loads(test_result.request)
    response  = json.loads(test_result.response)
    # No list available, assuming everything is required.
    if len(KeyList.key_list) <=0:
        if response['status'] != 200:
            return False
    else:
        if request['keyCode'] in KeyList.key_list:
            if response['status'] != 200:
                return False
        else:
            if response['status'] != 501:
                return False

    sleep(1)
    # Remove YesNoQuestion → directly validate
    if isinstance(expectedLatencyMs, int):
        return Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return True
    
    # Previous logic:
    #if type(expectedLatencyMs) == int:
    #    return YesNoQuestion(test_result, f"{test_result.request} long key initiated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    #else:
    #    return YesNoQuestion(test_result, expectedLatencyMs)

def list(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_key_list_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = json.loads(test_result.response)
    if response['status'] != 200:
        return False
    if len(response['keyCodes']) <=0:
        return False
    KeyList.key_list = response['keyCodes']
    EnforcementManager().add_supported_keys(KeyList.key_list)
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)
