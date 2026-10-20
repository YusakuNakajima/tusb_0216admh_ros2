"""Constants of the Turtle Industry TUSB-0216ADMH.

Sources:
- USB descriptors: read with ``lsusb -v`` on the unit at OnoLab (2026-10-20).
- Everything else: TUSB-0216ADMH manual (TUSB0216ADMH_M2.pdf, 8c, 2025-05),
  chapters 5 and 6.5, and the vendor Python sample (ADMHSmplPy, 2024-06-05).
"""

# --- USB descriptors (measured) ---
# The product string reads "TUSB-0212ADMx": the PID seems to be shared by the
# ADM family, so a match on VID/PID alone does not prove it is a 0216ADMH.
USB_VENDOR_ID = 0x0BA0
USB_PRODUCT_ID = 0x0024
USB_INTERFACE = 0
USB_EP_OUT = 0x02  # Bulk OUT, 64 byte packets
USB_EP_IN = 0x81  # Bulk IN, 64 byte packets

# --- Device ID switch (rear rotary switch) ---
DEVICE_ID_MIN = 0
DEVICE_ID_MAX = 15

# --- Analog input ---
ADC_BITS = 16
ADC_FULL_SCALE_COUNTS = 1 << ADC_BITS  # 65536
INPUT_SPAN_V = 2.0  # both ranges span 2 V

# Tusbadmh_InputType: 0 = bipolar (-1..+1 V), 1 = unipolar (0..2 V)
INPUT_TYPE_BIPOLAR = 0
INPUT_TYPE_UNIPOLAR = 1
# Voltage at raw count 0 for each input type (straight offset binary)
INPUT_TYPE_OFFSET_V = {
    INPUT_TYPE_BIPOLAR: -1.0,
    INPUT_TYPE_UNIPOLAR: 0.0,
}

# --- Clock (Tusbadmh_Clock_Select) ---
# ClkSel -> source frequency in Hz. 5 is the external CLOCK input.
CLOCK_SOURCE_HZ = {
    0: 200.0e6,
    1: 20.48e6,
    2: 16.384e6,
    3: 12.8e6,
    4: 1.92e6,
}
CLOCK_SOURCE_EXTERNAL = 5
CLOCK_DIVIDER_MAX = 199  # Div, the source is divided by (Div + 1)
CLOCK_DIVIDER_MAX_EXTERNAL = 24
CONVERSION_CLOCK_MIN_HZ = 1.0e6
CONVERSION_CLOCK_MAX_HZ = 25.0e6
AVERAGING_EXPONENT_MAX = 8  # Ave, averages 2**Ave conversions per sample

# Continuous acquisition that the manual expects the USB link to sustain.
# Above this the device FIFO (1 Mi samples per channel) eventually overflows.
CONTINUOUS_RATE_LIMIT_2CH_HZ = 100.0e3
CONTINUOUS_RATE_LIMIT_1CH_HZ = 200.0e3
DEVICE_FIFO_SAMPLES_PER_CH = 1 << 20

# --- Acquisition (Tusbadmh_Adc_Start) ---
TRIGGER_EXTERNAL = 0
TRIGGER_RISING = 1
TRIGGER_FALLING = 2
TRIGGER_SOFTWARE = 3
TRIGGER_NAMES = {
    'external': TRIGGER_EXTERNAL,
    'rising': TRIGGER_RISING,
    'falling': TRIGGER_FALLING,
    'software': TRIGGER_SOFTWARE,
}
MODE_CONTINUOUS = 0
MODE_REPEAT = 1
CYCLE_LENGTH_MAX = 1 << 20
PRETRIGGER_LENGTH_MAX = 1 << 20

# Analog trigger (Tusbadmh_ThLevel_Set), in raw counts
TRIGGER_LEVEL_MIN = 1
TRIGGER_LEVEL_MAX = 65534
TRIGGER_NOISE_LEVEL_MAX = 3277

# Tusbadmh_Status_Get
STATUS_STOPPED = 0
STATUS_WAITING_TRIGGER = 1
STATUS_SAMPLING = 2
OVERFLOW_CH1 = 0x1
OVERFLOW_CH2 = 0x2

# Tusbadmh_TransLimit, in samples
TRANSFER_LIMIT_MIN = 100
TRANSFER_LIMIT_MAX = 100000
TRANSFER_LIMIT_DEFAULT = 50000

# --- Error codes returned by the vendor DLL (manual 6.6) ---
ERROR_MESSAGES = {
    0: 'success',
    1: 'wrong ID number',
    2: 'driver not installed',
    3: 'device already open',
    4: 'too many devices connected',
    5: 'could not open device',
    6: 'device not found',
    7: 'device not open',
    8: 'invalid parameter',
    9: 'USB communication error',
    10: 'out of memory',
    11: 'continuous acquisition running',
    12: 'no acquired data',
    13: 'continuous acquisition not started',
    14: 'memory overflow',
    15: 'data sequence error',
    99: 'other error',
}
