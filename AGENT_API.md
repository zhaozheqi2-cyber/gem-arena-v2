# Agent API v2

提交一个 Python 标准库文件 `agent.py`，定义：

```python
def choose(observation, memory):
    assert observation['version'] == 'gem-arena-2.0'
    return {'action': 0, 'memory': None}
```

`action` 是 **当前** `observation['legal_actions']` 中的零起始索引，必须是整数，布尔值不接受。不要返回行动字典、旧索引或自己拼接的动作。`memory` 是可选 JSON 数据，最多 4096 字节；首次是 None，后续只回传给本选手。本回合内的辅助调用也会接续 memory。

每次调用均为新进程，不能依赖模块全局状态跨调用保留。禁止向 stdout 打印日志；输出由 worker 产生。stdout 上限 16384 字节；异常、超时、非法索引、错误 JSON 都会判本局负。不要访问文件、网络、其他选手或裁判内部对象。

## 观察

- `version`: `gem-arena-2.0`。v1 提交必须重新适配。
- `you`／`to_play`: 0 或 1，表示座位，与外部选手名字无关。
- `turn`: 已完成回合数；辅助阶段不变。`decisions`: 已完成的行动／辅助选择次数。
- `phase`: `main`、`discard` 或 `noble`。三者都调用同一个 choose。
- `bank`: 六维筹码，**白、蓝、绿、红、黑、金**。`colors` 也是此顺序。
- `players`: 两名玩家。每位有 `tokens`（六维）、`bonuses`（仅五维，无黄金折扣）、`score`、`cards`（已购牌 ID）、`reserved`、`nobles`（已获贵族 ID）。
- `market`: 三层公开牌数组，每牌 `id`、`tier`（1..3）、`bonus`（0..4）、`points`、`cost`（五维）。
- `nobles`: 尚未归属的贵族，每位 `id`、`points=3`、`requirements`（五维永久折扣要求）。
- `deck_counts`: 三层未翻开的牌堆张数；没有顺序或种子。
- `target=15`、`end_triggered`、`max_turns`（0 表示无上限）。
- `legal_actions`: 完整合法选项，包含所有黄金支付方式、超额退币组合和可选贵族。
- 比赛运行器额外提供 `turn_budget_ms` 和 `time_remaining_ms`。直接用 `Game.observation()` 本地测试时可没有这两项。

预留牌条目形状为 `{'card': 完整牌对象, 'public': bool}`。本人的预留牌始终能看到内容；对方从市场预留的明牌可见；对方盲抽条目是 `{'card': None, 'public': False, 'tier': 1}`，不含 ID、费用或分数。对方牌数可见。日志回放采取旁观视角，不暴露任一方盲抽内容。

## 行动类型

| phase | type | 字段／含义 |
| --- | --- | --- |
| main | buy | `card`、`source='market'/'reserved'`、`payment` 六维；不同支付方案是不同索引 |
| main | take | `tokens` 六维；黄金位总是 0 |
| main | reserve | `source='market', card=牌ID`，或 `source='deck', tier=1..3` |
| main | pass | 仅无其他合法主行动时出现 |
| discard | discard | `tokens` 六维退回数量，合计恰好为超额数 |
| noble | noble | `noble` 为所选贵族 ID，必须选一位 |

预留行动的黄金自动按规则领取；不能拒领后规避回合末退币。黄金不与被预留牌绑定，日后可以买别的牌。

## 一回合可能发生多次 choose

例如：`main` 拿 3 枚 → 变成 12 枚 → 同一玩家 `discard` 退 2 枚 → 如有达标贵族，同一玩家 `noble` 选一位 → 换人。`turn` 在最后一步后才加 1。不要只凭 turn 判断 observation 一定没变。

所有调用 **合计** 使用同一回合预算，默认 3000 毫秒，包含每次启动和通信。后续调用的剩余预算会减少。计时搜索请依据 `time_remaining_ms` 预留启动／通信余量，不要每次都硬编码用满 2 秒。主行动选择时也应给可能的辅助阶段留余量。超时不会自动回退到 action=0。

## 自测

`agents/starter.py` 是最小接口，`agents/greedy.py` 是公开基础版启发式，`agents/random_bot.py` 是公开随机基线。均非正式选手。用同一个开发包中的裁判测试；最终仍只提交自己的一个文件，不要把裁判数据模块当成运行时可导入依赖（可以在自己文件中带上公开牌表）。

```text
python -m arena.tournament --a agent.py --b agents/greedy.py --name-a Candidate --name-b PublicGreedy --games 20 --seed 1000 --out runs/practice-01
python -m arena.verify runs/practice-01
```
