# SynthRule — 运行结果 / Run Report

- **模型 / Model:** llm:deepseek-v4-flash
- **随机种子 / Seed:** `20260931`
- **任务数 / Tasks:** 14 (10 novel + 4 contamination-probe)
- **计分条目 / Scored items:** 1400
- **每题示例数 / Support examples:** 6
- **难度梯度 / Difficulty tiers:** [1, 2, 3, 4] rules
- **字母表 / Alphabets:** pseudoword, glyph, latin


![Phase profile](phase_profile.png)


## 1. 各阶段准确率（精确匹配，95% Wilson 区间）

| Agent | Phase A<br>prior only | Phase B<br>induction | Phase C<br>feedback | Phase D<br>explicit rules | Phase D − B |
|---|---|---|---|---|---|
| `oracle` | **100.0%**<br><sub>91.6%–100.0%</sub> | **100.0%**<br><sub>95.6%–100.0%</sub> | **100.0%**<br><sub>96.7%–100.0%</sub> | **100.0%**<br><sub>91.6%–100.0%</sub> | **+0.000** |
| `random` | **0.0%**<br><sub>0.0%–8.4%</sub> | **1.2%**<br><sub>0.2%–6.4%</sub> | **0.0%**<br><sub>0.0%–3.3%</sub> | **0.0%**<br><sub>0.0%–8.4%</sub> | **-0.012** |
| `identity` | **7.1%**<br><sub>2.5%–19.0%</sub> | **4.8%**<br><sub>1.9%–11.6%</sub> | **4.5%**<br><sub>1.9%–10.0%</sub> | **11.9%**<br><sub>5.2%–25.0%</sub> | **+0.071** |
| `align` | **9.5%**<br><sub>3.8%–22.1%</sub> | **4.8%**<br><sub>1.9%–11.6%</sub> | **3.6%**<br><sub>1.4%–8.8%</sub> | **9.5%**<br><sub>3.8%–22.1%</sub> | **+0.048** |
| `llm:deepseek-v4-flash` | **7.1%**<br><sub>2.5%–19.0%</sub> | **88.1%**<br><sub>79.5%–93.4%</sub> | **87.5%**<br><sub>80.1%–92.4%</sub> | **100.0%**<br><sub>91.6%–100.0%</sub> | **+0.119** |


> 表中准确率以**全部计分条目**为分母；被 harness 截断而无法作答的条目记为 0。下表给出**仅计已作答条目**的准确率 —— 若两表一致，说明没有条目被截断。


## 2. 仅计已作答条目的准确率

| Agent | Phase A | Phase B | Phase C | Phase D | Unparsed / total |
|---|---|---|---|---|---|
| `oracle` | 100.0% | 100.0% | 100.0% | 100.0% | 0 / 280 |
| `random` | 0.0% | 1.2% | 0.0% | 0.0% | 0 / 280 |
| `identity` | 7.1% | 4.8% | 4.5% | 11.9% | 0 / 280 |
| `align` | 9.5% | 4.8% | 3.6% | 9.5% | 0 / 280 |
| `llm:deepseek-v4-flash` | 7.1% | 96.1% | 96.1% | 100.0% | 17 / 280 |


## 3. 派生指标（按任务 bootstrap 95% 区间）

| Agent | learning gain<br>B − A | feedback gain<br>late C − early C | induction gap<br>D − B |
|---|---|---|---|
| `oracle` | +0.000<br><sub>[+0.00, +0.00]</sub> | +0.000<br><sub>[+0.00, +0.00]</sub> | +0.000<br><sub>[+0.00, +0.00]</sub> |
| `random` | +0.012<br><sub>[+0.00, +0.04]</sub> | +0.000<br><sub>[+0.00, +0.00]</sub> | -0.012<br><sub>[-0.04, +0.00]</sub> |
| `identity` | -0.024<br><sub>[-0.11, +0.05]</sub> | -0.054<br><sub>[-0.12, +0.02]</sub> | +0.071<br><sub>[-0.05, +0.20]</sub> |
| `align` | -0.048<br><sub>[-0.13, +0.02]</sub> | +0.036<br><sub>[-0.04, +0.12]</sub> | +0.048<br><sub>[-0.06, +0.18]</sub> |
| `llm:deepseek-v4-flash` | +0.810<br><sub>[+0.71, +0.90]</sub> | +0.000<br><sub>[-0.07, +0.07]</sub> | +0.119<br><sub>[+0.04, +0.21]</sub> |


## 4. 按难度分层

**难度 = 规则条数**

