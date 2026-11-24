==================================================
【强制约束！违反则对接失败！绝对不能修改！】
所有代码必须严格遵循：
1. 接口路径完全匹配openapi.yaml（比如/api/simulations，不能改）
2. 数据结构完全匹配schemas.json（字段名/类型/长度/单位/枚举不能改）
3. simulationId格式必须是^SIM-\d{3}$，robotId格式必须是^ROBOT-\d{3}$
4. timestamp必须是Unix毫秒时间戳（不能改秒/ISO）
5. jointPosition/jointVelocity/jointTorque必须是长度6的数组（不能改）
6. 单位必须是rad/rad/s/N·m（不能改deg）
7. MQTT Topic必须是simulation/{simulationId}/xxx（不能加前缀/后缀）
8. 1:N绑定必须实现GET /api/simulations/{simulationId}/robots接口
==================================================
