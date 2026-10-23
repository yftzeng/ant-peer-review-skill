# ant-peer-review

[English](README.md) | 繁體中文 | [简体中文](README.zh-CN.md)

這是一套給文章用的多模型**審核（Audit）**與**撰寫（Drafting）**工作流，適用於行銷文案、公關稿、新聞、技術文章和評論。

運作方式：
1. 兩個以上的 Claude 模型各自獨立審稿，彼此看不到對方的結果；
2. 每位 reviewer 再回應其他人的發現；
3. 最後由一段確定性的程式整合所有意見，產出體檢報告，內容包括有評分的問題錨點表、事實查證結果、否決紅線，以及 A/B 兩套修訂方案。

專案包含一支獨立的 Python CLI（`ant-peer-review`），以及一份驅動它的 Claude skill（`SKILL.md`）。

## 安裝

```bash
uv tool install --python 3.12 .          # 或：pipx install .
ant-peer-review --version
```

需求：
- Python 3.11 以上，沒有任何執行期相依套件。
- 選用（JavaScript 渲染的網頁）：`uv tool install '.[render]'`，再執行 `playwright install chromium`。抓取失敗時的順序是：退避重試 → 無頭瀏覽器 → AMP 版本 → 標註日期的 Wayback Machine 存檔 → 請你貼上內文。爬蟲不會偽裝成瀏覽器。
- 已登入的 `claude` CLI（Claude Code）。預設的呼叫方式是 `claude -p`，使用的是你的 Claude Code 訂閱額度。
- 選用：要讀 PDF，需安裝 `pip install 'ant-peer-review[pdf]'` 或 `pdftotext`。

## 快速開始

```bash
ant-peer-review            # 互動模式：首次使用先完成設定，接著跑完整個流程
```

首次使用時要選三件事：
- 介面語言：English、繁體中文或简体中文；
- 模型的呼叫方式；
- peer reviewer 模型：opus、sonnet 預設勾選，fable 可加選，至少要勾 2 個。每個勾選的模型都會先送一次小請求確認能用，才會儲存。

選單用方向鍵操作：↑/↓ 移動、Enter 選擇、空白鍵勾選 checkbox，也可以直接按數字鍵；`c` 新增自訂值，Esc 取消。用管線輸入、或設定 `ANT_PEER_REVIEW_PLAIN=1` 時，會改回輸入編號的方式。方向鍵操作已在 Linux 測試過；Windows 的按鍵讀取目前還沒有自動化測試。

之後每次執行，開頭都會印出：

```
Peer reviewers：opus, sonnet   （變更：ant-peer-review config models）
```

非互動模式（用於腳本、CI，或由 Claude 驅動）：

```bash
ant-peer-review new --yes --purpose audit \
  --target https://example.com/post --target ./drafts \
  --audience expertise=public+beginner,purpose=trend --brand acme
ant-peer-review decide <run-id> --yes --choice B --rule pr_landmine=dismissed
```

`--backend fake` 會用預先寫好的輸出跑完整個流程，不連網，適合展示和煙霧測試。

## 工作流程

| 階段 | 內容 |
|---|---|
| intake | **目的**：撰寫或審核。**目標**：逐行輸入，單獨一行輸入 `/done` 或連按兩次 Enter 結束。**受眾卡**共五層：專業度、決策層、產業／政治視角、信任距離、閱讀目的。每層都是 checkbox，可以多選，也可以加自訂值；全不勾就是略過。 |
| sources | 用安全爬蟲和轉檔程式把目標轉成 Markdown，每段每句都有固定編號（例如 `D1.P03.S2`）。Prompt injection 掃描會標記可疑文字，並把它從 reviewer 看到的內容中隱藏。 |
| rubric | 四個維度：結構邏輯（Macro）、事實論據（Accuracy）、語言表達（Micro）、傳播轉換（Impact，含 S 型曲線）。系統依受眾建議權重，你可以修改後再確認。 |
| review | 依 reviewer 名單順序分配視角：結構與論證、事實與合規，第 3 位擔任質疑者（Skeptic）。各 reviewer 獨立審稿，產出：各維度評分、篇章 → 段落 → 字句三層診斷、待查證的事實主張、敏感度掃描、6 條紅線判定、S 型曲線階段。 |
| factcheck | 事實主張寫進帳本，用網頁搜尋查證。只有當次搜尋真的回傳過的網址才算來源。選用功能：在受眾之後勾選，或加上 `--academic`，文中引用的 DOI 和 arXiv 會再透過 doi.org、Crossref、arXiv 查證是否存在、標題是否相符、有無撤稿。 |
| debate | 每位 reviewer 對其他人的發現表示贊同或提出異議，都要附證據。 |
| consensus | 用確定性的程式統計立場：沒提到不算同意，有異議就標成 SPLIT。接著套用紅線否決，算出加權總分和等級。 |
| report | 產出 `06-report.v<N>.md`，內容包括量化看板、紅線、問題錨點表、分歧、事實查證帳本、injection 掃描結果。 |
| revision | A 方案是輕度潤色，附逐字 diff，中文也能正確顯示。B 方案是深度重構，改完會由另一個模型複審。 |
| decision | 由你裁決有爭議的紅線，再選擇採用 A、B 或手動修改的版本，存成 `final.md`。反覆出現的修正會建議寫進該品牌的 Style Guide。 |

### 否決紅線

共 6 條：(a) 涉及違法、(b) 嚴重事實錯誤（幻覺）、(c) 品牌公關地雷、(d) 抄襲侵權、(e) 敏感政治、(f) 種族／多元性別與人權。

