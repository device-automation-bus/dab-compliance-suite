from DabClient import DabClient

class DabTester:
    def __init__(self):
        self.dab_test_client = DabClient()
        self.dab_test_client.connect("localhost",1883)
        self.operations = [
            "dab/operations/list",
            "dab/applications/list",
            "dab/applications/launch",
            "dab/applications/launch-with-content",
            "dab/applications/get-state",
            "dab/applications/exit",
            "dab/device/info",
            "dab/system/restart",
            "dab/system/settings/list",
            "dab/system/settings/get",
            "dab/system/settings/set",
            "dab/input/key/list",
            "dab/input/key-press",
            "dab/input/long-key-press",
            "dab/output/image",
            "dab/device-telemetry/start",
            "dab/device-telemetry/stop",
            "dab/app-telemetry/start",
            "dab/app-telemetry/stop",
            "dab/health-check/get",
            "dab/voice/list",
            "dab/voice/set",
            "dab/voice/send-audio",
            "dab/voice/send-text",
            "dab/version",
            "dab/system/language/list",
            "dab/system/language/get",
            "dab/system/language/set",
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
    
    def Run(self):
        for operation in self.operations:
            if self.execute_cmd(operation) == 0:
                print("[ OK ] ",end='')
            else:
                print("[ Error:",self.dab_test_client.response['status'],'] ',end='')
            print("operation:",operation)

    def Close(self):
        self.dab_test_client.disconnect()

if __name__ == "__main__":
    Tester = DabTester()
    Tester.Run()
    Tester.Close()

