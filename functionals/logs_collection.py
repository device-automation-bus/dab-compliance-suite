from functionals import functional_helpers as helpers
from dab_tester import to_test_id
from result_json import TestResult
from util.enforcement_manager import EnforcementManager, LOGS_COLLECTION_FOLDER
import config
import os
import time

LOGS_OPS = "ops: system/logs/start-collection, system/logs/stop-collection"
APP_RUN_WAIT = 15  # Seconds the app runs while logs are collected
COLLECTION_WAIT = 5  # Seconds each collection runs in the repeat check


def _stop_and_verify_logs(tester, device_id, logs, result):
    """
    Stops the log collection, reassembles the chunks and checks the folder
    structure. The archive is left extracted in LOGS_COLLECTION_FOLDER.

    Returns (stopped, error): whether the device accepted the stop, and an
    error message, or None when the archive is valid.
    """
    helpers.log_line(logs, "STEP", "Stopping log collection and reassembling the chunks.", result=result)
    status, _ = helpers.execute_cmd_and_log(tester, device_id, "system/logs/stop-collection", "{}", logs=logs, result=result)
    if status != 200:
        return False, f"system/logs/stop-collection returned {status} (expected 200)."
    if not EnforcementManager().verify_logs_chunk(tester, logs):
        return True, "Log chunks are missing, out of order or more than 2 s apart."
    if not EnforcementManager().verify_logs_structure(logs):
        return True, "The log archive does not have the system/, application/ and crash/ folders."
    return True, None


def run_logs_collection_app_folder_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – application logs are bucketed by DAB appId (spec 5.3)

    PASS if:
      - A log collection spanning a launch of the YouTube app returns a valid
        archive (all chunks, at most 2 s apart, with the DAB folder structure) AND
      - The archive has an application/<appId> folder with at least one
        non-empty file.
    OPTIONAL_FAILED if the operations are not supported.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")
    app_id = config.apps.get("youtube", "YouTube")

    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    collecting = False
    app_files = []

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id}, appId={app_id})", result=result)
        helpers.log_line(logs, "DESC", "Collect logs while the app runs; the archive must have its logs under application/<appId>.", result=result)

        cap_spec = f"{LOGS_OPS}, applications/launch, applications/exit"
        if not helpers.require_capabilities(tester, device_id, cap_spec, result, logs):
            return result

        # 1) Start log collection
        helpers.log_line(logs, "STEP", "Starting log collection.", result=result)
        status, _ = helpers.execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs=logs, result=result)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"system/logs/start-collection returned {status} (expected 200).")
            return result
        collecting = True

        # 2) Launch the app so it produces logs, then exit it
        helpers.log_line(logs, "STEP", f"Launching app via applications/launch (appId={app_id}).", result=result)
        status, _ = helpers.execute_cmd_and_log(tester, device_id, "applications/launch", f'{{"appId": "{app_id}"}}', logs=logs, result=result)
        if status != 200:
            helpers.finish(result, logs, "FAILED", f"applications/launch returned {status} (expected 200).")
            return result

        helpers.log_line(logs, "WAIT", f"Letting the app run for {APP_RUN_WAIT}s.", result=result)
        time.sleep(APP_RUN_WAIT)

        helpers.log_line(logs, "STEP", f"Exiting app via applications/exit (appId={app_id}).", result=result)
        helpers.execute_cmd_and_log(tester, device_id, "applications/exit", f'{{"appId": "{app_id}"}}', logs=logs, result=result)

        # 3) Stop log collection and verify the archive
        stopped, error = _stop_and_verify_logs(tester, device_id, logs, result)
        collecting = not stopped
        if error:
            helpers.finish(result, logs, "FAILED", error)
            return result

        # 4) Verify application/<appId> has the app logs
        app_dir = os.path.join(LOGS_COLLECTION_FOLDER, "application", app_id)
        helpers.log_line(logs, "STEP", f"Checking the app logs in application/{app_id}.", result=result)
        if not os.path.isdir(app_dir):
            helpers.finish(result, logs, "FAILED", f"The archive has no application/{app_id} folder.")
            return result
        app_files = [
            os.path.join(root, name)
            for root, _, names in os.walk(app_dir)
            for name in names
            if os.path.getsize(os.path.join(root, name)) > 0
        ]
        if not app_files:
            helpers.finish(result, logs, "FAILED", f"application/{app_id} has no non-empty log file.")
        else:
            helpers.finish(result, logs, "PASS", f"application/{app_id} has {len(app_files)} non-empty log file(s).")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        if collecting:
            # Do not leave a collection running for the next tests.
            tester.execute_cmd(device_id, "system/logs/stop-collection", "{}")
        EnforcementManager().delete_logs_collection_files()
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, appId={app_id}, app_log_files={len(app_files)}, id={test_id}, device={device_id}",
            result=result,
        )

    return result


def run_logs_collection_repeat_check(dab_topic, test_name, tester, device_id):
    """
    DAB 2.1 – log collection can run again after a stop (spec 5.3)

    PASS if:
      - Two log collections in a row both start with 200 and return a valid
        archive (all chunks, at most 2 s apart, with the DAB folder structure),
        i.e. stop-collection leaves the device ready for a new collection.
    OPTIONAL_FAILED if the operations are not supported.
    """
    test_id = to_test_id(f"{dab_topic}/{test_name}")

    logs = []
    result = TestResult(test_id, device_id, dab_topic, "{}", "UNKNOWN", "", logs)

    collecting = False
    completed = 0

    try:
        helpers.log_line(logs, "TEST", f"{test_name} (id={test_id}, device={device_id})", result=result)
        helpers.log_line(logs, "DESC", "Run two log collections in a row; both must return a valid archive.", result=result)

        if not helpers.require_capabilities(tester, device_id, LOGS_OPS, result, logs):
            return result

        for attempt in (1, 2):
            helpers.log_line(logs, "STEP", f"Starting log collection {attempt} of 2.", result=result)
            status, _ = helpers.execute_cmd_and_log(tester, device_id, "system/logs/start-collection", "{}", logs=logs, result=result)
            if status != 200:
                helpers.finish(result, logs, "FAILED", f"Collection {attempt}: system/logs/start-collection returned {status} (expected 200).")
                return result
            collecting = True

            helpers.log_line(logs, "WAIT", f"Collecting logs for {COLLECTION_WAIT}s.", result=result)
            time.sleep(COLLECTION_WAIT)

            stopped, error = _stop_and_verify_logs(tester, device_id, logs, result)
            collecting = not stopped
            EnforcementManager().delete_logs_collection_files()
            if error:
                helpers.finish(result, logs, "FAILED", f"Collection {attempt}: {error}")
                return result
            completed = attempt

        helpers.finish(result, logs, "PASS", "Both log collections returned a valid archive.")

    except helpers.UnsupportedOperationError as e:
        helpers.finish(result, logs, "OPTIONAL_FAILED", f"Unsupported op: {e.topic}")
    except Exception as e:
        helpers.finish(result, logs, "SKIPPED", f"Internal error: {e}")
    finally:
        if collecting:
            # Do not leave a collection running for the next tests.
            tester.execute_cmd(device_id, "system/logs/stop-collection", "{}")
        EnforcementManager().delete_logs_collection_files()
        final = getattr(result, "test_result", "UNKNOWN")
        helpers.set_outcome(result, final)
        result.test_result = final
        helpers.log_line(
            logs,
            "SUMMARY",
            f"outcome={final}, completed_collections={completed}, id={test_id}, device={device_id}",
            result=result,
        )

    return result
