from time import sleep
from dab_tester import YesNoQuestion, Default_Validations
import jsons
from schema import dab_response_validator
from util.enforcement_manager import EnforcementManager
from logger import LOGGER
from schema import list_system_settings_schema_20, list_system_settings_schema_21
import dab_tester

def restart(test_result, durationInMs=0,expectedLatencyMs=0):
    try:
        dab_response_validator.validate_dab_response_schema(test_result.response)
    except Exception as error:
        print("Schema error:", error)
        return False
    response  = jsons.loads(test_result.response)
    if response['status'] != 200:
        return False
    LOGGER.info("system/restart issued. Device will reboot; subsequent preflight health-check will wait for readiness.")
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

def settings_list(test_result, durationInMs=0, expectedLatencyMs=0):
    try:
        response = jsons.loads(test_result.response)
    except Exception as error:
        LOGGER.warn(f"system/settings/list: JSON parse error: {error}")
        try:
            test_result.logs.append(f"system/settings/list: JSON parse error: {error}")
        except Exception:
            pass
        EnforcementManager().set_supported_settings(None)
        return False

    # Update supported settings map regardless; callers can decide how to use it
    EnforcementManager().set_supported_settings(response)

    status = response.get("status")
    if status != 200:
        msg = f"system/settings/list returned status {status}; skipping required-fields check."
        try:
            LOGGER.result(msg)
        finally:
            try:
                test_result.logs.append(msg)
            except Exception:
                pass
        return False
    # Determine DAB version and required keys
    version = getattr(dab_tester, "DAB_VERSION", None) or "2.0"
    schema = list_system_settings_schema_21 if version == "2.1" else list_system_settings_schema_20
    required_keys = schema.get("required", [])

    # Compute and log missing fields (soft — do not fail)
    missing = [k for k in required_keys if k not in response]
    if missing:
        line1 = f"system/settings/list ({version}) — Missing fields mark the operation as unsupported; not implement via DAB."
        line2 = f" → claimed as Device is not supported this opeartions, Missing: [{', '.join(missing)}]"

        if hasattr(LOGGER, "result"):
            LOGGER.result(line1); LOGGER.result(line2)

        if getattr(test_result, "logs", None) is not None:
            test_result.logs.extend([line1, line2])

    # Proceed with your existing timing/latency validations
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
