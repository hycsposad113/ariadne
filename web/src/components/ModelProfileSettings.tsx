import { useT } from '../i18n';
import React, { useEffect, useState } from 'react';

type ModelProfile = {
  id: string;
  provider: string;
  model: string;
  status: string;
  status_detail: string;
  enabled: boolean;
  active: boolean;
  supports_json_schema: boolean;
  egress: string;
};

type ModelProfilesStatus = {
  active_profile_id: string | null;
  weekly_call_limit: number;
  weekly_calls_used: number | null;
  live_dispatch_enabled: boolean;
  dispatch_block_reason: string | null;
  profiles: ModelProfile[];
};

interface ModelProfileSettingsProps {
  apiBase: string;
}

const STATUS_LABELS: Record<string, string> = {
  AVAILABLE: '可用',
  NOT_LOGGED_IN: '尚未登入',
  MISSING_KEY: '缺少 Keychain key',
  DISABLED: '停用',
  NOT_CONFIGURED: '尚未設定',
  JSON_SCHEMA_UNSUPPORTED: '不支援 JSON Schema',
  OVER_BUDGET: '超出預算',
  BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED: '尚未授權 Live AI',
  BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE: 'ModelRun 記帳尚未接線',
  CLI_NOT_INSTALLED: 'CLI 未安裝',
  HERMES_NOT_CONFIGURED: 'Hermes profile 未設定',
  HERMES_TOOLSET_CHECK_REQUIRED: '需檢查 Hermes 工具狀態',
};

const dispatchMessage = (reason: string | null): string => {
  if (reason === 'BLOCKED_MODEL_RUN_ACCOUNTING_UNAVAILABLE') {
    return '目前只保存偏好，尚不啟動模型呼叫；耐久 ModelRun 記帳接線完成前，Live AI 維持封鎖。';
  }
  if (reason === 'BLOCKED_PROJECT_AI_AUTHORIZATION_REQUIRED') {
    return '目前只保存偏好，尚不啟動模型呼叫；Live AI 仍需要專案層級授權。';
  }
  return '目前只保存偏好，尚不啟動模型呼叫。';
};

export const ModelProfileSettings: React.FC<ModelProfileSettingsProps> = ({ apiBase }) => {
  const t = useT();
  const [status, setStatus] = useState<ModelProfilesStatus | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`${apiBase}/api/v1/model-profiles/status`)
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json() as Promise<ModelProfilesStatus>;
      })
      .then((data) => {
        if (!active) return;
        setStatus(data);
        setSelectedProfileId(data.active_profile_id || '');
        setError(null);
      })
      .catch(() => {
        if (active) setError('無法讀取模型 profile 狀態。');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [apiBase]);

  const saveSelection = async () => {
    if (!selectedProfileId) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(`${apiBase}/api/v1/model-profiles/active`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_id: selectedProfileId }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json() as ModelProfilesStatus;
      setStatus(data);
      setSelectedProfileId(data.active_profile_id || '');
      setMessage('profile 選擇已保存。');
    } catch {
      setError('無法保存 profile 選擇。');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section aria-label={t("AI 模型設定")} style={{ padding: 14, overflowY: 'auto', height: '100%', color: 'var(--text-main)' }}>
      <h2 style={{ margin: '0 0 8px', fontSize: 14 }}>{t("AI 模型設定")}</h2>
      <p style={{ margin: '0 0 12px', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
        {t("不會顯示或輸入任何 key。Keychain 狀態只確認服務項目存在，不會讀取 key 值。profile 選擇會保存於本機 runtime 設定，重啟 API 後仍保留。")} </p>

      {loading && <p role="status">{t("正在讀取 profile 狀態…")}</p>}
      {error && <p role="alert" style={{ color: 'var(--accent-amber)' }}>{t(error)}</p>}
      {status && (
        <>
          <p role="status" style={{ margin: '0 0 10px', fontSize: 11 }}>
            {t("Ariadne 目前使用：{profile}", { profile: status.active_profile_id || t('未設定') })}
          </p>
          <label htmlFor="active-model-profile" style={{ display: 'block', marginBottom: 5, fontSize: 11 }}>
            {t("使用中的 profile")} </label>
          <select
            id="active-model-profile"
            aria-label={t("使用中的 profile")}
            value={selectedProfileId}
            onChange={(event) => setSelectedProfileId(event.target.value)}
            style={{ width: '100%', marginBottom: 8, padding: 7, background: 'var(--bg-app)', color: 'var(--text-main)', border: '1px solid var(--border-subtle)', borderRadius: 4 }}
          >
            <option value="">{t("請選擇 profile")}</option>
            {status.profiles.map((profile) => (
              <option key={profile.id} value={profile.id} disabled={!profile.enabled || !profile.supports_json_schema || profile.status === 'NOT_LOGGED_IN'}>
                {profile.id}{profile.active ? t(" · 目前選用") : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={saveSelection}
            disabled={!selectedProfileId || saving || loading}
            style={{ width: '100%', padding: 7, marginBottom: 12 }}
          >
            {saving ? t("保存中…") : t("儲存 profile")}
          </button>

          <ul aria-label={t("模型 profile 狀態")} style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            {status.profiles.map((profile) => (
              <li key={profile.id} style={{ padding: '9px 0', borderTop: '1px solid var(--border-subtle)', fontSize: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                  <strong>{profile.id}</strong>
                  <span>{t(STATUS_LABELS[profile.status] || profile.status)}</span>
                </div>
                <div style={{ color: 'var(--text-muted)', marginTop: 3 }}>
                  {profile.provider}{profile.model ? ` · ${profile.model}` : ''} · {t(profile.egress)}
                </div>
                {profile.status_detail && (
                  <div style={{ color: 'var(--text-muted)', marginTop: 3 }}>{t(profile.status_detail)}</div>
                )}
              </li>
            ))}
          </ul>

          <p style={{ margin: '12px 0 4px', fontSize: 11 }}>
            {t("本週呼叫：")}{status.weekly_calls_used ?? t("無法確認")} / {status.weekly_call_limit}
          </p>
          <p role="note" style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
            {t(dispatchMessage(status.dispatch_block_reason))}
          </p>
        </>
      )}
      {message && <p role="status" style={{ fontSize: 11 }}>{t(message)}</p>}
    </section>
  );
};
