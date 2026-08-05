import type React from 'react';
import { useRef, useCallback, useEffect, useId, useMemo, useState } from 'react';
import type { HistoryItem } from '../../types/analysis';
import { Badge, Button, ScrollArea } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { HistoryListItem } from './HistoryListItem';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

interface HistoryListProps {
  items: HistoryItem[];
  isLoading: boolean;
  isLoadingMore: boolean;
  hasMore: boolean;
  selectedId?: number;  // 当前选中的历史记录 ID
  selectedIds: Set<number>;
  isDeleting?: boolean;
  onItemClick: (recordId: number) => void;  // 点击记录的回调
  onLoadMore: () => void;
  onToggleItemSelection: (recordId: number) => void;
  onToggleSelectAll: () => void;
  onDeleteSelected: () => void;
  paginationMode?: 'infinite' | 'paged';
  pageSize?: number;
  title?: string;
  emptyTitle?: string;
  emptyDescription?: string;
  className?: string;
}

/**
 * 历史记录列表组件 (升级版)
 * 使用新设计系统组件实现，支持批量选择和滚动加载
 */
export const HistoryList: React.FC<HistoryListProps> = ({
  items,
  isLoading,
  isLoadingMore,
  hasMore,
  selectedId,
  selectedIds,
  isDeleting = false,
  onItemClick,
  onLoadMore,
  onToggleItemSelection,
  onToggleSelectAll,
  onDeleteSelected,
  paginationMode = 'infinite',
  pageSize = 5,
  title,
  emptyTitle,
  emptyDescription,
  className = '',
}) => {
  const { t } = useUiLanguage();
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const loadMoreTriggerRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);
  const selectAllId = useId();
  const [currentPage, setCurrentPage] = useState(1);

  const localPageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const effectiveCurrentPage = Math.min(currentPage, localPageCount);
  const visibleItems = useMemo(() => {
    if (paginationMode !== 'paged') return items;
    const start = (effectiveCurrentPage - 1) * pageSize;
    return items.slice(start, start + pageSize);
  }, [effectiveCurrentPage, items, pageSize, paginationMode]);

  const selectedCount = visibleItems.filter((item) => selectedIds.has(item.id)).length;
  const allVisibleSelected = visibleItems.length > 0 && selectedCount === visibleItems.length;
  const someVisibleSelected = selectedCount > 0 && !allVisibleSelected;

  // 使用 IntersectionObserver 检测滚动到底部
  const handleObserver = useCallback(
    (entries: IntersectionObserverEntry[]) => {
      const target = entries[0];
      if (paginationMode === 'infinite' && target.isIntersecting && hasMore && !isLoading && !isLoadingMore) {
        const container = scrollContainerRef.current;
        if (container && container.scrollHeight > container.clientHeight) {
          onLoadMore();
        }
      }
    },
    [hasMore, isLoading, isLoadingMore, onLoadMore, paginationMode]
  );

  useEffect(() => {
    const trigger = loadMoreTriggerRef.current;
    const container = scrollContainerRef.current;
    if (!trigger || !container) return;

    const observer = new IntersectionObserver(handleObserver, {
      root: container,
      rootMargin: '20px',
      threshold: 0.1,
    });

    observer.observe(trigger);
    return () => observer.disconnect();
  }, [handleObserver]);

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  const handleToggleCurrentPage = useCallback(() => {
    for (const item of visibleItems) {
      if (allVisibleSelected || !selectedIds.has(item.id)) {
        onToggleItemSelection(item.id);
      }
    }
  }, [allVisibleSelected, onToggleItemSelection, selectedIds, visibleItems]);

  const handleNextPage = useCallback(async () => {
    if (effectiveCurrentPage < localPageCount) {
      setCurrentPage(effectiveCurrentPage + 1);
      return;
    }
    if (!hasMore || isLoadingMore) return;
    await onLoadMore();
    setCurrentPage(effectiveCurrentPage + 1);
  }, [effectiveCurrentPage, hasMore, isLoadingMore, localPageCount, onLoadMore]);

  return (
    <aside className={`glass-card overflow-hidden flex flex-col ${className}`}>
      <ScrollArea
        viewportRef={scrollContainerRef}
        viewportClassName="p-4"
        testId="home-history-list-scroll"
      >
        <div className="mb-4 space-y-3">
          <DashboardPanelHeader
            className="mb-1"
            title={title ?? t('history.defaultTitle')}
            titleClassName="text-sm font-medium"
            leading={(
              <svg className="h-4 w-4 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
            headingClassName="items-center"
            actions={
              selectedCount > 0 ? (
                <Badge variant="info" size="sm" className="history-selection-badge animate-in fade-in zoom-in duration-200">
                  {t('common.selectedCount', { count: selectedCount })}
                </Badge>
              ) : undefined
            }
          />

          {items.length > 0 && (
            <div className="flex items-center gap-2">
              <label
                className="flex flex-1 cursor-pointer items-center gap-2 rounded-lg px-2 py-1"
                htmlFor={selectAllId}
              >
                <input
                  id={selectAllId}
                  ref={selectAllRef}
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={paginationMode === 'paged' ? handleToggleCurrentPage : onToggleSelectAll}
                  disabled={isDeleting}
                  aria-label={t('history.selectAllHistoryAria')}
                  className="history-select-all-checkbox h-3.5 w-3.5 cursor-pointer bg-transparent accent-primary focus:ring-primary/30 disabled:opacity-50"
                />
                <span className="text-[11px] text-muted-text select-none">{t('common.selectAllCurrent')}</span>
              </label>
              <Button
                variant="danger-subtle"
                size="xsm"
                onClick={onDeleteSelected}
                disabled={selectedCount === 0 || isDeleting}
                isLoading={isDeleting}
                className="history-batch-delete-button disabled:!border-transparent disabled:!bg-transparent"
              >
                {isDeleting ? t('common.deleting') : t('common.delete')}
              </Button>
            </div>
          )}
        </div>

        {isLoading ? (
          <DashboardStateBlock
            loading
            compact
            title={t('history.loading')}
          />
        ) : items.length === 0 ? (
          <DashboardStateBlock
            title={emptyTitle ?? t('history.defaultEmptyTitle')}
            description={emptyDescription ?? t('history.defaultEmptyDescription')}
            icon={(
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            )}
          />
        ) : (
          <div className="space-y-2">
            {visibleItems.map((item) => (
              <HistoryListItem
                key={item.id}
                item={item}
                isViewing={selectedId === item.id}
                isChecked={selectedIds.has(item.id)}
                isDeleting={isDeleting}
                onToggleChecked={onToggleItemSelection}
                onClick={onItemClick}
              />
            ))}

            {paginationMode === 'infinite' ? <div ref={loadMoreTriggerRef} className="h-4" /> : null}

            {isLoadingMore && paginationMode === 'infinite' && (
              <div className="flex justify-center py-4">
                <div className="home-spinner h-5 w-5 animate-spin border-2" />
              </div>
            )}

            {!hasMore && items.length > 0 && paginationMode === 'infinite' && (
              <div className="text-center py-5">
                <div className="h-px bg-subtle w-full mb-3" />
                <span className="text-[10px] text-secondary-text uppercase tracking-[0.2em]">{t('history.bottomReached')}</span>
              </div>
            )}

          </div>
        )}
      </ScrollArea>

      {paginationMode === 'paged' && !isLoading && items.length > 0 ? (
        <div
          data-testid="history-pagination-footer"
          className="sticky bottom-0 z-10 flex shrink-0 items-center justify-between gap-3 border-t border-subtle bg-elevated/95 px-4 py-3 backdrop-blur"
        >
          <Button
            type="button"
            variant="ghost"
            size="xsm"
            disabled={effectiveCurrentPage === 1 || isLoadingMore}
            onClick={() => setCurrentPage(Math.max(1, effectiveCurrentPage - 1))}
          >
            {t('history.previousPage')}
          </Button>
          <span className="text-[11px] text-muted-text">
            {t('history.pageStatus', { page: effectiveCurrentPage })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="xsm"
            isLoading={isLoadingMore}
            disabled={(effectiveCurrentPage >= localPageCount && !hasMore) || isLoadingMore}
            onClick={() => void handleNextPage()}
          >
            {t('history.nextPage')}
          </Button>
        </div>
      ) : null}
    </aside>
  );
};
