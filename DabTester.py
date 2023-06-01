from DabClient import DabClient
from time import sleep
from readchar import readchar

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
    
    def Test_Case(self,device_id,test_case):
        (operation,request,extra_function)=test_case
        print("testing",operation,"... ",end='', flush=True)
        if self.execute_cmd(device_id, operation,request) == 0:
            if extra_function() == True:
                print("\033[1;32m[ PASS ]\033[0m")
            else:
                print("\033[1;31m[ FAILED ]\033[0m")
        else:
            print('\033[1;31m[ ',end='')
            print("Error",self.dab_client.last_error_code(),': ',end='')
            self.dab_client.last_error_msg()
            print(' ]\033[0m')
        if ((self.verbose == True)):
            print(self.dab_client.response())

    def Test_All(self,device_id,Test_Set):
        for operation in Test_Set:
            self.Test_Case(device_id,operation)
            sleep(5)

    def Close(self):
        self.dab_client.disconnect()
        
def Default_Test():
    sleep(0.2)
    return True

def Voice_Test():
    sleep(5)
    return True

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