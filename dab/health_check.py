from schema import dab_response_validator
from time import sleep
from DabTester import YesNoQuestion, Default_Validations

def get(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_health_check_response_schema(test_result.response)
    sleep(5)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)