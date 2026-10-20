# One block of consecutive samples from a TUSB-0216ADMH.
#
# header.stamp is the estimated host time of the first sample in the block:
# trigger time + first_sample_index / sample_rate_hz. The trigger time is the
# host clock when the trigger was sent (software) or first seen by polling
# (external / analog), so the absolute time is only good to about one poll
# period; spacing within and between blocks is exact.
std_msgs/Header header

float64 sample_rate_hz       # per channel, Hz
uint64 first_sample_index    # samples since the trigger, per channel

float32[] ch1_v              # V
float32[] ch2_v              # V, empty when only ch1 is acquired

uint8 OVERFLOW_CH1 = 1
uint8 OVERFLOW_CH2 = 2
uint8 overflow               # overflow bits from Tusbadmh_Status_Get
