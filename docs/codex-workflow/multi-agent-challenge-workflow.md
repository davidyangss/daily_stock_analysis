# 报告挑战与 Codex 多 SubAgent 协作协议

> 文档状态：目标工作流设计。当前仓库尚未提供完整的段落 ID、Challenge API、裁决存储和报告 amendment 运行时。

## 1. 目标

用户拿到分析报告后，可以选中一个段落或具体结论，写下质疑，并把问题路由给形成该结论的策略/角色及其反方。各 SubAgent 在原报告相同的数据截止时点和证据集上答辩；独立裁决角色检查证据和逻辑后，生成可追加到报告的修订，而不是静默覆盖原文。

最小闭环：

```text
报告（稳定 section/claim ID）
-> 用户选中文本并提出 challenge
-> Codex 锁定原 context revision
-> 相关策略/角色答辩 + 反方挑战
-> Evidence Verifier 检查引用
-> Challenge Judge 裁决
-> Report Editor 生成 amendment
-> 原报告保留，修订追加并建立双向链接
```

## 2. 不变量

1. **绑定原文**：挑战必须指向 `report_id + section_id`，最好再指向 `claim_id`。
2. **绑定时点**：答辩默认只使用原报告 `context_id/revision/data_cutoff` 中的数据。
3. **事实可追踪**：事实型 claim 必须引用 evidence ID。
4. **角色不越权**：策略解释规则，Trader 决定采用，Risk 调整风险，Judge 裁决，Editor 只改文案。
5. **原报告只读**：所有变化以 amendment/revision 附加。
6. **新旧数据分离**：新增行情或新闻会创建新 context revision，不能混入“原判断是否合理”的裁决。
7. **不强制唱反调**：反方如果证据支持原结论，可以返回 `support`；对抗的目标是检验，不是制造分歧。
8. **不自动交易**：challenge 和 amendment 都不构成下单指令。

## 3. 报告必须先具备可挑战结构

### 3.1 Report manifest

```json
{
  "report_id": "report_600519_20260804_001",
  "report_version": 1,
  "context_id": "ctx_600519_20260804_r1",
  "context_revision": 1,
  "subject": {"code": "600519", "name": "贵州茅台", "market": "cn"},
  "created_at": "2026-08-04T15:30:00+08:00",
  "data_cutoff": "2026-08-04T15:00:00+08:00",
  "sections": [],
  "amendments": []
}
```

### 3.2 稳定 Section ID

推荐 ID：

```text
market.technical
market.context
intel.news
intel.sentiment
fundamentals.quality
strategy.<strategy_id>
strategy.synthesis
research.bull
research.bear
research.decision
trader.plan
risk.aggressive
risk.conservative
risk.neutral
portfolio.final
data.evidence
data.quality
```

同一报告版本内 ID 不可变化。若同一策略出现多次，可追加用途或序号，例如 `strategy.volume_breakout.entry`。

### 3.3 Section 和 Claim

```json
{
  "section_id": "strategy.volume_breakout",
  "title": "放量突破策略",
  "owner_role": "strategy.volume_breakout",
  "content": "股价放量突破前高，突破可信度较高。",
  "content_hash": "sha256:...",
  "strategy_ids": ["volume_breakout"],
  "claims": [
    {
      "claim_id": "strategy.volume_breakout.claim.1",
      "claim_type": "fact|interpretation|recommendation|assumption",
      "text": "成交量达到 5 日均量的 2 倍。",
      "evidence_refs": ["technical.volume.2026-08-04"],
      "confidence": 0.84
    }
  ]
}
```

`content_hash` 用来检测用户标记后原段落是否已经变化。`claim_type` 可以帮助路由：事实争议优先交给 Evidence Verifier，解释争议交给策略/研究角色，仓位争议交给 Trader/Risk/Portfolio。

## 4. 用户标记和 `ChallengeRequest`

### 4.1 用户界面产生的最小标记

