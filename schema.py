from jsonschema import validate
import jsons

# DabRequest
dab_request_schema = {
    "type": "object",
    "properties": {},
    "required": []
}

# DabResponse
dab_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"}
    },
    "required": ["status"]
}

# Operation: operations/list
# OperationsListRequest
operations_list_request_schema = dab_request_schema

# ListSupportedOperationResponse
list_supported_operation_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "operations": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["status", "operations"]
}

# Operation: applications/list
# ApplicationListRequest
application_list_request_schema = dab_request_schema

# Application
application_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "friendlyName": {"type": "string"},
        "version": {"type": "string"}
    },
    "required": ["appId"]
}

# ListApplicationsResponse
list_applications_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "applications": {
            "type": "array",
            "items": application_schema
        }
    },
    "required": ["status", "applications"]
}

# Operation: applications/launch
# LaunchApplicationRequest
launch_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "parameters": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["appId"]
}

# LaunchApplicationResponse
launch_application_response_schema = dab_response_schema

# Operation: applications/launch_with_content
# LaunchApplicationWithContentRequest
launch_application_with_content_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "contentId": {"type": "string"},
        "parameters": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": ["appId", "contentId"]
}

# LaunchApplicationWithContentResponse
launch_application_with_content_response_schema = dab_response_schema

# Operation: applications/get_state
# GetApplicationStateRequest
get_application_state_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"}
    },
    "required": ["appId"]
}

# GetApplicationStateResponse
get_application_state_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}

# Operation: applications/exit
# ExitApplicationRequest
exit_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "force": {"type": "boolean"}
    },
    "required": ["appId"]
}

# ExitApplicationResponse
exit_application_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}
# InstallApplicationRequest
install_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "force": {"type": "boolean"}
    },
    "required": ["appId"]
}
# InstallApplicationResponse
install_application_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}

# UninstallApplicationRequest
uninstall_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "force": {"type": "boolean"}
    },
    "required": ["appId"]
}
# UnnstallApplicationResponse
uninstall_application_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}
# Clear_dataApplicationRequest
clear_data_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "force": {"type": "boolean"}
    },
    "required": ["appId"]
}
# clear_dataApplicationResponse
clear_data_application_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}
# InstallFromAppstoreApplicationRequest
install_from_appstore_application_request_schema = {
    "type": "object",
    "properties": {
        "appId": {"type": "string"},
        "force": {"type": "boolean"}
    },
    "required": ["appId"]
}
# InstallFromAppstoreApplicationResponse
install_from_appstore_application_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "state": {"type": "string"}
    },
    "required": ["status", "state"]
}

# Operation: device/info
# DeviceInfoRequest
device_info_request_schema = dab_request_schema

# NetworkInterfaceType and DisplayType
# These are enums and can be represented as strings in a JSON schema.

# NetworkInterface
network_interface_schema = {
    "type": "object",
    "properties": {
        "connected": {"type": "boolean"},
        "macAddress": {"type": "string"},
        "ipAddress": {"type": ["string", "null"]},
        "dns": {
            "type": ["array", "null"],
            "items": {"type": "string"}
        },
        "type": {"type": "string"}
    },
    "required": ["connected", "macAddress", "type"]
}

# DeviceInformation
device_information_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "manufacturer": {"type": "string"},
        "model": {"type": "string"},
        "serialNumber": {"type": "string"},
        "chipset": {"type": "string"},
        "firmwareVersion": {"type": "string"},
        "firmwareBuild": {"type": "string"},
        "networkInterfaces": {
            "type": "array",
            "items": network_interface_schema
        },
        "displayType": {"type": "string"},
        "screenWidthPixels": {"type": "integer"},
        "screenHeightPixels": {"type": "integer"},
        "uptimeSince": {"type": "integer"},
        "deviceId": {"type": "string"}
    },
    "required": ["status", "manufacturer", "model", "serialNumber", "chipset", 
                 "firmwareVersion", "firmwareBuild", "networkInterfaces", "displayType", 
                 "screenWidthPixels", "screenHeightPixels", "uptimeSince", "deviceId"]
}

# Operation: system/restart
# RestartRequest and RestartResponse
restart_request_schema = dab_request_schema
restart_response_schema = dab_response_schema

# Operation: system/settings/list
# SettingsListRequest
settings_list_request_schema = dab_request_schema