| Value | Phase A | Phase B | Phase C | Phase D |
|---|---|---|---|---|
| `oracle` · 1 | 100.0% | 100.0% | 100.0% | 100.0% |
| `oracle` · 2 | 100.0% | 100.0% | 100.0% | 100.0% |
| `oracle` · 3 | 100.0% | 100.0% | 100.0% | 100.0% |
| `oracle` · 4 | 100.0% | 100.0% | 100.0% | 100.0% |
| `random` · 1 | 0.0% | 4.2% | 0.0% | 0.0% |
| `random` · 2 | 0.0% | 0.0% | 0.0% | 0.0% |
| `random` · 3 | 0.0% | 0.0% | 0.0% | 0.0% |
| `random` · 4 | 0.0% | 0.0% | 0.0% | 0.0% |
| `identity` · 1 | 8.3% | 4.2% | 6.2% | 33.3% |
| `identity` · 2 | 8.3% | 4.2% | 0.0% | 8.3% |
| `identity` · 3 | 11.1% | 0.0% | 8.3% | 0.0% |
| `identity` · 4 | 0.0% | 11.1% | 4.2% | 0.0% |
| `align` · 1 | 8.3% | 4.2% | 6.2% | 16.7% |
| `align` · 2 | 16.7% | 4.2% | 6.2% | 8.3% |
| `align` · 3 | 0.0% | 5.6% | 0.0% | 11.1% |
| `align` · 4 | 11.1% | 5.6% | 0.0% | 0.0% |
| `llm:deepseek-v4-flash` · 1 | 0.0% | 100.0% | 100.0% | 100.0% |
| `llm:deepseek-v4-flash` · 2 | 8.3% | 83.3% | 84.4% | 100.0% |
| `llm:deepseek-v4-flash` · 3 | 22.2% | 88.9% | 100.0% | 100.0% |
| `llm:deepseek-v4-flash` · 4 | 0.0% | 77.8% | 62.5% | 100.0% |


## 5. 按字母表分层（tokenization 混淆检查）

**字母表家族**

| Value | Phase A | Phase B | Phase C | Phase D |
|---|---|---|---|---|
| `oracle` · glyph | 100.0% | 100.0% | 100.0% | 100.0% |
| `oracle` · latin | 100.0% | 100.0% | 100.0% | 100.0% |
| `oracle` · pseudoword | 100.0% | 100.0% | 100.0% | 100.0% |
| `random` · glyph | 0.0% | 0.0% | 0.0% | 0.0% |
| `random` · latin | 0.0% | 0.0% | 0.0% | 0.0% |
| `random` · pseudoword | 0.0% | 4.2% | 0.0% | 0.0% |
| `identity` · glyph | 11.1% | 0.0% | 4.2% | 22.2% |
| `identity` · latin | 0.0% | 2.4% | 3.6% | 14.3% |
| `identity` · pseudoword | 16.7% | 12.5% | 6.2% | 0.0% |
| `align` · glyph | 22.2% | 0.0% | 12.5% | 33.3% |
| `align` · latin | 4.8% | 4.8% | 1.8% | 4.8% |
| `align` · pseudoword | 8.3% | 8.3% | 0.0% | 0.0% |
| `llm:deepseek-v4-flash` · glyph | 11.1% | 88.9% | 79.2% | 100.0% |
| `llm:deepseek-v4-flash` · latin | 4.8% | 83.3% | 92.9% | 100.0% |
| `llm:deepseek-v4-flash` · pseudoword | 8.3% | 95.8% | 84.4% | 100.0% |


## 6. 训练数据污染探针

| Agent | Novel B | Familiar B | familiar_delta (B) | Novel D | Familiar D |
|---|---|---|---|---|---|
| `oracle` | 100.0% | 100.0% | **+0.000** | 100.0% | 100.0% |
| `random` | 1.7% | 0.0% | **-0.017** | 0.0% | 0.0% |
| `identity` | 5.0% | 4.2% | **-0.008** | 10.0% | 16.7% |
| `align` | 5.0% | 4.2% | **-0.008** | 10.0% | 8.3% |
| `llm:deepseek-v4-flash` | 90.0% | 83.3% | **-0.067** | 100.0% | 100.0% |


> `familiar_delta` = 熟悉字母表上的 B 阶段准确率 − 陌生字母表上的 B 阶段准确率。显著为正说明模型在见过的变换上更强，即存在检索优势而非学习优势。


## 7. 运行健康度

| Agent | Items | Unparsed | Truncated responses |
|---|---|---|---|
| `oracle` | 280 | 0 | 0 |
| `random` | 280 | 0 | 0 |
| `identity` | 280 | 0 | 0 |
| `align` | 280 | 0 | 0 |
| `llm:deepseek-v4-flash` | 280 | 17 | 17 |


> `Unparsed` = 无法从回复中解析出答案；`Truncated` = 回复因 `max_tokens` 被截断。两者必须与「模型答错」区分开 —— 若截断数偏高，准确率是系统性低估的。


## 8. Token 用量

| Agent | Calls | Errors | Truncated | Input | Output | Total |
|---|---|---|---|---|---|---|
| `llm:deepseek-v4-flash` | 364 | 0 | 101 | 78,979 | 4,516,088 | 4,595,067 |
