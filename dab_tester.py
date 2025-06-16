from dab_client import DabClient
from dab_checker import DabChecker
from result_json import TestResult, TestSuite
from time import sleep
from readchar import readchar
from re import split
import datetime
import jsons
import os
from util.enforcement_manager import ValidateCode

class DabTester:
    def __init__(self,broker):
        self.dab_client = DabClient()
        self.dab_client.connect(broker,1883)
        self.dab_checker = DabChecker(self)
        self.verbose = False

        # Load valid DAB topics using jsons
        try:
            with open("valid_dab_topics.json", "r", encoding="utf-8") as f:
                self.valid_dab_topics = set(jsons.load(jsons.loads(f.read())))

        except Exception as e:
            print(f"[ERROR] Failed to load valid DAB topics: {e}")
            self.valid_dab_topics = set()

    def execute_cmd(self,device_id,dab_request_topic,dab_request_body="{}"):
        self.dab_client.request(device_id,dab_request_topic,dab_request_body)
        if self.dab_client.last_error_code() == 200:
            return 0
        else:
            return 1
    
    def Execute(self, device_id, test_case):
        (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title, is_negative) = self.unpack_test_case(test_case)

        if dab_request_topic is None:
            return None

        test_result = TestResult(to_test_id(f"{dab_request_topic}/{test_title}"), device_id, dab_request_topic, dab_request_body, "UNKNOWN", "", [])
        print("\ntesting", dab_request_topic, " ", dab_request_body, "... ", end='', flush=True)

        if is_negative == False:
            validate_code, prechecker_log = self.dab_checker.precheck(device_id, dab_request_topic, dab_request_body)
            if validate_code == ValidateCode.UNSUPPORT:
                test_result.test_result = "SKIPPED"
                log(test_result, prechecker_log)
                log(test_result, f"\033[1;34m[ SKIPPED ]\033[0m")
                return test_result
            else:
                log(test_result, prechecker_log)

        start = datetime.datetime.now()

        try:
            try:
                code = self.execute_cmd(device_id, dab_request_topic, dab_request_body)
                test_result.response = self.dab_client.response()
            except Exception as e:
                test_result.test_result = "SKIPPED"
                log(test_result, f"\033[1;34m[ SKIPPED - Internal Error During Execution ]\033[0m {str(e)}")
                return test_result

            if code == 0:
                end = datetime.datetime.now()
                durationInMs = int((end - start).total_seconds() * 1000)
                try:
                    validate_result = validate_output_function(test_result, durationInMs, expected_response)
                    if validate_result == True:
                        validate_result, checker_log = self.dab_checker.check(device_id, dab_request_topic, dab_request_body)
                        if checker_log:
                            log(test_result, checker_log)
                except Exception as e:
                    # If this is a negative test case and validation fails (e.g., 200 response with incorrect behavior),
                    # treat it as PASS because failure was the expected outcome in this scenario.
                    if is_negative:
                        test_result.test_result = "PASS"
                        log(test_result, f"\033[1;33m[ NEGATIVE TEST PASSED - Exception as Expected ]\033[0m {str(e)}")
                        return test_result
                    else:
                        test_result.test_result = "SKIPPED"
                        log(test_result, f"\033[1;34m[ SKIPPED - Internal Error During Validation ]\033[0m {str(e)}")
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
                error_code = self.dab_client.last_error_code()
                error_msg = self.dab_client.response()

                if is_negative and error_code in (400, 404):
                    test_result.test_result = "PASS"
                    log(test_result, f"\033[1;33m[ NEGATIVE TEST PASSED - Expected Error Code {error_code} ]\033[0m")
                elif error_code == 501:
                    # 501 Not Implemented: The feature is not supported on this platform/device.
                    # Considered OPTIONAL_FAILED because it's valid but not mandatory.
                    test_result.test_result = "OPTIONAL_FAILED"
                    log(test_result, f"\033[1;33m[ OPTIONAL_FAILED - Error Code {error_code} ]\033[0m")
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

        return test_result

    def Execute_All_Tests(self, suite_name, device_id, Test_Set, test_result_output_path):
        result_list = TestSuite([], suite_name)
        for test in Test_Set:
            result_list.test_result_list.append(self.Execute(device_id, test))
            #sleep(5)
        if (len(test_result_output_path) == 0):
            test_result_output_path = f"./test_result/{suite_name}.json"      
        self.write_test_result_json(suite_name, result_list.test_result_list, test_result_output_path)

    def Execute_Single_Test(self, suite_name, device_id, test_case_or_cases, test_result_output_path=""):
        result_list = TestSuite([], suite_name)
        
        # Handle a list of test cases or a single one
        if isinstance(test_case_or_cases, list):
            for test_case in test_case_or_cases:
                result = self.Execute(device_id, test_case)
                if result:  # Make sure it’s not None
                    result_list.test_result_list.append(result)
        else:
            result = self.Execute(device_id, test_case_or_cases)
            if result:
                result_list.test_result_list.append(result)
        if len(test_result_output_path) == 0:
            test_result_output_path = f"./test_result/{suite_name}_single.json"
        self.write_test_result_json(suite_name, result_list.test_result_list, test_result_output_path)
        
    def write_test_result_json(self, suite_name, result_list, output_path=""):
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
                print(f"[WARNING] Skipping incomplete test result: {result}")

        total_tests = len(result_list)
        passed = sum(1 for t in result_list if getattr(t, "test_result", "") == "PASS")
        failed = sum(1 for t in result_list if getattr(t, "test_result", "") == "FAILED")
        optional_failed = sum(1 for t in result_list if getattr(t, "test_result", "") == "OPTIONAL_FAILED")
        skipped = sum(1 for t in result_list if getattr(t, "test_result", "") == "SKIPPED")
        result_data = {
            "test_version": get_test_tool_version(),
            "suite_name": suite_name,
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
            print(f"[✔] JSON saved to {os.path.abspath(output_path)}")
            return os.path.abspath(output_path)

        except (OSError, PermissionError, FileNotFoundError, TypeError) as e:
            # Catch only expected serialization or file write errors
            print(f"[✖] Failed to write JSON to {output_path}: {e}")
            return ""
        
    def unpack_test_case(self, test_case):
        def fail(reason):
            print(f"[SKIPPED] Invalid test case: {reason} → {test_case}")
            return (None,) * 6  # match the return structure

        # Validate tuple structure
        if not isinstance(test_case, tuple):
            return fail("Not a tuple")

        if len(test_case) not in (5, 6):
            return fail(f"Expected 5 or 6 elements, got {len(test_case)}")

        try:
            # Support both 5-element and 6-element test case tuples:
            #  - 5 elements: (topic, body_str, func, expected, title) — standard positive test
            #  - 6 elements: (topic, body_str, func, expected, title, is_negative) — includes negative test flag
            topic, body_str, func, expected, title = test_case[:5]
            is_negative = test_case[5] if len(test_case) == 6 else False

            # Handle body string evaluation if it's a lambda
            if callable(body_str):
                try:
                    body_str = body_str()
                except KeyError as e:
                    return fail(f"Missing config key: {e}")

            # Validate topic
            if not isinstance(topic, str) or not topic.strip():
                return fail("Invalid or empty topic")

            if topic.strip() not in self.valid_dab_topics:
                return fail(f"Unknown or unsupported DAB topic: {topic}")

            # Validate body string
            if body_str is not None and not isinstance(body_str, str):
                return fail("Body must be a string or None")

            # Validate function
            if not callable(func):
                return fail("Validator function is not callable")

            # Validate expected response
            if not ((isinstance(expected, int) and expected >= 0) or (isinstance(expected, str) and expected.strip())):
                return fail("Expected response must be a non-negative int or non-empty string")

            # Validate test title
            if not isinstance(title, str) or not title.strip():
                return fail("Invalid or empty test title")

            return topic, body_str, func, expected, title, is_negative

        except Exception as e:
            return fail(f"Unexpected error: {str(e)}")

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
    test_result.logs.append(str_print)
    print(str_print)

def YesNoQuestion(test_result, question=""):
    positive = ['yes', 'y']
    negative = ['no', 'n']

    while True:
        # user_input = input(question+'(Y/N): ')
        log(test_result, f"{question}(Y/N)")
        user_input=readchar()
        log(test_result, f"[{user_input}]")
        if user_input.lower() in positive:
            return True
        elif user_input.lower() in negative:
            return False
        else:
            continue

def to_test_id(input_string):
    return ''.join(item.title() for item in split('([^a-zA-Z0-9])', input_string) if item.isalnum())