# OutputResolution
output_resolution_schema = {
    "type": "object",
    "properties": {
        "width": {"type": "integer"},
        "height": {"type": "integer"},
        "frequency": {"type": "number"}
    },
    "required": ["width", "height", "frequency"]
}

# MatchContentFrameRate, HdrOutputMode, PictureMode, AudioOutputMode, AudioOutputSource, VideoInputSource
# These are enums and can be represented as strings in a JSON schema.

# ListSystemSettings
list_system_settings_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "language": {
            "type": "array",
            "items": {"type": "string"}
        },
        "outputResolution": {
            "type": "array",
            "items": output_resolution_schema
        },
        "memc": {"type": "boolean"},
        "cec": {"type": "boolean"},
        "lowLatencyMode": {"type": "boolean"},
        "matchContentFrameRate": {
            "type": "array",
            "items": {"type": "string"}
        },
        "hdrOutputMode": {
            "type": "array",
            "items": {"type": "string"}
        },
        "pictureMode": {
            "type": "array",
            "items": {"type": "string"}
        },
        "audioOutputMode": {
            "type": "array",
            "items": {"type": "string"}
        },
        "audioOutputSource": {
            "type": "array",
            "items": {"type": "string"}
        },
        "videoInputSource": {
            "type": "array",
            "items": {"type": "string"}
        },
        "audioVolume": {
            "type": "object",
            "properties": {
                "min": {"type": "integer"},
                "max": {"type": "integer"}
            },
            "required": ["min", "max"]
        },
        "mute": {"type": "boolean"},
        "textToSpeech": {"type": "boolean"}
    },
    "required": ["status", "language", "outputResolution", "memc", "cec", "lowLatencyMode",
                 "matchContentFrameRate", "hdrOutputMode", "pictureMode", "audioOutputMode",
                 "audioOutputSource", "videoInputSource", "audioVolume", "mute", "textToSpeech"]
}

system_settings_schema = {
    "language": {"type": "string"},
    "outputResolution": output_resolution_schema,
    "memc": {"type": "boolean"},
    "cec": {"type": "boolean"},
    "lowLatencyMode": {"type": "boolean"},
    "matchContentFrameRate": {"type": "string"},
    "hdrOutputMode": {"type": "string"},
    "pictureMode": {"type": "string"},
    "audioOutputMode": {"type": "string"},
    "audioOutputSource": {"type": "string"},
    "videoInputSource": {"type": "string"},
    "audioVolume": {"type": "integer"},
    "mute": {"type": "boolean"},
    "textToSpeech": {"type": "boolean"},
}

# Operation: system/settings/get
# GetSystemSettingsResponse
get_system_settings_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"}
    },
    "required": ["status"],

    "if": {
        "properties": {
            "status": { "const": 200 }
        }
    },
    "then": {
        "properties": system_settings_schema,
        "required": list(system_settings_schema.keys())
    },
    "else": {
        "properties": {
            "error": {"type": ["string", "null"]}
        },
        "required": ["error"]
    },

    "unevaluatedProperties": False
}

# SetSystemSettingsResponse
set_system_settings_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"}
    },
    "required": ["status"],

    "if": {
        "properties": {
            "status": { "const": 200 }
        }
    },
    "then": {
        "properties": system_settings_schema
    },
    "else": {
        "properties": {
            "error": {"type": ["string", "null"]}
        },
        "required": ["error"]
    },

    "unevaluatedProperties": False
}

# Operation: input/key/list
# KeyList
key_list_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "keyCodes": {
            "type": "array",
            "items": {"type": "string"}
        },
    },
    "required": ["status", "keyCodes"]
}

# Operation: input/key_press
# KeyPressRequest and LongKeyPressRequest
key_press_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "keyCode": {"type": "string"},
    },
    "required": ["id", "keyCode"]
}

# Operation: input/long_key_press
# LongKeyPressRequest
long_key_press_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "keyCode": {"type": "string"},
        "durationMs": {"type": "integer"},
    },
    "required": ["id", "keyCode", "durationMs"]
}

# KeyPressResponse
key_press_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
    },
    "required": ["status"]
}

# Operation: output/image
# OutputImageRequest and OutputImageResponse
output_image_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "outputLocation": {"type": "string"},
    },
    "required": ["id", "outputLocation"]
}

output_image_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "outputImage": {"type": "string"},
    },
    "required": ["status", "outputImage"]
}

# Operation: device_telemetry/start
# StartDeviceTelemetryRequest and StartDeviceTelemetryResponse
start_device_telemetry_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "duration": {"type": "number"},
    },
    "required": ["id", "duration"]
}

