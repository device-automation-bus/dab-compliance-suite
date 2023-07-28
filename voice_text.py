import dab.applications
import dab.system
import dab.voice

# Voice action steps
SEND_VOICE_TEXT_TEST_CASES = [
    ("voice/send-text",'{"requestText" : "Play lady Gaga music on YouTube", "voiceSystem": "Alexa"}', dab.voice.send_text, "Are you on search page with Lady Gaga?", "Voice launch Lady gaga"),
    ("voice/send-text",'{"requestText" : "Press enter", "voiceSystem": "Alexa"}', dab.voice.send_text, "Is video playing?", "Voice play video"),
    ("voice/send-text",'{"requestText" : "Play video", "voiceSystem": "Alexa"}', dab.voice.send_text, "If video was not playing, is it playing now?", "Voice resume video"),
    ("voice/send-text",'{"requestText" : "Set volume 0", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did volume of the video changed?", "voice mute"),
    ("voice/send-text",'{"requestText" : "Set volume 5", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did volume of the video changed?", "voice volume up"),
    ("voice/send-text",'{"requestText" : "Pause Video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video paused?", "voice pause"),
    ("voice/send-text",'{"requestText" : "Fast forward video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video playback fast forward?", "voice fastforward"),
    ("voice/send-text",'{"requestText" : "Rewind video", "voiceSystem": "Alexa"}', dab.voice.send_text, "Did video playback rewind?", "voice rewind"),
    ("voice/send-text",'{"requestText" : "Exit to main menu", "voiceSystem": "Alexa"}', dab.voice.send_text, "Are you on main menu?", "voice exit"),
]