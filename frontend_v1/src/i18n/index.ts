/**
 * src/i18n/index.ts — i18n initialization with react-i18next.
 *
 * Auto-detects browser language, falls back to English.
 * Translations are inline (no HTTP fetch for small app).
 *
 * Usage in components:
 *   import { useTranslation } from 'react-i18next';
 *   const { t } = useTranslation();
 *   <span>{t('common.save')}</span>
 *
 * Change language:
 *   import i18n from './i18n';
 *   i18n.changeLanguage('pl');
 */
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

import enCommon from './locales/en/common.json';
import plCommon from './locales/pl/common.json';

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    fallbackLng: 'en',
    supportedLngs: ['en', 'pl'],
    defaultNS: 'common',
    resources: {
      en: { common: enCommon },
      pl: { common: plCommon },
    },
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: 'lang',
    },
  });

export default i18n;
