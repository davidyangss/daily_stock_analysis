import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Ban, CheckCircle2, CircleDot, Play, RefreshCw, ShieldAlert, Square } from 'lucide-react';
import { ApiErrorAlert } from '../components/common';
import { traderAnalysisApi } from '../api/traderAnalysis';
import { getParsedApiError, type ParsedApiError } from '../api/error';
import type { TraderAnalysisRun, TraderAnalysisTraceEvent } from '../types/traderAnalysis';

const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);
const roleSteps = ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst', 'Bull / Bear Research', 'Trader', 'Risk Committee', 'Portfolio Manager'];
const today = () => new Date().toISOString().slice(0, 10);

const statusTone = (status?: string | null) => {
  if (status === 'complete') return 'text-emerald-600';
  if (status === 'degraded') return 'text-amber-600';
  if (status === 'insufficient_evidence') return 'text-red-600';
  return 'text-secondary-text';
};

const TraderAnalysisPage: React.FC = () => {
  const [symbol, setSymbol] = useState('600519');
  const [tradeDate, setTradeDate] = useState(today());
  const [run, setRun] = useState<TraderAnalysisRun | null>(null);
  const [error, setError] = useState<ParsedApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [polling, setPolling] = useState(false);
  const [trace, setTrace] = useState<TraderAnalysisTraceEvent[]>([]);
  const isTerminal = run ? terminalStatuses.has(run.taskStatus) : true;

  useEffect(() => {
    if (!run || terminalStatuses.has(run.taskStatus)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        setPolling(true);
        const [latest, latestTrace] = await Promise.all([traderAnalysisApi.getRun(run.runId), traderAnalysisApi.getTrace(run.runId)]);
        if (active) { setRun(latest); setTrace(latestTrace); }
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

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      setTrace([]);
      setRun(await traderAnalysisApi.createRun({ symbol, tradeDate }));
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
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  const cancel = async () => {
    if (!run) return;
    setError(null);
    try {
      setRun(await traderAnalysisApi.cancelRun(run.runId));
    } catch (err) {
      setError(getParsedApiError(err));
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
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
            {run?.analysisStatus ? <span className={`text-sm font-semibold ${statusTone(run.analysisStatus)}`}>{run.analysisStatus}</span> : null}
          </div>
          {run ? (
            <div className="grid gap-2 text-sm text-secondary-text sm:grid-cols-2">
              <span>Run ID: <span className="font-mono text-foreground">{run.runId}</span></span>
              <span>阶段: <span className="text-foreground">{run.currentStage}</span></span>
              <span>任务: <span className="text-foreground">{run.taskStatus}</span></span>
              <span className="sm:col-span-2">标的: <span className="text-foreground">{run.instrument?.description || run.symbol}</span></span>
            </div>
          ) : (
            <p className="text-sm text-secondary-text">首期固定四类 Analyst 与 1 轮研究/风险辩论；模型和 provider 由服务端配置。</p>
          )}
        </section>
      </section>

      {error ? <ApiErrorAlert error={error} /> : null}

      <section className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-lg border border-border bg-card p-4 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-foreground">角色流程</h2>
          <ol className="grid gap-2">
            {roleSteps.map((step, index) => (
              <li key={step} className="flex items-center gap-3 rounded-md border border-border bg-background px-3 py-2 text-sm">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs text-secondary-text">{index + 1}</span>
                <span className="text-foreground">{step}</span>
              </li>
            ))}
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
                        {issue.code}
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
          <p>{run.error.code}: {run.error.message}</p>
          <p className="mt-1 font-mono text-xs">trace_id={run.error.traceId}</p>
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
                <span className="font-medium text-foreground">{item.eventType}</span>
                {item.role ? <span className="rounded bg-muted px-2 py-0.5 text-xs">{item.role}</span> : null}
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
