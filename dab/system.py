from time import sleep
from dab_tester import YesNoQuestion, Default_Validations
import jsons
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager

def restart(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    print("restarting...wait 60s...",end='',flush=True)
    sleep(60)
    return YesNoQuestion(test_result, "Device re-started?")

def settings_get(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_get_system_settings_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def settings_set(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_set_system_settings_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def settings_list(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_list_system_settings_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        EnforcementManager().set_supported_settings(None)
        return False
    response  = jsons.loads(test_result.response)
    EnforcementManager().set_supported_settings(response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def start_log_collection(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_start_log_collection_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def stop_log_collection(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_stop_log_collection_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def setup_skip(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def power_mode_get(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_power_mode_get_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def power_mode_set(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        dab_response_validator.validate_power_mode_set_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)
