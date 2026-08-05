import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Ban, CheckCircle2, CircleDot, Download, ListTodo, Play, RefreshCw, ShieldAlert, Square } from 'lucide-react';
import { ApiErrorAlert } from '../components/common';
import { ReportMarkdownBody } from '../components/report/ReportMarkdownBody';
import { StockAutocomplete } from '../components/StockAutocomplete';
import { StepDetails } from '../components/trader-analysis/StepDetails';
import { TraderRunFlowGraph } from '../components/trader-analysis/TraderRunFlowGraph';
import { traderAnalysisApi } from '../api/traderAnalysis';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import type { TraderAnalysisEvent, TraderAnalysisRun, TraderAnalysisTraceEvent } from '../types/traderAnalysis';

const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);
const runsPageSize = 5;
const today = () => new Date().toISOString().slice(0, 10);
const stickySectionSummaryClass = 'sticky top-14 z-30 -mx-4 -mt-4 cursor-pointer list-inside border-b border-border bg-card/95 px-4 py-4 font-semibold text-foreground shadow-sm backdrop-blur';
const collapsibleSectionClass = 'rounded-lg border border-border bg-card p-4 shadow-sm [&:not([open])]:pb-0';

const displayLabels: Record<string, string> = {
  complete: '完整', degraded: '降级可用', insufficient_evidence: '证据不足',
  pending: '等待中', preflighting: '数据预检', running: '分析中', completed: '已完成', failed: '失败', cancelled: '已取消',
  queued: '已排队', collecting_evidence: '收集数据', running_graph: '生成分析', persisting: '保存结果',
  graph_running: '多角色分析',
  provider_error: '数据源调用失败', provider_empty: '数据源未返回数据', provider_invalid_payload: '数据源返回异常数据',
  daily_pct_change_recomputed: '日线涨跌幅口径已统一', unadjusted_corporate_action_break: '不复权日线存在除权断点',
  report_market_fact_corrected: '报告行情事实已纠正', report_unsupported_fund_flow_removed: '无证据资金流数值已移除',
  insufficient_daily_history: '历史日线不足', identity_mismatch: '证券代码不匹配', verified_snapshot_unavailable: '无法确认价格快照',
  historical_fundamentals_not_point_in_time: '历史基本面数据不满足时点要求',
  historical_news_not_point_in_time: '历史新闻数据不满足时点要求',
  runtime_news_not_point_in_time: '新闻数据不是历史时点快照',
  runtime_sentiment_not_point_in_time: '社区情绪不是历史时点快照',
  fundamentals_report_expired: '最近一期财报已超过一年',
  fundamentals_report_date_missing: '基本面数据缺少报告期',
  fundamentals_partial: '基本面数据部分可用',
  fundamentals_unavailable: '基本面数据不可用',
  fundamentals_runtime_snapshot: '基本面为运行时聚合快照',
  social_sources_unavailable: '社交情绪数据源不可用',
  limited_daily_history: '新股历史较短', 'evidence.started': '证据获取开始', 'evidence.completed': '证据获取完成',
  llm_start: '模型开始', llm_end: '模型完成', llm_error: '模型错误', tool_start: '工具开始', tool_end: '工具完成', tool_error: '工具错误',
  'run.created': '任务已创建', 'preflight.started': '数据预检开始', 'preflight.completed': '数据预检完成',
  'graph.started': '多角色分析开始', 'graph.completed': '多角色分析完成', 'run.failed': '任务失败', 'run.cancelled': '任务已取消',
  'llm.started': '模型请求开始', 'llm.completed': '模型响应完成', 'llm.failed': '模型请求失败',
  'tool.started': '工具调用开始', 'tool.completed': '工具调用完成', 'tool.failed': '工具调用失败',
  market: '市场分析师', sentiment: '情绪分析师', news: '新闻分析师', fundamentals: '基本面分析师',
  research_debate: '多空研究辩论', research_manager: '研究经理', trader: '交易员', risk_debate: '风险委员会', portfolio_manager: '投资组合经理',
};
const reportLabels: Record<string, string> = {
  market: '📈 市场技术分析', sentiment: '💭 市场情绪分析', news: '📰 新闻事件分析', fundamentals: '💰 基本面分析',
  bull_researcher: '🐂 多头研究员', bear_researcher: '🐻 空头研究员', research_decision: '🔬 研究经理决策',
  trader_plan: '💼 交易员计划', aggressive_analyst: '⚡ 激进分析师', conservative_analyst: '🛡️ 保守分析师',
  neutral_analyst: '⚖️ 中性分析师', portfolio_manager: '👔 投资组合经理', final_decision: '🎯 最终交易决策',
  investment_advice: '📋 投资建议', data_quality: '🧾 数据质量与分析限制',
};
const displayLabel = (value?: string | null) => value ? (displayLabels[value] || value) : '-';

