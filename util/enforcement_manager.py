from singleton_decorator import singleton
from typing import Dict, List

class Resolution:
    width: int
    height: int
    frequency: int

class Settings:
    status: int
    language: List[str]
    outputResolution: List[Resolution]
    memc: bool
    cec: bool
    lowLatencyMode: bool
    matchContentFrameRate: List[str]
    hdrOutputMode: List[str]
    pictureMode: List[str]
    audioOutputMode: List[str]
    audioOutputSource: List[str]
    videoInputSource: List[str]
    audioVolume: bool
    mute: bool
    textToSpeech: bool

@singleton
class EnforcementManager:
    def __init__(self):
        self.supported_operations = set()
        self.supported_keys = set()
        self.supported_voice_assistants = set()
        self.supported_settings = None
        self.supported_applications = set()

    def add_supported_operation(self, operation):
        self.supported_operations.add(operation)

    def is_operation_supported(self, operation):
        return not self.supported_operations or operation in self.supported_operations
    
    def add_supported_key(self, key):
        self.supported_keys.add(key)

    def is_key_supported(self, key):
        return not self.supported_keys or key in self.supported_keys
    
    def add_supported_voice_assistant(self, voice_assistant):
        self.supported_voice_assistants.add(voice_assistant)

    def is_voice_assistant_supported(self, voice_assistant):
        return not self.supported_voice_assistants or voice_assistant in self.supported_voice_assistants
    
    def get_voice_assistant(self):
        return "AmazonAlexa" if len(self.supported_voice_assistants) == 0 else self.supported_voice_assistants[0]
    
    def set_supported_settings(self, settings):
        self.supported_settings = settings

    def is_setting_supported(self, setting):
        """
        Checks if a setting is supported by the target.

        Args:
            setting: The name of the setting.

        Returns:
            True if the setting is supported, False otherwise.
        """

        if not self.supported_settings:
            return True

        if isinstance(self.supported_settings.get(setting), List) and self.supported_settings.get(setting):
            return True

        if isinstance(self.supported_settings.get(setting), Dict) and self.supported_settings.get(setting):
            return True

        if isinstance(self.supported_settings.get(setting), bool) and self.supported_settings.get(setting):
            return True
    
    def add_supported_application(self, application):
        self.supported_applications.add(application)

    def is_application_supported(self, application):
        return not self.supported_applications or application in self.supported_applications
