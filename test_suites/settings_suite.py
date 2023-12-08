import dab.applications
import dab.system
import dab.device

# Settings action steps
SEND_SETTING_ALL_TEST_CASES = [
    ("device/info",'{}', dab.device.info, 500, "Conformance"),
    ("system/settings/list",'{}', dab.system.list, 500, "Conformance"),
    ("system/settings/get",'{}', dab.system.get, 500, "Conformance"),
    ("system/settings/set",'{"language": "en-US"}', dab.system.set, 3000, "language"),
    ("system/settings/set",'{"outputResolution": {"width": 3840, "height": 2160, "frequency": 60} }', dab.system.set, 3000, "outputResolution"),
    ("system/settings/set",'{"outputResolution": {"width": 720, "height": 576, "frequency":50} }', dab.system.set, 3000, "outputResolution"),
    ("system/settings/set",'{"hdrOutputMode": "AlwaysHdr"}', dab.system.set, 3000, "hdrOutputMode"),
    ("system/settings/set",'{"hdrOutputMode": "HdrOnPlayback"}', dab.system.set, 3000, "hdrOutputMode"),
    ("system/settings/set",'{"pictureMode": "Standard"}', dab.system.set, 3000, "pictureMode"),
    ("system/settings/set",'{"pictureMode": "Dynamic"}', dab.system.set, 3000, "pictureMode"),
    ("system/settings/set",'{"audioOutputSource": "HDMI"}', dab.system.set, 3000, "audioOutputSource"),
    ("system/settings/set",'{"audioOutputSource": "Optical"}', dab.system.set, 3000, "audioOutputSource"),
    ("system/settings/set",'{"audioOutputSource": "Aux"}', dab.system.set, 3000, "audioOutputSource"),
    ("system/settings/set",'{"audioOutputMode": "Auto"}', dab.system.set, 3000, "audioOutputMode"),
    ("system/settings/set",'{"audioOutputMode": "PassThrough"}', dab.system.set, 3000, "audioOutputMode"),
    ("system/settings/set",'{"audioVolume": 20}', dab.system.set, 3000, "audioVolume"),
    ("system/settings/set",'{"audioVolume": 50}', dab.system.set, 3000, "audioVolume"),
    ("system/settings/set",'{"cec": false}', dab.system.set, 3000, "cec"),
    ("system/settings/set",'{"cec": true}', dab.system.set, 3000, "cec"),
    ("system/settings/set",'{"mute": true}', dab.system.set, 3000, "mute"),
    ("system/settings/set",'{"mute": false}', dab.system.set, 3000, "mute"),
    ("system/settings/set",'{"textToSpeech": false}', dab.system.set, 3000, "textToSpeech"),
    ("system/settings/set",'{"textToSpeech": true}', dab.system.set, 3000, "textToSpeech"),
    ("system/settings/set",'{"memc": true}', dab.system.set, 3000, "memc"),
    ("system/settings/set",'{"lowLatencyMode": true}', dab.system.set, 3000, "lowLatencyMode"),
    ("system/settings/set",'{"matchContentFrameRate": "EnabledSeamlessOnly"}', dab.system.set, 3000, "matchContentFrameRate"),
    ("system/settings/set",'{"videoInputSource": "Cast"}', dab.system.set, 3000, "videoInputSource"),
]