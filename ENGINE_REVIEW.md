# 规则、数据与许可记录

## 规则依据

- 官方基础版规则书（2024）：https://cdn.svc.asmodee.net/production-asmodeeca/uploads/2022/01/SCSPL01EN_SPLENDOR_RULES_LIGHT.pdf
- 出版商产品页：https://www.spacecowboys-games.com/game/splendor/

采用基础版双人配置与机制。阅读日期 2026-10-18。没有将 PDF、美术或商标文件复制到项目中。

## 评估过的开源实现

1. dsmiller95/SplendorSimulator：https://github.com/dsmiller95/SplendorSimulator ，固定提交 `0157ce7027880912219a688c665dd63632a1f42f`，MIT（Copyright 2022 Dmiller）。包含 Python／Rust 游戏模型、服务器接口及基础牌表。采用其 `game_data/cards.csv` 数值资料；原始 CSV 与许可证均随项目交付。运行时不依赖或执行它的游戏模型、AI 或服务器代码。
2. roeey777/Splendor-AI：https://github.com/roeey777/Splendor-AI ，固定提交 `95f84d2e6e839c0ef09ca97bdc3b3048a792fb0b`，仓库根许可证 MIT（Copyright 2024 roeey777）。游戏模型文件注明源自 Steven Spratley、Guang Ho、Michelle Blom 的课程环境。源码含框架／显示器导入，现有动作生成采用组合动作而且购牌使用单一资源充足性方案；若直接替换现有裁判接口，仍需对隐私和可选黄金支付重新审计。本版仅用其公开 CARDS／NOBLES 常量交叉核对，不复制或调用其引擎。

决定：沿用已验证的进程执行／比赛／日志架构，独立替换最小规则模块。这样保留单文件参赛接口、明确盲抽隐私、可列举主动黄金支付选项，并避免引入 GUI／机器学习依赖。不是宣称直接采用成熟上游引擎；成熟上游用于数值来源与交叉核验。

## 数据转换和验证

`data/upstream-cards.csv` 为固定提交的原始 CSV；`data/base.json` 将颜色顺序转换为白／蓝／绿／红／黑，统一成本、分数、层级和 ID。`data/provenance.json` 记录提交、路径、SHA256 和交叉核验地址。

按（层级、折扣颜色、分数、五色费用）多重集合逐一比较，90 张牌全部一致；10 位贵族的要求也全部一致。牌表来自开源记录而非本项目合成，也不声称拿实体卡逐张做了独立照片审核。公开规则书不逐一列出所有牌面数值。

## 许可边界

本项目自写代码 MIT，见 LICENSE。采用的上游数值资料附 `third_party/SplendorSimulator-LICENSE`，构建参赛包与完整项目包都会带上。开源代码许可不代表 Splendor 名称、官方美术或其他出版内容获得授权；本项目只提供非官方数值规则模拟和原创回放界面。

## 执行环境

本机 Python 3.12.14，stdlib，local 模式完成端到端测试。Docker 模式沿用原有实现，提供镜像固定、禁网、只读挂载、CPU／内存／PID 限制，但本机未安装 Docker，相关 3 项测试明确跳过；不能据此宣传已完成容器安全验证。
