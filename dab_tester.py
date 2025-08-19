from dab_client import DabClient
from dab_checker import DabChecker
from result_json import TestResult, TestSuite
from logger import LOGGER
from time import sleep
from readchar import readchar
from re import split
import datetime
import jsons
import json
import config
import os
from util.enforcement_manager import EnforcementManager
from util.enforcement_manager import ValidateCode
from sys import exit as sys_exit
import re
import time  

# Raised when preflight (discovery/health) decides we should stop the run.
class PreflightTermination(Exception):
    pass

class DabTester:
    def __init__(self, broker, override_dab_version=None):
        self.dab_client = DabClient()
        self.dab_client.connect(broker, 1883)
        self.dab_checker = DabChecker(self)
        self.verbose = False
        self.dab_version = None  # Will be set by auto-detect logic
        self.override_dab_version = override_dab_version
        self.logger = LOGGER
        self.logger.verbose = self.verbose
        # Load valid DAB topics using jsons
        try:
            with open("valid_dab_topics.json", "r", encoding="utf-8") as f:
                self.valid_dab_topics = set(jsons.load(jsons.loads(f.read())))
        except Exception as e:
            self.logger.error(f"Could not load 'valid_dab_topics.json'. The topic validation set is empty. Exception: {type(e).__name__}: {e}")
            self.valid_dab_topics = set()
    # -----------------------------
    # Core send/request wrapper
    # -----------------------------
    def execute_cmd(self,device_id,dab_request_topic,dab_request_body="{}"):
        self.dab_client.request(device_id,dab_request_topic,dab_request_body)
        if self.dab_client.last_error_code() == 200:
            return 0
        else:
            return 1
    # -----------------------------
    # Preflight helpers
    # “Preflight” just means the quick checks we run before a test starts—like an aviation pre-flight checklist.
    # -----------------------------
    def _preflight_discovery_or_raise(self, device_id: str, interactive: bool = True, fatal: bool = False):
        """
        Run dab/discovery and ensure `device_id` is present.
        If not present (or discovery fails), optionally prompt:
        [R]etry, [C]ontinue anyway, or [T]erminate.
        Raises PreflightTermination on terminate (or when interactive=False).
        """
        self.logger.info(
            f"Preflight step 1 of 2: looking for the device on the MQTT broker using discovery. "
            f"Target device is '{device_id}'."
        )

        def do_discover():
            try:
                return self.dab_client.discover_devices() or []
            except Exception as e:
                self.logger.error(f"Discovery did not complete. Reason: {e}")
                return None  # signal hard failure

        # 1) First attempt
        discovered_list = do_discover()
        if discovered_list is None:
            # discovery call itself failed
            if not interactive:
                raise PreflightTermination("Discovery failed.")
            # prompt loop
            while True:
                self.logger.prompt(
                    "The device is NOT discoverable. Choose one of the options: "
                    "Retry now (R), Continue anyway (C), or Terminate this run (T)."
                )
                answer = input(
                    "\n[PROMPT] Device is NOT discoverable.\n"
                    "         Choose an action:\n"
                    "         [R]etry discovery now\n"
                    "         [C]ontinue anyway (NOT recommended)\n"
                    "         [T]erminate this run (partial results will be saved)\n"
                    "         Enter choice [R/C/T]: "
                ).strip().lower()

                if answer in ("", "r", "retry"):
                    self.logger.info("Retrying discovery once …")
                    discovered_list = do_discover()
                    if discovered_list:
                        break  # proceed to evaluate results
                    self.logger.warn("Discovery still failing.")
                    continue
                if answer in ("c", "continue"):
                    self.logger.info("Proceeding without discovery gate (NOT recommended).")
                    return
                if answer in ("t", "terminate", "q", "quit"):
                    self.logger.info("Terminating this run based on the selected option.")
                    if fatal:
                        self.Close(); sys_exit(5)
                    raise PreflightTermination("Discovery failed; user chose to terminate.")
                self.logger.info("That was not a valid choice. Enter R, C, or T.")

        if not discovered_list:
            self.logger.error("No devices responded to discovery on the broker.")
            if not interactive:
                raise PreflightTermination("No devices discovered.")
            # prompt loop
            while True:
                self.logger.prompt(
                    "No devices discovered. Choose: Retry (R), Continue anyway (C), or Terminate (T)."
                )
                answer = input(
                    "\n[PROMPT] No devices responded to discovery.\n"
                    "         Choose an action:\n"
                    "         [R]etry discovery now\n"
                    "         [C]ontinue anyway (NOT recommended)\n"
                    "         [T]erminate this run (partial results will be saved)\n"
                    "         Enter choice [R/C/T]: "
                ).strip().lower()

                if answer in ("", "r", "retry"):
                    self.logger.info("Retrying discovery once …")
                    discovered_list = do_discover() or []
                    if discovered_list:
                        break
                    self.logger.warn("Still no devices discovered.")
                    continue
                if answer in ("c", "continue"):
                    self.logger.info("Proceeding without discovery gate (NOT recommended).")
                    return
                if answer in ("t", "terminate", "q", "quit"):
                    self.logger.info("Terminating this run based on the selected option.")
                    if fatal:
                        self.Close(); sys_exit(5)
                    raise PreflightTermination("No devices discovered; user chose to terminate.")
                self.logger.info("That was not a valid choice. Enter R, C, or T.")

        # Summarize findings and ensure target is present
        found_devices = []
        target_ip = None
        for entry in discovered_list:
            did = entry.get("deviceId") or entry.get("device_id")
            ip  = entry.get("ip") or entry.get("ipAddress") or "n/a"
            if did:
                found_devices.append((did, ip))
                if did == device_id:
                    target_ip = ip

        if found_devices:
            readable = ", ".join(f"{did} at {ip}" for did, ip in found_devices)
            self.logger.info(f"Discovery found these devices: {readable}.")

        if target_ip is None:
            ids = ", ".join(sorted({d for d, _ in found_devices})) if found_devices else "none"
            self.logger.error(
                f"The target device '{device_id}' was not in the discovery results. Devices seen: {ids}."
            )
            if not interactive:
                raise PreflightTermination("Target not discoverable.")
            # prompt loop
            while True:
                self.logger.prompt(
                    "Target not in discovery results. Choose: Retry (R), Continue anyway (C), or Terminate (T)."
                )
                answer = input(
                    "\n[PROMPT] Target was NOT found in discovery results.\n"
                    "         Choose an action:\n"
                    "         [R]etry discovery now\n"
                    "         [C]ontinue anyway (NOT recommended)\n"
                    "         [T]erminate this run (partial results will be saved)\n"
                    "         Enter choice [R/C/T]: "
                ).strip().lower()

                if answer in ("", "r", "retry"):
                    self.logger.info("Retrying discovery once …")
                    discovered_list = do_discover() or []
                    # re-check for target
                    target_ip = None
                    found_devices = []
                    for entry in discovered_list:
                        did = entry.get("deviceId") or entry.get("device_id")
                        ip  = entry.get("ip") or entry.get("ipAddress") or "n/a"
                        if did:
                            found_devices.append((did, ip))
                            if did == device_id:
                                target_ip = ip
                    if target_ip is not None:
                        break
                    self.logger.warn("Target still not present in discovery results.")
                    continue
                if answer in ("c", "continue"):
                    self.logger.info("Proceeding without discovery gate (NOT recommended).")
                    return
                if answer in ("t", "terminate", "q", "quit"):
                    self.logger.info("Terminating this run based on the selected option.")
                    if fatal:
                        self.Close(); sys_exit(5)
                    raise PreflightTermination("Target not discoverable; user chose to terminate.")
                self.logger.info("That was not a valid choice. Enter R, C, or T.")

        self.logger.ok(
            f"Discovery successful. The target device '{device_id}' is reachable at {target_ip}."
        )


    def pretest_health_check(self, device_id: str, retries: int = 3, delay_sec: int = 10, interactive: bool = True, fatal: bool = False,) -> bool:
        """
        Run dab/<device-id>/health-check/get before each test.
        Retries `retries` times (in addition to the first attempt) with `delay_sec` delay.
        If still unhealthy, interactively ask user to Retry / Continue / Terminate.
        Returns True if we should proceed with the test; False to skip/stop.
        """
        total_attempts = retries + 1
        self.logger.info(f"Preflight step 2 of 2: checking device health before running the test. Target device is '{device_id}'.")

        for attempt in range(1, total_attempts + 1):
            self.logger.info(f"Health check attempt {attempt} of {total_attempts} on the topic 'dab/{device_id}/health-check/get'.")
            try:
                self.dab_client.request(device_id, "health-check/get", "{}")
                resp_text = self.dab_client.response() or ""
                status = self.dab_client.last_error_code()

                healthy = False
                message = ""
                if resp_text:
                    try:
                        j = json.loads(resp_text)
                        healthy = bool(j.get("healthy", False))
                        message = j.get("message", "")
                    except Exception:
                        pass

                status_str = status if status is not None else "N/A"
                msg_suffix = f" with message: {message}" if message else ""
                self.logger.info(f"Health check response: HTTP {status_str}. Healthy flag is {healthy}{msg_suffix}.")

                if status == 200 and healthy:
                    self.logger.ok("Health check passed. Proceeding to run the test.")
                    return True

                if attempt < total_attempts:
                    self.logger.info(f"The device did not report healthy. Waiting {delay_sec} seconds before trying again.")
                    sleep(delay_sec)

            except Exception as e:
                if attempt < total_attempts:
                    self.logger.warn(f"There was an error during the health check: {e}. Waiting {delay_sec} seconds and trying again.")
                    sleep(delay_sec)
                else:
                    self.logger.warn(f"There was an error during the health check: {e}.")

        self.logger.error("The device did not pass the health check after several attempts. Check the device power, network connectivity, DAB service availability, and connection to the MQTT broker.")

        if not interactive:
            return False

        while True:
            self.logger.prompt("The device is unhealthy. Choose one of the options: Retry now (R), Continue anyway (C), or Terminate this run (T).")
            answer = input(
                "\n[PROMPT] Device is unhealthy.\n"
                "         Choose an action:\n"
                "         [R]etry health-check now\n"
                "         [C]ontinue anyway (NOT recommended)\n"
                "         [T]erminate this run (partial results will be saved)\n"
                "         Enter choice [R/C/T]: "
            ).strip().lower()

            if answer in ("", "r", "retry"):
                try:
                    self.logger.info("Retrying the health check once immediately.")
                    self.dab_client.request(device_id, "health-check/get", "{}")
                    resp_text = self.dab_client.response() or ""
                    status = self.dab_client.last_error_code()

                    healthy = False
                    message = ""
                    if resp_text:
                        try:
                            j = json.loads(resp_text)
                            healthy = bool(j.get("healthy", False))
                            message = j.get("message", "")
                        except Exception:
                            pass

                    status_str = status if status is not None else "N/A"
                    msg_suffix = f" with message: {message}" if message else ""
                    self.logger.info(f"Health check response: HTTP {status_str}. Healthy flag is {healthy}{msg_suffix}.")

                    if status == 200 and healthy:
                        self.logger.ok("Health check passed on the retry. Proceeding.")
                        return True
                    self.logger.warn("The device is still unhealthy after the retry.")

                except Exception as e:
                    self.logger.warn(f"There was an error during the health check retry: {e}.")
                continue

            if answer in ("c", "continue"):
                self.logger.info("Proceeding even though the device reported unhealthy.")
                return True

            if answer in ("t", "terminate", "q", "quit"):
                self.logger.info("Terminating this run based on the selected option.")
                if fatal:
                    self.Close()
                    sys_exit(5)
                return False

            self.logger.info("That was not a valid choice. Enter R, C, or T.")

    def _preflight_before_each_test_or_raise(self, device_id: str):
        """
        Full preflight: discovery then health-check.
        Raises PreflightTermination if we should stop the run.
        """
        # 1) Discovery (hard gate; no prompt)
        self._preflight_discovery_or_raise(device_id)

        # 2) Health-check (prompt allowed)
        ok = self.pretest_health_check(device_id, retries=3, delay_sec=10, interactive=True, fatal=False)
        if not ok:
            raise PreflightTermination("Health-check failed; user chose to terminate.")
    # -----------------------------
    # Main Execute for a single test
    # -----------------------------
    def Execute(self, device_id, test_case):
        # Unpack first so we can announce the test name before any preflight work
        (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title, is_negative, test_version) = self.unpack_test_case(test_case)

        if dab_request_topic is None:
            return None
        # Announce which test is starting (printed always)
        test_id = to_test_id(f"{dab_request_topic}/{test_title}")
        self.logger.result(f"Starting test '{test_title}' (ID {test_id}) on topic '{dab_request_topic}' for device '{device_id}'.")

        # ---------- test section ----------
        self.logger.test_start(
            name=test_title,
            test_id=test_id,
            topic=dab_request_topic,
            device=device_id,
            request_body=dab_request_body,
            suite=None  # keep None; pass suite name from callers if desired
        )
        section_wall_start = time.time()
        # -------------------------------------------------------------

        # NEW: make sure we always try to return to Home after this test finishes
        try:
            # Full preflight (discovery + health). If it fails/terminates, let it propagate to stop the run.
            self._preflight_before_each_test_or_raise(device_id)

            # Initialize result object for logging and reporting
            test_result = TestResult(to_test_id(f"{dab_request_topic}/{test_title}"), device_id, dab_request_topic, dab_request_body, "UNKNOWN", "", [])
            # ------------------------------------------------------------------------
            # DAB Version Compatibility Check
            # If the test is meant for DAB 2.1 but the dav version is on DAB 2.0,
            # treat this as OPTIONAL_FAILED instead of skipping or erroring out.
            # This ensures transparency in test result reporting.
            # ------------------------------------------------------------------------
            # Get dab version version (default "2.0") and convert both to float
            dab_version = self.dab_version or "2.0"
            required_version = float(test_version)

            # If the required test version > current dab version, mark as OPTIONAL_FAILED
            try:
                required_version = float(test_version)
                dab_version_float = float(dab_version)
                if dab_version_float < required_version:
                    test_result.test_result = "OPTIONAL_FAILED"
                    log(test_result, f"\033[1;33m[ OPTIONAL_FAILED - Requires DAB Version {required_version}, but DAB version is {dab_version_float} ]\033[0m")
                    # close section before returning
                    total_ms = int((time.time() - section_wall_start) * 1000)
                    self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                    return test_result
            except Exception as e:
                log(test_result, f"[WARNING] Version comparison failed: {e}")

            # Check operation support via operations/list (prechecker)
            if dab_request_topic != 'operations/list':
                validate_code, prechecker_log = self.dab_checker.is_operation_supported(device_id, dab_request_topic)

                if validate_code == ValidateCode.UNSUPPORT:
                    test_result.test_result = "OPTIONAL_FAILED"
                    log(test_result, prechecker_log)
                    log(test_result, f"\033[1;33m[ OPTIONAL_FAILED - Requires DAB Operation is NOT SUPPORTED ]\033[0m")
                    total_ms = int((time.time() - section_wall_start) * 1000)
                    self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                    return test_result

            # ------------------------------------------------------------------------
            # If precheck is supported and this is not a negative test case
            # Use precheck to determine if operation is supported
            # Optional precheck for non-negative tests
            # ------------------------------------------------------------------------
            if not is_negative:
                validate_code, prechecker_log = self.dab_checker.precheck(device_id, dab_request_topic, dab_request_body)
                if validate_code == ValidateCode.UNSUPPORT:
                    test_result.test_result = "OPTIONAL_FAILED"
                    log(test_result, prechecker_log)
                    log(test_result, f"\033[1;33m[ OPTIONAL_FAILED ]\033[0m")
                    total_ms = int((time.time() - section_wall_start) * 1000)
                    self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                    return test_result
                log(test_result, prechecker_log)

            start = datetime.datetime.now()

            try:
                # Send DAB request via broker
                try:
                    code = self.execute_cmd(device_id, dab_request_topic, dab_request_body)
                    test_result.response = self.dab_client.response()
                except Exception as e:
                    test_result.test_result = "SKIPPED"
                    log(test_result, f"\033[1;34m[ SKIPPED - Internal Error During Execution ]\033[0m {str(e)}")
                    total_ms = int((time.time() - section_wall_start) * 1000)
                    self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                    return test_result

                # If execution succeeded (error code 200)
                if code == 0:
                    end = datetime.datetime.now()
                    durationInMs = int((end - start).total_seconds() * 1000)

                    try:
                        validate_result = validate_output_function(test_result, durationInMs, expected_response)
                        if validate_result == True:
                            validate_result, checker_log = self.dab_checker.check(device_id, dab_request_topic, dab_request_body)
                            if checker_log:
                                log(test_result, checker_log)
                        else:
                            self.dab_checker.end_precheck(device_id, dab_request_topic, dab_request_body)
                    except Exception as e:
                        # If this is a negative test case and validation fails (e.g., 200 response with incorrect behavior),
                        # treat it as PASS because failure was the expected outcome in this scenario.
                        if is_negative:
                            # For negative test: failure is expected — pass the test
                            test_result.test_result = "PASS"
                            log(test_result, f"\033[1;33m[ NEGATIVE TEST PASSED - Exception as Expected ]\033[0m {(e)}")
                            total_ms = int((time.time() - section_wall_start) * 1000)
                            self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                            return test_result
                        else:
                            test_result.test_result = "SKIPPED"
                            log(test_result, f"\033[1;34m[ SKIPPED - Internal Error During Validation ]\033[0m {str(e)}")
                            total_ms = int((time.time() - section_wall_start) * 1000)
                            self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
                            return test_result

                    if validate_result == True:
                        test_result.test_result = "PASS"
                        log(test_result, "\033[1;32m[ PASS ]\033[0m")
                    else:
                        if is_negative:
                            test_result.test_result = "PASS"
                            log(test_result, "\033[1;33m[ NEGATIVE TEST PASSED - Validation Failed as Expected ]\033[0m")
                        else:
                            test_result.test_result = "FAILED"
                            log(test_result, "\033[1;31m[ FAILED ]\033[0m")
                else:
                    # Handle non-200 error codes
                    error_code = self.dab_client.last_error_code()
                    error_msg = self.dab_client.response()

                    if is_negative and error_code in (400, 404):
                        test_result.test_result = "PASS"
                        log(test_result, f"\033[1;33m[ NEGATIVE TEST PASSED - Expected Error Code {error_code} ]\033[0m")
                    elif error_code == 501:
                        # ------------------------------------------------------------------------------
                        # Handle 501 Not Implemented:
                        # If the operation is listed in dab/operations/list but not implemented,
                        # it is treated as a hard failure — this indicates a declared operation
                        # is missing implementation.
                        # If the operation is not listed in the supported list, mark as OPTIONAL_FAILED.
                        # ------------------------------------------------------------------------------
                        # Check if operation is listed in dab/operations/list
                        supported_code, op_check_log = self.dab_checker.is_operation_supported(device_id, dab_request_topic)
                        if supported_code == ValidateCode.SUPPORT:
                            test_result.test_result = "FAILED"
                            log(test_result, op_check_log)
                            log(test_result, f"\033[1;31m[ FAILED - Required DAB operation is NOT IMPLEMENTED (501) ]\033[0m")
                        else:
                            test_result.test_result = "OPTIONAL_FAILED"
                            log(test_result, f"\033[1;33m[ OPTIONAL_FAILED - Operation may not be mandatory, received 501 ]\033[0m")

                    elif error_code == 500:
                        # 500 Internal Server Error: Indicates a crash or failure not caused by the test itself.
                        # Marked as SKIPPED to avoid counting it as a hard failure.
                        test_result.test_result = "SKIPPED"
                        log(test_result, f"\033[1;34m[ SKIPPED - Internal Error Code {error_code} ]\033[0m {error_msg}")
                    else:
                        # All other non-zero error codes indicate test failure.
                        test_result.test_result = "FAILED"
                        log(test_result, "\033[1;31m[ COMMAND FAILED ]\033[0m")
                        log(test_result, f"Error Code: {error_code}")
                    self.dab_client.last_error_msg()

            except Exception as e:
                test_result.test_result = "SKIPPED"
                log(test_result, f"\033[1;34m[ SKIPPED - Internal Error ]\033[0m {str(e)}")

            if self.verbose and test_result.test_result != "SKIPPED":
                log(test_result, test_result.response)

            # ---------- close the test section ----------
            total_ms = int((time.time() - section_wall_start) * 1000)
            self.logger.test_end(outcome=test_result.test_result, duration_ms=total_ms)
            # --------------------------------------------------------

            return test_result

        finally:
            # Always try to go back Home after the test, regardless of outcome/early return/exception.
            try:
                self.return_to_home_after_test(device_id)
            except Exception:
                # best-effort cleanup; never let this affect runner flow
                pass

    def Execute_Functional_Tests(self, device_id, functional_tests, test_result_output_path=""):
        """
        Functional runner that mirrors conformance preflight:
        - For EACH test: run discovery + health-check (via _preflight_before_each_test_or_raise)
        - If preflight fails once, mark current + remaining as SKIPPED and stop.
        """
        result_list = []
        terminated_run = False

        for idx, test_case in enumerate(functional_tests, 1):
            try:
                dab_topic, test_category, test_func, test_name, *_ = test_case
            except Exception:
                dab_topic, test_category, test_func, test_name = ("unknown/topic", "functional", None, "Unknown")

            try:
                self._preflight_before_each_test_or_raise(device_id)
            except PreflightTermination:
                # Mark THIS test as skipped
                test_id = to_test_id(f"{dab_topic}/{test_category}")
                result_list.append(
                    TestResult(
                        test_id, device_id, dab_topic, "{}", "SKIPPED", "",
                        ["Preflight failed (discovery/health). Skipping this and remaining functional tests."]
                    )
                )
                # Mark REMAINING tests as skipped too
                for remaining in functional_tests[idx:]:
                    try:
                        r_topic, r_category, *_ = remaining
                    except Exception:
                        r_topic, r_category = ("unknown/topic", "functional")
                    r_test_id = to_test_id(f"{r_topic}/{r_category}")
                    result_list.append(
                        TestResult(
                            r_test_id, device_id, r_topic, "{}", "SKIPPED", "",
                            ["Run terminated during preflight. Remaining functional tests skipped."]
                        )
                    )
                terminated_run = True
                break  # stop executing further tests

            # Preflight OK → run the functional test
            try:
                if callable(test_func):
                    result = None
                    try:
                        result = test_func(dab_topic, test_category, test_name, self, device_id)
                        result_list.append(result)
                    finally:
                        # Always return to Home after each test
                        try:
                            self.return_to_home_after_test(device_id)
                        except Exception:
                            # Don't let cleanup interfere with the run
                            pass
                else:
                    # Not callable — record as SKIPPED but keep going
                    bad_id = to_test_id(f"{dab_topic}/{test_category}")
                    bad_result = TestResult(
                        bad_id, device_id, dab_topic, "{}", "SKIPPED", "",
                        ["Invalid functional test function: not callable."]
                    )
                    result_list.append(bad_result)
                    # Still try to return Home for consistency
                    try:
                        self.return_to_home_after_test(device_id)
                    except Exception:
                        pass

            except Exception as e:
                self.logger.error(f"Functional test execution failed: {e}")
                # Even on runner-level exceptions, still try returning Home
                try:
                    self.return_to_home_after_test(device_id)
                except Exception:
                    pass

        if not test_result_output_path:
            test_result_output_path = "./test_result/functional_result.json"

        device_info = self.get_device_info(device_id)
        self.write_test_result_json("functional", result_list, test_result_output_path, device_info=device_info)

        if terminated_run and self.verbose:
            self.logger.info("Functional test run ended early. Results file is written.")


    # -----------------------------
    # Conformance (suite) runner
    # -----------------------------
    def Execute_All_Tests(self, suite_name, device_id, Test_Set, test_result_output_path):
        if not self.dab_version:
            self.detect_dab_version(device_id)

        if suite_name == "functional":
            self.Execute_Functional_Tests(device_id, Test_Set, test_result_output_path)
            return
        
        # show total tests once (always as RESULT)
        total_tests = len(Test_Set)
        self.logger.result(f"Starting {suite_name} suite with {total_tests} tests.")

        result_list = TestSuite([], suite_name)
        try:
            # enumerate to print progress before each test
            for idx, test in enumerate(Test_Set, start=1):
                try:
                    topic, _body, _func, _expected, title, _is_negative, _ver = self.unpack_test_case(test)
                    if topic and title:
                        self.logger.result(f"{suite_name} progress {idx}/{total_tests}: {title} on topic '{topic}'.")
                    else:
                        self.logger.result(f"{suite_name} progress {idx}/{total_tests}: (test case not resolved).")
                except Exception:
                    self.logger.result(f"{suite_name} progress {idx}/{total_tests}: (test case not resolved).")

                r = self.Execute(device_id, test)  # may raise PreflightTermination
                if r:
                    result_list.test_result_list.append(r)
        except PreflightTermination:
            self.logger.warn("The run was terminated during the preflight stage. Writing partial results and stopping.")

        if (len(test_result_output_path) == 0):
            test_result_output_path = f"./test_result/{suite_name}.json"
        device_info = self.get_device_info(device_id)
        self.write_test_result_json(suite_name, result_list.test_result_list, test_result_output_path, device_info = device_info)

    # -----------------------------
    # Single test runner
    # -----------------------------
    def Execute_Single_Test(self, suite_name, device_id, test_case_or_cases, test_result_output_path=""):
        if not self.dab_version:
            self.detect_dab_version(device_id)

        if suite_name == "functional":
            self.Execute_Functional_Tests(device_id, test_case_or_cases, test_result_output_path)
            return

        result_list = TestSuite([], suite_name)
        try:
            if isinstance(test_case_or_cases, list):
                for test_case in test_case_or_cases:
                    result = self.Execute(device_id, test_case)  # may raise PreflightTermination
                    if result:
                        result_list.test_result_list.append(result)
            else:
                result = self.Execute(device_id, test_case_or_cases)  # may raise PreflightTermination
                if result:
                    result_list.test_result_list.append(result)
        except PreflightTermination:
            self.logger.warn("The run was terminated during the preflight stage. Writing partial results and stopping.")

        if len(test_result_output_path) == 0:
            test_result_output_path = f"./test_result/{suite_name}_single.json"
        device_info = self.get_device_info(device_id)
        self.write_test_result_json(suite_name, result_list.test_result_list, test_result_output_path, device_info = device_info)

    # -----------------------------
    # JSON writer & utilities
    # -----------------------------
    def write_test_result_json(self, suite_name, result_list, output_path="", device_info=None):
        """
        Serialize and write the test results to a JSON file in a structured format.

        Args:
            suite_name (str): The name of the test suite executed.
            result_list (list): List of TestResult objects containing individual test outcomes.
            output_path (str): The file path where the JSON output should be saved.
            This function computes a result summary, validates the result content,
            and writes a detailed structured JSON with summary and test details.
        """
        if not output_path:
            output_path = f"./test_result/{suite_name}.json"
        # Filter valid test results
        valid_results = []
        for result in result_list:
            required_fields = ["test_id", "device_id", "operation", "request", "test_result"]
            if all(hasattr(result, field) and getattr(result, field) is not None for field in required_fields):
                valid_results.append(result)
            else:
                self.logger.warn(f"An incomplete test result was skipped in the JSON writer: {result}")

        total_tests = len(result_list)
        passed = sum(1 for t in result_list if getattr(t, "test_result", "") == "PASS")
        failed = sum(1 for t in result_list if getattr(t, "test_result", "") == "FAILED")
        optional_failed = sum(1 for t in result_list if getattr(t, "test_result", "") == "OPTIONAL_FAILED")
        skipped = sum(1 for t in result_list if getattr(t, "test_result", "") == "SKIPPED")
        self.clean_result_fields(valid_results, fields_to_clean=["logs", "request", "response"])
        result_data = {
            "test_version": get_test_tool_version(),
            "suite_name": suite_name,
            "device_info": device_info if device_info else {},
            "result_summary": {
                "tests_executed": total_tests,
                "tests_passed": passed,
                "tests_failed": failed,
                "tests_optional_failed": optional_failed,
                "tests_skipped": skipped,
                "overall_passed": failed == 0 and skipped == 0
            },
            "test_result_list": result_list
        }
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                # Beautify using jsons and indent=4 passed through jdkwargs
                f.write(jsons.dumps(result_data, jdkwargs={"indent": 4}))
            self.logger.ok(f"Saved the results JSON at {os.path.abspath(output_path)}.")
            return os.path.abspath(output_path)

        except (OSError, PermissionError, FileNotFoundError, TypeError) as e:
            # Catch only expected serialization or file write errors
            self.logger.error(f"Could not write the results JSON to '{output_path}'. Reason: {e}")
            return ""

    def unpack_test_case(self, test_case):
        def fail(reason):
            self.logger.warn(f"Invalid test case: {reason}. This case will be skipped. Case: {test_case}")
            return (None,) * 7  # Expected structure length

        if isinstance(test_case, tuple) and len(test_case) >= 3:
            if test_case[1] == "functional" and callable(test_case[2]):
                # Functional test detected
                topic = test_case[0]
                body_str = "{}"  # No fixed payload required
                func = test_case[2]
                title = test_case[3] if len(test_case) > 3 else "FunctionalTest"
                test_version = str(test_case[4]) if len(test_case) > 4 else "2.0"
                is_negative = bool(test_case[5]) if len(test_case) > 5 else False
                expected = 0  # Expected not used but kept for tuple shape

                return topic, body_str, func, expected, title, is_negative, test_version

        # Validate input type
        if not isinstance(test_case, tuple):
            return fail("Test case is not a tuple")

        if len(test_case) not in (5, 6, 7):
            return fail(f"Expected 5, 6, or 7 elements, got {len(test_case)}")

        try:
            # Unpack mandatory components
            topic, body_str, func, expected, title = test_case[:5]

            # Defaults
            test_version = "2.0"
            is_negative = False

            # logic: test_version is always the 6th, is_negative is 7th
            if len(test_case) >= 6:
                test_version = str(test_case[5])
            if len(test_case) == 7:
                is_negative = bool(test_case[6])

            # Handle body string evaluation if it's a lambda
            if callable(body_str):
                try:
                    body_str = body_str()
                except KeyError as e:
                    return fail(f"Missing config key: {e}")

            # Validations
            if body_str is not None and not isinstance(body_str, str):
                return fail("Body must be a string or None")
            if not isinstance(topic, str) or not topic.strip():
                return fail("Invalid or empty topic")
            if topic not in self.valid_dab_topics:
                return fail(f"Unknown or unsupported DAB topic: {topic}")
            # Validate function
            if not callable(func):
                return fail("Validator function is not callable")
            # Validate expected response
            if not ((isinstance(expected, int) and expected >= 0) or (isinstance(expected, str) and expected.strip())):
                return fail("Expected must be a non-negative int or non-empty string")
            # Validate test title
            if not isinstance(title, str) or not title.strip():
                return fail("Invalid or empty title")

            return topic, body_str, func, expected, title, is_negative, test_version

        except Exception as e:
            return fail(f"Unexpected error: {str(e)}")

    def detect_dab_version(self, device_id):
        """
        Detects DAB version by calling 'dab/version' once.
        Stores version string in self.dab_version.
        Honors override_dab_version if explicitly provided.
        """
        if hasattr(self, 'override_dab_version') and self.override_dab_version:
            self.dab_version = self.override_dab_version
            self.logger.info(f"Using the forced DAB version override: {self.dab_version}.")
            return
        try:
            self.dab_client.request(device_id, "version", "{}")
            response = self.dab_client.response()

            if response:
                resp_json = json.loads(response)
                self.dab_version = resp_json.get("DAB Version", "2.0")
                self.logger.info(f"DAB version detected: {self.dab_version}.")
            else:
                self.logger.warn("The DAB version check returned an empty response. Defaulting to 2.0.")
                self.dab_version = "2.0"

        except Exception as e:
            self.logger.error(f"Could not detect the DAB version due to an error: {e}. Defaulting to 2.0.")
            self.dab_version = "2.0"

    def get_device_info(self, device_id):
        try:
            self.dab_client.request(device_id, "device/info", "{}")
            response = self.dab_client.response()
            if response:
                device_info = json.loads(response)

                # Extract only the required fields
                filtered_info = {
                    'manufacturer': device_info.get('manufacturer'),
                    'model': device_info.get('model'),
                    'serialNumber': device_info.get('serialNumber'),
                    'chipset': device_info.get('chipset'),
                    'firmwareVersion': device_info.get('firmwareVersion'),
                    'firmwareBuild': device_info.get('firmwareBuild'),
                    'deviceId': device_info.get('deviceId')
                }
                return filtered_info
        except Exception as e:
            self.logger.error(f"Could not fetch the device info from 'dab/{device_id}/device/info'. Reason: {e}")
        return {}

    def clean_result_fields(self, result_list, fields_to_clean=["logs", "request", "response"]):
        """
        Clean specified fields before JSON dump:
        - Remove ANSI color codes
        - Decode escaped sequences
        - Remove surrounding quotes
        - Normalize multiline strings into clean lines
        """
        ansi_pattern = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')
        for result in result_list:
            for field in fields_to_clean:
                if not hasattr(result, field):
                    continue
                raw_value = getattr(result, field)
                # Normalize to list of lines
                if isinstance(raw_value, list):
                    lines = raw_value
                else:
                    try:
                        decoded = bytes(str(raw_value), "utf-8").decode("unicode_escape")
                    except Exception:
                        decoded = str(raw_value)
                    lines = decoded.splitlines()
                # Clean each line
                cleaned_lines = []
                for line in lines:
                    line = ansi_pattern.sub('', line)
                    line = line.replace('"', '').replace("'", '')
                    line = line.strip()
                    if line:
                        cleaned_lines.append(line)
                setattr(result, field, cleaned_lines)
        return result_list

    def assert_device_available(self, device_id: str, fatal: bool = True) -> bool:
        """Ensure `device_id` is reachable via discovery (no health-check fallback)."""
        self.logger.info("Preflight: discovering devices to confirm the target is online.")
        try:
            devices = self.dab_client.discover_devices() or []
        except Exception as e:
            self.logger.warn(f"Discovery did not complete due to an error: {e}")
            devices = []

        if devices:
            target_ip = None
            pairs = []
            for d in devices:
                did = d.get("deviceId") or d.get("device_id")
                ip  = d.get("ip") or d.get("ipAddress") or "n/a"
                if did:
                    pairs.append(f"{did}:{ip}")
                    if did == device_id:
                        target_ip = ip
            self.logger.info(f"Discovered devices: {', '.join(pairs)}")

            if not target_ip:
                self.logger.fatal(f"The target device '{device_id}' was not found in discovery.")
                if fatal:
                    self.Close(); sys_exit(3)
                return False

            self.logger.ok(f"The target device '{device_id}' is reachable at {target_ip}.")
            return True

        # If we reach here, discovery returned no devices; do NOT fall back to health-check.
        self.logger.fatal("No devices were discovered, so the device availability cannot be verified.")
        if fatal:
            try:
                self.Close()
            except AttributeError:
                try:
                    self.dab_client.disconnect()
                except Exception:
                    pass
            sys_exit(4)
        return False
    
    def return_to_home_after_test(self, device_id, logs=None, delay=0.5):
        """
        Best-effort: send KEY_HOME once so the next test starts from Home.
        Swallows errors; adds a short log line if provided.
        """
        try:
            self.execute_cmd(device_id, "input/key-press", json.dumps({"keyCode": "KEY_HOME"}))
            _ = self.dab_client.response()  # drain response if any
            time.sleep(delay)
            if logs is not None:
                logs.append("[INFO] Post-test: sent KEY_HOME.")
        except Exception:
            if logs is not None:
                logs.append("[WARN] Post-test KEY_HOME failed (ignored).")

    def Close(self):
        self.dab_client.disconnect()


