# Launch kit (v0.3.0)

Everything here is a draft — replace bracketed parts with your real numbers
after running the tool on real logs.

## One-liner

> should-i-jev scans your LLM logs and codebase for calls that are secretly
> decisions (classify / route / rate / verify), prices what moving them to
> JEV would save, calibrates the models on your own traffic, and generates
> the migration PR. Zero dependencies, fully local.

## Show HN draft

**Title:** Show HN: Should-I-Jev – find the LLM calls that are decisions in disguise

**Text:**

JEV's pitch is that typed decision work (classify / route / rate / verify)
doesn't need a text generator. I kept wondering how much of a typical LLM
bill is actually that kind of work, so I built a scanner.

should-i-jev ingests your LLM logs (LiteLLM, Langfuse, OpenAI/Anthropic
usage exports — JSONL/CSV), scores every call on six "decision shape"
signals (ultra-short completions, JSON/enum outputs, classify/route/rate
verbs in the prompt, question shape, short inputs, output duplication), and
estimates what moving the flagged share to JEV would save. It also statically
scans your code (Python via AST, TS via patterns) to point at the exact
call sites, calibrates decision models on your own labels (ECE, reliability,
risk-coverage — do the stated probabilities mean anything?), and generates
a reviewable migration PR that marks each site and ships JEV-map sketches.

On the demo fixtures [replace with your real numbers]: 94% of audited calls
were decision-shaped but only ~12% of spend — the classification calls are
individually cheap and absurdly frequent, which is exactly the profile JEV
claims to win on.

Design choices worth flagging:

- Zero dependencies (pure stdlib, Python 3.9+), fully local, prompts
  redacted in reports — point it at real logs without a data-review meeting.
- Savings are scenario-based (÷100 conservative headline, the vendor-claimed
  ÷400 shown alongside); prices are dated and overridable. Text-less usage
  exports are reported as "insufficient data" rather than guessed at.
- Unofficial community tool, not affiliated with TypeSafe. It's a
  conversation-starter about decision-shaped workloads, not a benchmark.

`pip install -e .` from https://github.com/yzbcs/Should-I-Jev —
`python3 -m should_i_jev --demo --html` for the 30-second tour.

## awesome-jev PR entry (one line for the list)

- [should-i-jev](https://github.com/yzbcs/Should-I-Jev) — scan LLM logs & code for decision-shaped calls, estimate JEV migration savings, calibrate decision models (ECE/risk-coverage), and generate the migration PR. Zero-dependency, fully local.

## X / short post

Most LLM bills are full of calls that aren't really generation — routers,
classifiers, spam checks, judges. I built should-i-jev to find them:

– scans logs (LiteLLM/Langfuse/OpenAI/Anthropic exports) + your code
– prices the JEV migration (conservative scenarios, dated prices)
– calibrates decision models: ECE, reliability, risk-coverage
– generates the migration PR

Zero deps, fully local: https://github.com/yzbcs/Should-I-Jev

## 中文版（掘金 / V2EX / 知乎）

标题：你的 LLM 账单里，可能 90% 的调用根本不是"生成"

JEV 火了之后我一直好奇：普通公司的 LLM 流量里，到底有多少是"伪装成聊天的决策"——路由、分类、打分、审核？于是写了个扫描器 should-i-jev：

- 扫日志：LiteLLM / Langfuse / OpenAI / Anthropic 用量导出，六个"决策形状"信号打分
- 扫代码：Python AST + TS 模式匹配，直接定位到文件行号
- 算账：保守场景估算迁移 JEV 能省多少（价格标日期、可覆盖）
- 测可信度：ECE / 可靠性曲线 / 风险-覆盖，验证模型说的概率是不是真的
- 一键迁移 PR：标记每个调用点 + 生成 JEV map 草图

零依赖纯标准库、完全本地运行、prompt 自动脱敏。非官方社区工具。
https://github.com/yzbcs/Should-I-Jev

## Before posting

- [ ] Run on real logs, replace the demo numbers
- [ ] `pip install should-i-jev` works (PyPI publish)
- [ ] GitHub Release for v0.3.0 (paste RELEASE_NOTES.md)
- [ ] Repo topics set (jev, llm, cost-optimization, developer-tools)
- [ ] Screenshots current (docs/dashboard.png, docs/calibration.png)
