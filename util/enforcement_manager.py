from singleton_decorator import singleton
from typing import List, Dict
from enum import Enum
import base64
import tarfile
import json
import os
import shutil
import time

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

LOGS_COLLECTION_CATEGORIES = {"system", "application", "crash"}
LOGS_COLLECTION_FOLDER = "logs"
LOGS_COLLECTION_PACKAGE = f"{LOGS_COLLECTION_FOLDER}.tar.gz"
# Spec 5.3: max period between stop-collection chunk responses
LOGS_CHUNK_MAX_GAP_SEC = 2

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
        normalized = set()

        for op in operations if isinstance(operations, (list, set, tuple)) else ():
            if isinstance(op, str):
                op = op.strip()
                if op:
                    normalized.add(op)
            elif isinstance(op, dict):
                name = (
                    op.get("operation")
                    or op.get("name")
                    or op.get("topic")
                    or op.get("path")
                )
                if isinstance(name, str) and name.strip():
                    normalized.add(name.strip())

        self.supported_operations = normalized

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

    def get_supported_settings(self):
        return self.supported_settings

    def is_setting_supported(self, setting, value = None):
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

        if isinstance(self.supported_settings.get(setting), List) and value in self.supported_settings.get(setting):
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

    def verify_logs_chunk(self, tester, logs):
        # The chunks carry consecutive pieces of ONE base64 string, so they are
        # joined first and decoded once at the end.
        previous_remainingChunks = -1
        previous_received_at = None
        all_logArchives = []
        validate_state = False

        try:
            startTime = time.time()
            while True:
                chunkData, received_at = tester.dab_client.get_response_chunk()
                currentTime = time.time()
                if not chunkData:
                    if currentTime - startTime > LOGS_CHUNK_MAX_GAP_SEC:
                        print(f"More than {LOGS_CHUNK_MAX_GAP_SEC}s without receiving logs chunk. Timeout!")
                        logs.append(f"[FAILED] More than {LOGS_CHUNK_MAX_GAP_SEC}s without receiving logs chunk. Timeout!")
                        break
                    time.sleep(0.05)
                    continue

                startTime = currentTime
                if "remainingChunks" not in chunkData or "logArchive" not in chunkData:
                    print(f"Logs chunk without 'logArchive'/'remainingChunks': {chunkData}")
                    logs.append(f"[FAILED] Logs chunk without 'logArchive'/'remainingChunks': {json.dumps(chunkData)}")
                    break
                remainingChunks = chunkData["remainingChunks"]
                if previous_remainingChunks != -1 and remainingChunks != previous_remainingChunks - 1:
                    print(f"Lost the logs chunk with 'remainingChunks':{previous_remainingChunks - 1}.")
                    logs.append(f"[FAILED] Lost the logs chunk with 'remainingChunks':{previous_remainingChunks - 1}.")
                    break
                if previous_received_at is not None and received_at - previous_received_at > LOGS_CHUNK_MAX_GAP_SEC:
                    interval = received_at - previous_received_at
                    print(f"Logs chunk with 'remainingChunks':{remainingChunks} arrived {interval:.2f}s after the previous one (max {LOGS_CHUNK_MAX_GAP_SEC}s).")
                    logs.append(f"[FAILED] Logs chunk with 'remainingChunks':{remainingChunks} arrived {interval:.2f}s after the previous one (max {LOGS_CHUNK_MAX_GAP_SEC}s).")
                    break
                previous_received_at = received_at
                all_logArchives.append(chunkData["logArchive"])
                logs.append(f"Received logs chunk, remainingChunks={remainingChunks}, size={len(chunkData['logArchive'])}")
                previous_remainingChunks = remainingChunks
                if remainingChunks == 0:
                    validate_state = True
                    break
        finally:
            tester.dab_client.end_chunked_response()

        if validate_state == True:
            try:
                archive = base64.b64decode("".join(all_logArchives), validate=True)
                with open(LOGS_COLLECTION_PACKAGE, 'wb') as f:
                    f.write(archive)
                    print(f"Received all log chunks, and combined into {LOGS_COLLECTION_PACKAGE} file.")
                    logs.append(f"Received all log chunks, and combined into {LOGS_COLLECTION_PACKAGE} file.")
            except Exception as e:
                validate_state = False
                print(f"[Error] Combine chunks failed: {str(e)}")
                logs.append(f"[FAILED] Combine chunks failed: {str(e)}")

        return validate_state

    def verify_logs_structure(self, logs):
        logs_structure = set()
        # Drop folders left by a previous run so they can't satisfy the check
        if os.path.exists(LOGS_COLLECTION_FOLDER):
            shutil.rmtree(LOGS_COLLECTION_FOLDER, ignore_errors=True)
        try:
            with tarfile.open(LOGS_COLLECTION_PACKAGE, 'r:gz') as tar:
                tar.extractall(LOGS_COLLECTION_FOLDER)
        except Exception as e:
            print(f"[Error] Uncompress {LOGS_COLLECTION_PACKAGE}: {str(e)}")
            logs.append(f"[FAILED] Verify {LOGS_COLLECTION_PACKAGE} failed: {str(e)}")
            return False

        entries = os.listdir(LOGS_COLLECTION_FOLDER)
        for entry in entries:
            full_path = os.path.join(LOGS_COLLECTION_FOLDER, entry)
            if os.path.isdir(full_path):
                logs_structure.add(entry)

        if LOGS_COLLECTION_CATEGORIES.issubset(logs_structure):
            logs.append(f"The logs structure follow DAB requirement, include folder {LOGS_COLLECTION_CATEGORIES}")
            validate_state = True
        else:
            validate_state = False
            print(f"The logs structure doesn't follows DAB requirement.")
            logs.append(f"[FAILED] The logs structure doesn't follows DAB requirement.")

        return validate_state

    def delete_logs_collection_files(self):
        if os.path.exists(LOGS_COLLECTION_FOLDER):
            try:
                shutil.rmtree(LOGS_COLLECTION_FOLDER)
                print(f"Delete logs collection folder '{LOGS_COLLECTION_FOLDER}'.")
            except Exception as e:
                print(f"{str(e)}. Please delete logs collection folder {LOGS_COLLECTION_FOLDER} manually.")

        if os.path.exists(LOGS_COLLECTION_PACKAGE):
            try:
                os.remove(LOGS_COLLECTION_PACKAGE)
                print(f"Delete logs collection package '{LOGS_COLLECTION_PACKAGE}'.")
            except Exception as e:
                print(f"{str(e)}, Please delete logs collection package '{LOGS_COLLECTION_PACKAGE}' manually.")
