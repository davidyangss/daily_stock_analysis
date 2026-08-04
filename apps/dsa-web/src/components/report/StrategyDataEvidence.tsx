import { Fragment, type FC } from 'react';
import type {
  ReportLanguage,
  StrategyDataEvidence as StrategyDataEvidenceType,
  StrategyEvidenceItem,
} from '../../types/analysis';
import { Badge, Card } from '../common';
import { DashboardPanelHeader } from '../dashboard';
import { normalizeReportLanguage } from '../../utils/reportLanguage';

interface StrategyDataEvidenceProps {
  evidence?: StrategyDataEvidenceType | null;
  language?: ReportLanguage;
}

const TEXT = {
  zh: {
    eyebrow: '策略证据', title: '策略分析详情', verified: '已验证', limited: '数据受限',
    insufficient: '证据不足', strategy: '策略', selected: '所选策略', requirement: '依赖状态', tool: '关键数据工具',
    status: '状态', requiredBy: '依赖策略', values: '关键值', source: '数据源 / 链接', freshness: '时效/覆盖', noSource: '未记录数据源',
    data: '获取内容', failure: '失败详情', dataLink: '数据源网站', noDataLink: '未记录可公开数据链接',
    availableMetric: '可用', missingMetric: '缺失', prefetched: '分析前已获取', metric: '指标', metricValue: '数值', meaning: '含义',
    decisionTitle: '策略判定结果', overallDecision: '综合判定', signal: '判定信号', confidence: '置信度', advice: '操作建议',
    reasoning: '判定依据', conditionsMet: '满足条件', conditionsMissed: '未满足条件', inputTitle: '策略分析输入数据',
    completed: '已完成', failed: '执行失败', invalid: '结果无效', notEvaluated: '未单独评估', noInput: '本次未记录可展示的策略输入数据',
    jointEvaluation: '联合评估', specialistEvaluation: '独立评估', dependencies: '该策略依赖输入',
  },
  en: {
    eyebrow: 'Strategy evidence', title: 'Strategy analysis details', verified: 'Verified', limited: 'Limited',
    insufficient: 'Insufficient', strategy: 'Strategy', selected: 'Selected strategy', requirement: 'Dependency status', tool: 'Data tool',
    status: 'Status', requiredBy: 'Required by', values: 'Key values', source: 'Source / link', freshness: 'Freshness / coverage', noSource: 'Source unavailable',
    data: 'Data requested', failure: 'Failure details', dataLink: 'Source website', noDataLink: 'No public data link recorded',
    availableMetric: 'Available', missingMetric: 'Missing', prefetched: 'Prefetched', metric: 'Metric', metricValue: 'Value', meaning: 'Meaning',
    decisionTitle: 'Strategy decisions', overallDecision: 'Overall decision', signal: 'Signal', confidence: 'Confidence', advice: 'Action',
    reasoning: 'Decision basis', conditionsMet: 'Conditions met', conditionsMissed: 'Conditions missed', inputTitle: 'Strategy input data',
    completed: 'Completed', failed: 'Failed', invalid: 'Invalid', notEvaluated: 'Not separately evaluated', noInput: 'No displayable strategy input data was recorded',
    jointEvaluation: 'Joint evaluation', specialistEvaluation: 'Specialist evaluation', dependencies: 'Inputs required by this strategy',
  },
  ko: {
    eyebrow: '전략 근거', title: '전략 분석 상세', verified: '검증됨', limited: '데이터 제한',
    insufficient: '근거 부족', strategy: '전략', selected: '선택 전략', requirement: '의존 상태', tool: '데이터 도구',
    status: '상태', requiredBy: '의존 전략', values: '핵심 값', source: '출처 / 링크', freshness: '시점 / 범위', noSource: '출처 없음',
    data: '가져온 내용', failure: '실패 상세', dataLink: '데이터 소스 사이트', noDataLink: '공개 데이터 링크가 기록되지 않음',
    availableMetric: '사용 가능', missingMetric: '누락', prefetched: '사전 수집', metric: '지표', metricValue: '값', meaning: '의미',
    decisionTitle: '전략 판정', overallDecision: '종합 판정', signal: '판정 신호', confidence: '신뢰도', advice: '조치',
    reasoning: '판정 근거', conditionsMet: '충족 조건', conditionsMissed: '미충족 조건', inputTitle: '전략 분석 입력 데이터',
    completed: '완료', failed: '실행 실패', invalid: '결과 무효', notEvaluated: '개별 평가 없음', noInput: '표시 가능한 전략 입력 데이터가 기록되지 않음',
    jointEvaluation: '공동 평가', specialistEvaluation: '개별 평가', dependencies: '이 전략의 필수 입력',
  },
} as const;

