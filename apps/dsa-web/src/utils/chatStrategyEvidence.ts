import type { StrategyDataEvidence } from '../types/analysis';
import { toCamelCase } from '../api/utils';

const EVIDENCE_MARKER_RE = /\n*<!-- dsa-strategy-evidence:([A-Za-z0-9+/=]+) -->\s*$/;
const MODEL_MARKER_RE = /\n*<!-- dsa-chat-model:([A-Za-z0-9+/=]+) -->\s*$/;

export function parseChatStrategyEvidence(content: string): {
  visibleContent: string;
  evidence: StrategyDataEvidence | null;
  modelUsed: string;
} {
  const modelMatch = content.match(MODEL_MARKER_RE);
  let modelUsed = '';
  let withoutModel = content;
  if (modelMatch) {
    try {
      const bytes = Uint8Array.from(atob(modelMatch[1]), (char) => char.charCodeAt(0));
      modelUsed = new TextDecoder().decode(bytes);
    } catch {
      modelUsed = '';
    }
    withoutModel = content.replace(MODEL_MARKER_RE, '').trimEnd();
  }
  const match = withoutModel.match(EVIDENCE_MARKER_RE);
  if (!match) return { visibleContent: withoutModel, evidence: null, modelUsed };
  try {
    const bytes = Uint8Array.from(atob(match[1]), (char) => char.charCodeAt(0));
    const decoded = new TextDecoder().decode(bytes);
    const evidence = toCamelCase<StrategyDataEvidence>(JSON.parse(decoded));
    if (evidence.schemaVersion !== 'strategy-evidence-v1') throw new Error('Unsupported strategy evidence');
    return { visibleContent: withoutModel.replace(EVIDENCE_MARKER_RE, '').trimEnd(), evidence, modelUsed };
  } catch {
    return { visibleContent: withoutModel.replace(EVIDENCE_MARKER_RE, '').trimEnd(), evidence: null, modelUsed };
  }
}
