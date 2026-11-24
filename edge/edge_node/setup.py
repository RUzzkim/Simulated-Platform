from setuptools import setup
import os
from glob import glob

package_name = 'edge_node'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='edge',
    maintainer_email='edge@industrial-robot.local',
    description='工业机械臂仿真平台 - 边端节点',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'edge_node = edge_node.main:main',
        ],
    },
)
