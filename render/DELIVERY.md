# 成员 A 机械臂 · v2 渲染交付

正式渲染入口为 [product_final_v2.blend](checks/product_final_v2.blend)。静帧和动画脚本会校验入口及场景版本。动画全量渲染还要求两张预检图来自同一个场景文件。上版五项成品及 v2 预览场景存于 `before-final-v2/`。

## 静帧

| 产物 | CSV 姿态 | 验证 |
| --- | --- | --- |
| [HOME](outputs/frames/pose_home.png) | 搬运实录第 1 帧，0.01 s | 1600×1200，六轴与 HOME 一致 |
| [肘部深弯](outputs/frames/pose_elbow_bent.png) | 搬运实录第 766 帧，7.66 s，joint_3 为 −68.63° | 1600×1200，采用实录最深肘弯 |
| [肩部卡滞](outputs/frames/pose_shoulder_lock.png) | 卡滞实录第 150 帧，1.50 s | 1600×1200，joint_2 固定于 0.351318411 rad |

[静帧位姿逐项记录](checks/03_stills.json) · [夹爪特写](checks/product_v2_tool_final.png) · [网格干涉与 FK 验证](checks/assembly_geometry.json)

## 动画

| 产物 | 规格 | 运动依据 |
| --- | --- | --- |
| [正常工况](outputs/animations/normal_cycle.mp4) | H.264，1920×1080，30 fps，300 帧，10 秒 | 800 条正常轨迹，按源时间戳线性插值 |
| [肩部卡滞](outputs/animations/lock_event.mp4) | H.264，1920×1080，30 fps，300 帧，10 秒 | 800 条卡滞轨迹，源仿真时刻 0.30 s 锁定 joint_2 |

[正常预检帧](checks/motion_test_normal_cycle.png) · [卡滞预检帧](checks/motion_test_lock_event.png) · [两张预检的逐轴数据](checks/04_motion_preview.json)

预检和成片第 16、85、270 帧均核对了实际关节角与 CSV 的运动方向。卡滞片从第 12 帧起保持肩轴锁定，覆盖整段锁定的 289 帧 Blender 关节矩阵实测漂移为 0 rad。[逐帧肩轴矩阵核验](checks/final_v2_lock_joint_matrices.json)

两段均完成 300 帧完整解码。呈现时间戳以 1/30 秒连续递增，每一帧都与同帧号的 Blender 原始 PNG 匹配。正常片与卡滞片的最低逐帧 SSIM 分别为 0.996907 和 0.996862。两段抽帧的画面完整，运动方向与预检一致。[正常片解码报告](checks/final_v2_normal_cycle_verification.json) · [卡滞片解码报告](checks/final_v2_lock_event_verification.json)

## 场景参数

Blender 4.5.5 LTS，Cycles CUDA，NVIDIA GeForce RTX 5060 Ti，128 采样上限，自适应阈值 0.075，GPU 降噪，AgX。世界环境使用打包的 Studio Small 09 4K HDRI，强度 0.95，转角 218°，Gamma 1.12。铸壳基础粗糙度 0.25、金属度 0.90、各向异性 0.40。钢件金属度 1.00、粗糙度 0.20。金属接触 AO 混合权重 0.50。普通棚灯与两条窄光源形成臂身亮带。

## 目检与量化

夹爪一体式根部与横梁交界清楚。两块 14 mm 夹持垫镜像对向，开口 155.60 mm，夹指根部至导轨顶面最小间隙 0.40 mm。三种交付姿态下，受检夹指、夹持垫、横梁和导轨网格之间均无交叉。三张静帧的独立 FK 回归最大末端位置误差为 0.16 μm。

| 画面 | 直方图偏差 | 主体减背景亮度差 | 底座下方倒影 |
| --- | ---: | ---: | --- |
| 参考图 | — | +6.28 级 | 单图目检 |
| v2 HOME | 2.75% | −14.81 级 | 开关反射对照，79.26% 的测量区暗至少 2 级 |
| v2 近似参考机位 | 5.29% | +42.60 级 | 开关对照显示此视角以亮色反射为主，暗影覆盖 0% |

并排图的右栏采用独立展示姿态。壳体、底座比例和夹爪尺寸仍可区分。臂身条状亮带、端盖和法兰反射以及关节接触暗部已目检。[左参考、右渲染](checks/final_compare.png) · [量化记录](checks/final_v2_metrics.json)

## 耗时

从备份和夹爪精修到两段成片解码核验约 20 分 50 秒。最终两段动画渲染与编码合计约 14 分 31 秒，三张静帧净渲染 5.31 秒。[计时记录](checks/final_v2_timing.json)

## 复跑入口

