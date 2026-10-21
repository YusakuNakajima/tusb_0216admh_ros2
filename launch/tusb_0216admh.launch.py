# tusb_0216admh.launch.py
#
# TUSB-0216ADMH の AD 値を ~/adc_block（tusb_0216admh_ros2/msg/AdcBlock）に流す。
#   ros2 launch tusb_0216admh_ros2 tusb_0216admh.launch.py backend:=mock
# 取り込み設定は config/tusb_0216admh.yaml。
# mean:=true で、ブロックごとの平均電圧を std_msgs/Float32 で流す可視化用ノードも起動する
# （/tusb_0216admh_mean/ch1_mean_v, ch2_mean_v。rqt_plot 向け）。

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    config = LaunchConfiguration('config')
    backend = LaunchConfiguration('backend')
    mean = LaunchConfiguration('mean')
    return LaunchDescription([
        DeclareLaunchArgument(
            'config',
            default_value=PathJoinSubstitution(
                [FindPackageShare('tusb_0216admh_ros2'), 'config', 'tusb_0216admh.yaml']),
            description='parameter file'),
        DeclareLaunchArgument(
            'backend', default_value='usb', description='usb | mock'),
        DeclareLaunchArgument(
            'mean', default_value='false',
            description='also publish the per-block mean voltage as Float32 for plotting'),
        Node(
            package='tusb_0216admh_ros2',
            executable='tusb_0216admh_node.py',
            name='tusb_0216admh',
            output='screen',
            parameters=[config, {'backend': backend}],
        ),
        Node(
            package='tusb_0216admh_ros2',
            executable='adc_block_mean_node.py',
            name='tusb_0216admh_mean',
            output='screen',
            condition=IfCondition(mean),
        ),
    ])