```json
{
  "report_id": "report_600519_20260804_001",
  "section_id": "trader.plan",
  "claim_id": "trader.plan.claim.2",
  "selected_text": "放量突破已得到确认，可在现价附近建仓。",
  "challenge": "量比只有 1.3，为什么满足放量突破？",
  "requested_roles": [
    "strategy.volume_breakout",
    "trader",
    "risk.conservative"
  ]
}
```

如果 UI 还没有 claim ID，至少保存 section ID、选中文本、字符区间和当时的 content hash。不能只发送一段脱离报告的文本，因为同一句话在不同日期和策略中可能含义不同。

### 4.2 完整 `ChallengeRequest`

```json
{
  "challenge_id": "challenge_01J...",
  "report_id": "report_600519_20260804_001",
  "report_version": 1,
  "context_id": "ctx_600519_20260804_r1",
  "context_revision": 1,
  "section_id": "trader.plan",
  "claim_id": "trader.plan.claim.2",
  "selected_text": "放量突破已得到确认，可在现价附近建仓。",
  "selection_start": 42,
  "selection_end": 63,
  "section_content_hash": "sha256:...",
  "user_claim": "量比只有 1.3，为什么满足放量突破？",
  "challenge_type": "evidence|logic|assumption|strategy_fit|execution|risk|freshness",
  "scope": "original_evidence|refresh_evidence|both",
  "requested_roles": ["strategy.volume_breakout", "trader", "risk.conservative"],
  "evidence_refs": ["technical.volume.2026-08-04"],
  "created_at": "2026-08-04T16:00:00+08:00"
}
```

字段规则：

| 字段 | 规则 |
| --- | --- |
| `scope=original_evidence` | 只检验原报告在当时是否成立，默认值 |
| `scope=refresh_evidence` | 以新数据重新评估，必须创建新 context revision |
| `scope=both` | 分成两个子问题，分别给出“原判断审计”和“当前状态更新” |
| `requested_roles` | 用户可指定；主 Agent 可补充必要 verifier/judge，但不能删除用户指定角色 |
| `evidence_refs` | 用户认为直接相关的证据，可为空；系统仍会从 claim 找原始引用 |

## 5. SubAgent 上下文包

每个参与者收到共同 envelope，再附角色 slice：

```json
{
  "role_contract": {},
  "challenge_request": {},
  "report_fragment": {
    "section": {},
    "neighbor_sections": [],
    "upstream_claims": []
  },
  "context_ref": {
    "context_id": "ctx_600519_20260804_r1",
    "revision": 1,
    "data_cutoff": "2026-08-04T15:00:00+08:00"
  },
  "context_slice": {},
  "evidence_registry": {},
  "strategy_contracts": [],
  "prior_decisions": [],
  "output_schema": {}
}
```

### 5.1 上下文裁剪

| 参与者 | 必要上下文 |
| --- | --- |
| Strategy Agent | 自身版本化策略规则、required tools 证据、原策略结果、被挑战 claim |
| Trader | 全部策略结果/冲突、研究计划、组合约束、原 TraderProposal、关键证据 |
| Bull/Bear | 四类分报告、相关策略结果、被挑战 claim、证据质量摘要 |
| Risk | Trader plan、失效条件、仓位约束、相关策略和数据质量 |
| Evidence Verifier | claim、全部 evidence refs、来源/时点/计算口径；不需要角色人格 prompt |
| Judge | 所有答辩、verifier 结果、原 claim；原则上不重新抓数据 |
| Report Editor | 裁决、原段落、允许的 patch 操作；不需要完整原始行情 |

上下文片段必须来自同一 revision。主 Agent 若发现角色输出引用其他时点的值，应把该论据标为无效或转入 refresh 分支。

## 6. SubAgent 答辩输出 `ChallengeResponse`

所有策略和角色使用统一 envelope：