start_device_telemetry_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "duration": {"type": "number"},
    },
    "required": ["status", "duration"]
}

# Operation: device_telemetry/stop
# StopDeviceTelemetryRequest and StopDeviceTelemetryResponse
stop_device_telemetry_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
    },
    "required": ["id"]
}

stop_device_telemetry_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
    },
    "required": ["status"]
}

# Operation: app_telemetry/start
# StartApplicationTelemetryRequest and StartApplicationTelemetryResponse
start_app_telemetry_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "appId": {"type": "string"},
        "duration": {"type": "number"},
    },
    "required": ["id", "appId", "duration"]
}

start_app_telemetry_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "duration": {"type": "number"},
    },
    "required": ["status", "duration"]
}

# Operation: app_telemetry/stop
# StopApplicationTelemetryRequest and StopApplicationTelemetryResponse
stop_app_telemetry_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "appId": {"type": "string"},
    },
    "required": ["id", "appId"]
}

stop_app_telemetry_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
    },
    "required": ["status"]
}

# Operation: health_check/get
# HealthCheckRequest and HealthCheckResponse
health_check_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
    },
    "required": ["id"]
}

health_check_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "healthy": {"type": "boolean"},
        "message": {"type": ["string", "null"]},
    },
    "required": ["status", "healthy"]
}

# Operation: voice/list
# VoiceListRequest and ListVoiceResponse
voice_list_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
    },
    "required": ["id"]
}

list_voice_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "voiceSystems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["name", "enabled"]
            }
        },
    },
    "required": ["status", "voiceSystems"]
}

# Operation: voice/set
# SetVoiceSystemRequest and SetVoiceSystemResponse
set_voice_system_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "voiceSystem": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["name", "enabled"]
        },
    },
    "required": ["id", "voiceSystem"]
}

set_voice_system_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "voiceSystem": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["name", "enabled"]
        },
    },
    "required": ["status", "voiceSystem"]
}

# Operation: voice/send_audio
# SendAudioRequest and VoiceRequestResponse
send_audio_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "fileLocation": {"type": "string"},
        "voiceSystem": {"type": ["string", "null"]},
    },
    "required": ["id", "fileLocation"]
}

voice_request_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
    },
    "required": ["status"]
}

# Operation: voice/send_text
# SendTextRequest and VoiceTextRequestResponse
send_text_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "requestText": {"type": "string"},
        "voiceSystem": {"type": "string"},
    },
    "required": ["id", "requestText", "voiceSystem"]
}

voice_text_request_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
    },
    "required": ["status"]
}

# Operation: discovery
# DiscoveryRequest and DiscoveryResponse
discovery_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
    },
    "required": ["id"]
}

discovery_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "ip": {"type": "string"},
        "deviceId": {"type": "string"},
    },
    "required": ["status", "ip", "deviceId"]
}

# Operation: version
# VersionRequest and VersionResponse
version_request_schema = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
    },
    "required": ["id"]
}

version_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": ["string", "null"]},
        "versions": {
            "type": "array",
            "items": {
                "type": "string"
            }
        },
    },
    "required": ["status", "versions"]
}

#StartLogCollectionRequest
start_log_collection_request_schema = {
    "type": "object",
    "properties": {
        "duration": { "type": "integer" },
        "logLevel": { "type": "string" },  # INFO, DEBUG, ERROR
        "logTypes": {
            "type": "array",
            "items": { "type": "string" }
        }
    },
    "required": ["duration"]
}

#StartLogCollectionResponce
start_log_collection_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"}
    },
    "required": ["status"]
}

#StopLogCollectionRequest
stop_log_collection_request_schema = {
    "type": "object",
    "properties": {}
}

#StopLogCollectionResponse
stop_log_collection_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "logs": {"type": "string"}  # or binary/file path depending on device
    },
    "required": ["status", "logs"]
}

# Operation: system/power-mode/get
# GetPowerModeRequest
power_mode_get_request_schema = dab_request_schema

# GetPowerModeResponse
power_mode_get_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "powerMode": {"type": "string"}
    },
    "required": ["status", "powerMode"]
}

# Operation: system/power-mode/set
# SetPowerModeRequest
power_mode_set_request_schema = {
    "type": "object",
    "properties": {
        "powerMode": {"type": "string"}
    },
    "required": ["powerMode"]
}

