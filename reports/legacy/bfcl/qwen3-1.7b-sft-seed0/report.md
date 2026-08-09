# Qwen3-1.7B 在项目定义的 BFCL V4 非重叠公开数据划分上进行 QLoRA-SFT 后，在固定 200 条单轮 AST holdout 子集上的结果

## 结论

官方 BFCL AST accuracy 为 0.835000 (167/200)。
这是固定子集实验，不是 BFCL 官方全量成绩或排行榜成绩。

## 分类别结果

| 类别 | 任务数 | 正确 | 错误 | AST accuracy |
|---|---:|---:|---:|---:|
| simple_python | 50 | 45 | 5 | 0.900000 |
| multiple | 50 | 47 | 3 | 0.940000 |
| parallel | 50 | 40 | 10 | 0.800000 |
| parallel_multiple | 50 | 35 | 15 | 0.700000 |

## 补充诊断

- 输出可解析率：0.995000
- function-call schema-valid rate：0.985000
- 错误函数名：2
- 缺失参数：1
- 额外参数：0
- 参数类型错误：1
- 调用数量错误：4
- parallel/multiple 结构错误：4

这些诊断不替代官方 AST evaluator 指标。

## 资源与耗时

- 总耗时：817.298 秒
- 平均每任务耗时：4.086 秒
- 生成总耗时：804.296 秒
- GPU 峰值 allocated：2284549632 bytes
- GPU 峰值 reserved：2415919104 bytes
- 任务吞吐量：0.244709 tasks/s
- 生成输出吞吐量：18.432263 tokens/s

## 失败分析

`failures.jsonl` 包含全部 33 条真实官方失败及逐条根因。

- `multiple_10`：value_error:string；官方 AST evaluator 判定调用语义或参数值错误: value_error:string。
- `multiple_45`：simple_function_checker:missing_optional；官方 AST evaluator 判定调用语义或参数值错误: simple_function_checker:missing_optional。
- `multiple_74`：value_error:string；官方 AST evaluator 判定调用语义或参数值错误: value_error:string。
- `parallel_105`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_115`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_149`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_165`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_166`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_179`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_24`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_64`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_73`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_74`：parallel_function_checker_no_order:wrong_count；模型输出的函数调用数量与期望不一致。
- `parallel_multiple_112`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_multiple_127`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_multiple_131`：parallel_function_checker_no_order:cannot_find_match；模型函数调用参数类型不符合 schema。
- `parallel_multiple_132`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_multiple_15`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_multiple_160`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。
- `parallel_multiple_169`：parallel_function_checker_no_order:cannot_find_match；官方 AST evaluator 判定调用语义或参数值错误: parallel_function_checker_no_order:cannot_find_match。

## 适用范围

结果仅适用于项目定义的 BFCL V4 非重叠公开数据划分、固定单轮 AST holdout、seed 0 和 Qwen3-1.7B QLoRA-SFT；不能称为官方训练、官方全量成绩、排行榜成绩或独立分布泛化结果，也不能外推到多轮任务、ToolSandbox、tau2、偏好优化或 GRPO。
