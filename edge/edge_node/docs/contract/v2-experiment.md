# V2 实验契约（实现索引）

- 契约版本：`2.0.0`（2026-11-26 冻结）
- 人类可读定义：[`docs/v2-experiment-contract.md`](../../../../docs/v2-experiment-contract.md)
- Schema：
  - [`v2_run.schema.json`](v2_run.schema.json)
  - [`v2_trace_frame.schema.json`](v2_trace_frame.schema.json)
- 测试夹具：[`test/fixtures/v2_contract/`](../../test/fixtures/v2_contract/)
- 自动化测试：[`test/test_v2_contract.py`](../../test/test_v2_contract.py)
- 测试依赖：`jsonschema>=4.18`（见 `requirements-dev.txt`）
- 运行：

```powershell
py -m unittest discover -s edge/edge_node/test -p "test_v2_contract.py"
```

## 冻结范围

- 每次运行一条 Run 记录；每个控制周期一条 TraceFrame 记录，均以 `run_id` 关联。
- 字段、单位、枚举以 `docs/v2-experiment-contract.md` 为准。
- MQTT `RobotState`/`Heartbeat` 契约不变；本目录只新增 V2 实验记录 schema。

## 变更流程

1. 若删除/重命名/改类型或单位，升 MAJOR；新增可选字段升 MINOR；纯文档纠正升 PATCH。
2. 同步修改：契约文档、两份 schema、`test/fixtures/v2_contract/`、`test_v2_contract.py`。
3. 通知成员 A/B；B 的 validation-r1 原始记录不改写，新版本重新运行或迁移。
