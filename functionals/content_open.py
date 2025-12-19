from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config
import time
import sys

def run_content_open_invalid_content_id_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – content/open invalid contentId (negative)

    Goal:
      - Call content/open with a clearly invalid/non-existent contentId.
      - Verify the device does NOT treat it as success.
      - Expect a client error (400 Bad Request) for invalid contentId.
      - If the operation is not implemented (501), treat as OPTIONAL_FAILED.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    invalid_content_id = "dab-invalid-content-id-0000-should-not-exist"

    try:
        helpers.log_line(logs, "TEST", f"Content_Open Invalid Content_ID Check — {test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Ensure content/open rejects a non-existent contentId with an appropriate client error.", result=result)
        helpers.log_line(logs, "DESC", "Required operation: content/open.", result=result)
        helpers.log_line(logs, "DESC", "PASS if content/open returns 400 (client error) for the invalid contentId, not 200.", result=result)

        cap_spec = "ops: content/open"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        payload = json.dumps({"contentId": invalid_content_id})
        helpers.log_line(logs, "STEP", f"Sending content/open with invalid contentId={invalid_content_id!r}, payload={payload}", result=result)

        status, body = helpers.execute_cmd_and_log(tester, device_id, dab_topic, payload, logs=logs, result=result)
        helpers.log_line(logs, "INFO", f"content/open returned status={status} for invalid contentId.", result=result)

        if status == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "content/open is not implemented on this device (status=501).")
            return result
        elif status == 400:
            pass
        elif status == 200:
            helpers.finish(result, logs, "FAILED", "content/open returned 200 for an invalid/non-existent contentId; expected 400.")
            return result
        else:
            helpers.finish(result, logs, "FAILED", f"Unexpected status for invalid contentId: got {status}, expected 400 (Bad Request).")
            return result

        error_body = None
        if body:
            try:
                error_body = json.loads(body) if isinstance(body, str) else (body or {})
            except Exception as e:
                helpers.finish(result, logs, "FAILED", f"content/open error response for invalid contentId is not valid JSON: {e}")
                return result

        if isinstance(error_body, dict):
            error_fields = [f"{k}={error_body.get(k)!r}" for k in ("error", "message", "statusMessage", "reason") if k in error_body]
            if error_fields:
                helpers.log_line(logs, "INFO", "content/open error payload fields: " + ", ".join(error_fields), result=result)
            else:
                helpers.log_line(logs, "INFO", "content/open error payload has no explicit error/message fields; relying on status=400 only.", result=result)
        else:
            helpers.log_line(logs, "INFO", "content/open returned status=400 with no structured JSON body; treating as valid client error.", result=result)

        helpers.finish(result, logs, "PASS", "content/open correctly returned a client error (400) for a non-existent contentId.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")

    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error during content/open invalid contentId check: {e}")

    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(logs, "SUMMARY", f"outcome={final}, invalid_content_id={invalid_content_id!r}, id={test_id}, device={device_id}", result=result)

    return result
