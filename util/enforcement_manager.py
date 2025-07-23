from singleton_decorator import singleton
from typing import List, Dict
from enum import Enum

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

class ValidateCode(Enum):
    SUPPORT = 0
    UNSUPPORT = 1
    UNCERTAIN = 2

@singleton
class EnforcementManager:
    def __init__(self):
        self.supported_operations = set()
        self.supported_keys = set()
        self.supported_voice_assistants = set()
        self.supported_settings = None
        self.has_checked_settings = False
        self.supported_applications = set()

    def add_supported_operation(self, operation):
        self.supported_operations.add(operation)

    def is_operation_supported(self, operation):
        return not self.supported_operations or operation in self.supported_operations

    def add_supported_operations(self, operations):
        self.supported_operations = operations

    def get_supported_operations(self):
        return self.supported_operations
    
    def add_supported_key(self, key):
        self.supported_keys.add(key)

    def is_key_supported(self, key):
        return not self.supported_keys or key in self.supported_keys

    def add_supported_keys(self, keys):
        self.supported_keys = keys

    def get_supported_keys(self):
        return self.supported_keys
    
    def get_supported_voice_assistants(self, voice_assistant = None):
        if not voice_assistant:
            return self.supported_voice_assistants

        for voice_system in self.supported_voice_assistants:
            if voice_assistant == voice_system["name"]:
                return voice_system
        return None

    def set_supported_voice_assistants(self, voice_assistants):
        self.supported_voice_assistants = voice_assistants

    def get_voice_assistant(self, voice_assistant):
        return "AmazonAlexa" if len(self.supported_voice_assistants) == 0 else self.supported_voice_assistants[0]

    def check_supported_settings(self):
        return self.has_checked_settings

    def set_supported_settings(self, settings):
        self.supported_settings = settings
        self.has_checked_settings = True

    def is_setting_supported(self, setting):
        """
        Checks if a setting is supported by the target.

        Args:
            setting: The name of the setting.

        Returns:
            ValidateCode.SUPPORT, target supports the setting.
            ValidateCode.UNSUPPORT, target doesn't support the setting.
            ValidateCode.UNCERTAIN, uncertain whether the target support the setting.
        """

        if not self.supported_settings:
            return ValidateCode.UNCERTAIN

        if isinstance(self.supported_settings.get(setting), List) and self.supported_settings.get(setting):
            return ValidateCode.SUPPORT

        if isinstance(self.supported_settings.get(setting), bool) and self.supported_settings.get(setting):
            return ValidateCode.SUPPORT

        if (
               setting == 'audioVolume' and
               isinstance(self.supported_settings.get(setting), Dict) and
               any('min' in d for d in self.supported_settings.get(setting)) and
               any('max' in d for d in self.supported_settings.get(setting)) and
               self.supported_settings.get(setting)['min'] != self.supported_settings.get(setting)['max']
           ):
            return ValidateCode.SUPPORT

        return ValidateCode.UNSUPPORT

    def add_supported_application(self, application):
        self.supported_applications.add(application)

    def is_application_supported(self, application):
        return not self.supported_applications or application in self.supported_applications