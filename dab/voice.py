from schema import dab_response_validator
from time import sleep
from dab_tester import YesNoQuestion, Default_Validations
import jsons
from util.enforcement_manager import EnforcementManager

def send_audio(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(5)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"Can you verify the voice command has been initated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def send_text(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(5)
    if type(expectedLatencyMs) == int:
        return YesNoQuestion(test_result, f"Can you verify the voice command ${test_result.request} has been initated?") and Default_Validations(test_result, durationInMs, expectedLatencyMs)
    else:
        return YesNoQuestion(test_result, expectedLatencyMs)

def list(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_list_voice_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    EnforcementManager().set_supported_voice_assistants(response['voiceSystems'])
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def set(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_set_voice_system_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)