```json
{
  "challenge_id": "challenge_01J...",
  "agent_id": "strategy.volume_breakout",
  "role_type": "strategy|trader|research|risk|verifier",
  "context_id": "ctx_600519_20260804_r1",
  "stance": "support|oppose|mixed|insufficient",
  "claims": [
    {
      "text": "量比 1.3 未满足该策略约 2 倍均量的确认要求。",
      "claim_type": "fact|interpretation|recommendation",
      "evidence_refs": ["technical.volume.2026-08-04"]
    }
  ],
  "counterexamples": [],
  "assumptions": [],
  "evidence_refs": ["technical.volume.2026-08-04"],
  "missing_evidence": [],
  "confidence": 0.91,
  "recommended_change": "keep|clarify|weaken|replace|remove",
  "replacement_text": "当前价格突破阻力，但量能未达到放量突破策略的确认阈值，应视为待确认突破。",
  "reasoning": "..."
}
```

`stance` 始终相对于**原报告中被挑战的 claim**：`support` 表示原 claim 仍成立，`oppose` 表示原 claim 不成立，`mixed` 表示只能保留一部分，`insufficient` 表示证据不足以判断。它不表示 Agent 是否赞同用户。`recommended_change` 同样针对原报告文本。

### 6.1 不同角色的额外字段

策略 Agent：

```text
conditions_met
conditions_missed
original_signal
revised_signal
score_adjustment_delta
```

Trader：

```text
adopted_strategies
rejected_strategies
strategy_conflicts
action_before
action_after
position_impact
execution_plan_changes
```

Risk：

```text
risk_scenarios
invalidation_conditions
maximum_acceptable_exposure
risk_override
```

Evidence Verifier：

```text
verified_refs
invalid_refs
calculation_checks
time_boundary_checks
source_consistency_checks
```

## 7. 路由规则

### 7.1 默认参与者矩阵

| 被挑战内容 | 原作者/答辩方 | 默认反方或复核方 | 最终裁决关注点 |
| --- | --- | --- | --- |
| 行情、指标数值 | Market Analyst / 对应策略 | Evidence Verifier | 数值、窗口、复权、交易日 |
| 新闻或事件 | News Analyst / Event Strategy | Evidence Verifier + Bear Researcher | 发布时间、来源、原文/摘要、影响路径 |
| 基本面 | Fundamentals Analyst / Growth Strategy | Evidence Verifier + Bear Researcher | 报告期、可得日、跨期混合 |
| 单一策略 | 对应 Strategy Agent | Trader + Conservative Risk | 规则是否满足、策略是否适用 |
| 策略综合 | 各相关 Strategy Agents | Bull/Bear + Trader | 重复证据、冲突和权重 |
| Trader 行动 | Trader | 被采用/拒绝的策略 + 三类 Risk | 行动、仓位、条件与策略是否一致 |
| 风险结论 | 对应 Risk Analyst | Trader + 其他风险角色 | 情景完整性、约束和过度保守/激进 |
| Portfolio 最终结论 | Portfolio Manager | Trader + 三类 Risk + Judge | 是否忠实处理上游分歧 |

用户显式点名的角色必须参与。如果点名角色与问题无关，该角色可以返回 `insufficient` 并说明权限边界，而不是越权回答。

### 7.2 自动补充角色

主 Agent 可以补充：

- 所有事实争议添加 Evidence Verifier；
- 所有最终报告修改添加 Challenge Judge 和 Report Editor；
- 策略结论影响仓位时添加 Trader；
- Trader 行动可能提高风险时添加 Conservative Risk；
- 刷新数据时添加 Context Builder，并创建独立 refresh 子流程。

## 8. 执行状态机

```text
created
-> context_locked
-> routed
-> debating
-> evidence_verified
-> adjudicated
-> amendment_drafted
-> applied
```

异常终态：

```text
stale_selection
insufficient_context
needs_refresh_authorization
partially_answered
rejected
```

执行步骤：

