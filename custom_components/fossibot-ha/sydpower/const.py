# New SYDPOWER Local MQTT API
API_BASE_URL = "https://api.app.sydpower.com/http/router/client/device"
API_GET_DEVICE_LIST = f"{API_BASE_URL}/saas.pub_getDeviceList"
API_UPDATE_MQTT_STATE = f"{API_BASE_URL}/saas.pub_updateMqttState"

# Default MQTT port for local broker
DEFAULT_MQTT_PORT = 1883

# ---------------------------------------------------------------------------
# Modbus framing
#
# Slave address 17 (0x11) matches the "Slave Address 11" example throughout
# the Sydpower "Modbus RTU Protocol" document (Inverter-Protocol-V0).
#
# A device may override this via productInfo.modbus_address from the API.
# ---------------------------------------------------------------------------
REGISTER_MODBUS_ADDRESS = 17

# The protocol caps a single read at 100 words and requires the range to sit
# inside one 100-register block ("0~99 or 200~299 are OK, but 40~139 is not").
#
# Every documented V0 register — holding 0..79 and input 0..71 — falls inside
# the first 80 words, so an 80-word read covers the whole map. The read count
# is deliberately left at 80 rather than raised to the 100-word maximum: it is
# the count the devices are known to answer, and reading further buys nothing.
MODBUS_READ_COUNT = 80
MODBUS_MAX_READ_COUNT = 100

# ---------------------------------------------------------------------------
# Holding registers (function 03) — settings / device identity
# Source: Inverter-Protocol-V0.docx section 3.1
# ---------------------------------------------------------------------------
HREG_FACTORY_RESET = 0
HREG_DEBUG_MODE = 1
HREG_CHIP_TYPE = 2
HREG_VALUE_ADDRESS = 3
HREG_TIMEZONE = 4
HREG_PROTOCOL_VERSION = 5
HREG_DEVICE_TYPE_MODEL = 11
HREG_VOLTAGE_FREQ_TYPE = 12
HREG_AC_CHARGE_LEVEL = 13
HREG_AC_CHARGE_MAX_POWER = 14
HREG_DC_INPUT_TYPE = 15
HREG_DC_INPUT_MAX_POWER = 16
HREG_DC_INPUT_MAX_CURRENT = 17
HREG_DC_INPUT_MIN_VOLTAGE = 18
HREG_DC_INPUT_MAX_VOLTAGE = 19
HREG_DC_INPUT_CURRENT_SET = 20
HREG_QC_USB_CODE = 21
HREG_PD_LED_CODE = 22
HREG_USB_KEY = 24
HREG_DC_KEY = 25
HREG_AC_KEY = 26
HREG_LED_KEY = 27
HREG_PORT_XT60 = 30
HREG_PORT_CIGARETTE = 31
HREG_PORT_5521 = 32
HREG_WIRELESS_DISCHARGER = 35
HREG_WIRELESS_COM = 37
HREG_BATTERY_INFO = 40
HREG_BATTERY_PACK_FRAME = 41
HREG_FUNCTION_CODE_H = 44
HREG_FUNCTION_CODE_L = 45
HREG_VERSION_AC = 47
HREG_VERSION_BMS = 48
HREG_VERSION_PV = 49
HREG_VERSION_PANEL = 50
HREG_VERSION_EXTERNAL_COM = 51
HREG_WIFI_UPLOAD_INTERVAL = 54
HREG_BUZZER = 56
HREG_SILENT_CHARGING = 57
HREG_USB_SLEEP_TIME = 59
HREG_AC_SLEEP_TIME = 60
HREG_DC_SLEEP_TIME = 61
HREG_LCD_DIM_TIME = 62
HREG_AC_CHARGE_APPOINTMENT = 63
HREG_APP_CONTROL_SLEEP = 64
HREG_DISCHARGE_SOC_MIN = 66
HREG_CHARGE_SOC_MAX = 67
HREG_SHUTDOWN_WAIT_TIME = 68
HREG_LOW_BATTERY_NOTIFY = 69
HREG_GRID_AC_AUTO_OUTPUT = 70
HREG_SERIAL_FIRST = 72
HREG_SERIAL_LAST = 79

