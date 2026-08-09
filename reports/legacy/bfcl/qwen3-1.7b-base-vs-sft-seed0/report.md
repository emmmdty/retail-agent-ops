# Qwen3-1.7B BFCL Base 与 QLoRA-SFT 配对比较

## 结论

Qwen3-1.7B 在项目定义的 BFCL V4 非重叠公开数据划分上进行 QLoRA-SFT 后，在固定 200 条单轮 AST holdout 子集上的结果。

- Base：163/200 (0.815000)
- SFT：167/200 (0.835000)
- Success delta：+0.020000
- 配对 bootstrap 95% CI：[-0.040000, 0.080000]
- 改善/退化/不变：{'improved': 20, 'regressed': 16, 'unchanged': 164}

## 分类别结果

| 类别 | Base | SFT | Delta |
|---|---:|---:|---:|
| simple_python | 0.820000 | 0.900000 | +0.080000 |
| multiple | 0.900000 | 0.940000 | +0.040000 |
| parallel | 0.760000 | 0.800000 | +0.040000 |
| parallel_multiple | 0.780000 | 0.700000 | -0.080000 |

## 逐任务变化

- 改善：['simple_python_257', 'simple_python_354', 'simple_python_30', 'simple_python_267', 'simple_python_389', 'multiple_151', 'multiple_47', 'multiple_138', 'multiple_175', 'parallel_89', 'parallel_34', 'parallel_46', 'parallel_49', 'parallel_15', 'parallel_131', 'parallel_94', 'parallel_178', 'parallel_multiple_60', 'parallel_multiple_184', 'parallel_multiple_88']
- 退化：['simple_python_357', 'multiple_45', 'multiple_74', 'parallel_165', 'parallel_73', 'parallel_24', 'parallel_149', 'parallel_64', 'parallel_179', 'parallel_multiple_32', 'parallel_multiple_193', 'parallel_multiple_15', 'parallel_multiple_169', 'parallel_multiple_29', 'parallel_multiple_112', 'parallel_multiple_127']

完整真实问题、schema、原始输出、期望调用和官方错误保存在 comparison_analysis.jsonl，该文件不进入 git。

## 适用范围

这是项目定义的 BFCL V4 公开数据重新划分实验，不是官方训练、官方全量成绩、排行榜成绩或独立分布泛化结果。