1. **验证选择**：检查 report/version/section/content hash；不匹配则返回 `stale_selection`。
2. **锁定上下文**：加载原报告引用的 context revision 和 evidence registry。
3. **分类**：判断是事实、逻辑、假设、策略适配、执行、风险还是时效问题。
4. **路由**：合并用户指定参与者和默认矩阵。
5. **独立答辩**：各 SubAgent 先独立返回结构化意见，避免第一位发言者锚定其他角色。
6. **针对性反驳**：仅在首轮存在实质冲突时，把对方 claims 发送一轮交叉反驳。
7. **证据核验**：检查 evidence ID、值、计算、来源和截止时点。
8. **裁决**：Judge 对 claim 作 keep/amend/append/retract 决策。
9. **编辑**：Editor 依据裁决生成最小 patch。
10. **保存**：amendment 与原 section、challenge、context 双向关联。

建议最多一轮交叉反驳。若分歧源于缺失证据，继续辩论不会增加信息，应直接返回 `insufficient` 或请求 refresh。

## 9. Evidence Verifier

Evidence Verifier 是确定性检查优先的角色，不负责市场观点。检查清单：

1. evidence ID 是否存在于锁定的 registry；
2. 引用值是否与原始标准字段一致；
3. 指标窗口、公式、复权和单位是否正确；
4. 日线是否为完整收盘 K 线；
5. 新闻是正文、摘要还是社区观点；
6. 财报 `report_date` 与 `available_at` 是否满足分析截止点；
7. fallback/partial/stale 状态是否在 claim 中披露；
8. 多个 claim 是否把同一 evidence 误当成多份独立证据；
9. 价格、成交量、资金和币种是否发生跨来源口径混用；
10. 用户给出的新数字是否属于原 context；不属于则标记为外部主张，不能直接纳入裁决。

校验结果示例：

```json
{
  "challenge_id": "challenge_01J...",
  "agent_id": "evidence_verifier",
  "stance": "oppose",
  "verified_refs": ["technical.volume.2026-08-04"],
  "invalid_refs": [],
  "calculation_checks": [
    {
      "claim": "成交量达到 5 日均量 2 倍",
      "result": "failed",
      "expected": ">= 2.0",
      "actual": 1.3,
      "formula": "current_volume / previous_5d_average_volume"
    }
  ],
  "time_boundary_checks": [],
  "source_consistency_checks": [],
  "confidence": 1.0,
  "recommended_change": "replace"
}
```

## 10. Challenge Judge 裁决

Judge 只使用已经提交和验证的论据，不补造第三套事实。建议逐 claim 裁决，再汇总 section：

```json
{
  "challenge_id": "challenge_01J...",
  "report_id": "report_600519_20260804_001",
  "section_id": "trader.plan",
  "context_id": "ctx_600519_20260804_r1",
  "decision": "keep|amend|append|retract",
  "claim_decisions": [
    {
      "claim_id": "trader.plan.claim.2",
      "decision": "retract",
      "reason": "原证据量比为 1.3，不满足策略声明的放量确认条件。",
      "accepted_evidence_refs": ["technical.volume.2026-08-04"],
      "accepted_arguments": ["strategy.volume_breakout:claim.1"],
      "rejected_arguments": []
    }
  ],
  "trader_impact": {
    "action_changed": false,
    "position_changed": true,
    "notes": "由立即建仓改为等待量能确认"
  },
  "confidence": 0.94
}
```

决策语义：

| 决策 | 使用条件 |
| --- | --- |
| `keep` | 原文证据和逻辑均成立，无需变化 |
| `amend` | 原方向可保留，但需要削弱、澄清、增加条件或纠正局部事实 |
| `append` | 原文在当时成立，但新角度或风险值得补充 |
| `retract` | 核心事实错误、证据不支持或逻辑无法成立 |

## 11. `ReportAmendment` 与报告增补

SubAgent 不直接修改主报告。Report Editor 只消费 Judge 的结构化裁决：

