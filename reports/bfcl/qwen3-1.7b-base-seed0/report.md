# Qwen3-1.7B 在 BFCL V4 固定 200 条单轮 AST 子集上的零样本结果

## 结论

官方 BFCL AST accuracy 为 0.815000 (163/200)。
这是固定子集实验，不是 BFCL 官方全量成绩或排行榜成绩。

## 分类别结果

| 类别 | 任务数 | 正确 | 错误 | AST accuracy |
|---|---:|---:|---:|---:|
| simple_python | 50 | 41 | 9 | 0.820000 |
| multiple | 50 | 45 | 5 | 0.900000 |
| parallel | 50 | 38 | 12 | 0.760000 |
| parallel_multiple | 50 | 39 | 11 | 0.780000 |

## 补充诊断

- 输出可解析率：0.960000
- function-call schema-valid rate：0.945000
- 错误函数名：2
- 缺失参数：1
- 额外参数：0
- 参数类型错误：3
- 调用数量错误：22
- parallel/multiple 结构错误：18

这些诊断不替代官方 AST evaluator 指标。

## 资源与耗时

- 实际物理 GPU：1（NVIDIA GeForce RTX 4090，逻辑设备 `cuda:0`）
- 总耗时：581.326 秒
- 平均每任务耗时：2.907 秒
- 生成总耗时：568.787 秒
- 模型加载耗时：5.002 秒
- 官方 evaluator 耗时：0.096 秒
- GPU 峰值 allocated：2284549632 bytes（约 2.128 GiB）
- GPU 峰值 reserved：2390753280 bytes（约 2.226 GiB）

## 可复现与审计

- 运行代码 commit：`a3500c909d40b102f509735b1c619f1c9f7a355f`
- BFCL commit：`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`
- 冻结 manifest SHA-256：`a74a3748d3af289e8d3f808930b99b6eb5cb9c7d84ba678ff627c762e9448da9`
- 官方 `ast_checker.py` SHA-256：`2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538`
- 离线加载：`TRANSFORMERS_OFFLINE=1`、`HF_HUB_OFFLINE=1`，模型解析到 `/data/TJK/models/Qwen3-1.7B`
- `manifest.json` 保留模型文件哈希、GPU 映射、完整官方评分命令与 stdout；`run.log` 保留实际命令和阶段耗时。
- `failures.jsonl` 包含全部 37 条真实失败的 task_id、用户问题、函数 schema、原始模型输出、期望调用、官方错误类型和根因；该文件因包含原始 BFCL 内容不进入 git。

## 失败分析

`failures.jsonl` 包含全部 37 条真实官方失败及逐条根因。

- `multiple_10`：value_error:string；官方 AST evaluator 判定调用语义或参数值错误: value_error:string。
- `multiple_138`：multiple_function_checker:wrong_count；模型输出不可解析: missing_tool_call。
- `multiple_151`：value_error:list/tuple；官方 AST evaluator 判定调用语义或参数值错误: value_error:list/tuple。
- `multiple_175`：multiple_function_checker:wrong_count；模型输出不可解析: missing_tool_call。
- `multiple_47`：value_error:others；官方 AST evaluator 判定调用语义或参数值错误: value_error:others。
- `parallel_105`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_115`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_131`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_15`：parallel_function_checker_no_order:wrong_count；模型输出不可解析: missing_tool_call。
- `parallel_166`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_178`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_34`：parallel_function_checker_no_order:wrong_count；模型输出不可解析: invalid_tool_call_json。
- `parallel_46`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_49`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_74`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_89`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_94`：parallel_function_checker_no_order:cannot_find_match；模型函数调用参数类型不符合 schema。
- `parallel_multiple_131`：parallel_function_checker_no_order:cannot_find_match；模型函数调用参数类型不符合 schema。
- `parallel_multiple_132`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_multiple_160`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。

## 适用范围

结果仅适用于提交 manifest 冻结的 BFCL V4 单轮 AST 子集、seed 0、Qwen3-1.7B 4-bit NF4 零样本设置；不能外推到 BFCL 全量、官方排行榜、多轮任务、ToolSandbox、tau2、SFT、偏好优化或 GRPO。