const statusTone = (status?: string | null) => {
  if (status === 'complete') return 'text-emerald-600';
  if (status === 'degraded') return 'text-amber-600';
  if (status === 'insufficient_evidence') return 'text-red-600';
  return 'text-secondary-text';
};

const fetchRunsPage = async (page: number) => {
  const items = await traderAnalysisApi.listRuns({
    offset: (page - 1) * runsPageSize,
    limit: runsPageSize + 1,
  });
  return { items: items.slice(0, runsPageSize), hasNextPage: items.length > runsPageSize };
};

const TraderAnalysisPage: React.FC = () => {
  const [symbol, setSymbol] = useState('600519');
  const [tradeDate, setTradeDate] = useState(today());
  const [run, setRun] = useState<TraderAnalysisRun | null>(null);
  const [runs, setRuns] = useState<TraderAnalysisRun[]>([]);
  const [runsPage, setRunsPage] = useState(1);
  const [hasNextRunsPage, setHasNextRunsPage] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [events, setEvents] = useState<TraderAnalysisEvent[]>([]);
  const [trace, setTrace] = useState<TraderAnalysisTraceEvent[]>([]);
  const [debugExpanded, setDebugExpanded] = useState(false);
  const [loadingEvents, setLoadingEvents] = useState(false);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [runFlowExpanded, setRunFlowExpanded] = useState(false);
  const [traceExpanded, setTraceExpanded] = useState(false);
  const [activeReportKind, setActiveReportKind] = useState<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const loadEvents = async (runId: string) => {
    setLoadingEvents(true);
    try {
      const latestEvents = await traderAnalysisApi.getEvents(runId);
      if (selectedRunIdRef.current === runId) setEvents(latestEvents);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      if (selectedRunIdRef.current === runId) setLoadingEvents(false);
    }
  };

  const loadTrace = async (runId: string) => {
    setLoadingTrace(true);
    try {
      const latestTrace = await traderAnalysisApi.getTrace(runId);
      if (selectedRunIdRef.current === runId) setTrace(latestTrace);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      if (selectedRunIdRef.current === runId) setLoadingTrace(false);
    }
  };

  const loadRuns = async (selectFirst = false, page = runsPage) => {
    setLoadingRuns(true);
    try {
      const { items, hasNextPage } = await fetchRunsPage(page);
      setRuns(items);
      setHasNextRunsPage(hasNextPage);
      if (selectFirst && !run && items.length) await selectRun(items[0]);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoadingRuns(false);
    }
  };

  const selectRun = async (selected: TraderAnalysisRun) => {
    setError(null);
    selectedRunIdRef.current = selected.runId;
    setRun(selected);
    setActiveReportKind(selected.reports[0]?.kind ?? null);
    setSymbol(selected.symbol);
    setTradeDate(selected.tradeDate);
    setEvents([]);
    setTrace([]);
    try {
      const [latest, latestTrace] = await Promise.all([
        traderAnalysisApi.getRun(selected.runId),
        runFlowExpanded || traceExpanded ? traderAnalysisApi.getTrace(selected.runId) : Promise.resolve(null),
      ]);
      setRun(latest);
      if (latestTrace) setTrace(latestTrace);
      setActiveReportKind((current) => latest.reports.some((report) => report.kind === current) ? current : (latest.reports[0]?.kind ?? null));
      setSymbol(latest.symbol);
      setTradeDate(latest.tradeDate);
      if (debugExpanded) void loadEvents(latest.runId);
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  useEffect(() => { void loadRuns(true); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!runs.some((item) => !terminalStatuses.has(item.taskStatus))) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const page = await fetchRunsPage(runsPage);
        if (active) {
          setRuns(page.items);
          setHasNextRunsPage(page.hasNextPage);
        }
      } catch (err) {
        if (active) setError(getParsedApiError(err));
      }
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [runs, runsPage]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.taskStatus)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        setPolling(true);
        const [latest, latestEvents, latestTrace] = await Promise.all([
          traderAnalysisApi.getRun(run.runId),
          debugExpanded ? traderAnalysisApi.getEvents(run.runId) : Promise.resolve(null),
          runFlowExpanded || traceExpanded ? traderAnalysisApi.getTrace(run.runId) : Promise.resolve(null),
        ]);
        if (active) {
          setRun(latest);
          if (latestEvents) setEvents(latestEvents);
          if (latestTrace) setTrace(latestTrace);
          setRuns((items) => items.map((item) => item.runId === latest.runId ? latest : item));
        }
      } catch (err) {
        if (active) setError(getParsedApiError(err));
      } finally {
        if (active) setPolling(false);
      }
    }, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [run, debugExpanded, runFlowExpanded, traceExpanded]);

  const qualityIssues = useMemo(() => {
    if (!run) return [];
    return [...run.quality.blockingIssues, ...run.quality.warnings];
  }, [run]);

  const analysisSteps = useMemo(() => {
    const relevant = trace.filter((item) => item.eventType.startsWith('llm.') || item.eventType.startsWith('tool.'));
    const terminalOperations = new Set(relevant
      .filter((item) => item.eventType.endsWith('.completed') || item.eventType.endsWith('.failed'))
      .map((item) => item.payload.operationId)
      .filter((value): value is string => typeof value === 'string'));
    return relevant.filter((item) => !(
      item.eventType.endsWith('.started')
      && typeof item.payload.operationId === 'string'
      && terminalOperations.has(item.payload.operationId)
    ));
  }, [trace]);

  const activeReport = useMemo(() => {
    if (!run?.reports.length) return null;
    return run.reports.find((report) => report.kind === activeReportKind) ?? run.reports[0];
  }, [activeReportKind, run]);

  const submitRun = async (requestedSymbol: string) => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      setTrace([]);
      setEvents([]);
      const created = await traderAnalysisApi.createRun({ symbol: requestedSymbol, tradeDate });
      selectedRunIdRef.current = created.runId;
      setRun(created);
      setActiveReportKind(created.reports[0]?.kind ?? null);
      if (debugExpanded) void loadEvents(created.runId);
      if (runFlowExpanded || traceExpanded) void loadTrace(created.runId);
      setRunsPage(1);
      const firstPage = await fetchRunsPage(1);
      setRuns(firstPage.items);
      setHasNextRunsPage(firstPage.hasNextPage);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void submitRun(symbol);
  };

  const refresh = async (runId: string) => {
    setError(null);
    try {
      const [latest, latestEvents, latestTrace] = await Promise.all([
        traderAnalysisApi.getRun(runId),
        debugExpanded && selectedRunIdRef.current === runId ? traderAnalysisApi.getEvents(runId) : Promise.resolve(null),
        runFlowExpanded || traceExpanded ? traderAnalysisApi.getTrace(runId) : Promise.resolve(null),
      ]);
      if (selectedRunIdRef.current === runId) {
        setRun(latest);
        if (latestEvents) setEvents(latestEvents);
        if (latestTrace) setTrace(latestTrace);
      }
      setRuns((items) => items.map((item) => item.runId === latest.runId ? latest : item));
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const cancel = async (runId: string) => {
    if (!window.confirm(`确定要取消交易员分析任务 ${runId} 吗？取消后当前分析将停止，且无法继续。`)) return;
    setError(null);
    try {
      const cancelled = await traderAnalysisApi.cancelRun(runId);
      if (selectedRunIdRef.current === runId) setRun(cancelled);
      setRuns((items) => items.map((item) => item.runId === cancelled.runId ? cancelled : item));
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-0 py-6 sm:px-6 lg:px-8">
      <section className="grid gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
        <form onSubmit={submit} className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <CircleDot className="h-5 w-5 text-primary" />
            <h1 className="text-lg font-semibold text-foreground">交易员分析</h1>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm text-secondary-text">
              A 股代码或名称
              <StockAutocomplete
                value={symbol}
                onChange={setSymbol}
                onSubmit={(stockCode) => {
                  setSymbol(stockCode);
                  void submitRun(stockCode);
                }}
                allowedMarkets={['CN', 'BSE']}
                disabled={submitting}
                placeholder="输入代码或名称（例如 600519 或 贵州茅台）"
                ariaLabel="A 股代码或名称"
                className="h-10 rounded-md border-border bg-background px-3 text-foreground"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm text-secondary-text">
              分析日期
              <input value={tradeDate} onChange={(event) => setTradeDate(event.target.value)} type="date" className="h-10 rounded-md border border-border bg-background px-3 text-foreground" />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <button type="submit" className="btn-primary inline-flex items-center gap-2" disabled={submitting}>
              <Play className="h-4 w-4" />
              {submitting ? '提交中' : '开始分析'}
            </button>
          </div>
        </form>

        <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-foreground">任务状态</h2>
            {run?.analysisStatus ? <span className={`text-sm font-semibold ${statusTone(run.analysisStatus)}`}>{displayLabel(run.analysisStatus)}</span> : null}
          </div>
          {run ? (
            <div className="grid gap-2 text-sm text-secondary-text sm:grid-cols-2">
              <span>运行编号：<span className="font-mono text-foreground">{run.runId}</span></span>
              <span>阶段：<span className="text-foreground">{displayLabel(run.currentStage)}</span></span>
              <span>任务：<span className="text-foreground">{displayLabel(run.taskStatus)}</span></span>
              <span className="sm:col-span-2">标的: <span className="text-foreground">{run.instrument?.description || run.symbol}</span></span>
            </div>
          ) : (
            <p className="text-sm text-secondary-text">当前包含四类分析师与一轮研究、风险辩论；模型和服务商由服务端配置。</p>
          )}
        </section>
      </section>

      {error ? <ApiErrorAlert error={error} /> : null}

      <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ListTodo className="h-5 w-5 text-primary" />
            <div>
              <h2 className="text-base font-semibold text-foreground">交易员分析任务</h2>
              <p className="text-xs text-secondary-text">任务状态、报告和模型交互会持久保留，点击任务可继续查看。</p>
            </div>
          </div>
          <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void loadRuns(false, runsPage)} disabled={loadingRuns}>
            <RefreshCw className={`h-4 w-4 ${loadingRuns ? 'animate-spin' : ''}`} />
            刷新列表
          </button>
        </div>
        {runs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-left text-sm">
              <thead className="border-b border-border text-xs text-secondary-text">
                <tr><th className="px-3 py-2 font-medium">任务 ID</th><th className="px-3 py-2 font-medium">标的</th><th className="px-3 py-2 font-medium">分析日期</th><th className="px-3 py-2 font-medium">任务状态</th><th className="px-3 py-2 font-medium">当前阶段</th><th className="px-3 py-2 font-medium">报告内容</th><th className="px-3 py-2 font-medium">结果</th><th className="px-3 py-2 font-medium">操作</th></tr>
              </thead>
              <tbody>
                {runs.map((item) => (
                  <tr
                    key={item.runId}
                    className={`cursor-pointer border-b border-border/70 transition-colors hover:bg-muted/60 ${run?.runId === item.runId ? 'bg-primary/5' : ''}`}
                    onClick={() => void selectRun(item)}
                  >
                    <td className="px-3 py-3 font-mono text-xs text-secondary-text">{item.runId}</td>
                    <td className="px-3 py-3"><div className="font-medium text-foreground">{item.instrument?.name || item.symbol}</div><div className="font-mono text-xs text-secondary-text">{item.symbol}</div></td>
                    <td className="px-3 py-3 text-secondary-text">{item.tradeDate}</td>
                    <td className="px-3 py-3"><span className="rounded-full bg-muted px-2 py-1 text-xs font-medium text-foreground">{displayLabel(item.taskStatus)}</span></td>
                    <td className="px-3 py-3 text-secondary-text">{displayLabel(item.currentStage)}</td>
                    <td className="max-w-sm px-3 py-3 text-secondary-text">
                      {item.reports.length ? <div className="space-y-1">{item.reports.slice(0, 3).map((report) => (
                        <div key={report.kind}><span className="font-medium text-foreground">{reportLabels[report.kind] || report.title}</span><span className="ml-1 line-clamp-1">{report.content.slice(0, 80)}</span></div>
                      ))}{item.reports.length > 3 ? <span className="text-xs">另有 {item.reports.length - 3} 个报告模块</span> : null}</div> : '尚未生成报告'}
                    </td>
                    <td className={`px-3 py-3 font-medium ${statusTone(item.analysisStatus)}`}>{displayLabel(item.analysisStatus)}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <button type="button" className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs" aria-label={`刷新任务 ${item.runId}`} onClick={(event) => { event.stopPropagation(); void refresh(item.runId); }}>
                          <RefreshCw className="h-3.5 w-3.5" />刷新
                        </button>
                        <button type="button" className="btn-secondary inline-flex items-center gap-1 px-2 py-1 text-xs" aria-label={`取消任务 ${item.runId}`} disabled={terminalStatuses.has(item.taskStatus)} onClick={(event) => { event.stopPropagation(); void cancel(item.runId); }}>
                          <Square className="h-3.5 w-3.5" />取消
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-secondary-text">{loadingRuns ? '正在加载任务…' : '暂无交易员分析任务，请在上方创建第一个任务。'}</p>}
        <div className="mt-4 flex items-center justify-end gap-3 border-t border-border pt-3">
          <button
            type="button"
            className="btn-secondary"
            disabled={loadingRuns || runsPage === 1}
            onClick={() => {
              const previousPage = runsPage - 1;
              setRunsPage(previousPage);
              void loadRuns(false, previousPage);
            }}
          >
            上一页
          </button>
          <span className="text-sm text-secondary-text">第 {runsPage} 页</span>
          <button
            type="button"
            className="btn-secondary"
            disabled={loadingRuns || !hasNextRunsPage}
            onClick={() => {
              const nextPage = runsPage + 1;
              setRunsPage(nextPage);
              void loadRuns(false, nextPage);
            }}
          >
            下一页
          </button>
        </div>
      </section>

      <details className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <summary className="cursor-pointer list-inside font-semibold text-foreground">
            <span className="inline-flex items-center gap-2">
            {run?.analysisStatus === 'insufficient_evidence' ? <Ban className="h-5 w-5 text-red-600" /> : run?.analysisStatus === 'degraded' ? <AlertTriangle className="h-5 w-5 text-amber-600" /> : <CheckCircle2 className="h-5 w-5 text-emerald-600" />}
              <span className="text-base font-semibold text-slate-950 dark:text-slate-100">数据质量</span>
            </span>
          </summary>
          {run ? (
            <div className="mt-3 space-y-3 text-sm">
              <p className="text-secondary-text">来源：{run.quality.providersUsed.length ? run.quality.providersUsed.join(', ') : '无'}</p>
              {qualityIssues.length ? (
                <ul className="space-y-2">
                  {qualityIssues.map((issue, index) => (
                    <li key={`${issue.code}-${index}`} className="rounded-md border border-border bg-background p-3">
                      <div className="flex items-center gap-2 font-medium text-foreground">
                        <ShieldAlert className="h-4 w-4" />
                        {displayLabel(issue.code)}
                      </div>
                      <p className="mt-1 text-secondary-text">{issue.message}</p>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-secondary-text">暂无阻断问题或降级警告。</p>}
            </div>
          ) : <p className="mt-3 text-sm text-secondary-text">数据质量会始终显示在这里；证据不足时不会渲染成正常买卖建议。</p>}
      </details>

      {run?.reports.length ? (
        <details className={collapsibleSectionClass}>
          <summary className={stickySectionSummaryClass}>
            完整分析报告
            <span className="ml-2 text-xs font-normal text-secondary-text">各角色正式报告均以 Markdown 完整显示</span>
          </summary>
          <div className="mt-4 flex justify-end">
            <a className="btn-primary inline-flex items-center gap-2" href={`/api/v1/trader-analysis/runs/${encodeURIComponent(run.runId)}/download/markdown`} download={`${run.symbol}_分析报告_${run.tradeDate}.md`}>
              <Download className="h-4 w-4" />下载 Markdown
            </a>
          </div>
          <div className="sticky top-[7.0625rem] z-20 -mx-2 my-4 border-y border-border bg-card/95 px-2 py-2 backdrop-blur">
            <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label="分析报告模块">
              {run.reports.map((report) => {
                const active = activeReport?.kind === report.kind;
                return (
                  <button
                    key={report.kind}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    className={`shrink-0 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${active ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-background text-secondary-text hover:bg-muted hover:text-foreground'}`}
                    onClick={() => setActiveReportKind(report.kind)}
                  >
                    {reportLabels[report.kind] || report.title}
                  </button>
                );
              })}
            </div>
          </div>
          {activeReport ? (
            <article role="tabpanel" className="rounded-md border border-border bg-background p-4">
              <h3 className="mb-3 text-base font-semibold text-foreground">{reportLabels[activeReport.kind] || activeReport.title}</h3>
              <ReportMarkdownBody content={activeReport.content} />
            </article>
          ) : null}
        </details>
      ) : null}

      {run ? (
        <details className={collapsibleSectionClass} onToggle={(event) => {
          if (event.target !== event.currentTarget) return;
          const expanded = event.currentTarget.open;
          setRunFlowExpanded(expanded);
          if (expanded) void loadTrace(run.runId);
        }}>
          <summary className={stickySectionSummaryClass}>
            运行流
            <span className="ml-2 text-xs font-normal text-secondary-text">展开后加载完整流程图</span>
          </summary>
          {runFlowExpanded ? <div className="mt-4">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-xs text-secondary-text">完整展示证据预检、多角色并行分析、研究与风险决策及报告输出流程。</p>
              {polling ? <span className="inline-flex items-center gap-1 text-xs text-secondary-text"><RefreshCw className="h-3.5 w-3.5 animate-spin" />更新中</span> : null}
            </div>
            <TraderRunFlowGraph run={run} trace={trace} loading={loadingTrace} />
          </div> : null}
        </details>
      ) : null}

      {run?.error ? (
        <section className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <h2 className="mb-2 font-semibold">错误</h2>
          <p>{displayLabel(run.error.code)}：{run.error.message}</p>
          <p className="mt-1 font-mono text-xs">追踪编号：{run.error.traceId}</p>
        </section>
      ) : null}

      {run ? (
        <details className={collapsibleSectionClass} onToggle={(event) => {
          if (event.target !== event.currentTarget) return;
          const expanded = event.currentTarget.open;
          setDebugExpanded(expanded);
          if (expanded) void loadEvents(run.runId);
        }}>
          <summary className={stickySectionSummaryClass}>
            Debug 日志
            <span className="ml-2 text-xs font-normal text-secondary-text">展开后加载</span>
          </summary>
          <div className="mt-3">
            <p className="mt-1 text-xs text-secondary-text">与任务 ID {run.runId} 关联的运行阶段、错误和状态事件。</p>
          </div>
          {loadingEvents ? <p className="mt-3 text-sm text-secondary-text">正在加载 Debug 日志…</p> : events.length ? <ol className="mt-3 space-y-2">
            {events.map((item) => <li key={item.sequence} className="rounded-md border border-border bg-background p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-secondary-text">#{item.sequence}</span>
                <span className="font-medium text-foreground">{displayLabel(item.eventType)}</span>
                <span className="ml-auto text-xs text-secondary-text">{new Date(item.createdAt).toLocaleString()}</span>
              </div>
              {Object.keys(item.payload).length ? <details className="mt-2"><summary className="cursor-pointer text-xs text-secondary-text">查看事件数据</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-secondary-text">{JSON.stringify(item.payload, null, 2)}</pre></details> : null}
            </li>)}
          </ol> : <p className="text-sm text-secondary-text">当前任务尚未产生 Debug 日志。</p>}
        </details>
      ) : null}

      {run ? (
        <details className={collapsibleSectionClass} onToggle={(event) => {
          if (event.target !== event.currentTarget) return;
          const expanded = event.currentTarget.open;
          setTraceExpanded(expanded);
          if (expanded) void loadTrace(run.runId);
        }}>
          <summary className={stickySectionSummaryClass}>
            LLM 交互消息
            <span className="ml-2 text-xs font-normal text-secondary-text">展开后加载</span>
          </summary>
          <div className="mt-3">
            <p className="mt-1 text-xs text-secondary-text">与任务 ID {run.runId} 关联的脱敏模型请求、响应和工具调用。</p>
          </div>
          {loadingTrace ? <p className="mt-3 text-sm text-secondary-text">正在加载 LLM 交互消息…</p> : analysisSteps.length ? <ol className="mt-3 space-y-2">
            {analysisSteps.map((item) => <li key={item.sequence} className="rounded-md border border-border bg-background p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-secondary-text">#{item.sequence}</span>
                <span className="font-medium text-foreground">{displayLabel(item.eventType)}</span>
                {item.role ? <span className="rounded bg-muted px-2 py-0.5 text-xs">{displayLabel(item.role)}</span> : null}
                {item.deploymentName ? <span className="text-xs text-secondary-text">{item.deploymentName} · {item.provider}/{item.model}</span> : null}
                <span className="ml-auto text-xs text-secondary-text">{new Date(item.createdAt).toLocaleString()}</span>
              </div>
              {Object.keys(item.payload).length ? <details className="mt-2"><summary className="cursor-pointer text-xs text-secondary-text">查看输入 / 输出 / 执行信息</summary><div className="mt-2"><StepDetails payload={item.payload} /></div></details> : null}
            </li>)}
          </ol> : <p className="text-sm text-secondary-text">分析过程尚未产生；运行开始后会显示模型与工具步骤的详细输入输出。</p>}
        </details>
      ) : null}
    </div>
  );
};

export default TraderAnalysisPage;
