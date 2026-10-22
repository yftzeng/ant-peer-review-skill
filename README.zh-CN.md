# ant-peer-review

[English](README.md) | [繁體中文](README.zh-TW.md) | 简体中文

一套多模型的文章**审核（Audit）**与**撰写（Drafting）**工作流，适用于营销文案、公关稿、新闻、技术文章和评论。

运作方式：
1. 两个以上的 Claude 模型各自独立审稿，彼此看不到对方的结果；
2. 每位 reviewer 再逐条回应其他人的发现；
3. 最后由一段确定性的程序整合所有意见，生成体检报告，内容包括：评分、问题锚定表、事实核查结果、否决红线，以及 A/B 两套修订方案。

本项目包含一个独立的 Python CLI（`ant-peer-review`），以及驱动它的 Claude skill（`SKILL.md`）。

## 安装

```bash
uv tool install --python 3.12 .          # 或：pipx install .
ant-peer-review --version
```

环境要求：
- Python 3.11 以上，无任何运行时依赖。
- 可选（JavaScript 渲染的网页）：`uv tool install '.[render]'`，再执行 `playwright install chromium`。抓取失败时的顺序是：退避重试 → 无头浏览器 → AMP 版本 → 标注日期的 Wayback Machine 存档 → 请你粘贴正文。爬虫不会伪装成浏览器。
- 已登录的 `claude` CLI（Claude Code）。默认通过 `claude -p` 调用模型，消耗的是你的 Claude Code 订阅额度。
- 可选：如需读取 PDF，安装 `pip install 'ant-peer-review[pdf]'` 或 `pdftotext`。

## 快速开始

```bash
ant-peer-review            # 交互模式：首次使用先完成设置，然后跑完整个流程
```

首次使用时需要选择：
- 界面语言：English、繁體中文或简体中文；
- 模型的调用方式；
- peer reviewer 模型：opus、sonnet 默认勾选，fable 可加选，至少勾选 2 个。每个模型都会先发送一次测试请求，确认可用后才保存。

菜单用方向键操作：↑/↓ 移动，Enter 选择，空格勾选 checkbox，也可以直接按数字键；`c` 添加自定义值，Esc 取消。通过管道输入或设置 `ANT_PEER_REVIEW_PLAIN=1` 时，会改回输入编号的方式。方向键操作已在 Linux 上测试；Windows 的按键读取目前还没有自动化测试。

此后每次运行都会先输出：

```
Peer reviewers：opus, sonnet   （变更：ant-peer-review config models）
```

非交互模式（用于脚本、CI，或由 Claude 驱动）：

```bash
ant-peer-review new --yes --purpose audit \
  --target https://example.com/post --target ./drafts \
  --audience expertise=public+beginner,purpose=trend --brand acme
ant-peer-review decide <run-id> --yes --choice B --rule pr_landmine=dismissed
```

`--backend fake` 使用预设的输出离线跑完整个流程，适合演示和冒烟测试。

## 工作流程

| 阶段 | 内容 |
|---|---|
| intake | 选择目的（撰写或审核）；逐行输入目标，单独一行输入 `/done` 或连按两次 Enter 结束；填写受众卡。受众卡共五层：专业度、决策层、产业／政治视角、信任距离、阅读目的，每层都是 checkbox，可多选，也可添加自定义值；全不勾即跳过。 |
| sources | 通过安全爬虫和转换程序把目标转成 Markdown，每段每句都有固定编号（如 `D1.P03.S2`）。prompt injection 扫描会标记可疑文字，并对 reviewer 隐藏。 |
| rubric | 四个维度：结构逻辑（Macro）、事实论据（Accuracy）、语言表达（Micro）、传播转化（Impact，含 S 型曲线）。系统根据受众建议权重，由你修改并确认。 |
| review | 按 reviewer 名单顺序分配视角：结构与论证、事实与合规，第 3 位担任唱反调（Devil's Advocate）。每位 reviewer 独立产出：各维度评分、篇章 → 段落 → 字句三层诊断、待核查的事实主张、敏感度扫描、6 条红线的判定、S 型曲线阶段。 |
| factcheck | 事实主张记入账本并用网页搜索核查。只有当次搜索真正返回过的网址才算来源。可选功能：在受众之后勾选，或加上 `--academic`，文中引用的 DOI 和 arXiv 会再通过 doi.org、Crossref、arXiv 核查是否存在、标题是否相符、有无撤稿。 |
| debate | 每位 reviewer 对其他人的发现表示赞同或提出异议，都必须附证据。 |
| consensus | 用确定性程序统计各方立场：没提到不算同意；有异议的发现标为 SPLIT。随后执行红线否决，计算加权总分和等级。 |
| report | 生成 `06-report.v<N>.md`：量化看板、红线、问题锚定表、分歧、事实核查账本、injection 扫描结果。 |
| revision | A 方案为轻度润色，附逐字 diff，中文也能正确显示；B 方案为深度重构，由另一个模型复审。 |
| decision | 由你裁决有争议的红线，再采用 A、B 或手动修改的版本，保存为 `final.md`。反复出现的修正会建议写入该品牌的 Style Guide。 |

