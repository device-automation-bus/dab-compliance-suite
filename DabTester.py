from DabClient import DabClient

class DabTester:
    def __init__(self):
        self.dab_test_client = DabClient()
        self.dab_test_client.connect("localhost",1883)
        self.verbose = False

    def execute_cmd(self,operation,request="{}"):
        self.dab_test_client.request(operation,request)
        try:
            if self.dab_test_client.response['status'] == 200:
                return 0
            else:
                return 1
        except:
            self.dab_test_client.response['status'] = -1 # unknown error
            return 1
    
    def Test_Case(self,operation,request):
        if self.execute_cmd(operation,request) == 0:
            print("[ OK ] ",end='')
            print(operation)
        else:
            print('[ ',end='')
            self.dab_test_client.print_last_error()
            print(' ] ',operation,end='')
            print(operation)
            if self.verbose == True:
                self.dab_test_client.print_response()

    def Run_All(self,Test_Set):
        for operation in Test_Set:
            self.Test_Case(operation[0],operation[1])

    def Close(self):
        self.dab_test_client.disconnect()