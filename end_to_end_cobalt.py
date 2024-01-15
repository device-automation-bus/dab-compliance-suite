import dab.applications
import dab.system
import dab.input
import dab.voice
import config
from util.enforcement_manager import EnforcementManager

# Voice action steps
END_TO_END_TEST_CASE = [
    ("voice/list",'{}', dab.voice.list, 200, "Voice List"),
    ("voice/send-text",f'{{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "{EnforcementManager().get_voice_assistant()}"}}', dab.voice.send_text, "Are you on search page with Lady Gaga?", "End to end launch"),
    ("input/key-press",'{"keyCode": "KEY_ENTER"}', dab.input.key_press, "Is video playing?", "End to end key press Enter"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_UP", "durationMs": 3000}', dab.input.long_key_press, "Is volume going up?", "End to end volume up"),
    ("input/long-key-press",'{"keyCode": "KEY_VOLUME_DOWN", "durationMs": 2000}', dab.input.long_key_press, "Is volume going down?", "End to End volume down"),
    ("input/key-press",'{"keyCode": "KEY_PAUSE"}', dab.input.key_press, "Did video paused?", "End to End pause video"),
    ("input/long-key-press",'{"keyCode": "KEY_RIGHT", "durationMs": 3000}', dab.input.long_key_press, "Did video playback fastforward?", "End to end fastforward"),
    ("input/long-key-press",'{"keyCode": "KEY_LEFT", "durationMs": 3000}', dab.input.long_key_press, "Did video playback rewind?", "End to end rewind"),
    ("applications/exit",f'{{"appId": "{config.apps["youtube"]}"}}',dab.applications.exit, 1000, "End to end exit"),
]