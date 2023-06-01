from DabTester import DabTester
from DabTester import Default_Test
import dab.applications
import dab.system
import argparse

# Implement the test cases
Test_Cases = [
    ("operations/list",'{}',Default_Test),
    ("applications/list",'{}',Default_Test),
    ("applications/launch",'{"appId": "Cobalt"}',dab.applications.launch),
    #("applications/launch-with-content",'{"appId": "Cobalt", "contentId": "v=jfKfPfyJRdk"}',Default_Test),
    #("applications/get-state",'{"appId": "Cobalt"}',Default_Test),
    ("applications/exit",'{"appId": "Cobalt"}',dab.applications.exit),
    ("device/info",'{}',Default_Test),
    ("system/settings/list",'{}',Default_Test),
    ("system/settings/get",'{}',Default_Test),
    ("system/settings/set",'{"audioVolume": 20}',Default_Test),
    ("system/settings/set",'{"language": "en-US"}',Default_Test),
    ("system/settings/set",'{"outputResolution": {"width": 3840, "height": 2160, "frequency": 60} }',Default_Test),
    ("system/settings/set",'{"memc": true}',Default_Test),
    ("system/settings/set",'{"cec": true}',Default_Test),
    ("system/settings/set",'{"lowLatencyMode": true}',Default_Test),
    ("system/settings/set",'{"matchContentFrameRate": "EnabledSeamlessOnly"}',Default_Test),
    ("system/settings/set",'{"hdrOutputMode": "AlwaysHdr"}',Default_Test),
    ("system/settings/set",'{"pictureMode": "Standard"}',Default_Test),
    ("system/settings/set",'{"audioOutputMode": "Auto"}',Default_Test),
    ("system/settings/set",'{"audioOutputSource": "HDMI"}',Default_Test),
    ("system/settings/set",'{"videoInputSource": "Other"}',Default_Test),
    ("system/settings/set",'{"mute": false}',Default_Test),
    ("system/settings/set",'{"textToSpeech": true}',Default_Test),
    ("input/key/list",'{}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_HOME"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_UP"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_DOWN"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_MUTE"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_UP"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_DOWN"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_MENU"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_EXIT"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_INFO"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_GUIDE"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_CAPTIONS"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_UP"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_PAGE_UP"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_PAGE_DOWN"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_RIGHT"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_DOWN"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_LEFT"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_BACK"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_PLAY"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_PLAY_PAUSE"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_STOP"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_REWIND"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_FAST_FORWARD"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_SKIP_REWIND"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_0"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_1"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_2"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_3"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_4"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_5"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_6"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_7"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_8"}',Default_Test),
    ("input/key-press",'{"keyCode": "KEY_9"}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_HOME", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_MUTE", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_UP", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_DOWN", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_MENU", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_EXIT", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_INFO", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_GUIDE", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_CAPTIONS", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_UP", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_UP", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_DOWN", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_DOWN", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_ENTER", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_BACK", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY_PAUSE", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_PAUSE", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_STOP", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_REWIND", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_FAST_FORWARD", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_REWIND", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_0", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_1", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_2", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_3", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_4", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_5", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_6", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_7", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_8", "durationMs": 3000}',Default_Test),
    ("input/long-key-press",'{"keyCode": "KEY_9", "durationMs": 3000}',Default_Test),
    ("output/image",'{"outputLocation": "https://webhook.site/791918a1-cf5f-4a3e-9166-9f83af776232"}', Default_Test),
    ("device-telemetry/start",'{"durationMs": 1000}',Default_Test),
    ("device-telemetry/stop",'{}',Default_Test),
    ("app-telemetry/start",'{"appId": "Cobalt", "durationMs": 1000}',Default_Test),
    ("app-telemetry/stop",'{"appId": "Cobalt"}',Default_Test),
    ("health-check/get",'{}',Default_Test),
    ("voice/list",'{}',Default_Test),
    ("voice/set",'{}',Default_Test),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/ladygaga.wav"}',Default_Test),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube"}',Default_Test),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}',Default_Test),
    ("version",'{}',Default_Test),
    ("system/restart",'{}',dab.system.restart),
]

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-v","--verbose", 
                        help="increase output verbosity",
                        action="store_true")
    parser.set_defaults(verbose=False)
    parser.add_argument("-l","--list", 
                        help="list the test cases",
                        action="store_true")
    parser.set_defaults(list=False)
    parser.add_argument("-b","--broker", 
                        help="set the IP of the broker.Ex: -b 192.168.0.100",
                        type=str,
                        default="localhost")

    parser.add_argument("-I","--ID", 
                        help="set the Device ID.Ex: -I mydevice123",
                        type=str,
                        default="localhost")

    parser.add_argument("-c","--case", 
                        help="test only the specified case.Ex: -c 3",
                        type=int)
    parser.set_defaults(case=99999)
    args = parser.parse_args()
    
    # Use the DabTester
    device_id = args.ID

    Tester = DabTester(args.broker)
    
    Tester.verbose = args.verbose
    
    if(args.list == True):
        for i in range(len(Test_Cases)):
            print("[%02d]"%i,Test_Cases[i][0]," ",Test_Cases[i][1])
    else:
        if (args.case == 99999) or (not isinstance(args.case, (int))):
            # Test all the cases
            print("Testing all cases")
            Tester.Test_All(device_id,Test_Cases)
        else:
            # Test a single case
            Tester.Test_Case(device_id,(Test_Cases[args.case]))
        
    Tester.Close()