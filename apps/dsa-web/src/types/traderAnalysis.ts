export type TraderTaskStatus = 'pending' | 'preflighting' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TraderAnalysisStatus = 'complete' | 'degraded' | 'insufficient_evidence';

export type TraderAnalysisIssue = {
  code: string;
  severity: 'info' | 'warning' | 'blocking';
  capability: string;
  provider?: string | null;
  message: string;
  missingFields: string[];
  retriable: boolean;
};

export type TraderAnalysisRun = {
  runId: string;
  taskStatus: TraderTaskStatus;
  analysisStatus?: TraderAnalysisStatus | null;
  symbol: string;
  tradeDate: string;
  createdAt: string;
  startedAt?: string | null;
  completedAt?: string | null;
  currentStage: string;
  instrument?: {
    symbol: string;
    name: string;
    market: 'cn';
    exchange: 'SH' | 'SZ' | 'BJ';
    securityType: 'a_share';
    currency: 'CNY';
    tradeDate: string;
    description: string;
  } | null;
  quality: {
    providersUsed: string[];
    warnings: TraderAnalysisIssue[];
    blockingIssues: TraderAnalysisIssue[];
    overallStatus?: string | null;
  };
  reports: Array<{ kind: string; title: string; content: string }>;
  error?: {
    code: string;
    message: string;
    stage: string;
    traceId: string;
    retriable: boolean;
  } | null;
  links: Record<string, string>;
  metadata: Record<string, unknown>;
};

export type TraderAnalysisEvent = {
  runId: string;
  sequence: number;
  eventType: string;
  payload: Record<string, unknown>;
  createdAt: string;
};

export type TraderAnalysisTraceEvent = {
  runId: string;
  sequence: number;
  eventType: string;
  stage: string;
  role?: string | null;
  deploymentName?: string | null;
  provider?: string | null;
  model?: string | null;
  payload: Record<string, unknown>;
  createdAt: string;
};
