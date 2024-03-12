from schema import dab_response_validator
from time import sleep
from dab_tester import Default_Validations
import jsons


def start(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_start_device_telemetry_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)

def stop(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_stop_device_telemetry_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)