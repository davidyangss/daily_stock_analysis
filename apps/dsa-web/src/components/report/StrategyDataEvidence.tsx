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
    status: '状态', requiredBy: '依赖策略', values: '关键值', source: '来源', freshness: '时效/覆盖', noSource: '未标记来源',
  },
  en: {
    eyebrow: 'Strategy evidence', title: 'Critical data and sources', verified: 'Verified', limited: 'Limited',
    insufficient: 'Insufficient', strategy: 'Strategy', requirement: 'Dependency status', tool: 'Data tool',
    status: 'Status', requiredBy: 'Required by', values: 'Key values', source: 'Source', freshness: 'Freshness / coverage', noSource: 'Source unavailable',
  },
  ko: {
    eyebrow: '전략 근거', title: '핵심 데이터 및 출처', verified: '검증됨', limited: '데이터 제한',
    insufficient: '근거 부족', strategy: '전략', requirement: '의존 상태', tool: '데이터 도구',
    status: '상태', requiredBy: '의존 전략', values: '핵심 값', source: '출처', freshness: '시점 / 범위', noSource: '출처 없음',
  },
} as const;

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
        <table className="w-full min-w-[760px] text-xs">
          <thead className="text-muted-text">
            <tr className="home-divider border-b">
              <th className="px-2 py-2 text-left font-medium">{text.tool}</th>
              <th className="px-2 py-2 text-left font-medium">{text.status}</th>
              <th className="px-2 py-2 text-left font-medium">{text.requiredBy}</th>
              <th className="px-2 py-2 text-left font-medium">{text.values}</th>
              <th className="px-2 py-2 text-left font-medium">{text.source}</th>
              <th className="px-2 py-2 text-left font-medium">{text.freshness}</th>
            </tr>
          </thead>
          <tbody>
            {(evidence.items || []).slice(0, 30).map((item, index) => (
              <tr key={`${item.stage || 'agent'}-${item.tool}-${index}`} className="home-divider border-b last:border-b-0">
                <td className="px-2 py-2 font-mono text-foreground">{item.tool}</td>
                <td className="px-2 py-2"><Badge variant={statusVariant(item.status)}>{item.status}</Badge></td>
                <td className="px-2 py-2 text-muted-text">{item.requiredBy?.join(', ') || '—'}</td>
                <td className="max-w-[320px] px-2 py-2 text-foreground">{formatValues(item)}</td>
                <td className="px-2 py-2 text-muted-text">{item.sources?.join(', ') || text.noSource}</td>
                <td className="px-2 py-2 text-muted-text">{item.missingReason || formatCoverage(item)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};
