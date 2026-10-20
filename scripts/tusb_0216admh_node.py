#!/usr/bin/env python3
"""Publish TUSB-0216ADMH samples as tusb_0216admh_ros2/msg/AdcBlock.

Runs one continuous acquisition from startup to shutdown and publishes every
sample in order on ~/adc_block. The acquisition stops, and the node exits,
on a FIFO overflow, so a gap in the data is never published silently.
"""

import array

import numpy as np
import rclpy
from rclpy.duration import Duration
from rclpy.node import Node
from tusb_0216admh import constants as c
from tusb_0216admh import conversion
from tusb_0216admh_ros2.msg import AdcBlock
from tusb_0216admh.usb_device import create_device


class AcquisitionStopped(Exception):
    pass


class Tusb0216AdmhNode(Node):

    def __init__(self):
        super().__init__('tusb_0216admh')
        p = self.declare_parameter
        self.backend = p('backend', 'usb').value  # 'usb' or 'mock'
        self.device_id = p('device_id', 0).value  # rear ID switch, 0..15
        self.usb_index = p('usb_index', 0).value
        self.frame_id = p('frame_id', 'tusb_0216admh').value
        ch1_range = p('ch1_input_range', 'bipolar').value  # 'bipolar' or 'unipolar'
        ch2_range = p('ch2_input_range', 'bipolar').value
        self.clock_source = p('clock_source', 0).value  # ClkSel, 0..5
        self.clock_divider = p('clock_divider', 199).value  # Div, 0..199
        self.averaging_exponent = p('averaging_exponent', 8).value  # Ave, 0..8
        self.external_clock_hz = p('external_clock_hz', 0.0).value
        trigger_name = p('trigger', 'software').value
        self.trigger_level_v = p('trigger_level_v', 0.0).value
        self.trigger_noise_level_v = p('trigger_noise_level_v', 0.0244).value
        self.pretrigger_samples = p('pretrigger_samples', 0).value
        self.ch1_only = p('ch1_only', False).value
        self.poll_period_s = p('poll_period_s', 0.02).value
        self.max_block_samples = p('max_block_samples', 10000).value

        self.input_types = (conversion.input_type_from_name(ch1_range),
                            conversion.input_type_from_name(ch2_range))
        if trigger_name not in c.TRIGGER_NAMES:
            raise ValueError(f'trigger must be one of {sorted(c.TRIGGER_NAMES)}')
        self.trigger = c.TRIGGER_NAMES[trigger_name]
        self.sample_rate_hz = conversion.sample_rate_hz(
            self.clock_source, self.clock_divider, self.averaging_exponent,
            self.external_clock_hz or None)
        limit_hz = conversion.continuous_rate_limit_hz(self.ch1_only)
        if self.sample_rate_hz > limit_hz:
            self.get_logger().warn(
                f'{self.sample_rate_hz:.1f} Hz exceeds the {limit_hz:.0f} Hz the manual '
                'expects for continuous acquisition; expect a FIFO overflow')

        self.pub = self.create_publisher(AdcBlock, '~/adc_block', 10)
        kwargs = {'usb_index': self.usb_index} if self.backend == 'usb' else {}
        self.device = create_device(self.backend, self.device_id, **kwargs)
        self.trigger_time = None
        self.published_samples = 0
        self.running = False

        self.device.open()
        try:
            self.configure_and_start()
        except BaseException:
            self.shutdown()
            raise
        self.timer = self.create_timer(self.poll_period_s, self.poll)

    def configure_and_start(self):
        d = self.device
        d.set_input_type(*self.input_types)
        d.select_clock(self.clock_source, self.clock_divider, self.averaging_exponent)
        if self.trigger in (c.TRIGGER_RISING, c.TRIGGER_FALLING):
            # Level and noise band are raw counts, referred to the ch1 range.
            level = conversion.volts_to_counts(self.trigger_level_v, self.input_types[0])
            noise = round(self.trigger_noise_level_v * c.ADC_FULL_SCALE_COUNTS
                          / c.INPUT_SPAN_V)
            d.set_trigger_level(
                max(c.TRIGGER_LEVEL_MIN, min(c.TRIGGER_LEVEL_MAX, level)),
                max(0, min(c.TRIGGER_NOISE_LEVEL_MAX, noise)))
        d.start(1, self.pretrigger_samples, self.trigger, c.MODE_CONTINUOUS,
                int(self.ch1_only))
        self.running = True
        if self.trigger == c.TRIGGER_SOFTWARE:
            d.trigger()
            self.trigger_time = self.get_clock().now()
        self.get_logger().info(
            f'acquiring at {self.sample_rate_hz:.3f} Hz per channel '
            f'({self.backend} backend, trigger {self.trigger})')

    def poll(self):
        status, overflow = self.device.status()
        if self.trigger_time is None:
            if status != c.STATUS_SAMPLING:
                return
            self.trigger_time = self.get_clock().now()
            self.get_logger().info('trigger detected')

        ch1_len, ch2_len, _, _ = self.device.length()
        n = ch1_len if self.ch1_only else min(ch1_len, ch2_len)
        while n > 0:
            block = min(n, self.max_block_samples)
            self.publish_block(block, overflow)
            n -= block

        if overflow or status == c.STATUS_STOPPED:
            self.get_logger().error(
                f'acquisition stopped (status {status}, overflow bits {overflow}) after '
                f'{self.published_samples} samples per channel; exiting')
            raise AcquisitionStopped()

    def publish_block(self, n, overflow):
        msg = AdcBlock()
        offset_ns = round(self.published_samples * 1e9 / self.sample_rate_hz)
        msg.header.stamp = (self.trigger_time
                            + Duration(nanoseconds=offset_ns)).to_msg()
        msg.header.frame_id = self.frame_id
        msg.sample_rate_hz = self.sample_rate_hz
        msg.first_sample_index = self.published_samples
        msg.ch1_v = self.read_volts(0, n)
        if not self.ch1_only:
            msg.ch2_v = self.read_volts(1, n)
        msg.overflow = overflow
        self.pub.publish(msg)
        self.published_samples += n

    def read_volts(self, channel, n):
        counts = self.device.read(channel, n)
        if len(counts) != n:
            raise RuntimeError(f'ch{channel + 1}: asked for {n} samples, got {len(counts)}')
        volts = conversion.counts_to_volts(counts.astype(np.float32),
                                           self.input_types[channel])
        return array.array('f', volts.astype(np.float32).tobytes())

    def shutdown(self):
        try:
            if self.running:
                self.device.stop()
        finally:
            self.running = False
            self.device.close()


def main():
    rclpy.init()
    node = None
    try:
        node = Tusb0216AdmhNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, AcquisitionStopped):
        pass
    finally:
        if node is not None:
            node.shutdown()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
