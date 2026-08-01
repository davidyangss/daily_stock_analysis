import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Ban, CheckCircle2, CircleDot, ListTodo, Play, RefreshCw, ShieldAlert, Square } from 'lucide-react';
import { ApiErrorAlert } from '../components/common';
import { traderAnalysisApi } from '../api/traderAnalysis';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import type { TraderAnalysisRun, TraderAnalysisTraceEvent } from '../types/traderAnalysis';

const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);
const roleSteps = ['市场分析师', '情绪分析师', '新闻分析师', '基本面分析师', '多空研究辩论', '交易员', '风险委员会', '投资组合经理'];
const roleKeys = ['market', 'sentiment', 'news', 'fundamentals', 'research_debate', 'trader', 'risk_debate', 'portfolio_manager'];
const today = () => new Date().toISOString().slice(0, 10);

const displayLabels: Record<string, string> = {
  complete: '完整', degraded: '降级可用', insufficient_evidence: '证据不足',
  pending: '等待中', preflighting: '数据预检', running: '分析中', completed: '已完成', failed: '失败', cancelled: '已取消',
  queued: '已排队', collecting_evidence: '收集数据', running_graph: '生成分析', persisting: '保存结果',
  graph_running: '多角色分析',
  provider_error: '数据源调用失败', provider_empty: '数据源未返回数据', provider_invalid_payload: '数据源返回异常数据',
  insufficient_daily_history: '历史日线不足', identity_mismatch: '证券代码不匹配', verified_snapshot_unavailable: '无法确认价格快照',
  llm_start: '模型开始', llm_end: '模型完成', llm_error: '模型错误', tool_start: '工具开始', tool_end: '工具完成', tool_error: '工具错误',
  'run.created': '任务已创建', 'preflight.started': '数据预检开始', 'preflight.completed': '数据预检完成',
  'graph.started': '多角色分析开始', 'graph.completed': '多角色分析完成', 'run.failed': '任务失败', 'run.cancelled': '任务已取消',
  'llm.started': '模型请求开始', 'llm.completed': '模型响应完成', 'llm.failed': '模型请求失败',
  'tool.started': '工具调用开始', 'tool.completed': '工具调用完成', 'tool.failed': '工具调用失败',
  market: '市场分析师', sentiment: '情绪分析师', news: '新闻分析师', fundamentals: '基本面分析师',
  research_debate: '多空研究辩论', research_manager: '研究经理', trader: '交易员', risk_debate: '风险委员会', portfolio_manager: '投资组合经理',
};
const displayLabel = (value?: string | null) => value ? (displayLabels[value] || value) : '-';

const statusTone = (status?: string | null) => {
  if (status === 'complete') return 'text-emerald-600';
  if (status === 'degraded') return 'text-amber-600';
  if (status === 'insufficient_evidence') return 'text-red-600';
  return 'text-secondary-text';
};

const fetchAllRuns = async () => {
  const pageSize = 200;
  const allRuns: TraderAnalysisRun[] = [];
  for (let offset = 0; ; offset += pageSize) {
    const page = await traderAnalysisApi.listRuns({ offset, limit: pageSize });
    allRuns.push(...page);
    if (page.length < pageSize) return allRuns;
  }
};

