from DabClient import DabClient

class DabTester:
    def __init__(self):
        self.dab_test_client = DabClient()
        self.dab_test_client.connect("localhost",1883)

    def execute_cmd(self,operation,request="{}"):
        self.dab_test_client.request(operation,request)
        if self.dab_test_client.response['status'] == 200:
            print("OK")
            return 0
        else:
            print("ERROR")
            return 1
            
    def Close(self):
        self.dab_test_client.disconnect()

if __name__ == "__main__":

    Tester = DabTester()
    Tester.execute_cmd("dab/device/info")
    Tester.execute_cmd("dab/operations/list")
    Tester.Close()

