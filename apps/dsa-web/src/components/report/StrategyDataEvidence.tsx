import type React from 'react';
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
    eyebrow: '策略证据', title: '关键数据与来源', verified: '已验证', limited: '数据受限',
    insufficient: '证据不足', strategy: '策略', requirement: '依赖状态', tool: '关键数据工具',
    status: '状态', requiredBy: '依赖策略', values: '关键值', source: '数据源 / 链接', freshness: '时效/覆盖', noSource: '未记录数据源',
    data: '获取内容', failure: '失败详情', dataLink: '数据源网站', noDataLink: '未记录可公开数据链接',
    availableMetric: '可用', missingMetric: '缺失', prefetched: '分析前已获取', metric: '指标', metricValue: '数值', meaning: '含义',
  },
  en: {
    eyebrow: 'Strategy evidence', title: 'Critical data and sources', verified: 'Verified', limited: 'Limited',
    insufficient: 'Insufficient', strategy: 'Strategy', requirement: 'Dependency status', tool: 'Data tool',
    status: 'Status', requiredBy: 'Required by', values: 'Key values', source: 'Source / link', freshness: 'Freshness / coverage', noSource: 'Source unavailable',
    data: 'Data requested', failure: 'Failure details', dataLink: 'Source website', noDataLink: 'No public data link recorded',
    availableMetric: 'Available', missingMetric: 'Missing', prefetched: 'Prefetched', metric: 'Metric', metricValue: 'Value', meaning: 'Meaning',
  },
  ko: {
    eyebrow: '전략 근거', title: '핵심 데이터 및 출처', verified: '검증됨', limited: '데이터 제한',
    insufficient: '근거 부족', strategy: '전략', requirement: '의존 상태', tool: '데이터 도구',
    status: '상태', requiredBy: '의존 전략', values: '핵심 값', source: '출처 / 링크', freshness: '시점 / 범위', noSource: '출처 없음',
    data: '가져온 내용', failure: '실패 상세', dataLink: '데이터 소스 사이트', noDataLink: '공개 데이터 링크가 기록되지 않음',
    availableMetric: '사용 가능', missingMetric: '누락', prefetched: '사전 수집', metric: '지표', metricValue: '값', meaning: '의미',
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
  if (['verified', 'available'].includes(status)) return 'success';
  if (['limited', 'fallback', 'partial', 'estimated', 'stale'].includes(status)) return 'warning';
  if (['insufficient', 'missing', 'fetch_failed', 'not_supported'].includes(status)) return 'danger';
  return 'default';
};

const formatValues = (item: StrategyEvidenceItem): string => {
  const entries = Object.entries(item.keyValues || {}).slice(0, 8);
  return entries.length
    ? entries.map(([key, value]) => `${key}=${value ?? 'N/A'}`).join(' · ')
    : '—';
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

export const StrategyDataEvidence: React.FC<StrategyDataEvidenceProps> = ({
  evidence,
  language = 'zh',
}) => {
  const reportLanguage = normalizeReportLanguage(language);
  const text = TEXT[reportLanguage];
  if (!evidence || evidence.schemaVersion !== 'strategy-evidence-v1') return null;

  return (
    <Card variant="bordered" padding="md" className="home-panel-card text-left">
      <DashboardPanelHeader eyebrow={text.eyebrow} title={text.title} className="mb-3" />

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Badge variant={statusVariant(evidence.status)}>
          {text[evidence.status]}
        </Badge>
        {(evidence.strategyRequirements || []).map((requirement) => (
          <span key={requirement.skillId} className="home-accent-chip px-2 py-1 text-xs">
            {text.strategy}: {requirement.skillId} · {text.requirement}: {requirementStatusLabel(requirement.status, text)}
          </span>
        ))}
      </div>

      {evidence.limitations?.length ? (
        <div className="mb-3 rounded-lg border border-danger/30 bg-danger/5 p-3 text-xs leading-5 text-danger">
          {evidence.limitations.map((limitation) => <div key={limitation}>• {limitation}</div>)}
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[920px] text-xs">
          <thead className="text-muted-text">
            <tr className="home-divider border-b">
              <th className="px-2 py-2 text-left font-medium">{text.tool}</th>
              <th className="px-2 py-2 text-left font-medium">{text.status}</th>
              <th className="px-2 py-2 text-left font-medium">{text.data}</th>
              <th className="px-2 py-2 text-left font-medium">{text.requiredBy}</th>
              <th className="px-2 py-2 text-left font-medium">{text.values}</th>
              <th className="px-2 py-2 text-left font-medium">{text.source}</th>
              <th className="px-2 py-2 text-left font-medium">{text.failure}</th>
              <th className="px-2 py-2 text-left font-medium">{text.freshness}</th>
            </tr>
          </thead>
          <tbody>
            {(evidence.items || []).slice(0, 30).map((item, index) => (
              (() => {
                const legacyPresentation = LEGACY_TOOL_PRESENTATION[item.tool];
                const toolDisplayName = item.toolDisplayName || legacyPresentation?.name || item.tool;
                const toolDescription = item.toolDescription || legacyPresentation?.description;
                const dataDescription = item.dataDescription || legacyPresentation?.data || '—';
                const failureDetails = formatFailure(item, dataDescription);
                return <tr key={`${item.stage || 'agent'}-${item.tool}-${index}`} className="home-divider border-b align-top last:border-b-0">
                <td className="px-2 py-2 text-foreground">
                  <div className="font-medium">{toolDisplayName}</div>
                  {toolDescription ? <div className="mt-1 max-w-[220px] text-muted-text">{toolDescription}</div> : <div className="mt-1 font-mono text-muted-text">{item.tool}</div>}
                </td>
                <td className="px-2 py-2"><Badge variant={statusVariant(item.status)}>{statusLabel(item.status, reportLanguage)}</Badge></td>
                <td className="max-w-[180px] px-2 py-2 text-muted-text">{dataDescription}</td>
                <td className="px-2 py-2 text-muted-text">{item.requiredBy?.join(', ') || '—'}</td>
                <td className="max-w-[380px] px-2 py-2 text-foreground">
                  {item.prefetched ? (
                    <div className="mb-1 text-[11px] text-cyan">{text.prefetched}</div>
                  ) : null}
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
                  ) : formatValues(item)}
                </td>
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
              </tr>;
              })()
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};
