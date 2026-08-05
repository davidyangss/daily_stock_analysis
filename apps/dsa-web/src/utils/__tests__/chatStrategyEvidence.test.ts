import { describe, expect, it } from 'vitest';
import { parseChatStrategyEvidence } from '../chatStrategyEvidence';

describe('parseChatStrategyEvidence', () => {
  it('extracts persisted evidence and hides the transport marker', () => {
    const payload = {
      schema_version: 'strategy-evidence-v1',
      status: 'insufficient',
      selected_strategies: [{ skill_id: 'alpha', skill_name: '策略 A' }],
      strategy_evaluations: [{
        skill_id: 'alpha', status: 'completed', conditions_met: ['条件一'], conditions_missed: ['条件二'],
      }],
      items: [], strategy_requirements: [], limitations: [],
    };
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(payload))));
    const result = parseChatStrategyEvidence(`综合结论\n\n<!-- dsa-strategy-evidence:${encoded} -->`);

    expect(result.visibleContent).toBe('综合结论');
    expect(result.evidence?.selectedStrategies?.[0].skillId).toBe('alpha');
    expect(result.evidence?.strategyEvaluations?.[0].conditionsMissed).toEqual(['条件二']);
  });

  it('extracts and hides the actual model marker', () => {
    const model = btoa('openai/gpt-test, anthropic/claude-test');
    const result = parseChatStrategyEvidence(`回答\n\n<!-- dsa-chat-model:${model} -->`);

    expect(result.visibleContent).toBe('回答');
    expect(result.modelUsed).toBe('openai/gpt-test, anthropic/claude-test');
  });
});
