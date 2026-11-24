# 液压机械臂模型推导

## 1. 模型结构

仿真端不是演示动画，而是三阶耦合的数值模型：

1. 刚体动力学：`M(q)qdd + C(q,qd)qd + G(q) + F_f(qd) = tau`
2. 伺服阀二阶动力学：`xvdd + 2*zeta*wn*xvd + wn^2*xv = wn^2*u`
3. 两腔压力动力学与力矩输出：`tau = Dm*(P1 - P2)`

刚体部分用递归牛顿-欧拉法（RNEA）计算，不依赖第三方工具箱。

## 2. RNEA 的关键约定

- 标准 DH 旋转为 `R = Rz(theta) * Rx(alpha)`。
- 第 i 关节的转轴为该关节自身的局部 z 轴；转子惯量按 `Jm * a*a'` 加到连杆惯量上。
- 基座线加速度取 `[0, 0, -g]`，使 RNEA 结果中直接包含重力项。
- 质量矩阵由逐列 RNEA 求得：令 `qd=0`、`gravity=0`、`qdd=e_j`，得到的广义力为 `M(:,j)`。
- `C(q,qd)qd + G(q)` 由一次 `qdd=0`、`gravity=on` 的 RNEA 直接得到，不必显式构造科氏矩阵。

## 3. 液压执行器

### 3.1 腔压动力学

对摆动马达的两腔写流量连续性方程：

`dP1/dt = (beta_e/V1) * (Q1 - Dm*qd - Ct*(P1 - P2))`

`dP2/dt = (beta_e/V2) * (-Q2 + Dm*qd - Ct*(P1 - P2))`

其中：

- `beta_e` 为有效体积弹性模量；
- `V1=V2=V` 为单腔等效容积；
- `Dm` 为摆动马达弧度制排量；
- `qd` 为关节角速度；
- `Ct` 为总内漏与层流阻尼系数。

阀口流量按正反开口分别取压力差平方根：

`Q1 = Q_in*sqrt(Ps-P1) + Q_out*sqrt(P1-Pr)`

`Q2 = Q_out*sqrt(Ps-P2) + Q_in*sqrt(P2-Pr)`

`Q_in/Q_out` 由阀口位移的正负方向分配，输出力矩为 `Dm*(P1-P2)`。

### 3.2 腔室容积

不再对 6 个关节使用同一容积，而是：

`V = V_hose + k_vd*Dm_cm3_per_rad`

这样小排量腕部马达的液压刚度不会被人为放大容积所稀释。

### 3.3 静态阀口增益

零负载、零速度时，两腔压差由供油流量与总泄漏平衡近似：

`PL = Dm*(P1-P2) ≈ (Dm*Kq/Ct)*xv`

因此静态阀口力矩增益为：

`K_u = Dm*Kq/Ct`，`Kq = kv*sqrt(Ps-Pr)`

控制输出映射为：

`u = tau_cmd/K_u`

这样在正常工作区内，液压执行器近似为单位增益力矩源；压力和阀口仍然保留真实的非线性与限幅。

## 4. 液压固有频率与带宽

把压力动力学线性化后，可写为：

`(V/(2*beta_e))*dPL/dt = Kq*xv - Dm*qd - Ct*PL`

`M*qdd = Dm*PL`

合并得到液压固有频率：

`omega_h = sqrt(2*beta_e*Dm^2/(V*M))`

液压阻尼比：

`zeta_h = beta_e*Ct/(V*omega_h)`

液压阻尼极点约为：

`2*beta_e*Ct/V`

闭环带宽不能高于该极点的 0.25 倍太多，否则会激励液压谐振。当前整定取：

`wc = min(12, 0.25 * 2*beta_e*Ct/V)`

这正是先前控制器发散的修正根因：原来统一取 22 rad/s，已经越过小排量腕部马达的液压阻尼极点。

## 5. RBF 自适应补偿

定义误差与滑模量：

`e = q_d - q`

`edot = qd_d - qd`

`s = edot + Lambda*e`

RBF 输入为归一化后的 `[q, qd]`，控制律为：

`tau = f_hat + Kd*s`

`f_hat = W^T * phi(x)`

权重更新：

`dW/dt = Gamma * (phi*s^T - sigma_w*W)`

整定时按各关节等效惯量缩放 `Kd`：

`Kd_i = 2*zeta*M_ii*wc_i`

`Lambda_i = wc_i/(2*zeta)`

## 6. 数值积分

Python 孪生使用固定步长半隐式 Euler：

1. 用当前 `(q,qd,tau)` 计算加速度 `qdd`；
2. 先更新速度：`qd_next = qd + qdd*dt`；
3. 再用旧速度更新位置：`q_next = q + qd*dt + 0.5*qdd*dt^2`。

