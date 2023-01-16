from time import sleep
from DabTester import YesNoQuestion

def restart():
    print("restarting...wait 60s...",end='',flush=True)
    sleep(60)
    return YesNoQuestion("Cobalt re-started?")