# ---------------------------------------------------------------------------
# Input registers (function 04) — live measurements / status
# Source: Inverter-Protocol-V0.docx section 3.2
# ---------------------------------------------------------------------------
IREG_AC_CHARGE_LEVEL = 2
IREG_AC_CHARGE_POWER = 3
IREG_DC_CHARGE_POWER = 4
IREG_TYPEC_CHARGE_POWER = 5
IREG_TOTAL_CHARGE_POWER = 6
IREG_XT60_POWER = 8
IREG_CIGARETTE_POWER = 9
IREG_5521_POWER = 10
IREG_WIRELESS_POWER = 13
IREG_STORAGE_FLAG = 14
IREG_LED_POWER = 15
IREG_INV_OUTPUT_POWER = 16
IREG_INV_OUTPUT_VA = 17
IREG_AC_OUTPUT_VOLTAGE = 18
IREG_AC_OUTPUT_FREQUENCY = 19
IREG_AC_OUTPUT_POWER = 20
IREG_GRID_VOLTAGE = 21
IREG_GRID_FREQUENCY = 22
IREG_LIGHT_MODE = 25
IREG_USB1_POWER = 26
IREG_USB2_POWER = 27
IREG_USB3_POWER = 28
IREG_QC1_POWER = 30
IREG_QC2_POWER = 31
IREG_QC3_POWER = 32
IREG_PD1_POWER = 34
IREG_PD2_POWER = 35
IREG_PD3_POWER = 36
IREG_PD4_POWER = 37
IREG_PD5_POWER = 38
IREG_TOTAL_DISCHARGE_POWER = 39
IREG_SYSTEM_STATE_H = 41
IREG_SYSTEM_STATE_L = 42
IREG_FAULT_AC = 43
IREG_FAULT_AC_2 = 44
IREG_FAULT_PV = 45
IREG_FAULT_HIGH_PV = 46
IREG_BMS_AFE_STATUS = 47
IREG_BMS_USER_STATUS = 48
IREG_FAULT_PANEL_H = 50
IREG_FAULT_PANEL_L = 51
IREG_SLAVE_BATTERY_1 = 53
IREG_BATTERY_USABLE_CAPACITY = 54
IREG_SLAVE_BATTERY_2 = 55
IREG_BATTERY_SOC = 56
IREG_CHARGE_APPOINTMENT_REMAINING = 57
IREG_REMAINING_CHARGE_TIME = 58
IREG_REMAINING_DISCHARGE_TIME = 59
IREG_PV_ENERGY_TOTAL = 60
IREG_SLAVE_BATTERY_3 = 66
IREG_SLAVE_BATTERY_4 = 67
IREG_DISCHARGE_SOC_AVG = 70
IREG_CHARGE_SOC_AVG = 71

# ---------------------------------------------------------------------------
# Legacy aliases
#
# These names predate the protocol documentation and are referenced by
# modbus.py, the entity platforms and the test-suite. They are kept so that
# existing imports keep working; prefer the HREG_*/IREG_* names above, which
# make the register group (holding vs input) explicit.
# ---------------------------------------------------------------------------
REGISTER_TOTAL_INPUT = IREG_TOTAL_CHARGE_POWER            # input 06
REGISTER_DC_INPUT = IREG_DC_CHARGE_POWER                  # input 04
REGISTER_TOTAL_OUTPUT = IREG_TOTAL_DISCHARGE_POWER        # input 39
REGISTER_ACTIVE_OUTPUT_LIST = IREG_SYSTEM_STATE_H         # input 41
REGISTER_STATE_OF_CHARGE = IREG_BATTERY_SOC               # input 56

REGISTER_MAXIMUM_CHARGING_CURRENT = HREG_DC_INPUT_CURRENT_SET  # holding 20
REGISTER_USB_OUTPUT = HREG_USB_KEY                        # holding 24
REGISTER_DC_OUTPUT = HREG_DC_KEY                          # holding 25
REGISTER_AC_OUTPUT = HREG_AC_KEY                          # holding 26
REGISTER_LED = HREG_LED_KEY                               # holding 27
REGISTER_AC_SILENT_CHARGING = HREG_SILENT_CHARGING        # holding 57
REGISTER_USB_STANDBY_TIME = HREG_USB_SLEEP_TIME           # holding 59
REGISTER_AC_STANDBY_TIME = HREG_AC_SLEEP_TIME             # holding 60
REGISTER_DC_STANDBY_TIME = HREG_DC_SLEEP_TIME             # holding 61
REGISTER_SCREEN_REST_TIME = HREG_LCD_DIM_TIME             # holding 62
REGISTER_STOP_CHARGE_AFTER = HREG_AC_CHARGE_APPOINTMENT   # holding 63
REGISTER_DISCHARGE_LIMIT = HREG_DISCHARGE_SOC_MIN         # holding 66
REGISTER_CHARGING_LIMIT = HREG_CHARGE_SOC_MAX             # holding 67
REGISTER_SLEEP_TIME = HREG_SHUTDOWN_WAIT_TIME             # holding 68

# ---------------------------------------------------------------------------
# Enumerations from the protocol appendix
# ---------------------------------------------------------------------------

# Holding 40, high byte
BATTERY_TYPES = {
    1: "Ternary lithium",
    2: "LiFePO4",
    3: "Lead acid",
}

# Holding 11, high byte (&*2 "Device Type")
DEVICE_MARKET_TYPES = {
    0: "Portable Power Station 110V",
    1: "Portable Power Station 230V",
}

# Holding 15, low byte
DC_INPUT_TYPES = {
    0: "MPPT (PV)",
    1: "DC source",
}

# Input 25, low byte
LIGHT_MODES = {
    0: "Off",
    1: "On",
    2: "SOS",
    3: "Flash",
}

# Holding 12, bits 15..3 (&*3 "Voltage Type") — one bit per supported voltage
VOLTAGE_TYPE_BITS = {
    10: "110V",
    9: "380V",
    8: "230V",
    7: "220V",
    6: "240V",
    5: "120V",
    4: "200V",
    3: "100V",
}

# Holding 12, bits 2..0 (&*3 "Freq Type")
FREQ_TYPES = {
    1: "50Hz",
    2: "60Hz",
}

# Holding 37, low byte (&*6 "WireLess COM") — one bit per fitted radio
WIRELESS_COM_BITS = {
    4: "ZigBee",
    3: "LoRa",
    2: "GPRS",
    1: "Bluetooth",
    0: "Wi-Fi",
}
