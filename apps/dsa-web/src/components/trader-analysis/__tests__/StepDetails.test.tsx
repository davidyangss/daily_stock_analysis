import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StepDetails } from '../StepDetails';

describe('StepDetails', () => {
  it('separates a completed step into input, output, and execution information', () => {
    render(<StepDetails payload={{
      operationId: 'operation-1',
      input: { tool: 'get_stock_data', arguments: { ticker: '688825' } },
      output: { result: 'rows' },
      durationMs: 18,
    }} />);

    expect(screen.getByText('输入')).toBeInTheDocument();
    expect(screen.getByText('输出')).toBeInTheDocument();
    expect(screen.getByText('执行信息')).toBeInTheDocument();
    expect(screen.getByText(/688825/)).toBeInTheDocument();
    expect(screen.getByText(/rows/)).toBeInTheDocument();
    expect(screen.getByText(/operation-1/)).toBeInTheDocument();
  });

  it('keeps legacy trace payloads visible as detailed data', () => {
    render(<StepDetails payload={{ messages: ['legacy input'] }} />);

    expect(screen.getByText('详细数据')).toBeInTheDocument();
    expect(screen.getByText(/legacy input/)).toBeInTheDocument();
  });
});
