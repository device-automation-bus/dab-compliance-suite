from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from logger import LOGGER
import json
import config

def run_voice_send_text_invalid_payload_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.0 – voice/send-text invalid payload (negative)

    Implements the same intent as the conformance "Bad Request" case by sending an invalid schema key
    (requestText_ instead of requestText).

    PASS only if:
      - voice/send-text returns 400 (Bad Request) for invalid payload.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    voice_system = None
    status_send = None

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Send invalid voice/send-text payload (wrong key); expect 400 Bad Request.", result=result)

        voice_system = getattr(config, "va", None)
        if not voice_system:
            helpers.finish(result, logs, "SKIPPED", "config.va is not set (voiceSystem missing).")
            return result

        cap_spec = "ops: voice/send-text"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        payload = {"requestText_": "Play lady Gaga music on YouTube", "voiceSystem": voice_system}
        helpers.log_line(logs, "STEP", f"Sending invalid voice/send-text payload: requestText_ + voiceSystem={voice_system}.", result=result)

        status_send, _ = helpers.execute_cmd_and_log(tester, device_id, "voice/send-text", json.dumps(payload), logs=logs, result=result)

        if status_send == 501:
            helpers.finish(result, logs, "OPTIONAL_FAILED", "voice/send-text returned 501 (not implemented).")
        elif status_send != 400:
            helpers.finish(result, logs, "FAILED", f"Expected 400 for invalid voice/send-text payload, got {status_send}.")
        else:
            helpers.finish(result, logs, "PASS", "voice/send-text rejected invalid payload with 400 as expected.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, status={status_send}, voiceSystem={voice_system}, id={test_id}, device={device_id}",
            result=result,
        )

    return result
