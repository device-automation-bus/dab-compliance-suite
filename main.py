from DabClient import DabClient

class DabTester:
    def __init__(self):
        self.dab_test_client = DabClient()
        self.dab_test_client.connect("localhost",1883)
        self.verbose = False
        self.operations = [
            ("dab/operations/list","{}"),
            ("dab/applications/list","{}"),
            ("dab/applications/launch","{}"),
            ("dab/applications/launch-with-content","{}"),
            ("dab/applications/get-state","{}"),
            ("dab/applications/exit","{}"),
            ("dab/device/info","{}"),
            ("dab/system/restart","{}"),
            ("dab/system/settings/list","{}"),
            ("dab/system/settings/get","{}"),
            ("dab/system/settings/set","{}"),
            ("dab/input/key/list","{}"),
            ("dab/input/key-press",'{"keyCode": "KEY_DOWN"}'),
            ("dab/input/long-key-press","{}"),
            ("dab/output/image","{}"),
            ("dab/device-telemetry/start","{}"),
            ("dab/device-telemetry/stop","{}"),
            ("dab/app-telemetry/start","{}"),
            ("dab/app-telemetry/stop","{}"),
            ("dab/health-check/get","{}"),
            ("dab/voice/list","{}"),
            ("dab/voice/set","{}"),
            ("dab/voice/send-audio","{}"),
            ("dab/voice/send-text","{}"),
            ("dab/version","{}"),
            ("dab/system/language/list","{}"),
            ("dab/system/language/get","{}"),
            ("dab/system/language/set","{}"),
        ]

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
            if Tester.verbose == True:
                self.dab_test_client.print_response()
                

    def Run_All(self):
        for operation in self.operations:
            self.Test_Case(operation[0],operation[1])

    def Close(self):
        self.dab_test_client.disconnect()

if __name__ == "__main__":
    Tester = DabTester()
    # Tester.verbose = False
    Tester.Run_All()
    # Tester.Test_Case("dab/input/key-press",'{"keyCode": "KEY_DOWN"}')
    Tester.Close()

