"""ROS 2 controls and live visualization for the simulated arm."""

import math
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import ttk

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import Point
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray
from visualization_msgs.msg import Marker, MarkerArray

from .end_effector import JOINT_NAMES, EndEffector


class ControlPanel(Node):
    def __init__(self, window):
        super().__init__("arm_control_panel")
        self.window = window
        self.declare_parameter("read_only", False)
        self.read_only = self.get_parameter("read_only").value
        urdf = Path(get_package_share_directory("gazebo_arm")) / "urdf" / "hydraulic_arm.urdf"
        self.kinematics = EndEffector(urdf)
        self.command = self.create_publisher(Float64MultiArray, "joint_command", 10)
        self.markers = self.create_publisher(MarkerArray, "arm_trajectory", 10)
        self.create_subscription(JointState, "joint_states", self.on_state, 10)
        self.position = None
        self.target = None
        self.path = deque(maxlen=180)

        window.title("机械臂仿真控制")
        content = ttk.Frame(window, padding=16)
        content.pack(fill="both", expand=True)
        content.columnconfigure(1, weight=1)
        headings = ("关节", "", "角度读数（rad）") if self.read_only else ("关节", "目标角（rad）", "角度读数（rad）")
        for column, title in enumerate(headings):
            ttk.Label(content, text=title).grid(row=0, column=column, padx=8, pady=6, sticky="w")
        self.sliders = []
        self.readings = []
        for index, (name, (low, high)) in enumerate(zip(JOINT_NAMES, self.kinematics.limits), 1):
            ttk.Label(content, text=name).grid(row=index, column=0, sticky="w")
            slider = tk.Scale(content, from_=low, to=high, resolution=0.0001, digits=5,
                              orient="horizontal", length=330, state="disabled")
            if not self.read_only:
                slider.grid(row=index, column=1, sticky="ew", padx=8)
            reading = ttk.Label(content, text="—", width=12)
            reading.grid(row=index, column=2, sticky="w")
            self.sliders.append(slider)
            self.readings.append(reading)
        self.pose_readout = ttk.Label(content, text="等待仿真状态")
        self.pose_readout.grid(row=7, column=0, columnspan=3, sticky="w", pady=(12, 4))
        ttk.Button(content, text="清空轨迹", command=self.path.clear).grid(row=8, column=0, sticky="w")
        self.create_timer(0.05, self.refresh)

    def on_state(self, msg):
        if len(msg.name) != len(msg.position):
            return
        states = dict(zip(msg.name, msg.position))
        if not all(name in states and math.isfinite(states[name]) for name in JOINT_NAMES):
            return
        self.position = tuple(states[name] for name in JOINT_NAMES)
        if self.target is None:
            for slider, value in zip(self.sliders, self.position):
                if not self.read_only:
                    slider.configure(state="normal")
                slider.set(value)
            self.target = tuple(slider.get() for slider in self.sliders)

    def refresh(self):
        if self.position is None:
            return
        if not self.read_only:
            target = tuple(slider.get() for slider in self.sliders)
            # Retry a pending drag until the plant's command subscription is discovered.
            if target != self.target and self.command.get_subscription_count():
                self.command.publish(Float64MultiArray(data=list(target)))
                self.target = target
        x, y, z, roll, pitch, yaw = self.kinematics.pose(self.position)
        for label, value in zip(self.readings, self.position):
            label.configure(text=f"{value:+.4f}")
        self.pose_readout.configure(text=f"XYZ (m)  {x:+.3f}  {y:+.3f}  {z:+.3f}\n"
                                         f"RPY (rad)  {roll:+.3f}  {pitch:+.3f}  {yaw:+.3f}")
        point = Point(x=x, y=y, z=z)
        if not self.path or math.dist((x, y, z), (self.path[-1].x, self.path[-1].y, self.path[-1].z)) >= 0.004:
            self.path.append(point)
        track = self.marker(0, Marker.LINE_STRIP)
        track.scale.x = 0.0025
        track.color.r = track.color.g = track.color.b = 0.29
        track.points = list(self.path)
        markers = [track]
        if not self.read_only:
            goal = self.marker(1, Marker.SPHERE)
            gx, gy, gz, *_ = self.kinematics.pose(self.target)
            goal.pose.position = Point(x=gx, y=gy, z=gz)
            goal.scale.x = goal.scale.y = goal.scale.z = 0.018
            goal.color.r = goal.color.g = goal.color.b = 0.18
            markers.append(goal)
        self.markers.publish(MarkerArray(markers=markers))

    def marker(self, marker_id, marker_type):
        marker = Marker(id=marker_id, ns="end_effector", type=marker_type)
        marker.header.frame_id = "base_link"
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.pose.orientation.w = 1.0
        marker.color.a = 1.0
        return marker


def main(args=None):
    rclpy.init(args=args)
    window = tk.Tk()
    panel = ControlPanel(window)

    def spin():
        rclpy.spin_once(panel, timeout_sec=0)
        window.after(5, spin)

    window.after(0, spin)
    try:
        window.mainloop()
    finally:
        panel.destroy_node()
        rclpy.try_shutdown()
