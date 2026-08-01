import React, { useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { RunFlowGraph } from '../run-flow';
import type { RunFlowEdge, RunFlowLane, RunFlowNode, RunFlowStatus } from '../../types/runFlow';
import type { TraderAnalysisRun, TraderAnalysisTraceEvent } from '../../types/traderAnalysis';

type Props = {
  run: TraderAnalysisRun;
  trace: TraderAnalysisTraceEvent[];
  loading?: boolean;
};

const lanes: RunFlowLane[] = [
  { id: 'entry', label: '任务入口', order: 1 },
  { id: 'data_source', label: '证据预检', order: 2 },
  { id: 'analysts', label: '并行分析', order: 3 },
  { id: 'decision', label: '研究与决策', order: 4 },
  { id: 'artifact', label: '分析产物', order: 5 },
];

const roleDefinitions = [
  { id: 'market', lane: 'analysts', label: '市场分析师' },
  { id: 'sentiment', lane: 'analysts', label: '情绪分析师' },
  { id: 'news', lane: 'analysts', label: '新闻分析师' },
  { id: 'fundamentals', lane: 'analysts', label: '基本面分析师' },
  { id: 'research_debate', lane: 'decision', label: '多空研究辩论' },
  { id: 'research_manager', lane: 'decision', label: '研究经理' },
  { id: 'trader', lane: 'decision', label: '交易员' },
  { id: 'risk_debate', lane: 'decision', label: '风险委员会辩论' },
  { id: 'portfolio_manager', lane: 'decision', label: '投资组合经理' },
] as const;

const roleStatus = (run: TraderAnalysisRun, trace: TraderAnalysisTraceEvent[], role: string): RunFlowStatus => {
  const events = trace.filter((event) => event.role === role);
  if (events.some((event) => event.eventType === 'llm.failed')) return 'failed';
  if (events.some((event) => event.eventType === 'llm.completed')) return 'success';
  if (events.some((event) => event.eventType === 'llm.started')) return 'running';
  if (run.taskStatus === 'cancelled') return 'cancelled';
  if (run.taskStatus === 'failed') return 'skipped';
  return 'pending';
};

const lifecycleStatus = (run: TraderAnalysisRun, trace: TraderAnalysisTraceEvent[], completedEvent: string, activeEvent: string): RunFlowStatus => {
  if (trace.some((event) => event.eventType === completedEvent)) return 'success';
  if (trace.some((event) => event.eventType === activeEvent)) return 'running';
  if (run.taskStatus === 'cancelled') return 'cancelled';
  if (run.taskStatus === 'failed') return 'failed';
  return 'pending';
};

const edge = (from: string, to: string, status: RunFlowStatus, label?: string): RunFlowEdge => ({
  id: `${from}-${to}`,
  from,
  to,
  kind: 'control',
  status,
  label,
});

export const TraderRunFlowGraph: React.FC<Props> = ({ run, trace, loading = false }) => {
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const model = useMemo(() => {
    const createdStatus: RunFlowStatus = 'success';
    const preflightStatus = lifecycleStatus(run, trace, 'preflight.completed', 'preflight.started');
    const roleNodes: RunFlowNode[] = roleDefinitions.map((definition) => {
      const roleEvents = trace.filter((event) => event.role === definition.id);
      const started = roleEvents.find((event) => event.eventType === 'llm.started');
      const ended = [...roleEvents].reverse().find((event) => event.eventType === 'llm.completed' || event.eventType === 'llm.failed');
      return {
        id: definition.id,
        lane: definition.lane,
        kind: 'model',
        label: definition.label,
        status: roleStatus(run, trace, definition.id),
        provider: ended?.deploymentName || started?.deploymentName || null,
        startedAt: started?.createdAt || null,
        endedAt: ended?.createdAt || null,
        message: ended?.model || started?.model || null,
      };
    });
    const roleNodeById = new Map(roleNodes.map((node) => [node.id, node]));
    const finalStatus: RunFlowStatus = run.taskStatus === 'completed'
      ? (run.analysisStatus === 'degraded' ? 'degraded' : 'success')
      : run.taskStatus === 'failed' ? 'failed'
        : run.taskStatus === 'cancelled' ? 'cancelled' : 'pending';
    const nodes: RunFlowNode[] = [
      { id: 'request', lane: 'entry', kind: 'entry', label: `${run.symbol} 分析任务`, status: createdStatus, startedAt: run.createdAt },
      { id: 'preflight', lane: 'data_source', kind: 'data_source', label: '行情与证据预检', status: preflightStatus, startedAt: run.startedAt || null, message: run.quality.providersUsed.join('、') || null },
      ...roleNodes,
      { id: 'report', lane: 'artifact', kind: 'artifact', label: '完整分析报告', status: finalStatus, endedAt: run.completedAt || null, recordCount: run.reports.length },
    ];
    const edges: RunFlowEdge[] = [edge('request', 'preflight', preflightStatus, '开始预检')];
    for (const analyst of ['market', 'sentiment', 'news', 'fundamentals']) {
      edges.push(edge('preflight', analyst, roleNodeById.get(analyst)?.status || 'pending', '并行分析'));
      edges.push(edge(analyst, 'research_debate', roleNodeById.get('research_debate')?.status || 'pending', '观点汇聚'));
    }
    for (const [from, to, label] of [
      ['research_debate', 'research_manager', '研究裁决'],
      ['research_manager', 'trader', '生成计划'],
      ['trader', 'risk_debate', '风险评估'],
      ['risk_debate', 'portfolio_manager', '风险汇聚'],
      ['portfolio_manager', 'report', '输出报告'],
    ] as const) edges.push(edge(from, to, roleNodeById.get(to)?.status || finalStatus, label));
    return { nodes, edges };
  }, [run, trace]);

  return (
    <div className="relative min-h-64 space-y-3" aria-busy={loading}>
      <RunFlowGraph
        lanes={lanes}
        nodes={model.nodes}
        edges={model.edges}
        selectedNodeId={selectedNodeId}
        onSelectNode={(node) => setSelectedNodeId((current) => current === node.id ? null : node.id)}
      />
      {loading ? (
        <div
          className="absolute inset-0 z-30 flex min-h-64 items-center justify-center rounded-lg bg-background/80 backdrop-blur-[1px]"
          data-testid="trader-run-flow-loading-mask"
        >
          <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card px-6 py-5 shadow-lg">
            <RefreshCw className="h-6 w-6 animate-spin text-primary" aria-hidden="true" />
            <p className="text-sm font-medium text-foreground">正在加载运行流…</p>
          </div>
        </div>
      ) : null}
    </div>
  );
};
