# tusb_0216admh.launch.py
#
# TUSB-0216ADMH の AD 値を ~/adc_block（tusb_0216admh_ros2/msg/AdcBlock）に流す。
#   ros2 launch tusb_0216admh_ros2 tusb_0216admh.launch.py backend:=mock
# 取り込み設定は config/tusb_0216admh.yaml。

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config = LaunchConfiguration('config')
    backend = LaunchConfiguration('backend')
    return LaunchDescription([
        DeclareLaunchArgument(
            'config',
            default_value=PathJoinSubstitution(
                [FindPackageShare('tusb_0216admh_ros2'), 'config', 'tusb_0216admh.yaml']),
            description='parameter file'),
        DeclareLaunchArgument(
            'backend', default_value='usb', description='usb | mock'),
        Node(
            package='tusb_0216admh_ros2',
            executable='tusb_0216admh_node.py',
            name='tusb_0216admh',
            output='screen',
            parameters=[config, {'backend': backend}],
        ),
    ])