```json
{
  "amendment_id": "amendment_01J...",
  "report_id": "report_600519_20260804_001",
  "base_report_version": 1,
  "challenge_id": "challenge_01J...",
  "context_id": "ctx_600519_20260804_r1",
  "section_id": "trader.plan",
  "decision": "amend",
  "reason": "放量确认条件未满足，但价格突破事实仍可保留为待确认信号。",
  "accepted_evidence_refs": ["technical.volume.2026-08-04"],
  "rejected_arguments": [],
  "patch": {
    "operation": "append_after|replace|annotate|retract",
    "target_claim_id": "trader.plan.claim.2",
    "expected_content_hash": "sha256:...",
    "content": "修订：价格已越过阻力，但量比 1.3 未达到放量突破策略的确认条件。交易计划改为等待收盘与量能再次确认。"
  },
  "created_at": "2026-08-04T16:05:00+08:00",
  "created_by": "report_editor"
}
```

推荐展示方式：

```markdown
> 挑战修订 · 2026-08-04 16:05
>
> 用户质疑：量比只有 1.3，为什么满足放量突破？
>
> 裁决：原文“放量确认”不成立。保留价格突破事实，改为“待量能确认”；建仓计划延后。
>
> 证据：technical.volume.2026-08-04
```

默认使用 `annotate` 或 `append_after`，便于审计。只有用户明确查看“整合后的最新报告”时，才在派生视图中应用 `replace/retract`；底层原报告仍保持不变。

## 12. 原证据审计与新数据更新必须分叉

### 12.1 `original_evidence`

回答：“在报告生成当时，依据当时可用证据，这句话是否合理？”

- 复用原 `context_id/revision`；
- 不调用实时行情或新闻抓取；
- 允许重新计算原始数据中的确定性指标；
- 输出对原报告的 keep/amend/retract 裁决。

### 12.2 `refresh_evidence`

回答：“现在的新数据是否改变结论？”

- Context Builder 创建 `revision + 1`；
- 保存新增或变化的 evidence；
- 重新运行受影响策略和 Trader/Risk；
- 输出新的 update section，而不是判定旧报告当时错误。

### 12.3 `both`

Codex 将请求拆为两个关联 challenge run：

```text
challenge.audit   -> ctx_r1 -> 判断原报告
challenge.refresh -> ctx_r2 -> 判断当前状态
```

最终报告同时写明：

- 原结论当时是否成立；
- 哪些新事实后来出现；
- 当前策略和交易计划是否变化。

例如，“次日放量”不能证明前一日的“已放量”正确，只能说明后续确认条件已经发生。

## 13. 完整示例

原报告：

```text
[section_id=strategy.volume_breakout]
股价突破 100 元阻力，放量突破得到确认，策略给出 buy。
```

原 evidence：

```json
{
  "technical.volume.2026-08-04": {
    "value": {"volume_ratio_5d": 1.3},
    "quality": "available",
    "source": "daily_bars_provider_a"
  },
  "technical.resistance.2026-08-04": {
    "value": {"resistance": 100.0, "close": 101.2},
    "quality": "available",
    "source": "daily_bars_provider_a"
  }
}
```

用户挑战：

```text
突破是真的，但策略写的是成交量要达到 5 日均量约 2 倍。当前只有 1.3，为什么是 buy？
```

第一轮：

| Agent | stance | 结论 |
| --- | --- | --- |
| `strategy.volume_breakout` | oppose | 突破条件满足，量能确认不满足；原 `buy` 应降为 `hold/待确认` |
| `trader` | mixed | 可保留观察，但不应以该策略为立即建仓依据 |
| `risk.conservative` | oppose | 无量突破的假突破风险较高，等待收盘或后续放量 |
| `evidence_verifier` | oppose | 数值 1.3 可复核，未达到约 2.0 的策略规则 |

Judge：`amend`。Editor 增补：

```text
挑战修订：价格突破 100 元阻力的事实成立，但量比 1.3 未满足放量突破策略的确认条件。
该策略由 buy 调整为 hold/待确认；Trader 不以此作为立即建仓依据，等待量能或回踩确认。
```

这个结果修改的是策略解释及其对 Trader 的影响，不会让策略 Agent 自己决定最终仓位。

## 14. Codex 主 Agent 执行模板

以下模板可作为专项 Codex 工作流的主要上下文。实际调用时用结构化对象替换尖括号占位符。

