import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StrategyDataEvidence } from '../StrategyDataEvidence';

describe('StrategyDataEvidence', () => {
  it('shows required data, source, key values, and missing limitations', () => {
    const { container } = render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'insufficient',
          selectedStrategies: [{ skillId: 'volume_breakout', skillName: '放量突破' }],
          strategyEvaluations: [{
            skillId: 'volume_breakout',
            skillName: '放量突破',
            status: 'completed',
            evaluationMode: 'joint',
            signal: 'buy',
            confidence: 0.62,
            reasoning: '突破条件成立，但新闻数据缺失，结果不参与最终投票。',
            conditionsMet: ['价格突破近20日高点'],
            conditionsMissed: ['新闻催化未验证'],
          }],
          overallDecision: {
            signal: 'hold',
            confidence: 0.55,
            operationAdvice: '等待数据补齐后再判断',
            reasoning: '当前证据不足，综合判定为观望。',
          },
          strategyRequirements: [{
            skillId: 'volume_breakout',
            status: 'insufficient',
            missingTools: ['search_stock_news'],
            limitedTools: [],
            evidence: [
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
              },
              {
                tool: 'get_realtime_quote',
                toolDisplayName: '实时行情获取',
                dataDescription: '实时行情',
                status: 'available',
                sources: ['tushare'],
                cached: false,
                partial: false,
                keyValues: { price: 1880, volume_ratio: 1.2 },
                asOf: '2026-07-29T10:30:00+08:00',
              },
              {
                tool: 'search_stock_news',
                status: 'missing',
                sources: ['searxng'],
                cached: false,
                partial: false,
                keyValues: {},
                missingReason: 'no results',
              },
            ],
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

    expect(screen.getByText('策略分析详情')).toBeInTheDocument();
    expect(screen.getByText(/所选策略: 放量突破/)).toBeInTheDocument();
    expect(screen.getByText('策略判定结果')).toBeInTheDocument();
    const outputDetails = screen.getByText('策略分析输出').closest('details');
    const inputDetails = screen.getByText('策略分析输入数据').closest('details');

    expect(outputDetails).not.toHaveAttribute('open');
    expect(inputDetails).not.toHaveAttribute('open');
    expect(outputDetails?.querySelector('summary')).toHaveClass('sticky', 'top-0');
    expect(inputDetails?.querySelector('summary')).toHaveClass('sticky', 'top-0');
    expect(screen.getByText(/判定依据: 突破条件成立/)).not.toBeVisible();
    expect(screen.getByText('K线形态识别')).not.toBeVisible();

    fireEvent.click(outputDetails!.querySelector('summary')!);
    fireEvent.click(inputDetails!.querySelector('summary')!);

    expect(outputDetails).toHaveAttribute('open');
    expect(inputDetails).toHaveAttribute('open');
    expect(screen.getByText(/判定信号: 买入/)).toBeInTheDocument();
    expect(screen.getByText('联合评估')).toBeInTheDocument();
    expect(screen.queryByText('该策略依赖输入:')).not.toBeInTheDocument();
    expect(screen.getByText(/置信度: 62%/)).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '条件状态' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '判定条件' })).toBeInTheDocument();
    expect(screen.getByText('满足条件')).toBeInTheDocument();
    expect(screen.getByText('价格突破近20日高点')).toBeInTheDocument();
    expect(screen.getByText('未满足条件')).toBeInTheDocument();
    expect(screen.getByText('新闻催化未验证')).toBeInTheDocument();
    expect(screen.getByText('综合判定')).toBeInTheDocument();
    expect(screen.getByText(/判定信号: 持有\/观望/)).toBeInTheDocument();
    expect(screen.getByText(/操作建议: 等待数据补齐后再判断/)).toBeInTheDocument();
    expect(screen.getByText('策略分析输入数据')).toBeInTheDocument();
    expect(screen.getByText('K线形态识别')).toBeInTheDocument();
    expect(screen.getByText(/基于近期日线K线识别/)).toBeInTheDocument();
    expect(screen.getByText('抓取失败')).toBeInTheDocument();
    expect(screen.getByText(/AkshareFetcher：日线K线.*empty result/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '数据源网站：AkshareFetcher' })).toHaveAttribute('href', 'https://www.akshare.xyz/');
    expect(screen.getByText('数据限制')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '仍需补充的数据' })).toBeInTheDocument();
    expect(container.textContent).toContain('volume_breakout');
    expect(container.textContent).toContain('必需输入数据不可用');
    expect(screen.getByText('tushare')).toBeInTheDocument();
    expect(screen.getByText('price')).toBeInTheDocument();
    expect(screen.getByText('1,880')).toBeInTheDocument();
    expect(screen.getAllByText(/no results/)).toHaveLength(2);
  });

  it('keeps each strategy input table separate and localizes strategy diagnostics', () => {
    const { container } = render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'limited',
          selectedStrategies: [
            { skillId: 'expectation_repricing', skillName: 'expectation_repricing' },
            { skillId: 'concept_ranking', skillName: 'concept_ranking' },
          ],
          strategyEvaluations: [
            {
              skillId: 'expectation_repricing',
              skillName: 'expectation_repricing',
              status: 'completed',
              signal: 'hold',
              confidence: 0.5,
              reasoning: '估值字段部分可用。',
              conditionsMet: [],
              conditionsMissed: ['concept_ranking 尚未确认'],
            },
            {
              skillId: 'concept_ranking',
              skillName: 'concept_ranking',
              status: 'completed',
              signal: 'hold',
              confidence: 0.52,
              reasoning: '概念排序待确认。',
              conditionsMet: [],
              conditionsMissed: [],
            },
          ],
          strategyRequirements: [
            {
              skillId: 'expectation_repricing',
              status: 'limited',
              missingTools: [],
              limitedTools: ['get_stock_info'],
              evidence: [{
                tool: 'get_stock_info',
                status: 'partial',
                sources: ['iwencai'],
                cached: false,
                partial: true,
                keyValues: { pe_ratio: 18.5 },
                metricDetails: [{
                  key: 'revenue_yoy',
                  label: '营收同比增长率',
                  status: 'missing',
                  value: null,
                  displayValue: null,
                  missingReason: 'source_field_missing',
                }, {
                  key: 'roe',
                  label: '净资产收益率（ROE）',
                  status: 'missing',
                  value: null,
                  displayValue: null,
                  missingReason: 'source_field_missing',
                }],
              }],
            },
            {
              skillId: 'concept_ranking',
              status: 'verified',
              missingTools: [],
              limitedTools: [],
              evidence: [{
                tool: 'get_stock_info',
                status: 'available',
                sources: ['tushare'],
                cached: false,
                partial: false,
                keyValues: { concept_ranking: 3 },
              }],
            },
          ],
          items: [],
          limitations: ['expectation_repricing: required data degraded (get_stock_info)'],
        }}
        language="zh"
      />,
    );

    expect(screen.getAllByText('策略分析输出')).toHaveLength(2);
    expect(screen.getAllByText('策略分析输入数据')).toHaveLength(2);
    expect(screen.getByText('iwencai')).toBeInTheDocument();
    expect(screen.getByText('tushare')).toBeInTheDocument();
    expect(screen.getAllByText('缺失')).toHaveLength(2);
    expect(screen.getByText('数据限制')).toBeInTheDocument();
    expect(screen.getByText('必需输入数据部分可用')).toBeInTheDocument();
    expect(screen.getByText('营收同比增长率、净资产收益率（ROE）')).toBeInTheDocument();
    expect(screen.getByText('部分数据；iwencai')).toBeInTheDocument();
    expect(container.textContent).toContain('概念板块排名');
    expect(container.textContent).not.toContain('concept_ranking');
    expect(container.textContent).not.toContain('expectation_repricing');
    expect(container.textContent).not.toContain('required data degraded');
  });

  it('does not render when evidence is absent', () => {
    const { container } = render(
      <StrategyDataEvidence evidence={null} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('lists the exact missing fundamental contract for older partial evidence', () => {
    render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'limited',
          selectedStrategies: [{ skillId: 'expectation_repricing', skillName: 'expectation_repricing' }],
          strategyRequirements: [{
            skillId: 'expectation_repricing',
            status: 'limited',
            missingTools: [],
            limitedTools: ['get_stock_info'],
            evidence: [{
              tool: 'get_stock_info',
              status: 'partial',
              sources: ['iwencai'],
              cached: false,
              partial: true,
              keyValues: { pe_ratio: 18.5 },
            }],
          }],
          limitations: ['expectation_repricing: required data degraded (get_stock_info)'],
          items: [],
        }}
        language="zh"
      />,
    );

    expect(screen.getByText(
      '市净率（PB）、营收同比增长率、净利润同比增长率、净资产收益率（ROE）、毛利率',
    )).toBeInTheDocument();
  });

  it('keeps an explicitly selected strategy visible when no input was recorded', () => {
    render(
      <StrategyDataEvidence
        evidence={{
          schemaVersion: 'strategy-evidence-v1',
          status: 'insufficient',
          selectedStrategies: [{ skillId: 'bull_trend', skillName: '多头趋势策略' }],
          strategyEvaluations: [{
            skillId: 'bull_trend',
            skillName: '多头趋势策略',
            status: 'not_evaluated',
            conditionsMet: [],
            conditionsMissed: [],
          }],
          overallDecision: { signal: 'hold', reasoning: '未取得可用输入。' },
          strategyRequirements: [],
          limitations: [],
          items: [],
        }}
        language="zh"
      />,
    );

    expect(screen.getByText(/所选策略: 多头趋势策略/)).toBeInTheDocument();
    expect(screen.getByText('未单独评估')).toBeInTheDocument();
    expect(screen.getByText('本次未记录可展示的策略输入数据')).toBeInTheDocument();
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
    expect(screen.getByText(/分析前已获取/)).toBeInTheDocument();
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
