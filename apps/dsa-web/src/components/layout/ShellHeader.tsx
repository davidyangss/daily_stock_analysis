import type React from 'react';
import { Menu } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey } from '../../i18n/uiText';
import { UiLanguageToggle } from '../i18n/UiLanguageToggle';
import { ThemeToggle } from '../theme/ThemeToggle';

type ShellHeaderProps = {
  onOpenNav: () => void;
};

const TITLES: Record<string, { title: UiTextKey; description: UiTextKey }> = {
  '/': { title: 'layout.route.home.title', description: 'layout.route.home.description' },
  '/chat': { title: 'layout.route.chat.title', description: 'layout.route.chat.description' },
  '/portfolio': { title: 'layout.route.portfolio.title', description: 'layout.route.portfolio.description' },
  '/decision-signals': { title: 'layout.route.decisionSignals.title', description: 'layout.route.decisionSignals.description' },
  '/trader-analysis': { title: 'layout.route.traderAnalysis.title', description: 'layout.route.traderAnalysis.description' },
  '/screening': { title: 'layout.route.screening.title', description: 'layout.route.screening.description' },
  '/backtest': { title: 'layout.route.backtest.title', description: 'layout.route.backtest.description' },
  '/alerts': { title: 'layout.route.alerts.title', description: 'layout.route.alerts.description' },
  '/usage': { title: 'layout.route.usage.title', description: 'layout.route.usage.description' },
  '/settings': { title: 'layout.route.settings.title', description: 'layout.route.settings.description' },
};

export const ShellHeader: React.FC<ShellHeaderProps> = ({ onOpenNav }) => {
  const location = useLocation();
  const { t } = useUiLanguage();
  const normalizedPath = location.pathname === '/'
    ? '/'
    : location.pathname.replace(/\/+$/, '');
  const current = TITLES[normalizedPath];

  return (
    <header className="sticky top-0 z-[80] border-b border-border/60 bg-background/92 backdrop-blur-xl">
      <div className="relative mx-auto flex h-14 w-full max-w-[1680px] items-center justify-between gap-3 px-3 sm:px-4 lg:px-5">
        <button
          type="button"
          onClick={onOpenNav}
          className="inline-flex h-10 w-10 items-center justify-center justify-self-start rounded-xl border border-border/70 bg-card/70 text-secondary-text transition-colors hover:bg-hover hover:text-foreground sm:w-auto sm:gap-2 sm:px-3"
          aria-label={t('layout.openNav')}
        >
          <Menu className="h-5 w-5" />
          <span className="hidden text-sm font-medium sm:inline">{t('layout.navMenu')}</span>
        </button>

        <h1
          data-testid="shell-current-title"
          className="pointer-events-none absolute inset-x-16 top-1/2 -translate-y-1/2 truncate text-center text-sm font-semibold text-secondary-text sm:inset-x-40 sm:text-base"
        >
          {current ? t(current.title) : t('layout.appFallbackTitle')}
        </h1>

        <div className="hidden items-center justify-self-end gap-2 sm:flex">
          <UiLanguageToggle />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
};
