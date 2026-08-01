import apiClient from './index';
import { toCamelCase } from './utils';
import type { TraderAnalysisEvent, TraderAnalysisRun, TraderAnalysisTraceEvent } from '../types/traderAnalysis';

export const traderAnalysisApi = {
  async createRun(payload: { symbol: string; tradeDate: string }): Promise<TraderAnalysisRun> {
    const response = await apiClient.post('/api/v1/trader-analysis/runs', {
      symbol: payload.symbol,
      trade_date: payload.tradeDate,
    });
    return toCamelCase(response.data) as TraderAnalysisRun;
  },

  async getRun(runId: string): Promise<TraderAnalysisRun> {
    const response = await apiClient.get(`/api/v1/trader-analysis/runs/${encodeURIComponent(runId)}`);
    return toCamelCase(response.data) as TraderAnalysisRun;
  },

  async getEvents(runId: string, after = 0): Promise<TraderAnalysisEvent[]> {
    const response = await apiClient.get(`/api/v1/trader-analysis/runs/${encodeURIComponent(runId)}/events`, {
      params: { after },
    });
    return toCamelCase(response.data) as TraderAnalysisEvent[];
  },

  async getTrace(runId: string, after = 0): Promise<TraderAnalysisTraceEvent[]> {
    const response = await apiClient.get(`/api/v1/trader-analysis/runs/${encodeURIComponent(runId)}/trace`, { params: { after } });
    return toCamelCase(response.data) as TraderAnalysisTraceEvent[];
  },

  async cancelRun(runId: string): Promise<TraderAnalysisRun> {
    const response = await apiClient.post(`/api/v1/trader-analysis/runs/${encodeURIComponent(runId)}/cancel`);
    return toCamelCase(response.data) as TraderAnalysisRun;
  },
};
