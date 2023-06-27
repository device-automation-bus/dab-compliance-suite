from DabTester import DabTester
from DabTester import Default_Validations
import config
import dab.app_telemetry
import dab.device
import dab.health_check
import dab.input
import dab.operations
import dab.device_telemetry
import dab.voice
import dab.applications
import dab.system
import dab.output
import dab.version
import argparse

# Implement the test cases
Test_Cases = [
    ("operations/list",'{}', dab.operations.list, 200),
    ("applications/list",'{}', dab.applications.list, 200),
    ("applications/launch",f'{"appId": "{config.apps.youtube}"}', dab.applications.launch, 10000),
    ("applications/launch-with-content",f'{"appId": "{config.apps.youtube}", "contentId": "v=jfKfPfyJRdk"}', dab.applications.launch_with_content, 10000),
    ("applications/get-state",f'{"appId": "{config.apps.youtube}"}', dab.applications.get_state, 200),
    ("applications/exit",f'{"appId": "{config.apps.youtube}"}', dab.applications.exit, 5000),
    ("device/info",'{}', dab.device.info, 200),
    ("system/settings/list",'{}', dab.system.list, 200),
    ("system/settings/get",'{}', dab.system.get, 200),
    ("system/settings/set",'{"language": "en-US"}', dab.system.set, 3000),
    ("system/settings/set",'{"outputResolution": {"width": 3840, "height": 2160, "frequency": 60} }', dab.system.set, 3000),
    ("system/settings/set",'{"memc": true}', dab.system.set, 3000),
    ("system/settings/set",'{"cec": true}', dab.system.set, 3000),
    ("system/settings/set",'{"lowLatencyMode": true}', dab.system.set, 3000),
    ("system/settings/set",'{"matchContentFrameRate": "EnabledSeamlessOnly"}', dab.system.set, 3000),
    ("system/settings/set",'{"hdrOutputMode": "AlwaysHdr"}', dab.system.set, 3000),
    ("system/settings/set",'{"pictureMode": "Standard"}', dab.system.set, 3000),
    ("system/settings/set",'{"audioOutputMode": "Auto"}', dab.system.set, 3000),
    ("system/settings/set",'{"audioOutputSource": "HDMI"}', dab.system.set, 3000),
    ("system/settings/set",'{"videoInputSource": "Other"}', dab.system.set, 3000),
    ("system/settings/set",'{"audioVolume": 20}', dab.system.set, 3000),
    ("system/settings/set",'{"mute": false}', dab.system.set, 3000),
    ("system/settings/set",'{"textToSpeech": true}', dab.system.set, 3000),
    ("input/key/list",'{}', dab.input.list, 200),
    ("input/key-press",'{"keyCode": "KEY_HOME"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_UP"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_DOWN"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_MUTE"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_UP"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_DOWN"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_MENU"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_EXIT"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_INFO"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_GUIDE"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_CAPTIONS"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_UP"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_PAGE_UP"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_PAGE_DOWN"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_RIGHT"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_DOWN"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_LEFT"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_BACK"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_PLAY"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_PLAY_PAUSE"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_STOP"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_REWIND"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_FAST_FORWARD"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_SKIP_REWIND"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_0"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_1"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_2"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_3"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_4"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_5"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_6"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_7"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_8"}', dab.input.key_press, 1000),
    ("input/key-press",'{"keyCode": "KEY_9"}', dab.input.key_press, 1000),
    ("input/long-key-press",'{"keyCode": "KEY_HOME", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_MUTE", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_UP", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_DOWN", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_MENU", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_EXIT", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_INFO", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_GUIDE", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_CAPTIONS", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_UP", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_UP", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_DOWN", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_DOWN", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_ENTER", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_BACK", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY_PAUSE", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_PAUSE", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_STOP", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_REWIND", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_FAST_FORWARD", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_REWIND", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_0", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_1", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_2", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_3", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_4", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_5", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_6", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_7", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_8", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("input/long-key-press",'{"keyCode": "KEY_9", "durationMs": 3000}', dab.input.long_key_press, 5000),
    ("output/image",'{"outputLocation": "https://webhook.site/791918a1-cf5f-4a3e-9166-9f83af776232"}', dab.output.image, 2000),
    ("device-telemetry/start",'{"durationMs": 1000}', dab.device_telemetry.start, 200),
    ("device-telemetry/stop",'{}', dab.device_telemetry.stop, 200),
    ("app-telemetry/start",f'{"appId": "{config.apps.youtube}", "durationMs": 1000}', dab.app_telemetry.start, 200),
    ("app-telemetry/stop",f'{"appId": "{config.apps.youtube}"}', dab.app_telemetry.stop, 200),
    ("health-check/get",'{}', dab.health_check.get, 2000),
    ("voice/list",'{}', dab.voice.list, 200),
    ("voice/set",'{}', dab.voice.set, 5000),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/ladygaga.wav"}',dab.voice.send_audio, 10000),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube"}', dab.voice.send_text, 10000),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}', dab.voice.send_text, 10000),
    ("version",' {}', dab.version.default, 200),
    ("system/restart",' {}', dab.system.restart, 30000),
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
                        help="set the IP of the MQTT broker. Ex: -b 192.168.0.100",
                        type=str,
                        default="localhost")

    parser.add_argument("-I","--ID", 
                        help="set the DAB Device ID. Ex: -I mydevice123",
                        type=str,
                        default="localhost")

    parser.add_argument("-c","--case", 
                        help="test only the specified case. Ex: -c 3",
                        type=int)

    parser.add_argument("-o","--output", 
                        help="output location for the json file",
                        type=str)
    parser.set_defaults(output="")
    
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
            Tester.Execute_All_Tests("main", device_id, Test_Cases, args.output)
        else:
            # Test a single case
            Tester.Execute_Test_Case(device_id,(Test_Cases[args.case]))
        
    Tester.Close()