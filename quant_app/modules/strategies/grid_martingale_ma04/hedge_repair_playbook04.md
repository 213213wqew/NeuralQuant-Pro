# GridMartingaleMA04 对冲剥离体系设计文档（Design + Philosophy + Logic）

本文档用于明确当前策略的核心理念、设计边界、执行逻辑与评估方法。  
重点不是“猜顶猜底”，而是把高风险库存从不可控变成可压缩、可恢复、可验证。

---

## 1. 核心理念（Philosophy）

### 1.1 第一性原则
- **先活下来，再谈效率**：任何收益优化都不能破坏保证金与净敞口安全。
- **库存压缩优先于利润最大化**：对冲阶段目标是缩风险，不是追短期利润峰值。
- **分层处理优于一次性重锤**：坏仓按可承受预算逐步剥离，避免在最差点位硬割最大单。
- **规则执行优先于主观判断**：用状态机和阈值替代情绪化操作。

### 1.2 策略定位
- 这不是纯趋势策略，也不是纯反转策略。
- 本体系是 **网格仓位失衡后的库存修复系统**：
  - 先对冲波动
  - 再配对剥离
  - 最终回归常规模式

---

## 2. 设计目标（Design Objectives）

- 当单侧仓位过深时，停止放大同向风险。
- 用反向救援仓缓冲单边波动，控制净敞口失控。
- 让救援仓利润服务于“坏仓剥离”，而不是形成新库存。
- 在行情回撤/回吐时自动切换保护路径。
- 在仓位或保证金接近边界时强制进入“只减不加”。

---

## 3. 系统边界（System Boundaries）

### 3.1 系统做什么
- 识别单侧层数超阈值后的风险阶段。
- 进入对冲修复状态机并执行分支动作。
- 动态输出状态快照给面板（含模式、仓位、PnL、参考线）。

### 3.2 系统不做什么
- 不保证单次对冲必胜。
- 不追求在极端行情中高收益。
- 不依赖“下一根K线必反转”的假设。

---

## 4. 触发机制与方向判定

入口：`run_iteration()` -> `_try_enter_hedge_mode()`

- `buy_count >= InpHedgeTriggerLayers`
  - 触发侧（坏仓侧）=`BUY`
  - 救援侧（对冲侧）=`SELL`
- `sell_count >= InpHedgeTriggerLayers`
  - 触发侧（坏仓侧）=`SELL`
  - 救援侧（对冲侧）=`BUY`

进入修复模式时记录：
- `g_hedge_trigger_loss_at_start`：坏仓起始亏损基线
- `g_hedge_rescue_peak_profit`：救援利润峰值
- `g_hedge_repair_state`：当前状态

---

## 5. 状态机设计（State Machine）

核心函数：
- 判定：`_classify_hedge_repair_state(rescue_type)`
- 执行：`_run_hedge_repair_state_machine(rescue_type)`

状态列表：
- `expand_rescue`
- `peel_bad_side`
- `protect_rescue`
- `bad_side_recovery`
- `reduce_only`
- `exit_repaired`

### 5.1 expand_rescue（补救援）
- 目标：维持必要覆盖率，不做无上限加仓。
- 逻辑：按触发侧手数和亏损强度计算目标覆盖，分批补救援。
- 限制：单次开仓受 `InpHedgeRescueMaxOpenLot` 等约束。

### 5.2 peel_bad_side（配对剥离）
- 目标：把救援利润转换为坏仓减负。
- 逻辑：
  - 计算可用利润预算
  - 选取盈利救援仓做资金来源
  - 对触发侧亏损仓做全平或部分平
- 关键：保留最低净利润缓冲，避免“剥离后净值更差”。

### 5.3 protect_rescue（利润保护）
- 条件：救援利润达到高位后明显回吐。
- 处理：优先尝试配对剥离；若不可行，先锁一部分盈利救援仓。
- 目的：防止救援利润被行情回吐吞没。

### 5.4 bad_side_recovery（坏仓恢复）
- 条件：坏仓亏损较触发时显著收敛。
- 处理：
  - 优先平掉接近回本/小亏仓位
  - 必要时止损最差救援仓，避免救援变坏仓
- 本质：行情回归坏仓方向时，主动作库存收缩。

### 5.5 reduce_only（只减不加）
- 条件：仓位数或保证金触发风控边界。
- 行为：禁止新增，仅允许剥离、减仓、清理。
- 作用：防止修复阶段再次失控。

### 5.6 exit_repaired（退出修复）
- 条件：坏仓侧风险降至可接受或库存清空。
- 行为：清理剩余可清理仓位，重置修复模式。
- 结果：回到常规网格运行。