```powershell
$blender = Join-Path $env:LOCALAPPDATA 'SimPlatformBlender/blender-4.5.5-windows-x64/blender.exe'
$scene = 'render/checks/product_final_v2.blend'
& $blender -b $scene --python-exit-code 1 -P render/verify_assembly.py
& $blender -b $scene --python-exit-code 1 -P render/render_stills.py
& $blender -b $scene --python-exit-code 1 -P render/animate_from_csv.py -- --preview
& $blender -b $scene --python-exit-code 1 -P render/animate_from_csv.py
& $blender -b $scene --python-exit-code 1 -P render/setup_scene.py -- --final-v2-metrics
```

全量动画命令前，检查两张预检帧。编码和核验使用 PATH 中的 ffmpeg 与 ffprobe。指标脚本使用 Python Launcher 环境中的 NumPy 和 Pillow。

## 待办移交

1. 在项目日志登记 v2 成品、参考图指标和验收证据。
2. 在成员 A 模块文档引用本交付清单，补齐渲染入口、工况与演示说明。
3. 整理 `feature/a-joint-lock` 的提交，再合入 `develop`。

## RViz 主视觉移植与连接处验收

导出源为 [product_final_v2.blend](checks/product_final_v2.blend) 的 `v2-aligned-jaws` 定稿场景。58 个机械臂网格按 Blender 父层级归属到底座、六个连杆和末端三个固接组件。腕部轴承从 `joint_5_axis` 换算进 `link_5` 局部坐标。双指、两块增厚夹持垫、导轨、壳体及修饰件均纳入原始导出。场景网格只有 `Seamless studio floor`。灯光和相机也留在场景。[归属清单](../docs/member-a-rviz-validation/blender_mesh_ownership.json)

导出器求值各网格的修改器，转换到 link 局部坐标，再导出米制 Z-up 的三角网格和分角法线。由于现有导入器每个 DAE 读取一种材质，同一连杆按 `cast`、`steel`、`graphite`、`cover` 合批。原始导出用既有 `import_urdf.py` 往返测试，逐 link 包围盒误差最大 **0.000060 mm**，轴原点与轴向完全一致。[导出脚本](../sim/gazebo_arm/tools/export_blender_visuals.py)

正式模型以 Blender 定稿主构件为基础，在肩根、肘根和腕根重配过渡段。上一轮螺栓圈、止口和加强筋作为独立 visual 保留。重复的轴件按机械接口替换，轴承环和短轴按定稿壳体的安装面重新就位。新版由 [标准 URDF](../sim/gazebo_arm/urdf/hydraulic_arm.urdf) 随 `sim_arm.launch.py` 加载，旧 `force_path_preview.xml` 和专用启动文件标记为 legacy。[装配脚本](../sim/gazebo_arm/tools/assemble_blender_visuals.py) · [替换记录](../docs/member-a-rviz-validation/fitting.json)

| 验收点 | 实测结果 | 验证图文件 |
| --- | --- | --- |
| 肩轴根部 | 两侧壳体间隙各 4.00 mm，固定支座和活动壳轴向分件。 | `blender_rviz_shoulder_offline.png`，由标准 URDF 的 DAE 离线取景 |
| 肘部深弯 | 两侧壳体间隙各 3.00 mm。CSV 最深 −89.68°，内侧与外侧均纳入干涉检查。 | `blender_rviz_elbow.png` |
| 腕部 roll 和 pitch | 壳体间隙分别为 3.00 mm 与 3.50 mm，轴承环至壳体均为 0.55 mm。 | `blender_rviz_joint.png` |
| 末端法兰和双指 | 法兰 4 颗螺栓。两片垫约 14.00 mm，开口 155.60 mm，夹持面轴向对齐误差低于 0.001 mm。 | `blender_rviz_joint.png` |
| 底座到末端 | 逐旋转轴量测短轴与两侧轴承环，径向对边差最大 0.000032 mm。圆柱与壳体接合按止口、圆肩和分件缝处理。 | `blender_rviz_home.png` 与以上特写 |

同一 HOME 与观察方向的逐 link 并排图为 `blender_vs_rviz.png`，位于本机 `%LOCALAPPDATA%/SimPlatformROS/member-a-rviz-refined/`。并排图按主体缩放，RViz 画面采用透视投影，图注标出各主要构件。四张验证图也在该目录。肩部专项取景的 RViz 视口出现空白，肩部图采用同一标准 URDF 和网格的离线取景。肘部、腕部和 HOME 图为 RViz 实拍。[间隙与对中原始数据](../docs/member-a-rviz-validation/force_path_clearance.json)

标准 `colcon` 构建通过，日常启动链发布了安装后的新模型与六轴状态。成员 A 全量 4 项测试、14 个子测例通过。111 个姿态的 BVH 检查未检测到网格相交，逐关节变换一致。三种 YAML 各重跑一次，分别为 800、800、1050 帧，关节、末端位姿与事件逐项等于基线。物理连杆的面数倍率最高为 `link_4` 的 4.75 倍，HOME 的 RViz 状态栏为 21 fps。[网格与位姿回归](../docs/member-a-rviz-validation/blender_rviz_validation.json) · [工况回归](../docs/member-a-rviz-validation/blender_rviz_scenario_fk.json)
