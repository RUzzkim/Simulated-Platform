from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_share = get_package_share_directory('edge_node')
    config_file = os.path.join(pkg_share, 'config', 'edge_config.yaml')

    return LaunchDescription([
        Node(
            package='edge_node',
            executable='edge_node',
            name='edge_node',
            output='screen',
            parameters=[config_file],
            arguments=['--config', config_file],
        ),
    ])
