import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import TraderAnalysisPage from '../TraderAnalysisPage';
import type { TraderAnalysisRun } from '../../types/traderAnalysis';

const { mockListRuns, mockGetRun, mockGetEvents, mockGetTrace, mockCancelRun } = vi.hoisted(() => ({
  mockListRuns: vi.fn(),
  mockGetRun: vi.fn(),
  mockGetEvents: vi.fn(),
  mockGetTrace: vi.fn(),
  mockCancelRun: vi.fn(),
}));

vi.mock('../../api/traderAnalysis', () => ({
  traderAnalysisApi: {
    listRuns: mockListRuns,
    getRun: mockGetRun,
    getEvents: mockGetEvents,
    getTrace: mockGetTrace,
    createRun: vi.fn(),
    cancelRun: mockCancelRun,
  },
}));

const makeRun = (runId: string, symbol: string, tradeDate: string): TraderAnalysisRun => ({
  runId,
  symbol,
  tradeDate,
  taskStatus: 'completed',
  analysisStatus: 'complete',
  createdAt: `${tradeDate}T08:00:00Z`,
  currentStage: 'completed',
  quality: { providersUsed: [], warnings: [], blockingIssues: [] },
  reports: [],
  links: {},
  metadata: {},
});

describe('TraderAnalysisPage', () => {
  const firstRun = {
    ...makeRun('run-1', '600519', '2026-07-30'),
    metadata: { role_progress: { market: 'completed' } },
    reports: [
      { kind: 'market', title: '市场技术分析', content: '市场报告正文' },
      { kind: 'news', title: '新闻事件分析', content: '新闻报告正文' },
    ],
  };
  const secondRun = {
    ...makeRun('run-2', '000001', '2026-07-31'),
    quality: {
      providersUsed: [],
      blockingIssues: [],
      warnings: [
        { code: 'historical_fundamentals_not_point_in_time', severity: 'warning' as const, capability: 'fundamentals', message: '历史分析不会读取当前财务数据', missingFields: [], retriable: false },
        { code: 'historical_news_not_point_in_time', severity: 'warning' as const, capability: 'news', message: '历史分析不会读取未来新闻', missingFields: [], retriable: false },
        { code: 'social_sources_unavailable', severity: 'warning' as const, capability: 'sentiment', message: '情绪分析已降低置信度', missingFields: [], retriable: false },
        { code: 'fundamentals_runtime_snapshot', severity: 'warning' as const, capability: 'fundamentals', message: '运行时数据不代表历史快照', missingFields: [], retriable: false },
        { code: 'fundamentals_partial', severity: 'warning' as const, capability: 'fundamentals', message: '部分字段缺失', missingFields: [], retriable: false },
      ],
    },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    mockListRuns.mockResolvedValue([firstRun, secondRun]);
    mockGetRun.mockImplementation(async (runId: string) => runId === firstRun.runId ? firstRun : secondRun);
    mockGetEvents.mockResolvedValue([{
      runId: firstRun.runId,
      sequence: 1,
      eventType: 'run.created',
      payload: { stage: 'queued' },
      createdAt: '2026-07-30T08:00:00Z',
    }]);
    mockGetTrace.mockResolvedValue([{
      runId: firstRun.runId,
      sequence: 1,
      eventType: 'llm.completed',
      stage: 'market',
      role: 'market',
      payload: { input: { prompt: '分析' }, output: { text: '完成' } },
      createdAt: '2026-07-30T08:01:00Z',
    }]);
    mockCancelRun.mockImplementation(async (runId: string) => ({
      ...(runId === firstRun.runId ? firstRun : secondRun),
      taskStatus: 'cancelled',
      currentStage: 'cancelled',
    }));
  });

  it('syncs the analysis symbol and date when a task is selected', async () => {
    render(<TraderAnalysisPage />);

    const symbolInput = await screen.findByLabelText('A 股代码');
    const dateInput = screen.getByLabelText('分析日期');
    await waitFor(() => expect(symbolInput).toHaveValue(firstRun.symbol));
    expect(mockGetEvents).not.toHaveBeenCalled();
    expect(mockGetTrace).not.toHaveBeenCalled();
    expect(screen.queryByText('运行状态 / 角色流程')).not.toBeInTheDocument();
    expect(screen.getByText('运行流')).toBeInTheDocument();
    expect(screen.queryByTestId('run-flow-graph')).not.toBeInTheDocument();

    fireEvent.click(screen.getByText('运行流'));
    await waitFor(() => expect(mockGetTrace).toHaveBeenCalledWith(firstRun.runId));
    expect(screen.getByTestId('run-flow-graph')).toBeInTheDocument();
    expect(screen.getByTestId('run-flow-node-request')).toHaveTextContent('600519 分析任务');
    expect(screen.getByTestId('run-flow-node-preflight')).toHaveTextContent('行情与证据预检');
    expect(screen.getByTestId('run-flow-node-market')).toHaveTextContent('市场分析师');
    expect(screen.getByTestId('run-flow-node-research_debate')).toHaveTextContent('多空研究辩论');
    expect(screen.getByTestId('run-flow-node-risk_debate')).toHaveTextContent('风险委员会辩论');
    expect(screen.getByTestId('run-flow-node-report')).toHaveTextContent('完整分析报告');

    fireEvent.click(screen.getByText('Debug 日志'));
    await waitFor(() => expect(mockGetEvents).toHaveBeenCalledWith(firstRun.runId));
    const eventDetails = (await screen.findByText('查看事件数据')).closest('details');
    fireEvent.click(screen.getByText('查看事件数据'));
    expect(eventDetails).toHaveAttribute('open');
    expect(mockGetEvents).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText('LLM 交互消息'));
    await waitFor(() => expect(mockGetTrace).toHaveBeenCalledWith(firstRun.runId));
    const traceDetails = (await screen.findByText('查看输入 / 输出 / 执行信息')).closest('details');
    fireEvent.click(screen.getByText('查看输入 / 输出 / 执行信息'));
    expect(traceDetails).toHaveAttribute('open');
    expect(mockGetTrace).toHaveBeenCalled();

    const reportSummary = screen.getAllByText('完整分析报告').find((node) => node.closest('summary'));
    expect(reportSummary).toBeDefined();
    fireEvent.click(reportSummary!);
    expect(screen.getByRole('tabpanel')).toHaveTextContent('市场报告正文');
    fireEvent.click(screen.getByRole('tab', { name: '📰 新闻事件分析' }));
    expect(screen.getByRole('tabpanel')).toHaveTextContent('新闻报告正文');

    fireEvent.change(symbolInput, { target: { value: '300750' } });
    fireEvent.change(dateInput, { target: { value: '2026-08-01' } });
    fireEvent.click(screen.getByText(secondRun.runId));

    await waitFor(() => {
      expect(symbolInput).toHaveValue(secondRun.symbol);
      expect(dateInput).toHaveValue(secondRun.tradeDate);
    });
    fireEvent.click(screen.getByText('数据质量'));
    expect(screen.getByText('历史基本面数据不满足时点要求')).toBeInTheDocument();
    expect(screen.getByText('历史新闻数据不满足时点要求')).toBeInTheDocument();
    expect(screen.getByText('社交情绪数据源不可用')).toBeInTheDocument();
    expect(screen.getByText('基本面为运行时聚合快照')).toBeInTheDocument();
    expect(screen.getByText('基本面数据部分可用')).toBeInTheDocument();
  });

  it('places refresh and real cancellation actions on each task row', async () => {
    const running = { ...firstRun, taskStatus: 'running' as const, currentStage: 'graph_running' };
    mockListRuns.mockResolvedValue([running, secondRun]);
    mockGetRun.mockResolvedValue(running);
    render(<TraderAnalysisPage />);

    const refresh = await screen.findByRole('button', { name: `刷新任务 ${running.runId}` });
    expect(screen.queryByRole('button', { name: '刷新' })).not.toBeInTheDocument();
    fireEvent.click(refresh);
    await waitFor(() => expect(mockGetRun).toHaveBeenCalledWith(running.runId));

    fireEvent.click(screen.getByRole('button', { name: `取消任务 ${running.runId}` }));
    expect(window.confirm).toHaveBeenCalledWith(`确定要取消交易员分析任务 ${running.runId} 吗？取消后当前分析将停止，且无法继续。`);
    await waitFor(() => expect(mockCancelRun).toHaveBeenCalledWith(running.runId));
  });

  it('keeps a running task when cancellation is not confirmed', async () => {
    const running = { ...firstRun, taskStatus: 'running' as const, currentStage: 'graph_running' };
    mockListRuns.mockResolvedValue([running]);
    mockGetRun.mockResolvedValue(running);
    vi.mocked(window.confirm).mockReturnValue(false);
    render(<TraderAnalysisPage />);

    fireEvent.click(await screen.findByRole('button', { name: `取消任务 ${running.runId}` }));

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(mockCancelRun).not.toHaveBeenCalled();
  });

  it('collapses the complete report by default and keeps expanded section headers below the app header', async () => {
    render(<TraderAnalysisPage />);

    const reportSummary = await screen.findByText('完整分析报告');
    const reportDetails = reportSummary.closest('details');
    expect(reportDetails).not.toHaveAttribute('open');
    fireEvent.click(reportSummary);
    expect(reportDetails).toHaveAttribute('open');

    expect(screen.getByRole('tablist').parentElement).toHaveClass('md:sticky', 'md:top-[7.25rem]');

    for (const title of ['运行流', '完整分析报告', 'Debug 日志', 'LLM 交互消息']) {
      const details = screen.getByText(title).closest('details');
      expect(screen.getByText(title).closest('summary')).toHaveClass('sticky', 'top-14');
      expect(details).toHaveClass('[&:not([open])]:pb-0');
    }
  });

  it('collapses data quality by default and places the complete report before the run flow', async () => {
    render(<TraderAnalysisPage />);

    const qualitySummary = await screen.findByText('数据质量');
    expect(qualitySummary).toHaveClass('font-semibold', 'text-slate-950', 'dark:text-slate-100');
    const qualityDetails = qualitySummary.closest('details');
    expect(qualityDetails).not.toHaveAttribute('open');
    fireEvent.click(qualitySummary);
    expect(qualityDetails).toHaveAttribute('open');

    const reportSummary = screen.getByText('完整分析报告');
    const runFlowSummary = screen.getByText('运行流');
    expect(qualitySummary.compareDocumentPosition(reportSummary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(reportSummary.compareDocumentPosition(runFlowSummary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('covers the run-flow graph with a loading mask while trace is loading', async () => {
    let resolveTrace: (value: never[]) => void = () => undefined;
    mockGetTrace.mockReturnValue(new Promise((resolve) => { resolveTrace = resolve; }));
    render(<TraderAnalysisPage />);

    await screen.findAllByText(firstRun.runId);
    fireEvent.click(screen.getByText('运行流'));

    expect(await screen.findByTestId('trader-run-flow-loading-mask')).toHaveTextContent('正在加载运行流…');
    resolveTrace([]);
    await waitFor(() => expect(screen.queryByTestId('trader-run-flow-loading-mask')).not.toBeInTheDocument());
  });
});
