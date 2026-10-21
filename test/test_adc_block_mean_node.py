"""adc_block_mean_node reduces each AdcBlock to one Float32 per channel."""

import array
import importlib.util
import os

import pytest
import rclpy
from tusb_0216admh_ros2.msg import AdcBlock

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'adc_block_mean_node.py')


@pytest.fixture(scope='module')
def mod():
    spec = importlib.util.spec_from_file_location('adc_block_mean_node', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rclpy.init()
    yield module
    rclpy.shutdown()


def test_block_mean_v(mod):
    assert mod.block_mean_v(array.array('f', [0.1, 0.2, 0.3, 0.4])) == pytest.approx(0.25)
    assert mod.block_mean_v(array.array('f')) is None


class FakePublisher:
    def __init__(self):
        self.data = []

    def publish(self, msg):
        self.data.append(msg.data)


def test_publishes_one_mean_per_channel_and_skips_an_empty_ch2(mod):
    node = mod.AdcBlockMeanNode()
    try:
        node.pubs = (FakePublisher(), FakePublisher())
        msg = AdcBlock()
        msg.ch1_v = array.array('f', [-0.5, 0.5, 1.0])
        msg.ch2_v = array.array('f', [0.25, 0.25])
        node.on_block(msg)
        msg.ch2_v = array.array('f')  # ch1_only
        node.on_block(msg)
        assert node.pubs[0].data == [pytest.approx(1.0 / 3), pytest.approx(1.0 / 3)]
        assert node.pubs[1].data == [pytest.approx(0.25)]
    finally:
        node.destroy_node()