### 否决红线

共 6 条：(a) 涉及违法、(b) 严重事实错误（幻觉）、(c) 品牌公关地雷、(d) 抄袭侵权、(e) 敏感政治、(f) 种族／多元性别与人权。

满足以下任一条件，红线即成立：
- 2 位以上 reviewer 支持，且无人提出异议；
- 仅限 (b)：事实核查账本中有 `unsupported` 的主张作为证据。

红线一旦成立，无论总分多高，都直接判定**不合格**。有争议的红线，或只有一位 reviewer 支持的红线，会等待你裁决。

### 断点续跑

每次运行都有独立的工作区，`state.json` 记录每个阶段输入文件的 hash。只要某个输入发生变化，该阶段及其之后的所有阶段都会重跑。

| 命令 | 用途 |
|---|---|
| `ant-peer-review resume <run>` | 从第一个未完成的阶段继续。 |
| `ant-peer-review rerun <run> --from review` | 从指定阶段重跑。 |
| `ant-peer-review factcheck <run> --continue` | 补查尚未核实的事实。中途停止时，可选择「下次再继续」或「终止并完成」。选择「终止并完成」时，只有事实确实发生变化才会生成新版报告并附变更记录，且不会重新调用 reviewer。 |
| `ant-peer-review runs` | 列出所有任务及其下一个阶段。 |
| `ant-peer-review runs --summary` | 每个任务一行：总分、等级、成立的红线、问题数。加上 `--format csv --out f.csv` 可导出表格。 |
| `ant-peer-review recheck <run> --target <修改版> [--response 回复.md]` | 对照上一轮的发现复审作者的修改版，沿用同一组 reviewer 和评分标准。先只凭修改版逐条判定，之后才看作者回复。报告会多一张修改对照表。 |

## 数据存放位置

所有数据都保存在你自己的机器上，位于用户数据目录：`~/.local/share/ant-peer-review/`。Windows 下为 `%APPDATA%\ant-peer-review`，也可以用 `$ANT_PEER_REVIEW_HOME` 指定。

```
config.toml                语言、调用方式、reviewer、等级阈值
runs/<日期>-<slug>/          每次运行的工作区
LESSONS.md, lessons/       你的心得（索引＋原文归档），不随 skill 发布
site-profiles.json         各域名的爬取规则（屏蔽、User-Agent）
style-guides/<品牌>.md      你确认过的 Style Guide 规则
```

## 安全

- **爬虫：**
  - 首次请求和每次重定向都会重新检查 IP，屏蔽私有网段、loopback、link-local 和云 metadata 地址。
  - 连接固定在已检查的 IP 上，防止 DNS rebinding 绕到内部主机。
  - 遵守 robots.txt，并限制下载大小和内容类型。
- **文件夹转换：** 拒绝 symlink 和不认识的文件类型，读取前后各计算一次 hash。
- **Prompt injection：**
  - 抓取到的文字一律作为数据处理，而不是指令。
  - 这些文字只会放在单一的 `<untrusted_content>` 区块中交给模型；内容中如果出现相同的结束标记，会先被转义。
  - 看起来像在对 reviewer 下指令的文字会被标记并隐藏。
- **心得和 Style Guide：** 都需要你确认后才会写入。

## 开发

```bash
python3 -m pytest -q        # 100+ 个测试；行为规格写在 specs/features/*.md（Gherkin）
```

在本目录直接试用：`scripts/try.sh new --backend fake`。所有数据都写入 `./workspaces/`。该目录已被 git 忽略，`.claude/settings.json` 也禁止 Claude 读取，因为里面存放的是抓取到的不可信内容。

设计和各项决策见 [docs/DESIGN.md](docs/DESIGN.md)。参考过的 7 个 skill 清单及各自借鉴了什么，见 [docs/REFERENCES.md](docs/REFERENCES.md)。`anthropic-api` 后端的接口已预留，按开发顺序排在第二阶段实现。
