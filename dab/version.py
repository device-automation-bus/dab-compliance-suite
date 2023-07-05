from schema import dab_response_validator
from time import sleep
from DabTester import YesNoQuestion, Default_Validations
import jsons

def default(test_result, durationInMs=0,expectedLatencyMs=0):
    dab_response_validator.validate_version_response_schema(test_result.response)
    response  = jsons.loads(test_result.response)
    if response.status != 200:
        return False
    sleep(0.1)
    return Default_Validations(test_result, durationInMs, expectedLatencyMs)