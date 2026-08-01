import React from 'react';

type Props = {
  payload: Record<string, unknown>;
};

const JsonBlock: React.FC<{ label: string; value: unknown }> = ({ label, value }) => (
  <div>
    <h4 className="mb-1 text-xs font-semibold text-foreground">{label}</h4>
    <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/60 p-3 text-xs text-secondary-text">
      {JSON.stringify(value, null, 2)}
    </pre>
  </div>
);

export const StepDetails: React.FC<Props> = ({ payload }) => {
  const { input, output, error, durationMs, operationId, ...rest } = payload;
  const hasStructuredDetails = input !== undefined || output !== undefined || error !== undefined;

  if (!hasStructuredDetails) {
    return <JsonBlock label="详细数据" value={payload} />;
  }

  const metadata = {
    ...(durationMs !== undefined ? { durationMs } : {}),
    ...(operationId !== undefined ? { operationId } : {}),
    ...rest,
  };

  return (
    <div className="space-y-3">
      {input !== undefined ? <JsonBlock label="输入" value={input} /> : null}
      {output !== undefined ? <JsonBlock label="输出" value={output} /> : null}
      {error !== undefined ? <JsonBlock label="错误" value={error} /> : null}
      {Object.keys(metadata).length ? <JsonBlock label="执行信息" value={metadata} /> : null}
    </div>
  );
};
