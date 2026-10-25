import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import * as conditions from './i18n/conditions';
import * as evidence from './i18n/evidence';
import * as scenarios from './i18n/scenarios';
import * as shell from './i18n/shell';
import * as fabrics from './i18n/fabrics';
export type Language = 'en' | 'zh-TW';
export type TranslationValues = Record<string, string | number>;
type Entry = string | { en: string; 'zh-TW': string };
const dictionary: Record<string, Entry> = {};
function collect(value: unknown): void {
  if (!value || typeof value !== 'object') return;
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === 'string' || (entry && typeof entry === 'object' && 'en' in entry && 'zh-TW' in entry)) dictionary[key] = entry as Entry;
    else collect(entry);
  }
}
[conditions, evidence, scenarios, shell, fabrics].forEach(collect);
// State messages may have been produced before the language changed.
// Register reverse keys so those messages remain switchable without rewriting data.
for (const [source, entry] of Object.entries(dictionary)) {
  const localized = typeof entry === 'string' ? entry : entry['zh-TW'];
  if (localized && !dictionary[localized]) dictionary[localized] = {en: typeof entry === 'string' ? source : entry.en, 'zh-TW':localized};
}
export function translate(source: string, language: Language = 'en', values?: TranslationValues): string {
  if (!source) return '';
  const entry = dictionary[source];
  let result = typeof entry === 'string' ? (language === 'zh-TW' ? entry : source) : entry?.[language] ?? source;
  if (!entry) {
    for (const [pattern, candidate] of Object.entries(dictionary)) {
      if (!pattern.includes('{')) continue;
      const names: string[] = [];
      const escaped = pattern.split(/(\{[^}]+\})/g).map(part => {
        if (/^\{[^}]+\}$/.test(part)) { names.push(part.slice(1, -1)); return '(.*?)'; }
        return part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      }).join('');
      const matched = source.match(new RegExp(`^${escaped}$`));
      if (matched) {
        result = typeof candidate === 'string' ? (language === 'zh-TW' ? candidate : pattern) : candidate[language];
        values = { ...Object.fromEntries(names.map((name, i) => [name, matched[i + 1]])), ...values };
        break;
      }
    }
  }
  return result.replace(/\{([^}]+)\}/g, (placeholder, name: string) => values?.[name] === undefined ? placeholder : String(values[name]));
}
const STORAGE_KEY = 'urban-design-language';
const I18nContext = createContext<{ language: Language; setLanguage: (language: Language) => void }>({ language: 'en', setLanguage: () => {} });
export function I18nProvider({ children, language: controlledLanguage }: { children: React.ReactNode; language?: Language }) {
  const [language, updateLanguage] = useState<Language>(() => {
    if (controlledLanguage) return controlledLanguage;
    try { return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh-TW'; } catch { return 'zh-TW'; }
  });
  useEffect(() => {
    if (controlledLanguage) updateLanguage(controlledLanguage);
  }, [controlledLanguage]);
  const setLanguage = useCallback((next: Language) => {
    updateLanguage(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* Storage may be unavailable in private sessions. */ }
  }, []);
  return <I18nContext.Provider value={{ language, setLanguage }}>{children}</I18nContext.Provider>;
}
export const useI18n = () => useContext(I18nContext);
export function useT() {
  const { language } = useI18n();
  return useCallback((source: string, values?: TranslationValues) => translate(source, language, values), [language]);
}
