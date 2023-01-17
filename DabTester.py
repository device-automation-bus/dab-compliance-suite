from DabClient import DabClient
from time import sleep
from readchar import readchar

class DabTester:
    def __init__(self):
        self.dab_client = DabClient()
        self.dab_client.connect("localhost",1883)
        self.verbose = False

    def execute_cmd(self,operation,request="{}"):
        self.dab_client.request(operation,request)
        try:
            if self.code == 200:
                return 0
            else:
                return 1
        except:
            self.code = -1 # unknown error
            return 1
    
    def Test_Case(self,test_case):
        (operation,request,extra_function)=test_case
        print("testing",operation,"... ",end='', flush=True)
        if self.execute_cmd(operation,request) == 0:
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

    def Test_All(self,Test_Set):
        for operation in Test_Set:
            self.Test_Case(operation)

    def Close(self):
        self.dab_client.disconnect()
        
def Default_Test():
    sleep(1)
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