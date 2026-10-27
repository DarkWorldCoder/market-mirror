<div align="center">

<img src="docs/images/marketmirror-hero-v2.png" alt="MarketMirror：在真正投放之前，先让模拟买家试一遍你的营销方案" width="100%" />

# MarketMirror：AI 市场调研与营销模拟

**在真正花钱投放之前，先用模拟买家试一试你的广告、定价和销售话术。**

[English](README.md) · 简体中文

**开源，为 AI Agent 而生。** 可在 Claude Code、Codex、Cursor、Gemini CLI 或任何支持 MCP 的 Agent 中使用。装好插件后用自然语言提问（例如“在印度的年轻父母中测试这三个广告”），Agent 会构建模拟买家、运行测试并打开结果仪表盘。完全自托管：只有模型调用（发往你选择的模型提供方）和可选的公开资料检索会离开你的电脑。

**[项目网站](https://darkworldcoder.github.io/market-mirror/)** · **[打开在线演示](https://darkworldcoder.github.io/market-mirror/demo/)**：一次 2,999 名模拟买家运行的完整仪表盘，浏览器直接打开，无需安装。（Fitloop 是虚构的应用，所有数字均为模拟结果。）

如果 MarketMirror 帮你避免了一次失败的上线，点个 ⭐ 能让更多人发现它。

</div>

## MarketMirror 是什么？

MarketMirror 为你的下一个营销决策提供一群“练习观众”。描述你的产品和目标人群，它会生成一批 AI 模拟的人：他们会对你的广告做出反应、比较价格、提出问题和顾虑，并回应你的销售话术。

你会得到一份报告：什么吸引了他们、什么让他们却步、应该改什么，以及下一步该拿真实用户测试什么。你也可以实时观看模拟过程，并在仪表盘中查看结果。

例如：你要上线一款健身应用。广告应该主打“每天 15 分钟”还是“比去一次健身房还便宜”？免费试用要不要先绑卡？MarketMirror 让你在正式投放前先演练这些选择。

**买家是模拟的。** 他们的回答由 AI 生成，适合用来构思和比较方案。有希望的发现，请再用真实用户和小规模真实实验来确认。

## 适合谁？

| 如果你是… | 可以用 MarketMirror… |
|---|---|
| **创始人或小企业主** | 看看不同人群会如何理解你的产品、价格或首发优惠。 |
| **营销人员或代理商** | 在真实投放前比较广告、标题、邮件和受众。 |
| **销售团队** | 演练销售话术，提前发现可能的顾虑，尝试更清晰的回答。 |
| **产品或研究团队** | 探索购买决策和网站使用路径，再规划真实用户调研。 |
| **开发者或 AI Agent 构建者** | 通过命令行、API、Python 库或已连接的 AI 助手运行同样的流程。 |

## 可以测试什么？

| 你的问题 | MarketMirror 会做什么 |
|---|---|
| **哪个广告更吸引注意？** | 把你的广告混入模拟的 Facebook、Instagram、Reddit、TikTok、LinkedIn 或 X 信息流中，记录买家是停下、忽略、点击、评论还是隐藏。 |
| **哪个标题或文案更清楚？** | 向不同买家展示不同版本，收集他们的反应。 |
| **价格或优惠是否合适？** | 询问价格相关问题，比较不同优惠或价格档位。 |
| **上线前后会发生什么？** | 让买家在模拟社交平台上发帖、回复和互动，并按计划插入品牌帖子和事件。 |
| **邮件能打动他们吗？** | 在模拟收件箱中测试标题、正文或系列邮件。不会发送任何真实邮件。 |
| **销售话术效果如何？** | 展示话术、收集顾虑、尝试你的回应，再问一次他们的决定。 |
| **网站在哪里流失用户？** | 让模拟访客浏览真实网站，记录他们在哪里犹豫、离开或完成任务（如加入购物车）。 |
| **模拟结果和真实结果一致吗？** | 将模拟结果与真实结果配对比较（`backtest` / `calibrate`）。 |

同一个比较可以重复多次运行，看结果是否稳定；也可以让不同的 AI 模型同时扮演买家，看它们在哪里意见不一。两者都能揭示模拟本身的不确定性。

## 示例结果（全部为模拟）

**同样的 2,999 名买家、同样的优惠，结论却因“谁来作答”而不同：**

| 买家由谁编写 | 由谁扮演作答 | 愿意开始 / 也许 / 不会 |
|---|---|---|
| Claude（1,000 人） | Claude Sonnet 5.5 | 1.3% / 75.6% / 23.1% |
| Gemini（1,000 人） | Claude Sonnet 5.5（替补） | 0.9% / 69.7% / 29.4% |
| Codex（999 人） | Codex | 0.0% / 5.7% / 94.3% |

由 Gemini 编写、但由 Claude 扮演的买家，回答和 Claude 的买家相近。也就是说，在这次运行中，负责“作答”的模型对调查结果的影响远大于负责“编写人物”的模型。

**要不要先绑卡？** 150 名买家、3 种优惠、3 个随机种子：

| 试用优惠 | 模拟“愿意开始”平均值 | 3 个种子的最小–最大值 |
|---|---:|---:|
| 不绑卡 · USD 4.99 | 4.1% | 2.7–5.4% |
| 必须绑卡 · USD 4.99 | 0.2% | 0.0–0.7% |
| 不绑卡 · USD 2.99 | 6.7% | 5.3–8.0% |

种子范围描述的是模拟本身的波动。下一步应是一次小规模的真实随机实验。

## 快速开始

最快的方式（需要先安装 [uv](https://docs.astral.sh/uv/)）：在你的 Agent 的 MCP 配置中加一条。该包在 PyPI 上名为 `marketmirror`，并已收录于官方 MCP Registry（`io.github.DarkWorldCoder/market-mirror`）：

```json
{ "mcpServers": { "market-mirror": { "command": "uvx", "args": ["marketmirror"] } } }
```

然后让 Agent 运行 `doctor`，再运行 `setup` 安装引擎。也可以从源码安装（需要 Git、Bash、Python 3 和 uv；支持 Linux、macOS 和 WSL）：

```bash
git clone https://github.com/DarkWorldCoder/market-mirror.git
cd market-mirror
bash install.sh
./mm configure
```

模型可选 Anthropic、OpenAI、Google Gemini、DeepSeek、Kimi、通义千问（阿里云百炼）、智谱 GLM 等 API，或 Ollama / LM Studio 本地模型，也可以通过本地网关使用你已登录的 Claude Code、Codex 或 Gemini CLI。请在你自己的终端中运行 `./mm configure` 输入密钥，切勿把 API 密钥粘贴到聊天里。

Gemini CLI 用户也可以直接安装扩展：

```bash
gemini extensions install https://github.com/DarkWorldCoder/market-mirror
```

完整的安装、模型选择和工作流说明见 [英文 README](README.md#quick-start)。

## 与 OASIS 和 MiroFish 的关系

MarketMirror 基于 [MiroFish](https://github.com/666ghj/MiroFish) 构建，而 MiroFish 运行在 [OASIS](https://github.com/camel-ai/oasis) 之上。OASIS 提供逼真的社交平台（信息流、发帖、关注和推荐系统），供语言模型智能体在其中行动；MiroFish 在此基础上增加了知识图谱和预测报告；MarketMirror 则把它们变成一个以决策收尾的市场测试：分层的模拟买家（每人都有一段生活访谈）、广告与优惠测试、问卷、销售演练、多模型对比、离线报告和校准流程。

- 默认使用本地 SQLite 知识图谱和本地 embedding（多语言模型，可处理中文资料），无需 Zep 账号。

## 局限性

- **生成的访谈仍然是合成数据。** 再详细的人物设定，也不能把虚构的人变成真实的用户证据。
- **行为参数是假设。** 注意力、疲劳、社会认同和落地页阻力包含人工设定的先验，需要针对目标市场验证。
- **种子波动衡量的是模拟波动**，不是预测置信区间。
- **回测只回答特定问题。** 请在未参与调参的真实实验上分别验证绝对比率、排序和细分人群结论。

## 免费吗？

MarketMirror 源代码以 [AGPL-3.0](LICENSE) 协议开源。运行时可能消耗付费的 AI 调用额度、订阅额度或本地算力，具体取决于受众规模、访谈深度、测试项目和重复次数。

---

问题与反馈欢迎提交 [Issue](https://github.com/DarkWorldCoder/market-mirror/issues) 或参与 [Discussions](https://github.com/DarkWorldCoder/market-mirror/discussions)。如果它对你有帮助，欢迎点个 ⭐。