### 5.7 触发侧微加仓（可选，`InpHedgeTriggerMicroEnable`）
- **目的**：在已有救援浮盈垫的前提下，用小额单改善触发侧均价，使面板参考线更快达到可平区；与「触线平触发侧」「全平退出」衔接。
- **允许状态**：仅 `peel_bad_side`、`bad_side_recovery`（不在 `expand_rescue` / `protect_rescue` / `reduce_only` 下加触发侧）。
- **价位规则**：与主网格逆势加仓相反——空单坏仓在更高处补空、多单坏仓在更低处补多（使用 `InpHedgeTriggerMicroStepPts`）。
- **闸门**：救援侧浮盈 ≥ `InpHedgeTriggerMicroMinRescueProfit`；触发侧亏损 ≥ `InpHedgeTriggerMicroMinTriggerLoss`；次数 ≤ `InpHedgeTriggerMicroMaxAdds`；累计手数 ≤ `InpHedgeTriggerMicroMaxLotsAdd`；波动冻结与保证金缓冲同救援开仓。

---

## 6. “先小后中后大”思想的落地解释

该思想可以作为剥离层级策略：
- **第一层：先剥离小亏/近回本**，快速降仓位数与压力。
- **第二层：处理中间亏损层**，逐步压缩风险带。
- **第三层：大单触及盈利阈值优先锁定**，释放尾部风险权重。

注意：该思想必须叠加以下约束才能稳健：
- 净敞口上限
- 保证金底线
- 超时保护
- 连续亏损熔断

---

## 7. 关键参数分组（Parameter Topology）

### 7.1 对冲扩张
- `InpHedgeRescueBaseRatio`
- `InpHedgeRescueMaxRatio`
- `InpHedgeRescueStrongLossMoney`
- `InpHedgeRescueMaxOpenLot`

### 7.2 剥离预算
- `InpHedgePeelProfitUseRatio`
- `InpHedgePeelMinProfitMoney`
- `InpHedgePeelKeepProfitMoney`
- `InpHedgePeelMinNetMoney`

### 7.3 恢复与保护
- `InpHedgeRepairRecoveryRatio`
- `InpHedgeRepairRecoveredLossMoney`
- `InpHedgeRepairExitTriggerLossMoney`
- `InpHedgeRescueProtectStartMoney`
- `InpHedgeRescueProfitTrailBackPct`
- `InpHedgeRescueStopLossMoney`
- `InpHedgeRecoveryCloseMaxLossMoney`
- `InpHedgeRecoveryCloseMaxOrders`
- `InpHedgeReduceOnlyMarginLevel`
- `InpHedgeTriggerMicroEnable` / `InpHedgeTriggerMicroLot` / `InpHedgeTriggerMicroMaxAdds` / `InpHedgeTriggerMicroMaxLotsAdd` / `InpHedgeTriggerMicroStepPts` / `InpHedgeTriggerMicroMinRescueProfit` / `InpHedgeTriggerMicroMinTriggerLoss`

---

## 8. 可视化与参考线逻辑

- 常规模式：使用常规目标价输出参考线。
- 对冲模式：参考线改为基于对冲目标动态计算，随仓位和目标实时变化。
- 作用：让修复阶段也有价格锚点，便于人工观察执行质量。

---

## 9. 评估架构（Evaluation Framework）

### 9.1 风险硬指标（Gate）
- `Max Drawdown %`
- `Min Margin Level %`
- `Max Net Lots`
- `Max Total Positions`
- `Longest Hedge Duration`

### 9.2 修复效率指标
- `Hedge Trigger Count`
- `Peel Attempt Count`
- `Peel Success Rate`
- `Median Recovery Time`
- `Inventory Compression Ratio`

### 9.3 收益质量指标
- `Net PnL After Cost`
- `Profit Factor`
- `Realized/Floating Ratio`

### 9.4 稳健性指标
- `Regime Robustness Score`
- `Parameter Sensitivity Score`

### 9.5 场景矩阵
- 震荡窄幅
- 震荡宽幅
- 单边慢趋势
- 单边急趋势
- V 反场景
- 高点差场景

---

## 10. 运行与调参原则（Operational Rules）

- 先做小仓、长样本验证，不在高杠杆直接试错。
- 先守风控红线，再追求收益改善。
- 调参遵循“少参数优先，稳健区间优先”，不追单次最优点。
- 任何版本上线前必须通过场景矩阵，不允许只看单一行情截图。

---

## 11. 结论

本方案的本质是：  
**通过状态机把“失衡库存”变成“可管理库存”，把不可控风险转化为可量化、可收敛、可复盘的流程。**

在执行层面，优先级始终是：
**生存性 > 风险收敛 > 修复效率 > 收益优化。**

