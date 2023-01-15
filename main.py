from DabTester import DabTester

Test_Cases = [
    ("dab/operations/list","{}"),
    ("dab/applications/list","{}"),
    ("dab/applications/launch","{}"),
    ("dab/applications/launch-with-content","{}"),
    ("dab/applications/get-state","{}"),
    ("dab/applications/exit","{}"),
    ("dab/device/info","{}"),
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
    # ("dab/system/restart","{}"),
]

if __name__ == "__main__":
    Tester = DabTester()
    
    Tester.verbose = True
    Tester.Test_All(Test_Cases)
    
    # Tester.Test_Case("dab/input/key-press",'{"keyCode": "KEY_RIGHT"}')
    
    Tester.Close()

