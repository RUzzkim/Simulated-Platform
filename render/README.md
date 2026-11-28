# 成员 A 机械臂申报素材

成品在 `outputs/frames/` 和 `outputs/animations/`。导入和渲染直接读取仓库的 URDF、网格和 CSV。装配外形、材质和灯光在 Blender 端生成。

```text
render/
  import_urdf.py
  mechanical_details.py
  setup_scene.py
  trajectory_data.py
  verify_assembly.py
  render_stills.py
  animate_from_csv.py
  checks/                  Blender 场景、阶段检查表数据和抽帧证据
  outputs/
    frames/
      pose_home.png
      pose_elbow_bent.png
      pose_shoulder_lock.png
    animations/
      normal_cycle.mp4
      lock_event.mp4
```

## 装配外观修订

| 部位 | 对照和修订 | 证据 |
| --- | --- | --- |
| 底座与肩部 | 生成图能看清固定底板和转台之间的分界。原模型的螺栓头低于底板顶面。新版把四组螺栓和垫圈坐在固定底板上，回转组件与固定密封环分开。肩部轴销留在支座上，轴套随上臂转动 | [底座特写](checks/base_detail.png) · [ABB IRB 1200 安装手册](https://library.e.abb.com/public/9756cb53ed724a54a56fb365b6fa0bbc/3HAC046983%20PM%20IRB%201200-en.pdf) |
| 肘部与腕部 | 生成图把轴端、壳体和连接缝表现为不同零件。新版让上臂的两片叉耳跨在肘轴套外侧，前臂随轴套转动。腕部用叉架、转轴和法兰表达两根相交的旋转轴。沿用教程中把网格绑定到各自 link、由 joint 描述轴线的建模方法 | [肘部前后对比](checks/assembly_compare_elbow_detail.png) · [腕部前后对比](checks/assembly_compare_tool_detail.png) · [XBot-Arm 教程 URDF](https://github.com/jiuyewxy/ros_arm_tutorials/blob/melodic-devel/darm/urdf/darm.urdf) |
| 夹爪 | 生成图的夹指安装在独立壳体前端。新版由封闭壳体、平行导轨、左右滑座和双指组成。教程夹指为转动关节，本项目的夹指采用原有固定开口姿态，双指原点间距 212 mm | [夹爪正面](checks/jaw_detail.png) · [SCHUNK PGN-plus-E 装配手册](https://qa.stb.cloud.schunk.com/media/IM0021323.PDF) |
| 检查范围 | 从正常、卡滞和搬运数据的 2450 条记录提取角度范围。用三角网格相交检查覆盖六轴对应的底座回转、肩部、肘部、腕部两轴和末端法兰。每处 25 个采样角度，所查零件对均无相交。三张静帧的末端位置误差最大约 0.16 μm。结论适用于这组渲染网格与采样角度 | [网格检查](checks/assembly_geometry.json) · [参考生成图](checks/industrial_reference.png) · [整机前后对比](checks/assembly_compare_studio_home.png) |

肘部叉耳与转动轴套的名义轴向间隙为每侧 3 mm，腕俯仰叉耳约为每侧 3.5 mm。装配改动由 `mechanical_details.py` 生成，尺寸为展示模型选取。强度、轴承寿命和实际夹持力属于后续机械工程校核。

## 阶段 1 · 环境与导入

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| Blender 4.x | Winget 校验 MSI 后请求管理员权限。此次运行使用 Blender 官方 4.5.5 LTS 免安装版，ZIP 的 SHA-256 与发行文件一致 | [版本](checks/blender-version.txt) · [校验值](checks/blender-archive-sha256.txt) |
| 导入模型 | 导入 15 个 link、40 个 visual 实例。六个运动关节使用 URDF 的局部原点和旋转轴 | [导入报告](checks/01_import.json) · [导入场景](checks/imported_arm.blend) |
| HOME 对照 | 同方向观察时，底座、肩、肘、腕和夹爪朝向与 RViz HOME 一致。参考图取自仓库已有截图，保留当时的外观。末端位置误差约 0.076 μm，旋转矩阵分量的最大绝对误差约 7.55×10⁻⁸ | [左 RViz，右 Blender](checks/home_comparison.png) · [仓库原截图](../member-a-delivery/rviz-industrial-arm-home.png) |

## 阶段 2 · 材质与影棚

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| CUDA 和降噪 | Cycles 使用 NVIDIA GeForce RTX 5060 Ti。64 采样上限，自适应阈值 0.06，最少 8 采样，启用 GPU 降噪 | [场景参数](checks/02_scene.json) · [渲染日志](checks/02_scene.log) |
| 材质和相机 | 缎面银灰铸壳 0.96/0.31，枪灰关节与导轨 0.94/0.38，法兰亮钢 1.00/0.22，深灰橡胶夹持垫 0/0.79。数值按金属度/基础粗糙度记。铸壳拉丝和端盖车纹通过粗糙度及各向异性反射模拟，主光与窄条反光在浅灰影棚上拉开明暗。保留整机 45°、肘部、末端三台展示机位 | [影棚场景](checks/studio.blend) · [HOME 并排对照](checks/metal_compare_studio_home.png) · [Blender Principled BSDF](https://docs.blender.org/manual/en/4.5/render/shader_nodes/shader/principled.html) |
| 特写机位 | 肘部机位对准 joint_3 转轴，末端机位从外侧展示腕架与法兰，并增加底座与两根夹爪导轨的观察机位 | [肘部](checks/elbow_detail.png) · [腕部与末端](checks/tool_detail.png) · [底座](checks/base_detail.png) · [双指与导轨](checks/jaw_detail.png) |

## 阶段 3 · 静帧

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| HOME | 搬运 CSV 第 1 帧与项目 HOME 完全一致 | [pose_home.png](outputs/frames/pose_home.png) |
| 肘部深弯 | 搬运 CSV 第 766 帧，joint_3 为 −68.63°。这是实录中最接近 90° 的肘弯 | [pose_elbow_bent.png](outputs/frames/pose_elbow_bent.png) |
| 肩部卡滞 | 卡滞 CSV 第 150 帧，源仿真时刻 1.50 s，joint_2 保持锁定值 0.351318411 rad | [pose_shoulder_lock.png](outputs/frames/pose_shoulder_lock.png) |
| 目检 | 降低宽面补光，用窄条反射表现铸壳边缘和法兰。首轮车纹偏重，降低纹理强度后重渲三张。最终图均为 1600×1200，轮廓完整，铸壳高光连续，肘、腕和底座在成图机位未见明显外露穿模 | [源记录、误差和渲染时间](checks/03_stills.json) |

## 阶段 4 · 动画

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| 运动预检 | 两组各渲染第 61 帧。逐轴读取 Blender 局部旋转，核对相邻帧的运动符号和末端位姿。卡滞源轨迹在 0.30 s 锁定 joint_2，后续角度漂移为 0，其余五轴在预检帧仍在运动 | [正常预检](checks/motion_test_normal_cycle.png) · [卡滞预检](checks/motion_test_lock_event.png) · [预检数值](checks/04_motion_preview.json) |
| 重采样 | 两条各 800 帧的源轨迹按原时间戳线性插值到 300 帧，包含实际首尾姿态。源记录区间 0.01–8.00 s 在成片中均匀放慢，机位和光照在两段间固定 | [渲染脚本](animate_from_csv.py) |
| 固定机位构图 | 全部 600 个姿态的网格包围盒都在画内。全程最紧一侧仍有约 5.4% 留边，运动连杆包围盒与地面的最小距离约 64 mm | [600 帧构图校验](checks/04_framing.json) |
| 正常成片 | H.264，1920×1080，30 fps，300 帧，10.00 秒。抽查第 16、85、270 帧，画面完整，位置和运动方向与 CSV 一致，解码画面与本版渲染帧的最低 SSIM 为 0.9967 | [正常动画](outputs/animations/normal_cycle.mp4) · [逐轴数值](checks/04_normal_cycle.json) · [解码核验](checks/04_normal_decoded_validation.json) |
| 卡滞成片 | 同规格。抽查第 16、85、270 帧，画面完整，位置和运动方向与 CSV 一致，joint_2 保持锁定。解码画面与本版渲染帧的最低 SSIM 为 0.9967 | [卡滞动画](outputs/animations/lock_event.mp4) · [逐轴数值](checks/04_lock_event.json) · [解码核验](checks/04_lock_decoded_validation.json) |
| 全片解码 | 两段成片各完整解码 300 帧。编码使用 libx264、CRF 16、yuv420p | [正常规格](checks/04_normal_ffprobe.json) · [卡滞规格](checks/04_lock_ffprobe.json) |

装配修订定稿后的静帧、预检和动画渲染共用时约 15 分 32 秒。其中正常动画渲染及编码约 7 分 06 秒，卡滞约 8 分 19 秒。[装配修订计时](checks/assembly_timing.json)

## 参考图质感对齐

量化只使用 `industrial_reference.png` 左侧 311×318 的整机画面，避开右侧两张特写和中间分隔线。各轮沿用同一 Blender 展示姿态和相机，图像统一至相同的测量尺寸。参考图用手绘轮廓分区，渲染图用 alpha 轮廓分区。直方图偏差使用累计亮度直方图的归一化 Wasserstein 距离，高光用 sRGB 亮度码值大于 240 的像素比例，对比度用主体均值减背景均值。

| 轮次 | 唯一变量 | 直方图偏差 | 高光占比 | 底座下方暗色倒影覆盖 |
| --- | --- | ---: | ---: | ---: |
| 1 | 起始值。地面灰度 0.66、地面粗糙度 0.82、环境反射强度 0.065 | 25.55% | 1.30% | 0.00% |
| 2 | 地面灰度 0.66 → 0.235 | 17.80% | 1.30% | 0.00% |
| 3 | 地面灰度 0.235 → 0.038 | 3.19% | 1.30% | 0.00% |
| 4 | 地面粗糙度 0.82 → 0.27 | 8.26% | 1.29% | 0.00% |
| 5 | 环境反射强度 0.065 → 0.35 | 4.06% | 1.30% | 4.59% |
| 6 | 环境反射强度 0.35 → 0.60 | 2.03% | 1.31% | 14.50% |

第 6 轮达到量化停机条件。参考高光占比为 0.22%，第 6 轮高出 1.09 个百分点。倒影覆盖通过关闭机械臂的反射射线可见性、保持地面及光源一致的对照渲染测得，判据为底座下方至少 8% 的测量区暗两级以上。参考图只有一张成图，底座下的倒影与阴影无法单独分离。并排目检仍可通过夹爪方向、壳体及底座比例区分两张图，参考图主体与背景对比为 6.28 级，第 6 轮为 32.13 级。

复跑单轮可使用 `blender -b render/checks/studio.blend --python-exit-code 1 -P render/setup_scene.py -- --reference-round 6`。比较程序通过 Python Launcher 调用 NumPy 和 Pillow。[并排图](checks/final_compare.png) · [逐轮日志](checks/metrics_log.json) · [第六轮场景](checks/reference_fit.blend)

## 产品渲染精修

原成品和场景保存在 `before-final/`。新场景从这份 Blender 场景读取原网格与相机。网格顶点、面和局部变换在 62 个部件上逐一比对一致。[模型核验](checks/product_geometry.log)

| 轮次 | 变更 | HOME 直方图偏差 |
| --- | --- | ---: |
| 1 | 导入 Studio Small 09 4K HDRI，强度 0.8，转角 35°。保留原有补光 | 9.81% |
| 2 | 地面灰度 0.038 → 0.012 | 3.69% |
| 3 | 铸壳金属度/粗糙度/各向异性 0.90/0.30/0.40，枪灰 0.85/0.45/0.28，亮钢 1.00/0.20/0.35，橡胶 0/0.70/0 | 3.57% |
| 4 | 金属面叠加 0.5 的短距离接触 AO，并调整边缘反射色调 | 3.50% |
| 5 | 铸壳、枪灰和检修盖加程序粗糙度细纹。检修盖纹理沿臂身方向拉伸 | 3.50% |
| 6 | HDRI 转角 102°、强度 0.75 | 3.16% |
| 7 | HDRI 转角 218°、强度 0.80。选定本轮作为成品场景 | 2.58% |
| 8 | 测试相机可见的背景提亮材质，第 7 轮的 HOME 主体/背景对比更接近参考 | 3.99% |

第 7 轮 HOME 的主体与背景亮度差为 9.37 级，参考图为 6.28 级。最终 1600×1200 HOME 复测的直方图偏差为 2.58%。并排图采用此前的近似参考机位，其直方图偏差为 8.01%，仍可通过夹爪方向、底座比例、壳体轮廓和背景明暗分布区分两图。最终场景使用 Cycles CUDA、128 采样上限和 GPU 降噪，4K HDRI 随 `.blend` 打包。[逐轮指标](checks/product_metrics.json) · [最终并排](checks/final_compare.png) · [肘部特写](checks/product_elbow_detail.png) · [产品场景](checks/product_final.blend) · [场景核验](checks/product_scene.json) · [HDRI 来源](https://polyhaven.com/a/studio_small_09) · [Blender AO 节点](https://docs.blender.org/manual/en/4.5/render/shader_nodes/input/ao.html)

终稿静帧、预检与两段动画共用时 22 分 28 秒。两段视频均完整解码 300 帧，抽查第 16、85、270 帧，解码画面与本版渲染帧的最低 SSIM 均为 0.9965。卡滞段 `joint_2` 锁定后漂移为 0。[计时](checks/product_timing.json) · [正常动画核验](checks/04_normal_decoded_validation.json) · [卡滞动画核验](checks/04_lock_decoded_validation.json)

## v2 正式交付与复跑

静帧、动画、指标和复跑指令见 [DELIVERY.md](DELIVERY.md)。正式渲染从 `checks/product_final_v2.blend` 读取场景，采样上限随场景保存。完整动画先把逐帧 PNG 写入 `work/`，随后编码为 MP4。缓存按场景、轨迹、URDF 和渲染脚本区分版本。
