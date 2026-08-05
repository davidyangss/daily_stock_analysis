import type { UiLanguage } from '../i18n/uiText';

export function formatStrategyNames(
  strategyNames: string[] | undefined,
  fallback: string,
  language: UiLanguage,
): string {
  const names = Array.from(new Set(
    (strategyNames || [])
      .map((name) => name.trim())
      .filter(Boolean),
  ));
  return names.length > 0 ? names.join(language === 'en' ? ', ' : '、') : fallback;
}
