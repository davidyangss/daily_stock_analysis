import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { HomeStockWorkspace, type HomeWatchlistRow } from '../HomeStockWorkspace';
import type { StockBarItem } from '../../../types/analysis';

const baseProps = {
  onTabChange: vi.fn(),
  watchlistLoading: false,
  watchlistActioning: false,
  watchlistMessage: null,
  onAddToWatchlist: vi.fn().mockResolvedValue(undefined),
  onRemoveFromWatchlist: vi.fn().mockResolvedValue(undefined),
  onRefreshWatchlist: vi.fn().mockResolvedValue(undefined),
  onAnalyzeWatchlist: vi.fn().mockResolvedValue(undefined),
  isBatchAnalyzing: false,
  batchStatus: null,
  isLoadingTodayItems: false,
  todayLoadError: false,
  watchlistAnalyzedTodayCount: 0,
  historyItems: [],
  isLoadingHistory: false,
  isLoadingMoreHistory: false,
  historyHasMore: false,
  selectedHistoryIds: new Set<number>(),
  onHistoryItemClick: vi.fn(),
  onLoadMoreHistory: vi.fn(),
  onToggleHistorySelection: vi.fn(),
  onToggleSelectAllHistory: vi.fn(),
  onDeleteSelectedHistory: vi.fn(),
};

const watchlistRows: HomeWatchlistRow[] = Array.from({ length: 6 }, (_, index) => ({
  code: `T00${index + 1}`,
  analyzedToday: false,
}));

const todayItems: StockBarItem[] = Array.from({ length: 6 }, (_, index) => ({
  id: index + 1,
  stockCode: `D00${index + 1}`,
  stockName: `今日股票${index + 1}`,
  analysisCount: 1,
  lastAnalysisTime: `2026-08-05T0${index}:00:00+08:00`,
}));

function clickNextPage() {
  const footer = screen.getByTestId('home-workspace-pagination-footer');
  const buttons = footer.querySelectorAll('button');
  fireEvent.click(buttons[buttons.length - 1]);
  return footer;
}

describe('HomeStockWorkspace pagination', () => {
  it('shows five watchlist rows per page and pins pagination to the card footer', () => {
    render(
      <HomeStockWorkspace
        {...baseProps}
        activeTab="watchlist"
        watchlistRows={watchlistRows}
        todayItems={[]}
      />,
    );

    expect(screen.getAllByText('T005')).toHaveLength(2);
    expect(screen.queryAllByText('T006')).toHaveLength(0);
    expect(screen.getByRole('button', { name: '历史' }).parentElement).toHaveClass('sticky', 'top-0', 'z-20');

    const footer = clickNextPage();
    expect(footer).toHaveClass('sticky', 'bottom-0', 'shrink-0');
    expect(screen.getAllByText('T006')).toHaveLength(2);
    expect(screen.queryAllByText('T005')).toHaveLength(0);
  });

  it('shows five today records per page with the same pinned footer', () => {
    render(
      <HomeStockWorkspace
        {...baseProps}
        activeTab="today"
        watchlistRows={[]}
        todayItems={todayItems}
      />,
    );

    expect(screen.getByText('今日股票5')).toBeInTheDocument();
    expect(screen.queryByText('今日股票6')).not.toBeInTheDocument();

    const footer = clickNextPage();
    expect(footer).toHaveClass('sticky', 'bottom-0', 'shrink-0');
    expect(screen.getByText('今日股票6')).toBeInTheDocument();
    expect(screen.queryByText('今日股票5')).not.toBeInTheDocument();
  });
});
