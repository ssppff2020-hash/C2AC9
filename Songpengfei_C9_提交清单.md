# C9 提交清单 / Submission Checklist

**作者 / Author:** Songpengfei ｜ **赛道 / Track:** Track 1 — Learning ｜ **日期:** 2026-10-05

---

## 1. 必交文件对照（C9 阶段）

| 挑战要求 | 命名格式 | 本包文件 | 状态 |
|---------|---------|---------|------|
| Benchmark 代码 + README | `姓名_C9_benchmark/` | `Songpengfei_C9_benchmark/` | ✅ |
| 任务说明文档 | `姓名_C9_task说明.md` | `Songpengfei_C9_task说明.md` | ✅ |
| 测试结果 | `姓名_C9_测试结果.md` | `Songpengfei_C9_测试结果.md` | ✅ |
| 反思报告（500–800 字）| `姓名_C9_反思报告.md` | `Songpengfei_C9_反思报告.md` | ✅ |
| ⚡ AI 日志 | `姓名_C9_AI日志.md` | `Songpengfei_C9_AI日志.md` | ✅ |
| 拿来说明 | `姓名_C9_拿来说明.md` | `Songpengfei_C9_拿来说明.md` | ✅ |

## 2. 必交文件对照（C2A 阶段）

| 挑战要求 | 命名格式 | 本包文件 | 状态 |
|---------|---------|---------|------|
| 提案正文（800–1500 字）| `姓名_C2A_proposal.md` | `Songpengfei_C2A_proposal.md` | ✅ |
| 提案迭代版（鼓励）| `姓名_C2A_proposal_v2.md` | `Songpengfei_C2A_proposal_v2.md` | ✅ |
| ⚡ AI 日志 | `姓名_C2A_AI日志.md` | `Songpengfei_C2A_AI日志.md` | ✅ |
| 拿来说明 | `姓名_C2A_拿来说明.md` | `Songpengfei_C2A_拿来说明.md` | ✅ |

---

## 3. 代码包内容

```
Songpengfei_C9_benchmark/
├── README.md                      完整说明：任务、四阶段、指标、门槛、局限
├── requirements.txt               仅 requests（核心为纯标准库）
├── run_benchmark.py               CLI 入口
├── configs/default.yaml           默认配置（含门槛与预算的标定说明）
├── synthrule/
│   ├── __init__.py
│   ├── universe.py                规则语言 + 确定性执行器（ground truth）
│   ├── generator.py               程序化生成 + 四道门槛 + 污染探针
│   ├── prompts.py                 四阶段 prompt 构造
│   ├── agents.py                  参照基线 + LLM 适配器（含截断防御）
│   ├── scoring.py                 答案解析 + 精确匹配 + 编辑距离部分分
│   ├── runner.py                  编排 + Wilson/bootstrap 区间
│   └── report.py                  Markdown 报告 + 图表生成
├── tests/test_synthrule.py        25 项单元测试
├── data/
│   ├── tasks_seed20260931.json    主测试冻结题集（14 宇宙）
│   └── tasks_hard_seed20260931.json  困难模式冻结题集（8 宇宙）
└── results/
    ├── full.json                  主测试原始数据（1400 条）
    ├── hard.json                  困难模式原始数据（560 条）
    ├── report.md / phase_profile.png
    └── hard_report.md / hard_phase_profile.png
```

---

## 4. 复现步骤

```bash
cd Songpengfei_C9_benchmark
pip install -r requirements.txt

# 1) 单元测试（无需联网）
python tests/test_synthrule.py                 # 期望：25/25 passed

# 2) 主测试（用冻结题集，逐题可复现）
python run_benchmark.py --tasks data/tasks_seed20260931.json \
    --agents oracle random identity align llm --out results/full.json

# 3) 困难模式
python run_benchmark.py --tasks data/tasks_hard_seed20260931.json \
    --difficulties 4 5 6 --support 4 \
    --agents oracle random identity align llm --out results/hard.json

# 4) 生成报告
python -m synthrule.report results/full.json --out results/report.md \
    --figure results/phase_profile.png
```

模型经环境变量接入：`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_MODEL`。

---

## 5. 评分标准自查

| 维度 | 权重 | 本包对应证据 |
|------|------|-------------|
| **Benchmark 质量** | 30% | 四阶段协议 + Phase D 判别效度对照（定义 Induction Gap）；四道生成门槛；三字母表混淆控制；污染探针。实测归纳缺口 +0.119 / +0.425 |
| **技术实现** | 20% | 6 模块 + CLI + 报告器；25 项单元测试全通过；ground truth 双实现互验；冻结题集逐题可复现；纯标准库核心 |
| **测试有效性** | 20% | oracle 恒 100% 验证管线；非 LLM 基线 ≤12.5%；困难模式落入 20–80% 区间并给出缺口 +0.425。**局限已如实声明**：仅 1 个模型，未证明跨模型区分度 |
| **拿来主义质量** | 15% | 12 项已核验来源（ARC / SCAN / ARC-AGI-3 / BIG-bench / MMLU / DeepMind 框架 / 污染检测文献等）；逐项写明拿什么、弃什么、为什么 |
| **反思深度** | 15% | 反思报告含 3 个意外困难的根因分析、2 项负面结果（污染探针无判别力、截断假象）、5 条具体改进方案、AI 反向举证 4 处 |

**红旗自查：**
- ❌ 核心交付物缺失 → 已全部提供
- ❌ 无 AI 使用记录 / AAR → 两份 AI 日志 + 反思报告
- ❌ 一句话指令直接提交、无迭代 → 6 次实质迭代，每次含现象、诊断、修复、验证

---

## 6. 一句话提交说明（可直接发群）

> 这是我的 C2A/C9 提交，选择了 **Track 1（Learning 学习能力）**。
> 核心设计是用程序化生成的"规则宇宙"保证答案在预训练中不存在，并用 **Phase D（显式规则对照）**
> 把"能执行"和"能归纳"分开，定义为 **Induction Gap = acc(D) − acc(B)**。
> 实测 deepseek-v4-flash：执行 100%，归纳 88.1%（困难模式下 57.5%），
> **归纳缺口在困难模式下放大到 +0.425** —— 即"规则告诉它就会用，要自己归纳就不行"。
> 全程 6 次实质迭代，其中一次差点因推理模型 `max_tokens` 截断报出完全错误的结论。欢迎反馈！
