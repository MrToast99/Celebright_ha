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
EP_GET_DEVICE_EVENTS = "/getDeviceEvents"  # v3 event format

# AWS AppSync GraphQL — live device status (from HAR capture)
APPSYNC_URL = "https://4n5p3mnjnbdrdcuwf3v5o5r7jq.appsync-api.ca-central-1.amazonaws.com/graphql"

# AWS IoT MQTT (from HAR capture)
IOT_ENDPOINT = "a153dwfz99hvwi-ats.iot.ca-central-1.amazonaws.com"

# MQTT topics: devices/{id}/{protocol}/{app|device|server}/{command}
# Firmware 3.x speaks "v3", older "v2"; a command on the wrong version is silently
# ignored, so the protocol is probed per device (newest first).
MQTT_PROTOCOLS = ("v3", "v2")
MQTT_DEFAULT_PROTOCOL = "v3"
MQTT_CMD_SET_COLOR = "setColor"               # payload: {"color": "RRGGBB"}
MQTT_CMD_LOAD_SCENE = "loadSavedScene"        # payload: {"savedSceneUuid": "<uuid>"}
MQTT_CMD_RESUME_SCHEDULE = "setResumeSchedule"  # payload: {}
MQTT_CMD_GET_STATE = "getSystemState"         # payload: {"UTCTimeFromApp": epoch_int}
MQTT_STATE_SUBTOPIC = "systemState"           # inbound: devices/{id}/v2/device/systemState
MQTT_ACTIVE_SCENE_FIELD = "activeSavedScene"  # v2 systemState: active scene UUID
# v2 colour/brightness keys: guessed from setColor's field name, never verified.
MQTT_STATE_COLOR_FIELD = "color"              # RRGGBB hex string, if present
MQTT_STATE_BRIGHTNESS_FIELD = "brightness"    # 0-255, if the device reports it separately

# Device status field names (getUserDeviceStatuses response)
STATUS_FIELD = "Status"
STATUS_ONLINE = "Online"
STATE_FIELD = "State"
SCHEDULE_ENABLED_FIELD = "Schedule Enabled"
CURRENT_DISPLAY_FIELD = "Current Display"
DISPLAY_OFF = "Off"

SCAN_INTERVAL_SECONDS = 30
