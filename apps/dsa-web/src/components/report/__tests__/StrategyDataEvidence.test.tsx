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

  it('shows prefetched chip metrics and missing fields in readable form', () => {
    render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'verified',
          strategyRequirements: [],
          limitations: [],
          items: [{
            tool: 'get_chip_distribution',
            toolDisplayName: '筹码分布分析',
            dataDescription: '筹码分布数据',
            status: 'available',
            sources: ['akshare_sina_calculated'],
            cached: false,
            partial: false,
            prefetched: true,
            keyValues: { avg_cost: 470.14 },
            metricDetails: [
              {
                key: 'profit_ratio',
                label: '获利盘比例',
                status: 'available',
                value: 0.0758,
                displayValue: '7.58%',
                unit: '%',
                description: '当前价格以下的获利筹码占比',
              },
              {
                key: 'concentration_70',
                label: '70%筹码集中度',
                status: 'missing',
                value: null,
                displayValue: null,
                unit: '%',
                description: '核心筹码区间的集中程度',
                missingReason: 'source_field_missing',
              },
            ],
            missingFields: ['concentration_70'],
          }],
        }}
        language="zh"
      />,
    );

    expect(screen.getByText('筹码分布分析')).toBeInTheDocument();
    expect(screen.getByText('分析前已获取')).toBeInTheDocument();
    expect(screen.getByText('获利盘比例')).toBeInTheDocument();
    expect(screen.getByText('7.58%')).toBeInTheDocument();
    expect(screen.getByText('70%筹码集中度')).toBeInTheDocument();
    expect(screen.getByText('缺失')).toBeInTheDocument();
  });

  it('formats large values and clarifies daily-bar descriptions in old reports', () => {
    render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'verified',
          strategyRequirements: [],
          limitations: [],
          items: [{
            tool: 'get_daily_history',
            status: 'available',
            sources: ['db_cache'],
            cached: true,
            partial: false,
            keyValues: {},
            metricDetails: [
              {
                key: 'latest_volume',
                label: '最近交易日成交量',
                status: 'available',
                value: 97123885,
                displayValue: '97123885.00股',
                unit: '股',
                description: '最近一根日K线的成交股数',
              },
              {
                key: 'latest_amount',
                label: '最近交易日成交额',
                status: 'available',
                value: 35483794588,
                displayValue: '35483794588.00元',
                unit: '元',
                description: '最近一根日K线的成交金额',
              },
            ],
          }],
        }}
        language="zh"
      />,
    );

    expect(screen.getByText('97,123,885.00股')).toBeInTheDocument();
    expect(screen.getByText('35,483,794,588.00元')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '指标' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '数值' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '含义' })).toBeInTheDocument();
    expect(screen.getByText('最近一个交易日的成交股数')).toBeInTheDocument();
    expect(screen.getByText('最近一个交易日的成交金额')).toBeInTheDocument();
  });
});
