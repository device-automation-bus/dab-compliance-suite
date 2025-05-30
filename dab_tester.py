from dab_client import DabClient
from dab_checker import DabChecker
from result_json import TestResult, TestSuite
from time import sleep
from readchar import readchar
from re import split
import datetime
import jsons
import os
import signal

class DabTester:
    def __init__(self,broker):
        self.dab_client = DabClient()
        self.dab_client.connect(broker,1883)
        self.dab_checker = DabChecker(self)
        self.verbose = False

    def execute_cmd(self,device_id,dab_request_topic,dab_request_body="{}"):
        self.dab_client.request(device_id,dab_request_topic,dab_request_body)
        if self.dab_client.last_error_code() == 200:
            return 0
        else:
            return 1
    
    def Execute(self, device_id, test_case):
        (dab_request_topic, dab_request_body, validate_output_function, expected_response, test_title)=test_case
        test_result = TestResult(to_test_id(f"{dab_request_topic}/{test_title}"), device_id, dab_request_topic, dab_request_body, "UNKNOWN", "", [])
        print("\ntesting", dab_request_topic, " ", dab_request_body, "... ", end='', flush=True)
        start = datetime.datetime.now()
        code = self.execute_cmd(device_id, dab_request_topic, dab_request_body)
        test_result.response = self.dab_client.response()
        if  code == 0:
            end = datetime.datetime.now()
            duration = end - start
            durationInMs = int(duration.total_seconds() * 1000)
            exception = None
            try:
                validate_result = validate_output_function(test_result, durationInMs, expected_response)
                if validate_result == True:
                    validate_result, checker_log = self.dab_checker.check(device_id, dab_request_topic, dab_request_body)
                    if checker_log:
                        log(test_result, checker_log)
            except Exception as e:
                validate_result = False
                exception = e
            
            if validate_result == True:
                log(test_result, "\033[1;32m[ PASS ]\033[0m")
                test_result.test_result = "PASS"
            else:
                log(test_result, "\033[1;31m[ FAILED ]\033[0m")
                if exception:
                    log(test_result, f"{type(exception).__name__} raised during result validation:\n\033[0;31m{exception}\033[0m\n")
                test_result.test_result = "FAILED"
        else:
            log(test_result, '\033[1;31m[ ')
            log(test_result, f"Error: self.dab_client.last_error_code()")
            self.dab_client.last_error_msg()
            log(test_result, ' ]\033[0m')
        if ((self.verbose == True)):
            #log(test_result, self.dab_client.response())
            log(test_result, test_result.response)
        return test_result

    def Execute_All_Tests(self, suite_name, device_id, Test_Set, test_result_output_path):
        result_list = TestSuite([], suite_name)
        for test in Test_Set:
            result_list.test_result_list.append(self.Execute(device_id, test))
            #sleep(5)
        if (len(test_result_output_path) == 0):
            test_result_output_path = f"./test_result/{suite_name}.json"      
        # Construct the output including test_version
        output = {
            "test_version": get_test_tool_version(),
            "suite_name": suite_name,
            "test_result_list": result_list.test_result_list
        }
        file_dump = jsons.dumps(output, indent=4)
        with open(test_result_output_path, "w") as outfile:
            outfile.write(file_dump)
            print(f"Results path: {test_result_output_path}")

    def Execute_Single_Test(self, suite_name, device_id, test_case, test_result_output_path=""):
        result = self.Execute(device_id, test_case)
        result_list = TestSuite([], suite_name)
        result_list.test_result_list.append(result)
        if len(test_result_output_path) == 0:
            test_result_output_path = f"./test_result/{suite_name}_single.json"
        output = {
            "test_version": get_test_tool_version(),
            "suite_name": suite_name,
            "test_result_list": result_list.test_result_list
        }
        file_dump = jsons.dumps(output, indent=4)
        with open(test_result_output_path, "w") as outfile:
            outfile.write(file_dump)
            print(f"Result path: {test_result_output_path}")

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
        elif user_input == '\x03':
            os.kill(os.getpid(), signal.SIGINT)
        elif user_input == '\x04':
            os.kill(os.getpid(), signal.SIGQUIT)
        elif user_input == '\x1a':
            os.kill(os.getpid(), signal.SIGTSTP)
        else:
            continue

def to_test_id(input_string):
    return ''.join(item.title() for item in split('([^a-zA-Z0-9])', input_string) if item.isalnum())