```text
你是 Challenge Orchestrator。处理 <challenge_request>，必须遵守：

1. 锁定 <report_manifest.context_id/revision>，除非 scope 要求 refresh。
2. 校验 section/claim/content_hash，失败返回 stale_selection。
3. 从角色矩阵选择最小参与者集合，保留用户 requested_roles。
4. 为每个 SubAgent 只提供完成职责所需的 context slice。
5. 首轮独立答辩；只有实质冲突才进行一轮交叉反驳。
6. 所有事实 claim 交给 Evidence Verifier。
7. 不允许任何 SubAgent 直接改报告。
8. Judge 先裁决，Editor 再生成最小 amendment。
9. 输出 challenge 状态、各角色结果、证据校验、裁决和 amendment。
10. 不把研究建议表述为自动交易指令。
```

主 Agent 最终输出 envelope：

```json
{
  "challenge_id": "...",
  "status": "applied|partially_answered|insufficient_context|stale_selection",
  "context": {"original": "ctx_r1", "refresh": null},
  "participants": [],
  "responses": [],
  "verification": {},
  "adjudication": {},
  "amendment": {},
  "unresolved_questions": []
}
```

## 15. SubAgent 任务模板

### 15.1 Strategy Tool Agent

```text
身份：<strategy_id> 策略工具，不是最终交易员。
任务：仅用 <context_id/revision> 中的证据，判断被挑战 claim 是否符合策略版本 <version>。
必须：逐项给出 conditions_met/missed，引用 evidence ID，披露缺失和质量状态。
禁止：决定最终仓位、引入新数据、引用未提供的事实、为了维护原报告而降低规则标准。
输出：ChallengeResponse JSON；若 required tool 证据不足，stance=insufficient。
```

### 15.2 Trader

```text
身份：对行动负责的交易员，可采用、拒绝或降权策略。
任务：评估 challenge 是否改变 adopted/rejected strategies、行动、仓位、执行或失效条件。
必须：说明策略选择理由、策略冲突、action_before/after、position_impact 和 evidence refs。
禁止：把单个策略信号直接当最终仓位；采纳 evidence_status=insufficient 的策略；创造新事实。
输出：ChallengeResponse JSON + Trader 扩展字段。
```

### 15.3 Bull / Bear Researcher

```text
身份：研究辩论方。
任务：构建对被挑战 claim 最强的支持/反对论证，并承认不利证据。
必须：区分事实、解释和假设；引用原 context evidence。
禁止：为了角色立场忽略确定性反例；直接修改 Trader 或报告输出。
输出：ChallengeResponse JSON。
```

### 15.4 Risk Analyst

```text
身份：<aggressive|conservative|neutral> 风险角色。
任务：判断 challenge 对回撤情景、失效条件、仓位上限和执行计划的影响。
必须：列 risk_scenarios、invalidation_conditions、maximum_acceptable_exposure、risk_override。
禁止：伪造风险概率或市场事实；替代 Portfolio Manager 作最终裁决。
输出：ChallengeResponse JSON + Risk 扩展字段。
```

### 15.5 Evidence Verifier

```text
身份：证据校验器，不持有多空立场。
任务：核验 claim 的数值、公式、窗口、单位、来源、复权、可得时点和质量传播。
必须：只使用 evidence registry；逐项输出 verified/invalid refs 和检查结果。
禁止：形成仓位建议；用当前数据替代历史数据；把搜索摘要说成正文。
输出：ChallengeResponse JSON + Verifier 扩展字段。
```

### 15.6 Challenge Judge

```text
身份：独立裁决者。
任务：依据已提交答辩和 verifier 结果，对每个 claim 作 keep/amend/append/retract 决策。
必须：列接受的 evidence/arguments、拒绝理由、对 Trader 的影响和置信度。
禁止：重新抓数据、引入未答辩的新论点、直接润色整份报告。
输出：Adjudication JSON。
```

### 15.7 Report Editor

