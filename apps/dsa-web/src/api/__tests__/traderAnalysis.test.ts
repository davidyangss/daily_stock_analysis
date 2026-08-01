import { beforeEach, describe, expect, it, vi } from 'vitest';
import { traderAnalysisApi } from '../traderAnalysis';

const { get, post } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock('../index', () => ({
  default: {
    get,
    post,
  },
}));

const runPayload = {
  run_id: 'run-1',
  symbol: '600519',
  trade_date: '2026-07-31',
  task_status: 'queued',
  current_stage: 'queued',
  analysis_status: null,
  instrument: null,
  quality: {
    blocking_issues: [],
    warnings: [],
    providers_used: [],
  },
  reports: [],
  error: null,
  created_at: '2026-07-31T10:00:00',
  updated_at: '2026-07-31T10:00:00',
  links: {},
};

describe('traderAnalysisApi', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
  });

  it('creates runs on the versioned API path with snake_case payload fields', async () => {
    post.mockResolvedValueOnce({ data: runPayload });

    const result = await traderAnalysisApi.createRun({
      symbol: '600519',
      tradeDate: '2026-07-31',
    });

    expect(post).toHaveBeenCalledWith('/api/v1/trader-analysis/runs', {
      symbol: '600519',
      trade_date: '2026-07-31',
    });
    expect(result.runId).toBe('run-1');
    expect(result.taskStatus).toBe('queued');
  });

  it('reads runs and events from versioned API paths', async () => {
    get.mockResolvedValueOnce({ data: runPayload });
    get.mockResolvedValueOnce({
      data: [
        {
          seq: 1,
          run_id: 'run-1',
          stage: 'market',
          message: 'ok',
          created_at: '2026-07-31T10:00:01',
        },
      ],
    });

    const run = await traderAnalysisApi.getRun('run/1');
    const events = await traderAnalysisApi.getEvents('run/1', 3);

    expect(get).toHaveBeenNthCalledWith(1, '/api/v1/trader-analysis/runs/run%2F1');
    expect(get).toHaveBeenNthCalledWith(2, '/api/v1/trader-analysis/runs/run%2F1/events', {
      params: { after: 3 },
    });
    expect(run.runId).toBe('run-1');
    expect(events[0].runId).toBe('run-1');
  });

  it('lists durable trader-analysis runs', async () => {
    get.mockResolvedValueOnce({ data: [runPayload] });

    const result = await traderAnalysisApi.listRuns({ taskStatus: ['running'], limit: 25 });

    expect(get).toHaveBeenCalledWith('/api/v1/trader-analysis/runs', {
      params: { task_status: ['running'], offset: 0, limit: 25 },
    });
    expect(result[0].runId).toBe('run-1');
  });

  it('cancels runs on the versioned API path', async () => {
    post.mockResolvedValueOnce({ data: { ...runPayload, task_status: 'cancelled' } });

    const result = await traderAnalysisApi.cancelRun('run/1');

    expect(post).toHaveBeenCalledWith('/api/v1/trader-analysis/runs/run%2F1/cancel');
    expect(result.taskStatus).toBe('cancelled');
  });
});
