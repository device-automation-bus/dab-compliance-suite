from DabTester import DabTester
from DabTester import Default_Test
import applications 
import system

if __name__ == "__main__":
    Tester = DabTester()
    Test_Cases = [
        ("dab/operations/list",'{}',Default_Test),
        ("dab/applications/list",'{}',Default_Test),
        ("dab/applications/launch",'{"appId": "Cobalt"}',applications.launch),
        ("dab/applications/launch-with-content",'{}',Default_Test),
        ("dab/applications/get-state",'{"appId": "Cobalt"}',Default_Test),
        ("dab/applications/exit",'{"appId": "Cobalt"}',applications.exit),
        ("dab/device/info",'{}',Default_Test),
        ("dab/system/settings/list",'{}',Default_Test),
        ("dab/system/settings/get",'{}',Default_Test),
        ("dab/system/settings/set",'{}',Default_Test),
        ("dab/input/key/list",'{}',Default_Test),
        ("dab/input/key-press",'{"keyCode": "KEY_DOWN"}',Default_Test),
        ("dab/input/long-key-press",'{}',Default_Test),
        ("dab/output/image",'{}',Default_Test),
        ("dab/device-telemetry/start",'{}',Default_Test),
        ("dab/device-telemetry/stop",'{}',Default_Test),
        ("dab/app-telemetry/start",'{}',Default_Test),
        ("dab/app-telemetry/stop",'{}',Default_Test),
        ("dab/health-check/get",'{}',Default_Test),
        ("dab/voice/list",'{}',Default_Test),
        ("dab/voice/set",'{}',Default_Test),
        ("dab/voice/send-audio",'{}',Default_Test),
        ("dab/voice/send-text",'{}',Default_Test),
        ("dab/version",'{}',Default_Test),
        ("dab/system/language/list",'{}',Default_Test),
        ("dab/system/language/get",'{}',Default_Test),
        ("dab/system/language/set",'{}',Default_Test),
        ("dab/system/restart",'{}',system.restart),
    ]
    
    Tester.verbose = False
    Tester.Test_All(Test_Cases)
    
    Tester.Close()