def Default_Validations(test_result, durationInMs=0, expectedLatencyMs=0):
    sleep(0.2)
    log(test_result, f"\n{test_result.operation} Latency, Expected: {expectedLatencyMs} ms, Actual: {durationInMs} ms\n")
    if durationInMs > expectedLatencyMs:
        log(test_result, f"{test_result.operation} took more time than expected.\n")
        return False
    return True

def get_test_tool_version():
    try:
        with open("test_version.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev.000000"

def log(test_result, str_print):
    """
    Normalizes any incoming text (even if it has leading/trailing newlines),
    prints each non-empty line via the unified LOGGER with a timestamp,
    and stores the stamped line into test_result.logs.
    """
    s = str(str_print).replace("\r\n", "\n")
    for raw in s.split("\n"):
        line = raw.strip()
        if not line:
            continue 
        LOGGER.result(line)                  # console with timestamp
        test_result.logs.append(LOGGER.stamp(line))  # persist stamped line

def YesNoQuestion(test_result, question=""):
    positive = ['yes', 'y']
    negative = ['no', 'n']

    # ANSI colors
    GREEN = "\x1b[32m"
    RED   = "\x1b[31m"
    CYAN  = "\x1b[36m"
    YELL  = "\x1b[33m"
    RESET = "\x1b[0m"

    while True:
        # Show the prompt with colors: question in cyan, Y in green, N in red
        colored_prompt = f"{CYAN}{question}{RESET} ({GREEN}Y{RESET}/{RED}N{RESET})"
        # ensure prompt appears on a new line even if the previous print used end=''
        log(test_result, colored_prompt)
        user_input = readchar()
        lower = user_input.lower()
        if lower in positive:
            log(test_result, f"{GREEN}[{user_input}]{RESET}")
            return True
        elif lower in negative:
            log(test_result, f"{RED}[{user_input}]{RESET}")
            return False
        else:
            log(test_result, f"{YELL}[{user_input}] Please press Y or N.{RESET}")
            continue

def to_test_id(input_string):
    return ''.join(item.title() for item in split('([^a-zA-Z0-9])', input_string) if item.isalnum())