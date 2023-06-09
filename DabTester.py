from DabClient import DabClient
from result_json import TestOutcome, TestSuite
from time import sleep
from readchar import readchar
import datetime
import jsons

class DabTester:
    def __init__(self,broker):
        self.dab_client = DabClient()
        self.dab_client.connect(broker,1883)
        self.verbose = False

    def execute_cmd(self,device_id,operation,request="{}"):
        self.dab_client.request(device_id,operation,request)
        if self.dab_client.last_error_code() == 200:
            return 0
        else:
            return 1
    
    def Test_Case(self, device_id, test_case):
        (operation, request, extra_function, params)=test_case
        test_outcome = TestOutcome(device_id, operation, request, "unknwon", "")
        print("\ntesting", operation, " ", request, "... ", end='', flush=True)
        start = datetime.datetime.now()
        if self.execute_cmd(device_id, operation, request) == 0:
            end = datetime.datetime.now()
            duration = end - start
            durationInMs = int(duration.total_seconds() * 1000)
            if extra_function(durationInMs, params) == True:
                print("\033[1;32m[ PASS ]\033[0m")
                test_outcome.outcome = "PASS"
            else:
                print("\033[1;31m[ FAILED ]\033[0m")
                test_outcome.outcome = "FAILED"
        else:
            print('\033[1;31m[ ',end='')
            print("Error",self.dab_client.last_error_code(),': ',end='')
            self.dab_client.last_error_msg()
            print(' ]\033[0m')
        if ((self.verbose == True)):
            print(self.dab_client.response())
            test_outcome.response = self.dab_client.response()
        return test_outcome

    def Test_All(self, suite_name, device_id, Test_Set, file_path):
        result_list = TestSuite([], suite_name)
        for operation in Test_Set:
            result_list.test_outcome_list.append(self.Test_Case(device_id, operation))
            sleep(5)
        if (len(file_path) == 0):
            file_path = f"./test_result/{suite_name}.json"
        file_dump = jsons.dumps(result_list, indent = 4)
        with open(file_path, "w") as outfile:
                outfile.write(file_dump)


    def Close(self):
        self.dab_client.disconnect()
        
def Default_Test(durationInMs=0, expectedLatencyMs=0):
    sleep(0.2)
    print("\nOperation Latency, Expected: ", expectedLatencyMs, " ms, Actual: ", durationInMs, " ms\n")
    if durationInMs > expectedLatencyMs:
        print("Operation took more time than expected.\n")
        return False
    return True

def Voice_Test(durationInMs=0, args=''):
    sleep(5)
    return YesNoQuestion(args)

def YesNoQuestion(question=""):
    positive = ['yes', 'y']
    negative = ['no', 'n']

    while True:
        # user_input = input(question+'(Y/N): ')
        print(question,'(Y/N): ',end='', flush=True)
        user_input=readchar()
        print(' ['+user_input+'] ',end='')
        if user_input.lower() in positive:
            return True
        elif user_input.lower() in negative:
            return False
        else:
            continue