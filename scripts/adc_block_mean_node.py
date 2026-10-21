#!/usr/bin/env python3
"""Publish the mean voltage of each AdcBlock as std_msgs/Float32, for plotting.

rqt_plot draws one point per message and has to unpack the whole sample array
of every AdcBlock, which gets slow. This node reduces each block (about 79
samples per channel at the default 3906.25 Hz) to its mean, so one light
Float32 arrives per block (about 50 Hz):

    ~/ch1_mean_v, ~/ch2_mean_v    std_msgs/Float32, V

    ros2 run rqt_plot rqt_plot /tusb_0216admh_mean/ch1_mean_v/data

For viewing only: averaging is a low-pass filter, so content faster than one
block (20 ms by default) is lost, and the Float32 carries no timestamp. Record
AdcBlock itself for analysis.
"""

import signal

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from tusb_0216admh_ros2.msg import AdcBlock


def block_mean_v(samples_v):
    """Mean of one channel of a block in V, or None for an empty channel."""
    if len(samples_v) == 0:
        return None
    return float(np.mean(np.asarray(samples_v, dtype=np.float64)))


class AdcBlockMeanNode(Node):

    def __init__(self):
        super().__init__('tusb_0216admh_mean')
        input_topic = self.declare_parameter(
            'input_topic', '/tusb_0216admh/adc_block').value
        self.pubs = (self.create_publisher(Float32, '~/ch1_mean_v', 10),
                     self.create_publisher(Float32, '~/ch2_mean_v', 10))
        self.create_subscription(AdcBlock, input_topic, self.on_block, 10)

    def on_block(self, msg):
        for pub, samples_v in zip(self.pubs, (msg.ch1_v, msg.ch2_v)):
            mean_v = block_mean_v(samples_v)
            if mean_v is not None:  # ch2 is empty with ch1_only
                pub.publish(Float32(data=mean_v))


def main():
    rclpy.init()
    node = AdcBlockMeanNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # ros2 launch sends Ctrl-C twice
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
