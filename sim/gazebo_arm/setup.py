from glob import glob

from setuptools import setup

package_name = "gazebo_arm"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        ("share/" + package_name + "/urdf", glob("urdf/*.urdf") + glob("urdf/*.xacro")),
        ("share/" + package_name + "/rviz", glob("rviz/*.rviz")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/worlds", glob("worlds/*.world")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="platform",
    maintainer_email="noreply@example.com",
    description="轻量实时仿真端：6R 液压机械臂 plant（ROS2）",
    license="Proprietary",
    entry_points={
        "console_scripts": [
            "plant_node = gazebo_arm.plant_node:main",
            "scene_node = gazebo_arm.scene_node:main",
            "gazebo_bridge = gazebo_arm.gazebo_bridge:main",
            "grasp_node = gazebo_arm.grasp_node:main",
        ],
    },
)
