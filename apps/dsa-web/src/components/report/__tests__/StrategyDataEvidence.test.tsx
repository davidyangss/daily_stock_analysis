import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StrategyDataEvidence } from '../StrategyDataEvidence';

describe('StrategyDataEvidence', () => {
  it('shows required data, source, key values, and missing limitations', () => {
    render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'insufficient',
          strategyRequirements: [{
            skillId: 'volume_breakout',
            status: 'insufficient',
            missingTools: ['search_stock_news'],
            limitedTools: [],
            evidence: [],
          }],
          items: [
            {
              tool: 'analyze_pattern',
              toolDisplayName: 'K线形态识别',
              toolDescription: '基于近期日线K线识别十字星、锤头线和吞没等形态。',
              dataDescription: '日线K线（开盘、最高、最低、收盘、成交量）',
              status: 'fetch_failed',
              sources: ['AkshareFetcher'],
              sourceLinks: [{ name: 'AkshareFetcher', url: 'https://www.akshare.xyz/' }],
              failureAttempts: [{ provider: 'AkshareFetcher', operation: 'get_daily_data', reason: 'empty result' }],
              cached: false,
              partial: false,
              keyValues: {},
              required: true,
              requiredBy: ['volume_breakout'],
            },
            {
              tool: 'get_realtime_quote',
              status: 'available',
              sources: ['tushare'],
              cached: false,
              partial: false,
              keyValues: { price: 1880, volume_ratio: 1.2 },
              asOf: '2026-07-29T10:30:00+08:00',
              required: true,
              requiredBy: ['volume_breakout'],
            },
            {
              tool: 'search_stock_news',
              status: 'missing',
              sources: ['searxng'],
              cached: false,
              partial: false,
              keyValues: {},
              missingReason: 'no results',
              required: true,
              requiredBy: ['volume_breakout'],
            },
          ],
          limitations: ['volume_breakout: required data unavailable (search_stock_news)'],
        }}
        language="zh"
      />,
    );

    expect(screen.getByText('关键数据与来源')).toBeInTheDocument();
    expect(screen.getByText('K线形态识别')).toBeInTheDocument();
    expect(screen.getByText(/基于近期日线K线识别/)).toBeInTheDocument();
    expect(screen.getByText('抓取失败')).toBeInTheDocument();
    expect(screen.getByText(/AkshareFetcher：日线K线.*empty result/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '数据源网站：AkshareFetcher' })).toHaveAttribute('href', 'https://www.akshare.xyz/');
    expect(screen.getByText(/volume_breakout: required data unavailable/)).toBeInTheDocument();
    expect(screen.getByText('tushare')).toBeInTheDocument();
    expect(screen.getByText(/price=1880/)).toBeInTheDocument();
    expect(screen.getByText(/no results/)).toBeInTheDocument();
  });

  it('does not render when evidence is absent', () => {
    const { container } = render(
      <StrategyDataEvidence evidence={null} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