以下任一情況，紅線就算成立：
- 2 位以上 reviewer 支持，而且沒有人提出異議；
- 僅限 (b)：事實查證帳本中有 `unsupported` 的主張作為證據。

紅線一旦成立，不論總分多高，都直接判**不合格**。有爭議、或只有一位 reviewer 支持的紅線，會等你裁決。

### 斷點續跑

每次執行都有獨立的工作區，`state.json` 記錄每個階段輸入檔的 hash。只要輸入改變，該階段和它之後的所有階段都會重跑。

| 指令 | 用途 |
|---|---|
| `ant-peer-review resume <run>` | 從第一個沒完成的階段繼續。 |
| `ant-peer-review rerun <run> --from review` | 從指定階段重跑。 |
| `ant-peer-review factcheck <run> --continue` | 補查還沒驗證的事實。中途停下時，可選「下次再繼續」或「終止並完成」。選「終止並完成」時，只有事實真的有變化才會產生新版報告並附變更紀錄，而且不會重新呼叫 reviewer。 |
| `ant-peer-review runs` | 列出所有工作和各自的下一個階段。 |
| `ant-peer-review runs --summary` | 每個工作一列：總分、等級、成立的紅線、問題數。加上 `--format csv --out f.csv` 可匯出試算表。 |
| `ant-peer-review recheck <run> --target <修改版> [--response 回覆.md]` | 對照前一輪的發現複審作者的修改版，沿用同一組 reviewer 和評分標準。先只憑修改版逐條判定，之後才看作者回覆。報告會多一張修改對照表。 |

## 資料存放位置

所有資料都留在你自己的機器上，存放在使用者資料目錄：`~/.local/share/ant-peer-review/`，Windows 為 `%APPDATA%\ant-peer-review`，也可以用 `$ANT_PEER_REVIEW_HOME` 指定。

```
config.toml                語言、呼叫方式、reviewer、等級門檻
runs/<日期>-<slug>/          每次執行的工作區
LESSONS.md, lessons/       你的心得（索引＋原文封存），不隨 skill 發佈
site-profiles.json         各網域的爬取規則（封鎖、User-Agent）
style-guides/<品牌>.md      你確認過的 Style Guide 規則
```

## 安全

- **爬蟲：**
  - 第一次請求和每一次轉址都會重新檢查 IP，擋掉私有網段、loopback、link-local 和雲端 metadata 位址。
  - 連線固定在檢查過的那個 IP，防止 DNS rebinding 繞到內部主機。
  - 遵守 robots.txt，並限制下載大小和內容類型。
- **資料夾轉檔：** 拒絕 symlink 和不認得的檔案類型；讀檔前後各算一次 hash。
- **Prompt injection：** 抓下來的文字一律當資料，不當指令。這些文字只會放在單一的 `<untrusted_content>` 區塊裡交給模型，內容中如果出現同樣的結束標記，會先被轉義。看起來像在對 reviewer 下指令的文字會被標記並隱藏。
- **心得和 Style Guide** 都要你確認後才會寫入。

## 開發

```bash
python3 -m pytest -q        # 100+ 個測試；行為規格寫在 specs/features/*.md（Gherkin）
```

在這個目錄直接試用：`scripts/try.sh new --backend fake`。所有資料都寫進 `./workspaces/`。這個目錄已被 git 忽略，`.claude/settings.json` 也禁止 Claude 讀取，因為裡面存的是爬下來的不可信內容。

設計與各項決策見 [docs/DESIGN.md](docs/DESIGN.md)；參考來源見下方[參考來源](#參考來源)。`anthropic-api` 的呼叫介面已預留，依開發順序排在第二階段實作。

## 參考來源

完整清單、借鏡了什麼、在本 repo 的哪裡：[docs/REFERENCES.md](docs/REFERENCES.md)。

參考過的審稿 skill（皆為 MIT；只借鏡概念，未複製程式碼或文字）：
- [K-Dense-AI peer-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/peer-review/SKILL.md) (MIT)
- [tsingke/thesis-review-skill](https://github.com/tsingke/thesis-review-skill) (MIT)
- [jam-cc/paper-review.skill](https://github.com/jam-cc/paper-review.skill) (MIT)
- [K-Dense-AI paperzilla](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paperzilla/SKILL.md) (MIT)
- [K-Dense-AI paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/skills/paper-lookup/SKILL.md) (MIT)

其餘概念依據的公開來源：RFC 7282 (consensus), Altman & Bland 1995 (absence of evidence), Kim et al. 2025 (correlated LLM errors), the Cochrane Handbook (blinded assessment), the CGI-I scale, NASA SWE-059 (traceability), Noble 2017 (responding to reviewers), Toulmin (argument structure), NIST SP 800-86 and AI RMF, OWASP LLM01/LLM05:2025, Greshake et al. 2023 (indirect prompt injection), Unicode UAX #15 / UTS #39, Trojan Source and CWE-367。詳見 [docs/REFERENCES.md §6](docs/REFERENCES.md#6-independent-sources-replace-rows-69)。

設計期間另讀過 4 個 skill，但授權不允許商用（CC BY-NC 4.0，或未聲明授權）。在那裡看到的每個概念都已改用上述獨立來源並重新命名，本 repo 不含任何它們的內容。

## 授權

[MIT](LICENSE) © 2026 Yi-Feng Tzeng，可商用。

- 執行期沒有相依套件。選用套件各有授權：`pdf` → pypdf（BSD-3-Clause）、`render` → Playwright（Apache-2.0）、`test` → pytest（MIT）。
- 執行時抓取的資料（網頁、doi.org、Crossref、arXiv）仍屬原權利人，工具只存進你的 workspace，不在本授權範圍內。