# SetPowerModeResponse
power_mode_set_response_schema = {
    "type": "object",
    "properties": {
        "status": {"type": "integer"},
        "error": {"type": "string"},
        "powerMode": {"type": "string"}
    },
    "required": ["status", "powerMode"]
}

class dab_response_validator(object):
    def __init__(self):
        pass

    @staticmethod
    def validate_dab_response_schema(response):
        validate(instance=jsons.loads(response), schema=dab_response_schema)

    @staticmethod
    def validate_list_supported_operation_response_schema(response):
        validate(instance=jsons.loads(response), schema=list_supported_operation_response_schema)

    @staticmethod
    def validate_list_applications_response_schema(response):
        validate(instance=jsons.loads(response), schema=list_applications_response_schema)

    @staticmethod
    def validate_launch_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=launch_application_response_schema)

    @staticmethod
    def validate_launch_application_with_content_response_schema(response):
        validate(instance=jsons.loads(response), schema=launch_application_with_content_response_schema)

    @staticmethod
    def validate_get_application_state_response_schema(response):
        validate(instance=jsons.loads(response), schema=get_application_state_response_schema)

    @staticmethod
    def validate_exit_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=exit_application_response_schema)

    @staticmethod
    def validate_install_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=install_application_response_schema)

    @staticmethod
    def validate_uninstall_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=uninstall_application_response_schema)

    @staticmethod
    def validate_clear_data_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=clear_data_application_response_schema)
    
    @staticmethod
    def validate_install_from_appstore_application_response_schema(response):
        validate(instance=jsons.loads(response), schema=install_from_appstore_application_response_schema)

    @staticmethod
    def validate_device_information_schema(response):
        validate(instance=jsons.loads(response), schema=device_information_schema)

    @staticmethod
    def validate_restart_response_schema(response):
        validate(instance=jsons.loads(response), schema=restart_response_schema)

    @staticmethod
    def validate_list_system_settings_schema(response):
        validate(instance=jsons.loads(response), schema=list_system_settings_schema)

    @staticmethod
    def validate_get_system_settings_response_schema(response):
        validate(instance=jsons.loads(response), schema=get_system_settings_response_schema)

    @staticmethod
    def validate_set_system_settings_response_schema(response):
        validate(instance=jsons.loads(response), schema=set_system_settings_response_schema)

    @staticmethod
    def validate_key_list_schema(response):
        validate(instance=jsons.loads(response), schema=key_list_schema)

    @staticmethod
    def validate_output_image_response_schema(response):
        validate(instance=jsons.loads(response), schema=output_image_response_schema)

    @staticmethod
    def validate_start_device_telemetry_response_schema(response):
        validate(instance=jsons.loads(response), schema=start_device_telemetry_response_schema)

    @staticmethod
    def validate_stop_device_telemetry_response_schema(response):
        validate(instance=jsons.loads(response), schema=stop_device_telemetry_response_schema)

    @staticmethod
    def validate_start_app_telemetry_response_schema(response):
        validate(instance=jsons.loads(response), schema=start_app_telemetry_response_schema)

    @staticmethod
    def validate_stop_app_telemetry_response_schema(response):
        validate(instance=jsons.loads(response), schema=stop_app_telemetry_response_schema)

    @staticmethod
    def validate_health_check_response_schema(response):
        validate(instance=jsons.loads(response), schema=health_check_response_schema)

    @staticmethod
    def validate_list_voice_response_schema(response):
        validate(instance=jsons.loads(response), schema=list_voice_response_schema)

    @staticmethod
    def validate_set_voice_system_response_schema(response):
        validate(instance=jsons.loads(response), schema=set_voice_system_response_schema)

    @staticmethod
    def validate_discovery_response_schema(response):
        validate(instance=jsons.loads(response), schema=discovery_response_schema)

    @staticmethod
    def validate_version_response_schema(response):
        validate(instance=jsons.loads(response), schema=version_response_schema)

    @staticmethod
    def validate_stop_log_collection_response_schema(response):
        validate(instance=jsons.loads(response), schema=stop_log_collection_response_schema)

    @staticmethod
    def validate_start_log_collection_response_schema(response):
        validate(instance=jsons.loads(response), schema=start_log_collection_response_schema)

    @staticmethod
    def validate_power_mode_set_response_schema(response):
        validate(instance=jsons.loads(response), schema=power_mode_set_response_schema)

    @staticmethod
    def validate_power_mode_get_response_schema(response):
        validate(instance=jsons.loads(response), schema=power_mode_get_response_schema)
