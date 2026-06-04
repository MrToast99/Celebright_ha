DOMAIN = "celebright"

# Config entry keys
CONF_EMAIL = "email"
CONF_PASSWORD = "password"

# AWS / Cognito (from HAR capture)
AWS_REGION = "ca-central-1"
COGNITO_CLIENT_ID = "24i7jos86etak1v53s7rtu5bf9"
COGNITO_USER_POOL_ID = "ca-central-1_lzEahW8hj"
COGNITO_IDENTITY_POOL_ID = "ca-central-1:b2c6822a-e037-4b88-923b-6baeb102cb02"
COGNITO_IDP_ENDPOINT = "https://cognito-idp.ca-central-1.amazonaws.com/"
COGNITO_IDENTITY_ENDPOINT = "https://cognito-identity.ca-central-1.amazonaws.com/"

# REST API (AWS API Gateway)
API_BASE = "https://app-api.celebright.com"
EP_GET_USER_DATA = "/getUserData"
EP_GET_DEVICE_STATUSES = "/getUserDeviceStatuses"
EP_GET_DEVICE_ZONES = "/getDeviceZones"
EP_GET_DEVICE_SCENES = "/getDeviceScenes"

# AWS IoT MQTT (from HAR capture)
IOT_ENDPOINT = "a153dwfz99hvwi-ats.iot.ca-central-1.amazonaws.com"

# MQTT topic structure: devices/{device_id}/v2/{direction}/{command}
# Subscribe: devices/{id}/v2/server/#  and  devices/{id}/v2/device/#
# Publish:   devices/{id}/v2/app/{command}
MQTT_CMD_SET_COLOR = "setColor"               # payload: {"color": "RRGGBB"}
MQTT_CMD_LOAD_SCENE = "loadSavedScene"        # payload: {"savedSceneUuid": "<uuid>"}
MQTT_CMD_RESUME_SCHEDULE = "setResumeSchedule"  # payload: {}
MQTT_CMD_GET_STATE = "getSystemState"         # payload: {"UTCTimeFromApp": epoch_int}
MQTT_STATE_SUBTOPIC = "systemState"           # inbound: devices/{id}/v2/device/systemState
MQTT_ACTIVE_SCENE_FIELD = "activeSavedScene"  # UUID in systemState when a scene is active

# Device status field names (getUserDeviceStatuses response)
STATUS_FIELD = "Status"
STATUS_ONLINE = "Online"
STATE_FIELD = "State"
SCHEDULE_ENABLED_FIELD = "Schedule Enabled"
CURRENT_DISPLAY_FIELD = "Current Display"
DISPLAY_OFF = "Off"

SCAN_INTERVAL_SECONDS = 30