const TraderAnalysisPage: React.FC = () => {
  const [symbol, setSymbol] = useState('600519');
  const [tradeDate, setTradeDate] = useState(today());
  const [run, setRun] = useState<TraderAnalysisRun | null>(null);
  const [runs, setRuns] = useState<TraderAnalysisRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [trace, setTrace] = useState<TraderAnalysisTraceEvent[]>([]);
  const isTerminal = run ? terminalStatuses.has(run.taskStatus) : true;

  const loadRuns = async (selectFirst = false) => {
    setLoadingRuns(true);
    try {
      const items = await fetchAllRuns();
      setRuns(items);
      if (selectFirst && !run && items.length) await selectRun(items[0]);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setLoadingRuns(false);
    }
  };

  const selectRun = async (selected: TraderAnalysisRun) => {
    setError(null);
    setRun(selected);
    try {
      const [latest, latestTrace] = await Promise.all([
        traderAnalysisApi.getRun(selected.runId),
        traderAnalysisApi.getTrace(selected.runId),
      ]);
      setRun(latest);
      setTrace(latestTrace);
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
        const items = await fetchAllRuns();
        if (active) setRuns(items);
      } catch (err) {
        if (active) setError(getParsedApiError(err));
      }
    }, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [runs]);

  useEffect(() => {
    if (!run || terminalStatuses.has(run.taskStatus)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        setPolling(true);
        const [latest, latestTrace] = await Promise.all([traderAnalysisApi.getRun(run.runId), traderAnalysisApi.getTrace(run.runId)]);
        if (active) {
          setRun(latest); setTrace(latestTrace);
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
  }, [run]);

  const qualityIssues = useMemo(() => {
    if (!run) return [];
    return [...run.quality.blockingIssues, ...run.quality.warnings];
  }, [run]);

  const roleProgress = useMemo(() => {
    const completed = new Set(trace.filter((item) => item.eventType === 'llm.completed' && item.role).map((item) => item.role as string));
    const active = [...trace].reverse().find((item) => item.eventType === 'llm.started' && item.role && !completed.has(item.role))?.role;
    return { completed, active };
  }, [trace]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      setTrace([]);
      const created = await traderAnalysisApi.createRun({ symbol, tradeDate });
      setRun(created);
      setRuns((items) => [created, ...items.filter((item) => item.runId !== created.runId)]);
    } catch (err) {
      setError(getParsedApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  const refresh = async () => {
    if (!run) return;
    setError(null);
    try {
      const [latest, latestTrace] = await Promise.all([traderAnalysisApi.getRun(run.runId), traderAnalysisApi.getTrace(run.runId)]);
      setRun(latest); setTrace(latestTrace);
      setRuns((items) => items.map((item) => item.runId === latest.runId ? latest : item));
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const cancel = async () => {
    if (!run) return;
    setError(null);
    try {
      const cancelled = await traderAnalysisApi.cancelRun(run.runId);
      setRun(cancelled);
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
              A 股代码
              <input value={symbol} onChange={(event) => setSymbol(event.target.value)} className="h-10 rounded-md border border-border bg-background px-3 text-foreground" placeholder="600519" maxLength={24} />
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
            <button type="button" className="btn-secondary inline-flex items-center gap-2" disabled={!run} onClick={refresh}>
              <RefreshCw className={`h-4 w-4 ${polling ? 'animate-spin' : ''}`} />
              刷新
            </button>
            <button type="button" className="btn-secondary inline-flex items-center gap-2" disabled={!run || isTerminal} onClick={cancel}>
              <Square className="h-4 w-4" />
              取消
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
          <button type="button" className="btn-secondary inline-flex items-center gap-2" onClick={() => void loadRuns()} disabled={loadingRuns}>
            <RefreshCw className={`h-4 w-4 ${loadingRuns ? 'animate-spin' : ''}`} />
            刷新列表
          </button>
        </div>
        {runs.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead className="border-b border-border text-xs text-secondary-text">
                <tr><th className="px-3 py-2 font-medium">标的</th><th className="px-3 py-2 font-medium">分析日期</th><th className="px-3 py-2 font-medium">任务状态</th><th className="px-3 py-2 font-medium">当前阶段</th><th className="px-3 py-2 font-medium">创建时间</th><th className="px-3 py-2 font-medium">结果</th></tr>
              </thead>
              <tbody>
                {runs.map((item) => (
                  <tr
                    key={item.runId}
                    className={`cursor-pointer border-b border-border/70 transition-colors hover:bg-muted/60 ${run?.runId === item.runId ? 'bg-primary/5' : ''}`}
                    onClick={() => void selectRun(item)}
                  >
                    <td className="px-3 py-3"><div className="font-medium text-foreground">{item.instrument?.name || item.symbol}</div><div className="font-mono text-xs text-secondary-text">{item.symbol}</div></td>
                    <td className="px-3 py-3 text-secondary-text">{item.tradeDate}</td>
                    <td className="px-3 py-3"><span className="rounded-full bg-muted px-2 py-1 text-xs font-medium text-foreground">{displayLabel(item.taskStatus)}</span></td>
                    <td className="px-3 py-3 text-secondary-text">{displayLabel(item.currentStage)}</td>
                    <td className="px-3 py-3 text-secondary-text">{new Date(item.createdAt).toLocaleString()}</td>
                    <td className={`px-3 py-3 font-medium ${statusTone(item.analysisStatus)}`}>{displayLabel(item.analysisStatus)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="rounded-md border border-dashed border-border p-6 text-center text-sm text-secondary-text">{loadingRuns ? '正在加载任务…' : '暂无交易员分析任务，请在上方创建第一个任务。'}</p>}
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-foreground">角色流程</h2>
          <ol className="grid gap-2">
            {roleSteps.map((step, index) => {
              const role = roleKeys[index];
              const completed = roleProgress.completed.has(role);
              const active = roleProgress.active === role;
              return (
              <li key={step} className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm ${active ? 'border-primary bg-primary/5' : 'border-border bg-background'}`}>
                <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs ${completed ? 'bg-emerald-100 text-emerald-700' : active ? 'bg-primary text-primary-foreground' : 'bg-muted text-secondary-text'}`}>{completed ? '✓' : index + 1}</span>
                <span className="text-foreground">{step}</span>
                <span className="ml-auto text-xs text-secondary-text">{completed ? '已完成' : active ? '进行中' : '等待中'}</span>
              </li>
              );
            })}
          </ol>
        </div>

        <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <div className="mb-3 flex items-center gap-2">
            {run?.analysisStatus === 'insufficient_evidence' ? <Ban className="h-5 w-5 text-red-600" /> : run?.analysisStatus === 'degraded' ? <AlertTriangle className="h-5 w-5 text-amber-600" /> : <CheckCircle2 className="h-5 w-5 text-emerald-600" />}
            <h2 className="text-base font-semibold text-foreground">数据质量</h2>
          </div>
          {run ? (
            <div className="space-y-3 text-sm">
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
          ) : <p className="text-sm text-secondary-text">数据质量会始终显示在这里；证据不足时不会渲染成正常买卖建议。</p>}
        </div>
      </section>

      {run?.error ? (
        <section className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
          <h2 className="mb-2 font-semibold">错误</h2>
          <p>{displayLabel(run.error.code)}：{run.error.message}</p>
          <p className="mt-1 font-mono text-xs">追踪编号：{run.error.traceId}</p>
        </section>
      ) : null}

      {run?.reports.length ? (
        <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-foreground">报告</h2>
          <div className="space-y-4">
            {run.reports.map((report) => (
              <article key={report.kind} className="rounded-md border border-border bg-background p-4">
                <h3 className="mb-2 font-semibold text-foreground">{report.title}</h3>
                <pre className="whitespace-pre-wrap text-sm leading-6 text-secondary-text">{report.content}</pre>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {run ? (
        <section className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-foreground">分析过程</h2>
          {trace.length ? <ol className="space-y-2">
            {trace.map((item) => <li key={item.sequence} className="rounded-md border border-border bg-background p-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-secondary-text">#{item.sequence}</span>
                <span className="font-medium text-foreground">{displayLabel(item.eventType)}</span>
                {item.role ? <span className="rounded bg-muted px-2 py-0.5 text-xs">{displayLabel(item.role)}</span> : null}
                {item.deploymentName ? <span className="text-xs text-secondary-text">{item.deploymentName} · {item.provider}/{item.model}</span> : null}
                <span className="ml-auto text-xs text-secondary-text">{new Date(item.createdAt).toLocaleString()}</span>
              </div>
              {Object.keys(item.payload).length ? <details className="mt-2"><summary className="cursor-pointer text-xs text-secondary-text">查看输入 / 输出 / 数据</summary><pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap text-xs text-secondary-text">{JSON.stringify(item.payload, null, 2)}</pre></details> : null}
            </li>)}
          </ol> : <p className="text-sm text-secondary-text">分析过程尚未产生；运行开始后会显示阶段、模型交互、工具与证据。</p>}
        </section>
      ) : null}
    </div>
  );
};

export default TraderAnalysisPage;
