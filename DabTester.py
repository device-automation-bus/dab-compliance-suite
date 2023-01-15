from DabClient import DabClient
from time import sleep

class DabTester:
    def __init__(self):
        self.dab_client = DabClient()
        self.dab_client.connect("localhost",1883)
        self.verbose = False

    def execute_cmd(self,operation,request="{}"):
        self.dab_client.request(operation,request)
        try:
            if self.dab_client.response['status'] == 200:
                return 0
            else:
                return 1
        except:
            self.dab_client.response['status'] = -1 # unknown error
            return 1
    
    def Test_Case(self,operation,request,extra_function):
        if self.execute_cmd(operation,request) == 0:
            if extra_function() == True:
                print("[ PASS ] ",end='')
            else:
                print("[ FAILED ] ",end='')
            print(operation)
        else:
            print('[ ',end='')
            self.dab_client.print_last_error()
            print(' ] ',operation)
        if ((self.verbose == True)):
            self.dab_client.print_response()

    def Test_All(self,Test_Set):
        for operation in Test_Set:
            self.Test_Case(operation[0],operation[1],operation[2])

    def Close(self):
        self.dab_client.disconnect()
        
def Default_Test():
    sleep(1)

def YesNoQuestion(question=""):
    positive = ['yes', 'y']
    negative = ['no', 'n']

    while True:
        user_input = input(question+'(Y/N): ')
        if user_input.lower() in positive:
            return True
        elif user_input.lower() in negative:
            return False
        else:
            print('Type yes(Y) or no(N)')
            continue
