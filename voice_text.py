import config
import dab.applications
import dab.system
import dab.voice
from util.enforcement_manager import EnforcementManager

# Voice action steps
SEND_VOICE_TEXT_TEST_CASES = [
    ("voice/list",'{}', dab.voice.list, 200, "Voice List"),
    ("voice/send-text",f'{{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Are you on search page with Lady Gaga?", "Voice launch Lady gaga"),
    ("voice/send-text",f'{{"requestText" : "Press enter", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Is video playing?", "Voice play video"),
    ("voice/send-text",f'{{"requestText" : "Play video", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "If video was not playing, is it playing now?", "Voice resume video"),
    ("voice/send-text",f'{{"requestText" : "Set volume 0", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Did volume of the video changed?", "voice mute"),
    ("voice/send-text",f'{{"requestText" : "Set volume 5", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Did volume of the video changed?", "voice volume up"),
    ("voice/send-text",f'{{"requestText" : "Pause Video", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Did video paused?", "voice pause"),
    ("voice/send-text",f'{{"requestText" : "Fast forward video", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Did video playback fast forward?", "voice fastforward"),
    ("voice/send-text",f'{{"requestText" : "Rewind video", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Did video playback rewind?", "voice rewind"),
    ("voice/send-text",f'{{"requestText" : "Exit to main menu", "voiceSystem": "{config.va}"}}', dab.voice.send_text, "Are you on main menu?", "voice exit"),
]