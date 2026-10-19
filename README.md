# Gem Arena v2 · 璀璨宝石 AI 编程对战

可运行的 Python 双人 Splendor 基础规则赛场，以及六份冻结智能体的正式循环赛记录。无第三方 Python 依赖。

实现 90 张发展牌、贵族、黄金、明牌及盲抽预留、黄金支付选择、回合内退币、贵族选择与完整末轮结算。非官方实现，不含 Duel 或扩展，也不使用官方卡面插画。

## 正式赛结果

六家两两各 50 局，共 **750 局**；每组 25 个种子交换先手。每位选手 250 局，先后手各 125 局。

最初有 26 局在第 400 手被执行器安全停止。主办方随后要求从原局面继续，完整恢复暗牌、牌堆、库存、阶段和先后手；其中 Claude 对肥鱼第 33 局在第 440 手以 15∶6 结束，其他 25 局运行至第 800 手仍未结束，保存为待续。

**最新结果为 725 局已结束、25 局待续，正常平局为 0。待续不计平局、不发半分。** 所有待续局的可能结果都不足以改变目前六家的名次。

| 排名 | 选手 | 胜 | 负 | 待续 | 已获积分 | 最高可能积分 |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Sol／Prism II | 207 | 42 | 1 | 207 | 208 |
| 2 | Astra／Codex | 201 | 46 | 3 | 201 | 204 |
| 3 | Claude | 175 | 66 | 9 | 175 | 184 |
| 4 | Gemini | 79 | 170 | 1 | 79 | 80 |
| 5 | Qwen | 62 | 177 | 11 | 62 | 73 |
| 6 | DeepSeek／肥鱼 | 1 | 224 | 25 | 1 | 26 |

原先已经结束的 724 局不变。两次超时判负保留，发生在 Astra 对 Sol 第 3 局、Claude 对肥鱼第 1 局；没有非法行动。历史原始汇总仍在压缩记录内，它把初始安全停止计为平局；阅读最新成绩请以本页及 `records/latest-summary.json` 为准。

成绩仅对应本批冻结程序、规则、种子及执行环境；不代表模型厂牌的普遍排名。六份代码的 SHA-256 与原赛提交一致。

## 下载记录并看回放

- [750 局原始日志与离线回放](records/formal-750.zip)
- [26 局原局面续赛、回放与现场](records/continuation-26.zip)
- [完整比赛配置及版本指纹](competition.json)
- [最新详细汇总](records/latest-summary.json)

克隆或下载整个仓库后，在仓库根目录执行：

```text
python tools/unpack_records.py
```

然后双击 `runs/official/v2-six-way-750-overtime/index.html` 看最新续赛总表，或 `runs/official/v2-six-way-750/index.html` 看原始 750 局回放。HTML 全部内嵌数据，可离线播放、单步、拖动进度或全屏录制。续赛回放从第 400 手开始。现场文件保留私有牌堆以支持裁判恢复；旁观 HTML 仍隐藏盲抽牌。

公开元数据去掉了本机绝对路径；750 个原始逐局 JSON 保持字节不变，其哈希列于 `records/original-game-sha256.json`。

## 安装、检查与试赛

Python 3.12 或更新版本，无需 pip 安装。Windows 可将 `python` 换成 `py -3.12`。

```text
python -m unittest discover -s tests -v
python tools/verify_official.py
python -m arena.tournament --a submissions/astra/agent.py --b submissions/sol/agent.py --name-a Astra --name-b Sol --games 2 --seed 398607633 --timeout 3 --max-turns 0 --out runs/my-match
```

`verify_official.py` 从种子逐帧重放 750 局和 26 局续赛，核对记录；不重新运行智能体搜索。计时搜索会随机器和并行负载变化，因此重新比赛不保证行动或比分逐手相同。

当前原引擎的普通 CLI 默认 400 手安全上限并记平局，这是首阶段的历史执行约定。示例显式使用 `--max-turns 0` 关闭人工终局；差策略可能无限拿币、退币。仓库发布的正式续赛已单独处理为待续，并未按 CLI 的默认方式结算。比赛规则见 [RULES.md](RULES.md)，接口见 [AGENT_API.md](AGENT_API.md)。

每完整回合共享 3 秒，包括主行动、退币、选贵族各次进程启动及通信。正式记录来自 local 可信模式、最多 8 局并发；未启用容器 CPU／内存硬隔离。Docker 方案随代码提供，但本轮没有实测。参赛者独立开发时的代码隔离和开发预算由主办方管理。

## 给选手发同一套规则与 API

```text
python -m arena.kit participant-kit-v2.zip
```

打包器只收录引擎、规则、API、测试和公开示例，不收录 `submissions/` 或正式赛记录。本仓库是已结束测试赛的公开资料；新赛事应重新选择保留种子、冻结提交并统一开发及执行条件。

## 许可与数据来源

项目代码使用 [MIT](LICENSE)。六份智能体保留原始提交，随本赛事项目发布；本仓库不宣称参赛模型的身份或性能已经独立认证。

牌表来自 MIT 许可的开源项目，保留 [上游许可证](third_party/SplendorSimulator-LICENSE)，具体出处、固定提交与交叉检查见 [data/provenance.json](data/provenance.json) 和 [ENGINE_REVIEW.md](ENGINE_REVIEW.md)。没有复制官方插画、卡面或标志，不表示获得出版商背书。
