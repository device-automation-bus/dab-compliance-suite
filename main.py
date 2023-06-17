from DabTester import DabTester
from DabTester import Default_Validations
from schema import dab_response_validator
import dab.applications
import dab.system
import argparse

# Implement the test cases
Test_Cases = [
    ("operations/list",'{}',Default_Validations, 200, dab_response_validator.validate_list_supported_operation_response_schema),
    ("applications/list",'{}',Default_Validations, 200, dab_response_validator.validate_list_applications_response_schema),
    ("applications/launch",'{"appId": "Cobalt"}',dab.applications.launch, 10000, dab_response_validator.validate_dab_response_schema),
    ("applications/launch-with-content",'{"appId": "Cobalt", "contentId": "v=jfKfPfyJRdk"}',dab.applications.launch_with_content, 10000, dab_response_validator.validate_dab_response_schema),
    ("applications/get-state",'{"appId": "Cobalt"}',Default_Validations, 200, dab_response_validator.validate_get_application_state_response_schema),
    ("applications/exit",'{"appId": "Cobalt"}',dab.applications.exit, 5000, dab_response_validator.validate_exit_application_response_schema),
    ("device/info",'{}',Default_Validations, 200, dab_response_validator.validate_device_information_schema),
    ("system/settings/list",'{}',Default_Validations, 200, dab_response_validator.validate_list_system_settings_schema),
    ("system/settings/get",'{}',Default_Validations, 200, dab_response_validator.validate_get_system_settings_response_schema),
    ("system/settings/set",'{"language": "en-US"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"outputResolution": {"width": 3840, "height": 2160, "frequency": 60} }',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"memc": true}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"cec": true}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"lowLatencyMode": true}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"matchContentFrameRate": "EnabledSeamlessOnly"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"hdrOutputMode": "AlwaysHdr"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"pictureMode": "Standard"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"audioOutputMode": "Auto"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"audioOutputSource": "HDMI"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"videoInputSource": "Other"}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"audioVolume": 20}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"mute": false}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("system/settings/set",'{"textToSpeech": true}',Default_Validations, 3000, dab_response_validator.validate_set_system_settings_response_schema),
    ("input/key/list",'{}',Default_Validations, 200, dab_response_validator.validate_key_list_schema),
    ("input/key-press",'{"keyCode": "KEY_HOME"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_UP"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_VOLUME_DOWN"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_MUTE"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_UP"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_CHANNEL_DOWN"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_MENU"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_EXIT"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_INFO"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_GUIDE"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_CAPTIONS"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_UP"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_PAGE_UP"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_PAGE_DOWN"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_RIGHT"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_DOWN"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_LEFT"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_BACK"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_PLAY"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_PLAY_PAUSE"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_STOP"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_REWIND"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_FAST_FORWARD"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_SKIP_REWIND"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_0"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_1"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_2"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_3"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_4"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_5"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_6"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_7"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_8"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/key-press",'{"keyCode": "KEY_9"}',Default_Validations, 1000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_HOME", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_MUTE", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_UP", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_CHANNEL_DOWN", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_MENU", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_EXIT", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_INFO", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_GUIDE", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_CAPTIONS", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_UP", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_UP", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_PAGE_DOWN", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_DOWN", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_ENTER", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_BACK", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_PLAY_PAUSE", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_PAUSE", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_STOP", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_REWIND", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_FAST_FORWARD", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_REWIND", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_SKIP_FAST_FORWARD", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_0", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_1", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_2", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_3", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_4", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_5", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_6", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_7", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_8", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("input/long-key-press",'{"keyCode": "KEY_9", "durationMs": 3000}',Default_Validations, 5000, dab_response_validator.validate_dab_response_schema),
    ("output/image",'{"outputLocation": "https://webhook.site/791918a1-cf5f-4a3e-9166-9f83af776232"}', Default_Validations, 2000, dab_response_validator.validate_output_image_response_schema),
    ("device-telemetry/start",'{"durationMs": 1000}',Default_Validations, 200, dab_response_validator.validate_start_device_telemetry_response_schema),
    ("device-telemetry/stop",'{}',Default_Validations, 200, dab_response_validator.validate_stop_device_telemetry_response_schema),
    ("app-telemetry/start",'{"appId": "Cobalt", "durationMs": 1000}',Default_Validations, 200, dab_response_validator.validate_start_app_telemetry_response_schema),
    ("app-telemetry/stop",'{"appId": "Cobalt"}',Default_Validations, 200, dab_response_validator.validate_stop_app_telemetry_response_schema),
    ("health-check/get",'{}',Default_Validations, 2000, dab_response_validator.validate_health_check_response_schema),
    ("voice/list",'{}',Default_Validations, 200, dab_response_validator.validate_list_voice_response_schema),
    ("voice/set",'{}',Default_Validations, 5000, dab_response_validator.validate_set_voice_system_response_schema),
    ("voice/send-audio",'{"fileLocation": "https://storage.googleapis.com/ytlr-cert.appspot.com/voice/ladygaga.wav"}',Default_Validations, 10000, dab_response_validator.validate_dab_response_schema),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube"}',Default_Validations, 10000, dab_response_validator.validate_dab_response_schema),
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}',Default_Validations, 10000, dab_response_validator.validate_dab_response_schema),
    ("version",' {}',Default_Validations, 200, dab_response_validator.validate_version_response_schema),
    ("system/restart",' {}',dab.system.restart, 30000, dab_response_validator.validate_dab_response_schema),

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