import dab.applications
import dab.input
import config

# The user must be logged into Netflix to perform the Play Movie test
NETFLIX_TEST_CASES = [
# This is your RDK UI shell, replace callsign if different
#    ("applications/exit", f'{{"appId": "GravityApp", "background": true}}', dab.applications.exit, 10000, "GravityApp Suspend"),

    ("applications/launch",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.launch, 20000, "Netflix Launch"),
    ("applications/get-state",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.get_state, 200, "Netflix After Launch"),

#Wait until Netflix shows the user menu before answering test result
    ("input/key-press",'{"keyCode": "KEY_ENTER"}', dab.input.key_press, 1000, "Netflix KEY_ENTER 1"),

    ("applications/exit", f'{{"appId": "{config.apps["netflix"]}", "background": true}}', dab.applications.exit, 5000, "Netflix Suspend"),
    ("applications/get-state",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.get_state, 200, "Netflix After Suspend"),

    ("applications/exit",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.exit, 5000, "Netflix Stop"),
    ("applications/get-state",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.get_state, 200, "Netflix After Stop"),

    ("applications/launch",f'{{"appId": "{config.apps["netflix"]}","parameters": ["m=80092839"]}}', dab.applications.launch, 20000, "Netflix Play Movie"),

#Wait until Netflix shows the play menu before answering test result
    ("input/key-press",'{"keyCode": "KEY_ENTER"}', dab.input.key_press, 1000, "Netflix KEY_ENTER 2"),

    ("applications/get-state",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.get_state, 200, "Netflix After Play Movie"),

    ("applications/exit",f'{{"appId": "{config.apps["netflix"]}"}}', dab.applications.exit, 5000, "Netflix Stop Again"),

#  The current dab-adapter-rs Media Keys do not work with Netflix. Use those keys with "/opt/dab_platform_keymap.json":

#{
#    "RDKSHELL_KEY_PAUSE":19,
#    "RDKSHELL_KEY_PLAY":226,
#    "RDKSHELL_KEY_HOMEPAGE":409
#}

#    ("input/key-press",'{"keyCode": "RDKSHELL_KEY_PAUSE"}', dab.input.key_press, 1000, "RDKSHELL_KEY_PAUSE"),
#    ("input/key-press",'{"keyCode": "RDKSHELL_KEY_PLAY"}', dab.input.key_press, 1000, "RDKSHELL_KEY_PLAY"),
#    ("input/key-press",'{"keyCode": "RDKSHELL_KEY_HOMEPAGE"}', dab.input.key_press, 1000, "RDKSHELL_KEY_HOMEPAGE"),

# This is your RDK UI shell, replace callsign if different
#    ("applications/launch", f'{{"appId": "GravityApp"}}', dab.applications.launch, 10000, "GravityApp Launch"),
]