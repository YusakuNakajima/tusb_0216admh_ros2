"""The node rejects bad settings before it opens the device."""

import importlib.util
import os

import numpy as np
import pytest
import rclpy
import rclpy.time
from rclpy.parameter import Parameter

SCRIPT = os.path.join(os.path.dirname(__file__), '..', 'scripts', 'tusb_0216admh_node.py')


@pytest.fixture(scope='module')
def node_module():
    spec = importlib.util.spec_from_file_location('tusb_0216admh_node', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rclpy.init()
    yield module
    rclpy.shutdown()


class RecordingDevice:
    """Fails the test if the node touches the device."""

    opened = False

    def open(self):
        RecordingDevice.opened = True


@pytest.fixture
def device(node_module, monkeypatch):
    RecordingDevice.opened = False
    monkeypatch.setattr(node_module, 'create_device', lambda *a, **k: RecordingDevice())
    return RecordingDevice


@pytest.mark.parametrize('overrides', [
    {'trigger': 'rising', 'trigger_level_v': 2.0},          # outside +-1 V
    {'trigger': 'falling', 'trigger_noise_level_v': -0.01},
    {'max_block_samples': 0},
    {'max_block_samples': -5},
    {'poll_period_s': -1.0},
    {'poll_period_s': 0.0},
    {'pretrigger_samples': 100},                            # with the software trigger
    {'pretrigger_samples': -1, 'trigger': 'external'},
    {'trigger': 'sometimes'},
])
def test_bad_settings_are_rejected_before_open(node_module, device, monkeypatch, overrides):
    params = [Parameter(k, value=v) for k, v in {'backend': 'mock', **overrides}.items()]
    original = rclpy.node.Node.__init__

    def init_with_overrides(self, name, **kwargs):
        original(self, name, parameter_overrides=params, **kwargs)

    monkeypatch.setattr(rclpy.node.Node, '__init__', init_with_overrides)
    with pytest.raises(ValueError):
        node_module.Tusb0216AdmhNode()
    assert not device.opened


def test_mock_with_pretrigger_fails_and_closes_the_device(node_module, monkeypatch):
    from tusb_0216admh.device import AdmhError
    from tusb_0216admh.mock_device import MockTusbAdmhDevice

    created = []

    def create(*args, **kwargs):
        created.append(MockTusbAdmhDevice())
        return created[-1]

    monkeypatch.setattr(node_module, 'create_device', create)
    params = [Parameter('backend', value='mock'), Parameter('trigger', value='external'),
              Parameter('pretrigger_samples', value=100)]
    original = rclpy.node.Node.__init__
    monkeypatch.setattr(rclpy.node.Node, '__init__',
                        lambda self, name, **kw: original(self, name,
                                                          parameter_overrides=params, **kw))
    with pytest.raises(AdmhError):
        node_module.Tusb0216AdmhNode()
    assert not created[0]._is_open


class FakeDevice:
    def read(self, channel, n):
        return np.full(n, 0x8000, dtype=np.uint16)


class FakePublisher:
    def __init__(self):
        self.msgs = []

    def publish(self, msg):
        self.msgs.append(msg)


def test_stamp_before_the_clock_origin(node_module):
    # Trigger seen at t = 1 s with 10000 pretrigger samples at 3906.25 Hz:
    # the first sample is 2.56 s earlier, at -1.56 s.
    node = object.__new__(node_module.Tusb0216AdmhNode)
    node.trigger_time = rclpy.time.Time(nanoseconds=1_000_000_000)
    node.pretrigger_samples = 10000
    node.published_samples = 0
    node.sample_rate_hz = 3906.25
    node.frame_id = 'f'
    node.ch1_only = False
    node.input_types = (0, 0)
    node.device = FakeDevice()
    node.pub = FakePublisher()
    node.publish_block(5, 0)
    stamp = node.pub.msgs[0].header.stamp
    assert (stamp.sec, stamp.nanosec) == (-2, 440_000_000)
    assert node.published_samples == 5
    assert list(node.pub.msgs[0].ch1_v) == [0.0] * 5