// Older persisted reports predate the presentation fields produced by the API.
// Keep their evidence readable while new reports receive the complete metadata.
const LEGACY_TOOL_PRESENTATION: Record<string, { name: string; description: string; data: string }> = {
  analyze_pattern: {
    name: 'K线形态识别',
    description: '基于近期日线K线识别十字星、锤头线、吞没、突破和箱体等形态。',
    data: '近期日线K线（开盘、最高、最低、收盘、成交量）',
  },
};

const METRIC_DESCRIPTION_OVERRIDES: Record<string, string> = {
  latest_open: '最近一个交易日的开盘价',
  latest_high: '最近一个交易日的最高价',
  latest_low: '最近一个交易日的最低价',
  latest_close: '最近一个已完成交易日的收盘价',
  latest_volume: '最近一个交易日的成交股数',
  latest_amount: '最近一个交易日的成交金额',
};

// Old reports persist displayValue as text. Format its numeric prefix here so
// history benefits from readability improvements without rewriting snapshots.
const formatMetricDisplayValue = (value: unknown): string => {
  const textValue = String(value ?? '—');
  const match = textValue.match(/^([+-]?)(\d[\d,]*)(\.\d+)?(.*)$/);
  if (!match) return textValue;
  const [, sign, integerPart, decimalPart = '', suffix] = match;
  const groupedInteger = integerPart.replaceAll(',', '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${sign}${groupedInteger}${decimalPart}${suffix}`;
};

const statusVariant = (status: string): 'success' | 'warning' | 'danger' | 'default' => {
  if (['verified', 'available', 'completed'].includes(status)) return 'success';
  if (['limited', 'fallback', 'partial', 'estimated', 'stale', 'not_evaluated'].includes(status)) return 'warning';
  if (['insufficient', 'missing', 'fetch_failed', 'not_supported', 'failed', 'invalid'].includes(status)) return 'danger';
  return 'default';
};

const signalLabel = (signal: string, language: ReportLanguage): string => {
  const labels = {
    zh: { strong_buy: '强烈买入', buy: '买入', add: '加仓', hold: '持有/观望', reduce: '减仓', sell: '卖出', strong_sell: '强烈卖出', watch: '观察', avoid: '回避', alert: '警示' },
    en: { strong_buy: 'Strong buy', buy: 'Buy', add: 'Add', hold: 'Hold', reduce: 'Reduce', sell: 'Sell', strong_sell: 'Strong sell', watch: 'Watch', avoid: 'Avoid', alert: 'Alert' },
    ko: { strong_buy: '강력 매수', buy: '매수', add: '추가 매수', hold: '보유/관망', reduce: '축소', sell: '매도', strong_sell: '강력 매도', watch: '관찰', avoid: '회피', alert: '경고' },
  } as const;
  return labels[language][signal as keyof typeof labels.zh] || signal || '—';
};

const formatCoverage = (item: StrategyEvidenceItem): string => {
  const parts = [
    item.asOf ? `as-of ${item.asOf}` : '',
    typeof item.recordCount === 'number' ? `${item.recordCount} records` : '',
    typeof item.requestedRecords === 'number' ? `requested ${item.requestedRecords}` : '',
    item.cached ? 'cache' : '',
    item.partial ? 'partial' : '',
  ].filter(Boolean);
  return parts.join(' · ') || '—';
};

const requirementStatusLabel = (
  status: string,
  text: typeof TEXT.zh | typeof TEXT.en | typeof TEXT.ko,
): string => {
  if (status === 'verified') return text.verified;
  if (status === 'limited') return text.limited;
  if (status === 'insufficient') return text.insufficient;
  return status;
};

const statusLabel = (status: string, language: ReportLanguage): string => {
  const labels = {
    zh: { available: '成功', fetch_failed: '抓取失败', missing: '无数据', not_supported: '不支持', fallback: '已降级', partial: '部分数据', estimated: '估算', stale: '数据过期' },
    en: { available: 'Success', fetch_failed: 'Fetch failed', missing: 'No data', not_supported: 'Unsupported', fallback: 'Fallback', partial: 'Partial', estimated: 'Estimated', stale: 'Stale' },
    ko: { available: '성공', fetch_failed: '가져오기 실패', missing: '데이터 없음', not_supported: '미지원', fallback: '대체 소스', partial: '일부 데이터', estimated: '추정', stale: '오래된 데이터' },
  } as const;
  return labels[language][status as keyof typeof labels.zh] || status;
};

const evaluationStatusLabel = (
  status: string,
  text: typeof TEXT.zh | typeof TEXT.en | typeof TEXT.ko,
): string => {
  if (status === 'completed') return text.completed;
  if (status === 'insufficient') return text.insufficient;
  if (status === 'failed') return text.failed;
  if (status === 'invalid') return text.invalid;
  if (status === 'not_evaluated') return text.notEvaluated;
  return status;
};

const formatConfidence = (confidence?: number, fallback?: string): string => {
  if (typeof confidence === 'number' && Number.isFinite(confidence)) {
    return `${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%`;
  }
  return fallback || '—';
};

const formatFailure = (item: StrategyEvidenceItem, dataDescription: string): string[] => {
  if (item.failureAttempts?.length) {
    return item.failureAttempts.map((attempt) => (
      `${attempt.provider}：${dataDescription}（${attempt.operation}）失败：${attempt.reason}`
    ));
  }
  if (item.failureSource || item.failureReason || item.missingReason) {
    const source = item.failureSource || item.sources?.join(', ') || '未记录数据源';
    const operation = item.failureOperation ? `（${item.failureOperation}）` : '';
    return [`${source}${operation}：${item.failureReason || item.missingReason || '未返回可用数据'}`];
  }
  return [];
};

export const StrategyDataEvidence: FC<StrategyDataEvidenceProps> = ({
  evidence,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = TEXT[reportLanguage];
  if (!evidence || evidence.schemaVersion !== 'strategy-evidence-v1') return null;
  const selectedStrategies = evidence.selectedStrategies || [];
  const strategyEvaluations = evidence.strategyEvaluations || [];
  const strategyRequirements = evidence.strategyRequirements || [];
  const overallDecision = evidence.overallDecision;
  const items = evidence.items || [];

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <DashboardPanelHeader eyebrow={text.eyebrow} title={text.title} className="mb-3" />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge variant={statusVariant(evidence.status)}>
          {text[evidence.status]}
        </Badge>
        {selectedStrategies.map((strategy) => (
          <span key={strategy.skillId} className="home-accent-chip px-2 py-1 text-xs">
            {text.selected}: {strategy.skillName || strategy.skillId}
            {strategy.skillName && strategy.skillName !== strategy.skillId ? ` (${strategy.skillId})` : ''}
          </span>
        ))}
        {strategyRequirements.map((requirement) => (
          <span key={requirement.skillId} className="home-accent-chip px-2 py-1 text-xs">
            {text.strategy}: {requirement.skillId} · {text.requirement}: {requirementStatusLabel(requirement.status, text)}
          </span>
        ))}
      </div>

      {strategyEvaluations.length ? (
        <div className="mb-4">
          <h4 className="mb-2 text-xs font-semibold text-foreground">{text.decisionTitle}</h4>
          <div className="space-y-2">
            {strategyEvaluations.map((evaluation) => {
              const signal = evaluation.signal || '';
              const requirement = strategyRequirements.find(
                (item) => item.skillId === evaluation.skillId,
              );
              return (
                <div key={evaluation.skillId} className="rounded-lg border border-border/60 bg-muted/10 p-3 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-foreground">{evaluation.skillName || evaluation.skillId}</span>
                    <code className="text-[11px] text-muted-text">{evaluation.skillId}</code>
                    <Badge variant={statusVariant(evaluation.status)}>
                      {evaluationStatusLabel(evaluation.status, text)}
                    </Badge>
                    {evaluation.evaluationMode ? (
                      <Badge variant="default">
                        {evaluation.evaluationMode === 'joint' ? text.jointEvaluation : text.specialistEvaluation}
                      </Badge>
                    ) : null}
                    {signal ? <Badge variant="info">{text.signal}: {signalLabel(signal, reportLanguage)}</Badge> : null}
                    {typeof evaluation.confidence === 'number' ? (
                      <span className="text-muted-text">{text.confidence}: {formatConfidence(evaluation.confidence)}</span>
                    ) : null}
                  </div>
                  {evaluation.reasoning ? (
                    <p className="mt-2 leading-5 text-secondary-text">{text.reasoning}: {evaluation.reasoning}</p>
                  ) : null}
                  {evaluation.conditionsMet?.length ? (
                    <div className="mt-2 text-success">{text.conditionsMet}: {evaluation.conditionsMet.join('；')}</div>
                  ) : null}
                  {evaluation.conditionsMissed?.length ? (
                    <div className="mt-1 text-danger">{text.conditionsMissed}: {evaluation.conditionsMissed.join('；')}</div>
                  ) : null}
                  {requirement?.evidence?.length ? (
                    <div className="mt-2 border-t border-border/50 pt-2 text-muted-text">
                      <div className="font-medium text-foreground">{text.dependencies}:</div>
                      <div className="mt-1 space-y-1">
                        {requirement.evidence.map((item) => {
                          const presentation = LEGACY_TOOL_PRESENTATION[item.tool];
                          const name = item.toolDisplayName || presentation?.name || item.tool;
                          const dataDescription = item.dataDescription || presentation?.data;
                          return (
                            <div key={`${evaluation.skillId}-${item.tool}`}>
                              {name}{dataDescription ? `（${dataDescription}）` : ''}：{statusLabel(item.status, reportLanguage)}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}

      {overallDecision ? (
        <div className="mb-4 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-foreground">{text.overallDecision}</span>
            {overallDecision.signal ? (
              <Badge variant="info">{text.signal}: {signalLabel(overallDecision.signal, reportLanguage)}</Badge>
            ) : null}
            <span className="text-muted-text">
              {text.confidence}: {formatConfidence(overallDecision.confidence, overallDecision.confidenceLabel)}
            </span>
          </div>
          {overallDecision.operationAdvice ? (
            <div className="mt-2 text-foreground">{text.advice}: {overallDecision.operationAdvice}</div>
          ) : null}
          {overallDecision.reasoning ? (
            <div className="mt-1 leading-5 text-secondary-text">{text.reasoning}: {overallDecision.reasoning}</div>
          ) : null}
        </div>
      ) : null}

      {evidence.limitations?.length ? (
        <div className="mb-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs leading-5 text-danger">
          {evidence.limitations.map((limitation) => <div key={limitation}>• {limitation}</div>)}
        </div>
      ) : null}

      <h4 className="mb-2 text-xs font-semibold text-foreground">{text.inputTitle}</h4>
      {items.length ? <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-xs">
          <thead className="text-muted-text">
            <tr className="home-divider border-b">
              <th className="px-2 py-2 text-left font-medium">{text.tool}</th>
              <th className="px-2 py-2 text-left font-medium">{text.status}</th>
              <th className="px-2 py-2 text-left font-medium">{text.data}</th>
              <th className="px-2 py-2 text-left font-medium">{text.requiredBy}</th>
              <th className="px-2 py-2 text-left font-medium">{text.source}</th>
              <th className="px-2 py-2 text-left font-medium">{text.failure}</th>
              <th className="px-2 py-2 text-left font-medium">{text.freshness}</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 30).map((item, index) => (
              (() => {
                const legacyPresentation = LEGACY_TOOL_PRESENTATION[item.tool];
                const toolDisplayName = item.toolDisplayName || legacyPresentation?.name || item.tool;
                const toolDescription = item.toolDescription || legacyPresentation?.description;
                const dataDescription = item.dataDescription || legacyPresentation?.data || '—';
                const failureDetails = formatFailure(item, dataDescription);
                const rowKey = `${item.stage || 'agent'}-${item.tool}-${index}`;
                const rawValues = Object.entries(item.keyValues || {}).slice(0, 8);
                return <Fragment key={rowKey}>
                <tr className="align-top">
                <td className="px-2 py-2 text-foreground">
                  <div className="font-medium">{toolDisplayName}</div>
                  {toolDescription ? <div className="mt-1 max-w-[220px] text-muted-text">{toolDescription}</div> : <div className="mt-1 font-mono text-muted-text">{item.tool}</div>}
                </td>
                <td className="px-2 py-2"><Badge variant={statusVariant(item.status)}>{statusLabel(item.status, reportLanguage)}</Badge></td>
                <td className="max-w-[180px] px-2 py-2 text-muted-text">{dataDescription}</td>
                <td className="px-2 py-2 text-muted-text">{item.requiredBy?.join(', ') || '—'}</td>
                <td className="max-w-[180px] px-2 py-2 text-muted-text">
                  <div>{item.sources?.join(', ') || text.noSource}</div>
                  {item.sourceLinks?.length ? item.sourceLinks.map((link) => (
                    <a key={link.url} href={link.url} target="_blank" rel="noreferrer" className="mt-1 block text-primary hover:underline">
                      {text.dataLink}：{link.name}
                    </a>
                  )) : item.status === 'available' ? <div className="mt-1">{text.noDataLink}</div> : null}
                </td>
                <td className="max-w-[300px] px-2 py-2 text-muted-text">
                  {failureDetails.map((detail) => <div key={detail}>{detail}</div>)}
                  {!failureDetails.length ? '—' : null}
                </td>
                <td className="px-2 py-2 text-muted-text">{formatCoverage(item)}</td>
              </tr>
              <tr className="home-divider border-b align-top last:border-b-0">
                <td colSpan={7} className="px-2 pb-3 pt-1 text-foreground">
                  <div className="mb-1.5 flex items-center gap-2 text-[11px] font-medium text-muted-text">
                    <span>{text.values}</span>
                    {item.prefetched ? <span className="text-cyan">· {text.prefetched}</span> : null}
                  </div>
                  {item.metricDetails?.length ? (
                    <div className="overflow-x-auto rounded-md border border-border/60">
                      <table className="w-full min-w-[520px] text-[11px]">
                        <thead className="bg-muted/30 text-muted-text">
                          <tr className="home-divider border-b">
                            <th className="px-2 py-1.5 text-left font-medium">{text.metric}</th>
                            <th className="px-2 py-1.5 text-left font-medium">{text.status}</th>
                            <th className="px-2 py-1.5 text-right font-medium">{text.metricValue}</th>
                            <th className="px-2 py-1.5 text-left font-medium">{text.meaning}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {item.metricDetails.map((metric) => (
                            <tr key={metric.key} className="home-divider border-b align-top last:border-b-0">
                              <td className="px-2 py-1.5 font-medium">{metric.label}</td>
                              <td className={`px-2 py-1.5 ${metric.status === 'available' ? 'text-success' : 'text-danger'}`}>
                                {metric.status === 'available' ? text.availableMetric : text.missingMetric}
                              </td>
                              <td className="whitespace-nowrap px-2 py-1.5 text-right tabular-nums">
                                {metric.status === 'available'
                                  ? formatMetricDisplayValue(metric.displayValue ?? metric.value)
                                  : '—'}
                              </td>
                              <td className="min-w-[180px] px-2 py-1.5 leading-4 text-muted-text">
                                {METRIC_DESCRIPTION_OVERRIDES[metric.key] || metric.description || '—'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : rawValues.length ? (
                    <div className="overflow-x-auto rounded-md border border-border/60">
                      <table className="w-full min-w-[360px] text-[11px]">
                        <thead className="bg-muted/30 text-muted-text">
                          <tr className="home-divider border-b">
                            <th className="px-2 py-1.5 text-left font-medium">{text.metric}</th>
                            <th className="px-2 py-1.5 text-right font-medium">{text.metricValue}</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rawValues.map(([key, value]) => (
                            <tr key={key} className="home-divider border-b last:border-b-0">
                              <td className="px-2 py-1.5 font-medium">{key}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{formatMetricDisplayValue(value)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : <span className="text-muted-text">—</span>}
                </td>
              </tr>
              </Fragment>;
              })()
            ))}
          </tbody>
        </table>
      </div> : <p className="text-xs text-muted-text">{text.noInput}</p>}
    </Card>
  );
};