```text
身份：报告修订编辑。
任务：把 Judge 裁决转换成针对一个 section/claim 的最小 amendment。
必须：保留原意中仍成立的部分，附 challenge 和 evidence 引用，使用允许的 patch 操作。
禁止：超出裁决范围、隐藏原文、改变未被挑战段落、创造新事实。
输出：ReportAmendment JSON。
```

## 16. 失败和降级

| 情况 | 行为 |
| --- | --- |
| 报告或 section 不存在 | `insufficient_context`，不凭 selected text 猜原报告 |
| content hash 已变化 | `stale_selection`，要求用户基于最新版本重新确认标记 |
| 原 evidence registry 缺失 | 可做逻辑审查，但事实裁决标 `insufficient`，不得宣称已核验 |
| 某 SubAgent 失败 | 保留其他答辩，状态 `partially_answered`，Judge 不推断缺席方观点 |
| required tool 原证据缺失 | 对应策略 `insufficient`，不进入 Trader 的正向采用列表 |
| 用户要求新数据 | 创建 refresh revision；若运行时需要外部权限，明确请求，不静默降为旧数据 |
| 角色输出非结构化 | 尝试一次 schema 修复；仍失败则标记该角色失败，不从自由文本猜关键枚举 |
| Judge 认为证据无法裁决 | 不生成事实性替换；以 `append` 记录未决问题和需要的数据 |

## 17. 持久化与审计对象

最低需要保存：

```text
ReportManifest
ReportSection / ReportClaim
AgentContextPack revision
EvidenceRegistry
StrategyDefinition version
StrategyResult
TraderProposal / PortfolioDecision
ChallengeRequest
ChallengeResponse
EvidenceVerification
Adjudication
ReportAmendment
```

关联关系：

```text
Report -> Context revision
Section -> Claims -> Evidence refs
Challenge -> Report/Section/Claim
Response -> Challenge/Agent/Context
Adjudication -> Responses/Verified evidence
Amendment -> Adjudication/Base report version
```

所有对象应记录创建时间和生成者。敏感 provider trace 可继续按现有低敏公开边界保存，报告只暴露适合用户查看的 evidence 摘要。

## 18. 最小实现切片

### Phase 1：可寻址报告

- 给现有策略和交易员报告增加 section ID、claim ID、context ID 和 evidence refs。
- 只做导出/存储，不改变现有决策。

### Phase 2：只读挑战

- 接受 ChallengeRequest。
- 运行一个策略答辩方、Trader、Conservative Risk 和 Evidence Verifier。
- 返回结构化裁决，但暂不写报告。

### Phase 3：报告 amendment

- 保存 Judge 和 ReportAmendment。
- Web 支持选中文本、查看答辩和在报告旁显示修订。

### Phase 4：新数据分支与自定义策略

- 支持 original/refresh/both。
- 为用户策略增加版本、发布和 challenge 路由。

Phase 2 已能验证专项 Codex 多 SubAgent 工作流是否有效；Phase 3 才形成用户要求的完整“挑战后增补报告”闭环。

## 19. 与现有仓库的衔接点

| 目标对象 | 可复用现有能力 | 当前缺口 |
| --- | --- | --- |
| Context/Evidence | `AnalysisContextPack`、工具证据、交易员 `data_evidence` | 统一 evidence ID 和 context revision |
| Strategy Response | `SkillAgent` 结构化输出和 evidence status | challenge envelope、策略版本、claim 引用 |
| Trader/Risk | TradingAgents state 和完整角色链 | Strategy-to-Trader Adapter、challenge 输出 schema |
| Report | 策略 dashboard、交易员分模块报告 | 稳定 section/claim ID 和 immutable manifest |
| 用户入口 | Ask 会话、Web 报告页面 | 文本标记、requested roles、challenge 历史 |
| 编辑与审计 | 报告/任务持久化基础 | Adjudication 和 ReportAmendment 存储 |

实现时优先添加兼容字段和适配层，避免破坏现有策略分析、交易员独立任务和 Web 报告载荷。
