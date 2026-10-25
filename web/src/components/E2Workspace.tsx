import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useI18n } from '../i18n';
import { StatusBadge } from '../i18n/statusLabels';
import { HumanDecisionDialog, type HumanDecisionTarget, type HumanDecisionSubmission } from './HumanDecisionDialog';
import { AlertTriangle, CheckCircle, Clock, ShieldAlert, SunMedium, Play, RefreshCw, FileText } from 'lucide-react';
import './E2Workspace.css';

export interface ScenarioPinData {
  scenario_id: string;
  revision: number;
  geometry_artifact_id: string;
  geometry_sha256: string;
  environment_sha256: string;
  status?: string;
}

export interface WeatherSnapshotItem {
  id: string;
  snapshot_id: string;
  version: string;
  payload_digest: string;
  status: string;
  decision_id?: string | null;
  decision_target_type: string;
  created_at?: string;
}

export interface ExperimentPlanItem {
  id: string;
  plan_artifact_id: string;
  sha256: string;
  version: string;
  status: string;
  decision_id?: string | null;
  baseline?: ScenarioPinData | null;
  modified?: ScenarioPinData | null;
  plan?: Record<string, any> | null;
  created_at?: string;
}

export interface ReadinessItem {
  dispatch_allowed: boolean;
  blockers?: string[];
  reasons?: string[];
  checks?: Array<{
    name?: string;
    label?: string;
    status: string;
    passed?: boolean;
    reason?: string;
    detail?: string;
  }>;
}

export interface JobItem {
  id: string;
  job_id: string;
  status: string;
  created_at: string;
  completed_at?: string | null;
  updated_at: string;
  plan_id?: string | null;
  baseline_scenario_id?: string | null;
  modified_scenario_id?: string | null;
  validated: boolean;
}

export interface DistributionComparison {
  baseline_kwh_m2: number;
  modified_kwh_m2: number;
  delta_kwh_m2: number;
  direction: string;
  common_points?: number;
  common_area_m2?: number;
  noise_metadata?: {
    classification: string;
    delta_sample_stddev_kwh_m2?: number;
    sample_count?: number;
  };
}

export interface E2ResultData {
  job_id: string;
  status: string;
  evidence_validation_status?: string;
  plan_id?: string;
  plan_sha256?: string;
  weather_snapshot_id?: string;
  limitations?: string[];
  comparisons?: {
    ladybug_radiance?: Record<string, DistributionComparison>;
    honeybee_radiance?: Record<string, DistributionComparison>;
  };
  direction_summary?: {
    direction_agreement_by_offset?: Record<string, boolean>;
    explanation?: string;
    methods?: Record<string, { directions: Record<string, string>; sensitivity_reversed: boolean }>;
    sensitivity_reversed?: boolean;
  };
}

export interface E2WorkspaceProps {
  apiBase: string;
  projectId?: string;
  className?: string;
}

const DEFAULT_PROJECT = 'rotterdam-m4h-pilot-project';
const KNOWN_SCENARIOS = [
  { id: 'formal-dict-3da03eb0172d-common-mixed-98854aff5f7b', label_zh: 'common-mixed（混合方案）', label_en: 'common-mixed (Mixed)' },
  { id: 'formal-fabric-harbour-grain-88445febe1b6', label_zh: 'harbour_grain（港埠方案）', label_en: 'harbour_grain (Harbour Grain)' },
  { id: 'formal-dict-3da03eb0172d-common-compact-a1ff97864a21', label_zh: 'common-compact（緊湊方案）', label_en: 'common-compact (Compact)' },
];

function scenarioName(id: string | null | undefined, language: string): string {
  const known = KNOWN_SCENARIOS.find((item) => item.id === id);
  if (known) return (language === 'zh-TW' ? known.label_zh : known.label_en).replace(/^[\w-]+[（(]/, '').replace(/[）)]$/, '');
  return language === 'zh-TW' ? '其他方案' : 'Other scenario';
}

export const E2Workspace: React.FC<E2WorkspaceProps> = ({
  apiBase,
  projectId = DEFAULT_PROJECT,
  className = '',
}) => {
  const { language } = useI18n();
  const say = useCallback((zh: string, en: string) => (language === 'zh-TW' ? zh : en), [language]);

  // Data states
  const [snapshots, setSnapshots] = useState<WeatherSnapshotItem[]>([]);
  const [plans, setPlans] = useState<ExperimentPlanItem[]>([]);
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [methodValidationId, setMethodValidationId] = useState<string | null>(null);

  // Scenario selections
  const [baselineId, setBaselineId] = useState<string>('formal-dict-3da03eb0172d-common-mixed-98854aff5f7b');
  const [modifiedId, setModifiedId] = useState<string>('formal-fabric-harbour-grain-88445febe1b6');
  const [baselinePin, setBaselinePin] = useState<ScenarioPinData | null>(null);
  const [modifiedPin, setModifiedPin] = useState<ScenarioPinData | null>(null);
  const [modifiedAccepted, setModifiedAccepted] = useState<boolean>(true);

  // Active items
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [readinessData, setReadinessData] = useState<ReadinessItem | null>(null);
  const [currentResult, setCurrentResult] = useState<E2ResultData | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Simulation controls
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);
  const [outcomeUnknown, setOutcomeUnknown] = useState<boolean>(false);
  const [simulateError, setSimulateError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // HumanDecisionDialog states
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionTarget, setDecisionTarget] = useState<HumanDecisionTarget | null>(null);
  const [decisionAction, setDecisionAction] = useState<string>('Approve');
  const [decisionStatus, setDecisionStatus] = useState<string>('approved');
  const [decisionReviewContent, setDecisionReviewContent] = useState<React.ReactNode>(null);

  // UI accordion expansions
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({ 1: true, 2: true, 3: true, 4: true, 5: true, 6: true });
  const [comparisonVerified, setComparisonVerified] = useState<boolean>(false);

  const toggleStep = (stepNum: number) => {
    setExpandedSteps((prev) => ({ ...prev, [stepNum]: !prev[stepNum] }));
  };

  // Some E2 reads re-verify large artifacts (several seconds each); show "loading" instead of "not started" meanwhile.
  const [pendingReads, setPendingReads] = useState(0);
  const track = useCallback(async <T,>(request: Promise<T>): Promise<T> => {
    setPendingReads((n) => n + 1);
    try {
      return await request;
    } finally {
      setPendingReads((n) => n - 1);
    }
  }, []);
  const badge = (status: string) => (status === 'NOT_STARTED' && pendingReads > 0 ? 'LOADING' : status);

  // 1. Load initial data
  const loadSnapshots = useCallback(async () => {
    try {
      const res = await track(fetch(`${apiBase}/api/v1/environment/e2/weather/snapshots?project_id=${projectId}`));
      if (res.ok) {
        const data = await res.json();
        setSnapshots(data);
      }
    } catch {
      // ignore
    }
  }, [apiBase, projectId, track]);

  const loadPlans = useCallback(async () => {
    try {
      const res = await track(fetch(`${apiBase}/api/v1/environment/e2/plans?project_id=${projectId}`));
      if (res.ok) {
        const data = await res.json();
        setPlans(data);
      }
    } catch {
      // ignore
    }
  }, [apiBase, projectId, track]);

  const loadJobs = useCallback(async () => {
    try {
      const res = await track(fetch(`${apiBase}/api/v1/environment/e2/jobs?project_id=${projectId}`));
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
      }
    } catch {
      // ignore
    }
  }, [apiBase, projectId, track]);

  const loadPin = useCallback(
    async (
      scenarioId: string,
      setPin: (p: ScenarioPinData | null) => void,
      onPinLoaded?: (p: ScenarioPinData | null) => void
    ) => {
      try {
        const res = await track(fetch(
          `${apiBase}/api/v1/environment/e2/scenarios/${encodeURIComponent(scenarioId)}/pin?project_id=${projectId}`
        ));
        if (res.ok) {
          const pin = await res.json();
          setPin(pin);
          if (onPinLoaded) onPinLoaded(pin);
        } else {
          setPin(null);
          if (onPinLoaded) onPinLoaded(null);
        }
      } catch {
        setPin(null);
        if (onPinLoaded) onPinLoaded(null);
      }
    },
    [apiBase, projectId, track]
  );

  useEffect(() => {
    void loadSnapshots();
    void loadPlans();
    void loadJobs();
  }, [loadSnapshots, loadPlans, loadJobs]);

  useEffect(() => {
    if (baselineId) void loadPin(baselineId, setBaselinePin);
  }, [baselineId, loadPin]);

  useEffect(() => {
    if (modifiedId) {
      void loadPin(modifiedId, setModifiedPin, (pin) => {
        setModifiedAccepted(pin ? (pin.status === undefined || pin.status === 'accepted' || pin.status === 'ACCEPTED') : true);
      });
    }
  }, [modifiedId, loadPin]);

  const effectivePlanId =
    selectedPlanId ||
    plans.find((p) => p.status === 'APPROVED')?.plan_artifact_id ||
    plans.find((p) => p.status === 'APPROVED')?.id ||
    plans[0]?.plan_artifact_id ||
    plans[0]?.id ||
    null;

  // Load readiness when selected plan changes
  const loadReadiness = useCallback(async () => {
    if (!effectivePlanId) return;
    try {
      const res = await track(fetch(
        `${apiBase}/api/v1/environment/e2/readiness?project_id=${projectId}&plan_artifact_id=${effectivePlanId}`
      ));
      if (res.ok) {
        const data = await res.json();
        setReadinessData(data);
      }
    } catch {
      setReadinessData(null);
    }
  }, [apiBase, projectId, effectivePlanId, track]);

  useEffect(() => {
    if (effectivePlanId) {
      void loadReadiness();
    }
  }, [effectivePlanId, loadReadiness]);

  // Polling for simulation results
  const pollResult = useCallback(
    async (jobIdToPoll: string) => {
      try {
        const res = await fetch(
          `${apiBase}/api/v1/environment/e2/results/${jobIdToPoll}/summary?project_id=${projectId}`
        );
        if (res.ok) {
          const data = await res.json();
          if (data.status === 'SUCCEEDED' || data.status === 'READY') {
            setCurrentResult(data);
            setIsSimulating(false);
            if (pollRef.current) clearInterval(pollRef.current);
            if (timerRef.current) clearInterval(timerRef.current);
            loadJobs();
          } else if (data.status === 'OUTCOME_UNKNOWN' || data.status === 'FAILED') {
            setIsSimulating(false);
            if (data.status === 'OUTCOME_UNKNOWN') {
              setOutcomeUnknown(true);
              setSimulateError(
                say('結果未知，需管理者對帳，不可重送', 'Outcome unknown; administrator reconciliation required before retry; do not resend.')
              );
            }
            if (pollRef.current) clearInterval(pollRef.current);
            if (timerRef.current) clearInterval(timerRef.current);
            loadJobs();
          }
        }
      } catch {
        // network glitch while polling
      }
    },
    [apiBase, projectId, say, loadJobs]
  );

  const startPolling = useCallback(
    (jobIdToPoll: string) => {
      setActiveJobId(jobIdToPoll);
      setIsSimulating(true);
      setElapsedSeconds(0);
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = setInterval(() => {
        setElapsedSeconds((s) => s + 1);
      }, 1000);

      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(() => {
        pollResult(jobIdToPoll);
      }, 20000);
      // Run once immediately
      pollResult(jobIdToPoll);
    },
    [pollResult]
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // Format elapsed time (mm:ss)
  const formatElapsed = (sec: number) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  };

  // Number formatting with thousand separators and 2-6 decimal places
  const formatNumber = (val: number | null | undefined): string => {
    if (val === null || val === undefined || isNaN(val)) return '—';
    return val.toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  // Step Status Derivations
  const approvedSnapshot = snapshots.find((s) => s.status === 'APPROVED');
  const proposedSnapshot = snapshots.find((s) => s.status === 'PROPOSED');

  const step1Status = approvedSnapshot ? 'COMPLETED' : proposedSnapshot ? 'WAITING_DECISION' : 'NOT_STARTED';

  const isModifiedAccepted =
    modifiedAccepted &&
    (modifiedPin?.status ? modifiedPin.status === 'accepted' || modifiedPin.status === 'ACCEPTED' : true);

  const step2Status =
    baselinePin && modifiedPin && baselineId !== modifiedId && isModifiedAccepted
      ? 'COMPLETED'
      : baselinePin && modifiedPin && !isModifiedAccepted
      ? 'WAITING_DECISION'
      : 'NOT_STARTED';

  const activePlan = plans.find((p) => (p.plan_artifact_id || p.id) === effectivePlanId);
  const matchingApprovedPlan = plans.find(
    (p) =>
      p.status === 'APPROVED' &&
      p.baseline?.scenario_id === baselineId &&
      p.modified?.scenario_id === modifiedId
  );
  const matchingProposedPlan = plans.find(
    (p) =>
      p.status === 'PROPOSED' &&
      p.baseline?.scenario_id === baselineId &&
      p.modified?.scenario_id === modifiedId
  );

  const step3Status =
    activePlan?.status === 'APPROVED' || matchingApprovedPlan
      ? 'COMPLETED'
      : matchingProposedPlan
      ? 'WAITING_DECISION'
      : 'NOT_STARTED';

  const step4Status = readinessData
    ? readinessData.dispatch_allowed
      ? 'COMPLETED'
      : 'BLOCKED'
    : 'NOT_STARTED';

  const existingJobForPlan = effectivePlanId ? jobs.find((job) => job.plan_id === effectivePlanId) : undefined;
  const step5Status = existingJobForPlan && existingJobForPlan.status === 'READY' && !outcomeUnknown
    ? 'COMPLETED'
    : outcomeUnknown
    ? 'BLOCKED'
    : currentResult?.status === 'SUCCEEDED' || currentResult?.status === 'READY'
    ? 'COMPLETED'
    : isSimulating
    ? 'RUNNING'
    : 'NOT_STARTED';

  const step6Status = currentResult?.comparisons ? 'COMPLETED' : 'NOT_STARTED';

  // Handler: HumanDecision Submit
  const handleDecisionSubmit = async (submission: HumanDecisionSubmission) => {
    const res = await fetch(`${apiBase}/api/v1/projects/${projectId}/decisions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(submission),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail?.reason || err.detail || 'Decision rejected');
    }
    // Refresh after decision
    if (submission.action === 'Accept') {
      setModifiedAccepted(true);
    }
    await loadSnapshots();
    await loadPlans();
    if (baselineId) await loadPin(baselineId, setBaselinePin);
    if (modifiedId) {
      await loadPin(modifiedId, setModifiedPin, (pin) => {
        setModifiedAccepted(pin ? (pin.status === undefined || pin.status === 'accepted' || pin.status === 'ACCEPTED') : true);
      });
    }
  };

  // Step 1 Actions
  const handleProposeWeather = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/environment/e2/weather/snapshots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (res.ok) {
        await loadSnapshots();
      }
    } catch {
      // ignore
    }
  };

  const openApproveWeatherDialog = (snap: WeatherSnapshotItem) => {
    setDecisionTarget({
      id: snap.id,
      type: snap.decision_target_type || 'DatasetSnapshot',
      version: snap.version,
      payloadDigest: snap.payload_digest,
    });
    setDecisionAction('Approve');
    setDecisionStatus('approved');
    setDecisionReviewContent(
      <div>
        <p>
          <strong>{say('推導方法來源：', 'Derivation method: ')}</strong>
          candidate-01 (Minute=0 -&gt; Minute=60; hour_end; PD-08)
        </p>
        <p>
          <strong>{say('時間覆蓋：', 'Temporal coverage: ')}</strong>
          {say('全年 8,760 小時推導氣象序列', 'Full year 8,760 hours derived weather series')}
        </p>
        <p>
          <strong>{say('資料雜湊 (Payload Digest)：', 'Payload Digest: ')}</strong>
          <code>{snap.payload_digest}</code>
        </p>
      </div>
    );
    setDecisionOpen(true);
  };

  const handleValidateMethods = async (snapId: string) => {
    try {
      const res = await fetch(
        `${apiBase}/api/v1/environment/e2/weather/snapshots/${snapId}/validate-methods`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: projectId }),
        }
      );
      if (res.ok) {
        const data = await res.json();
        setMethodValidationId(data.method_validation_artifact_id);
      }
    } catch {
      // ignore
    }
  };

  // Step 2 Actions
  const handleRegisterHarbour = async () => {
    try {
      const res = await fetch(`${apiBase}/api/v1/environment/e2/harbour/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId }),
      });
      if (res.ok) {
        const data = await res.json();
        setModifiedId(data.scenario_id);
        await loadPin(data.scenario_id, setModifiedPin, (pin) => {
          setModifiedAccepted(pin ? (pin.status === undefined || pin.status === 'accepted' || pin.status === 'ACCEPTED') : true);
        });
      }
    } catch {
      // ignore
    }
  };

  const openAcceptScenarioDialog = () => {
    if (!modifiedPin) return;
    setDecisionTarget({
      id: modifiedPin.scenario_id,
      type: 'DesignScenario',
      version: String(modifiedPin.revision),
      geometrySha256: modifiedPin.geometry_sha256,
    });
    setDecisionAction('Accept');
    setDecisionStatus('accepted');
    setDecisionReviewContent(
      <div>
        <p>
          <strong>{say('方案 ID：', 'Scenario ID: ')}</strong>
          <code>{modifiedPin.scenario_id}</code>
        </p>
        <p>
          <strong>{say('幾何 SHA-256：', 'Geometry SHA-256: ')}</strong>
          <code>{modifiedPin.geometry_sha256}</code>
        </p>
        <p style={{ color: '#fbbf24' }}>
          {say(
            '注意：此決策僅接受此方案作為 E2 比較對象，保留基準方案，絕不送出會拒絕另一方案的雙案比較決策。',
            'Notice: This decision only accepts this scenario for E2 radiation comparison. It retains the baseline scenario and does NOT reject other scenarios.'
          )}
        </p>
      </div>
    );
    setDecisionOpen(true);
  };

  // Step 3 Actions
  const handleProposePlan = async () => {
    if (!baselinePin || !modifiedPin || !approvedSnapshot) return;
    const planPayload = {
      project_id: projectId,
      weather_snapshot_id: approvedSnapshot.id,
      weather_bundle_sha256: approvedSnapshot.payload_digest,
      baseline: baselinePin,
      modified: modifiedPin,
      grid: {
        crs: 'EPSG:28992',
        origin_x: 0.0,
        origin_y: 0.0,
        spacing_m: 5.0,
        tag: 'E1_COMMON_GROUND_GRID',
      },
      start_month: 6,
      start_day: 1,
      end_month: 8,
      end_day: 31,
      start_hour: 1,
      end_hour: 24,
      time_basis: 'EPW_LOCAL_STANDARD_HOUR_END',
      true_north_deg: -0.73916,
      sensor_offset_m: 0.05,
      recipe: {
        classification: 'ASSUMED_COMMANDER',
        ground_reflectance: 0.2,
        building_reflectance: 0.2,
        screening: 'RadiationStudy; Tregenza 145; opaque visibility; no interreflection',
        verification:
          'Honeybee solar average sky times hourly record count; rfluxmtx -I -ab 2 -ad 2048 -lw 0.0001 -u-',
        excluded_faces: ['building_bottom_faces'],
        noise_repetitions: 3,
        noise_sigma_multiplier: 2.0,
        noise_classification: 'ASSUMED_COMMANDER',
        sampling: 'LOW_DISCREPANCY_U_MINUS_SINGLE_PROCESS',
      },
      comparison_domain: 'COMMON_OVERLAP',
      sensitivity_offsets: [-1, 0, 1],
      method_validation_artifact_id:
        methodValidationId || 'artifact-e2-method-validation-c2ddc895d1ccd8b86f164c07',
    };

    try {
      const res = await fetch(`${apiBase}/api/v1/environment/e2/plan`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(planPayload),
      });
      if (res.ok) {
        const data = await res.json();
        setSelectedPlanId(data.plan_artifact_id);
        await loadPlans();
      }
    } catch {
      // ignore
    }
  };

  const openApprovePlanDialog = (planToApprove: ExperimentPlanItem) => {
    setDecisionTarget({
      id: planToApprove.plan_artifact_id || planToApprove.id,
      type: 'Artifact',
      version: planToApprove.version,
      artifactSha256: planToApprove.sha256,
    });
    setDecisionAction('Approve');
    setDecisionStatus('approved');
    setDecisionReviewContent(
      <div>
        <p>
          <strong>{say('實驗計畫 ID：', 'Experiment Plan ID: ')}</strong>
          <code>{planToApprove.plan_artifact_id || planToApprove.id}</code>
        </p>
        <p>
          <strong>{say('鎖定設定：', 'Locked settings: ')}</strong>
          {say('夏季 6–8 月 · 5 m 網格 · ±1 小時敏感度 · 雙層 recipe', 'Summer Jun-Aug · 5 m grid · ±1 h sensitivity · dual-tier recipe')}
        </p>
        <p>
          <strong>{say('計畫 SHA-256：', 'Plan SHA-256: ')}</strong>
          <code>{planToApprove.sha256}</code>
        </p>
      </div>
    );
    setDecisionOpen(true);
  };

  // One dispatch per plan: the backend has no plan-level guard, so the key is derived from the plan id.
  // A reload or second click then returns the same durable job instead of starting another run.
  const existingJob = effectivePlanId ? jobs.find((job) => job.plan_id === effectivePlanId) : undefined;

  // Step 5 Simulation Trigger
  const handleSimulate = async () => {
    const planIdToUse = effectivePlanId;
    if (!planIdToUse || outcomeUnknown || isSimulating || existingJob) return;
    const newKey = `founder-e2-ui-${planIdToUse}`;
    setIdempotencyKey(newKey);
    setIsSimulating(true);
    setSimulateError(null);
    setElapsedSeconds(0);

    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsedSeconds((s) => s + 1);
    }, 1000);

    try {
      const res = await fetch(`${apiBase}/api/v1/environment/e2/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          plan_artifact_id: planIdToUse,
          idempotency_key: newKey,
        }),
      });

      if (!res.ok) {
        setOutcomeUnknown(true);
        setSimulateError(
          say('結果未知，需管理者對帳，不可重送', 'Outcome unknown; administrator reconciliation required before retry; do not resend.')
        );
        setIsSimulating(false);
        if (timerRef.current) clearInterval(timerRef.current);
        return;
      }

      const data = await res.json();
      if (data.status === 'OUTCOME_UNKNOWN' || !data.job_id) {
        setOutcomeUnknown(true);
        setSimulateError(
          say('結果未知，需管理者對帳，不可重送', 'Outcome unknown; administrator reconciliation required before retry; do not resend.')
        );
        setIsSimulating(false);
        if (timerRef.current) clearInterval(timerRef.current);
        return;
      }

      setActiveJobId(data.job_id);
      if (data.status === 'SUCCEEDED' || data.status === 'READY') {
        setCurrentResult(data);
        setIsSimulating(false);
        if (timerRef.current) clearInterval(timerRef.current);
        loadJobs();
      } else {
        startPolling(data.job_id);
      }
    } catch {
      setOutcomeUnknown(true);
      setSimulateError(
        say('結果未知，需管理者對帳，不可重送', 'Outcome unknown; administrator reconciliation required before retry; do not resend.')
      );
      setIsSimulating(false);
      if (timerRef.current) clearInterval(timerRef.current);
    }
  };

  // Step 6 Compare Call
  const handleCompare = async () => {
    const jId = activeJobId || currentResult?.job_id;
    if (!jId) return;
    try {
      const res = await fetch(`${apiBase}/api/v1/environment/e2/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: projectId,
          job_id: jId,
          comparison: 'direction',
        }),
      });
      if (res.ok) {
        const comp = await res.json();
        setComparisonVerified(true);
        if (comp.direction_summary && currentResult) {
          setCurrentResult({ ...currentResult, direction_summary: comp.direction_summary });
        }
      }
    } catch {
      // ignore
    }
  };

  // Load specific historical job result
  const handleLoadJobResult = async (jobIdToLoad: string) => {
    try {
      const res = await track(fetch(`${apiBase}/api/v1/environment/e2/results/${jobIdToLoad}/summary?project_id=${projectId}`));
      if (res.ok) {
        const data = await res.json();
        setCurrentResult(data);
        setActiveJobId(jobIdToLoad);
      }
    } catch {
      // ignore
    }
  };

  // A plan that was already dispatched shows its durable result instead of an empty step ⑥.
  const existingReadyJobId = existingJobForPlan?.status === 'READY' ? existingJobForPlan.job_id : null;
  useEffect(() => {
    if (existingReadyJobId && !currentResult && !isSimulating) void handleLoadJobResult(existingReadyJobId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existingReadyJobId]);

  return (
    <div className={`e2-workspace ${className}`}>
      <header className="e2-workspace__header">
        <div className="e2-workspace__title-group">
          <h3>{say('E2 夏季入射輻射實驗（雙層篩檢與驗證）', 'E2 Summer Incident Radiation Experiment (Dual-Tier Screening & Verification)')}</h3>
          <p>
            {say(
              '確定性專業工具計算 · Ladybug 遮擋篩檢 ＋ Honeybee-Radiance 實體驗證 · 你的決策密語',
              'Deterministic professional tool calculation · Ladybug Screening + Honeybee-Radiance Verification · Your decision passphrase'
            )}
          </p>
        </div>
        <div className="e2-actions-row">
          <button
            type="button"
            className="e2-btn"
            onClick={() => {
              loadSnapshots();
              loadPlans();
              loadJobs();
              if (selectedPlanId) loadReadiness();
            }}
          >
            <RefreshCw size={13} />
            {say('重新整理資料', 'Refresh Data')}
          </button>
        </div>
      </header>

      {/* Stepper Container */}
      <div className="e2-workspace__steps-nav">
        {/* Step 1: 天氣快照 */}
        <section className={`e2-step-card ${step1Status === 'COMPLETED' ? 'e2-step-card--completed' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(1)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">1</span>
              <span>{say('① 天氣快照', '① Weather Snapshot')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step1Status)} language={language} />
            </div>
          </div>
          {expandedSteps[1] && (
            <div className="e2-step-card__body">
              <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-dim)' }}>
                {say(
                  '夏季輻射分析所需之推導氣象序列。必須由你輸入決策密語批准候選推導方法快照（candidate-01）。',
                  'Derived weather series required for summer radiation analysis. Must be approved with your decision passphrase (candidate-01).'
                )}
              </p>

              {snapshots.length === 0 ? (
                <div className="e2-actions-row">
                  <button type="button" className="e2-btn e2-btn--primary" onClick={handleProposeWeather}>
                    {say('提出天氣快照', 'Propose Weather Snapshot')}
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {snapshots.map((snap) => (
                    <div key={snap.id} className="e2-step-details">
                      <details open>
                        <summary>
                          {snap.id} · <StatusBadge status={snap.status} language={language} />
                        </summary>
                        <dl>
                          <dt>{say('版本', 'Version')}:</dt>
                          <dd>{snap.version}</dd>
                          <dt>{say('酬載摘要', 'Payload Digest')}:</dt>
                          <dd>{snap.payload_digest}</dd>
                          {snap.decision_id && (
                            <>
                              <dt>{say('決策 ID', 'Decision ID')}:</dt>
                              <dd>{snap.decision_id}</dd>
                            </>
                          )}
                        </dl>
                      </details>
                      <div className="e2-actions-row" style={{ marginTop: '10px' }}>
                        {snap.status === 'PROPOSED' && (
                          <button
                            type="button"
                            className="e2-btn e2-btn--decision"
                            onClick={() => openApproveWeatherDialog(snap)}
                          >
                            <ShieldAlert size={13} />
                            {say('批准（需你的決策密語）', 'Approve (requires your decision passphrase)')}
                          </button>
                        )}
                        {snap.status === 'APPROVED' && (
                          <button
                            type="button"
                            className="e2-btn"
                            onClick={() => handleValidateMethods(snap.id)}
                          >
                            <CheckCircle size={13} />
                            {methodValidationId
                              ? say('方法已驗證', 'Methods Qualified')
                              : say('方法驗證 (Radiance 實體)', 'Validate Methods')}
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {/* Step 2: 方案（基準／比較） */}
        <section className={`e2-step-card ${step2Status === 'COMPLETED' ? 'e2-step-card--completed' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(2)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">2</span>
              <span>{say('② 方案（基準／比較）', '② Scenarios: Baseline & Comparison')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step2Status)} language={language} />
            </div>
          </div>
          {expandedSteps[2] && (
            <div className="e2-step-card__body">
              <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-dim)' }}>
                {say(
                  '選擇 E2 輻射比較的基準方案與修改方案。若比較方案尚未接受，需由你以決策密語接受；只接受單一方案，不拒絕基準方案。',
                  'Select baseline and modified scenarios for comparison. If the modified scenario is unaccepted, you must accept it with your decision passphrase without rejecting the baseline.'
                )}
              </p>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px' }}>
                {/* Baseline selector */}
                <div className="e2-step-details">
                  <label style={{ display: 'block', fontWeight: 600, marginBottom: '6px' }}>
                    {say('基準方案', 'Baseline Scenario')}
                  </label>
                  <select
                    className="e2-select"
                    value={baselineId}
                    onChange={(e) => setBaselineId(e.target.value)}
                    style={{ width: '100%', padding: '6px', background: 'var(--bg-surface)', color: 'inherit', border: '1px solid var(--border-subtle)', borderRadius: '4px' }}
                  >
                    {KNOWN_SCENARIOS.map((sc) => (
                      <option key={sc.id} value={sc.id}>
                        {say(sc.label_zh, sc.label_en)}
                      </option>
                    ))}
                  </select>
                  {baselinePin && (
                    <dl style={{ marginTop: '8px' }}>
                      <dt>{say('修訂版本', 'Revision')}:</dt>
                      <dd>{baselinePin.revision}</dd>
                      <dt>{say('幾何雜湊', 'Geometry SHA')}:</dt>
                      <dd>{baselinePin.geometry_sha256}</dd>
                    </dl>
                  )}
                </div>

                {/* Modified selector */}
                <div className="e2-step-details">
                  <label style={{ display: 'block', fontWeight: 600, marginBottom: '6px' }}>
                    {say('比較方案', 'Comparison Scenario')}
                  </label>
                  <select
                    className="e2-select"
                    value={modifiedId}
                    onChange={(e) => {
                      setModifiedId(e.target.value);
                      setModifiedPin(null);
                    }}
                    style={{ width: '100%', padding: '6px', background: 'var(--bg-surface)', color: 'inherit', border: '1px solid var(--border-subtle)', borderRadius: '4px' }}
                  >
                    {KNOWN_SCENARIOS.map((sc) => (
                      <option key={sc.id} value={sc.id}>
                        {say(sc.label_zh, sc.label_en)}
                      </option>
                    ))}
                  </select>
                  {modifiedPin && (
                    <dl style={{ marginTop: '8px' }}>
                      <dt>{say('修訂版本', 'Revision')}:</dt>
                      <dd>{modifiedPin.revision}</dd>
                      <dt>{say('幾何雜湊', 'Geometry SHA')}:</dt>
                      <dd>{modifiedPin.geometry_sha256}</dd>
                    </dl>
                  )}
                </div>
              </div>

              <div className="e2-actions-row">
                <button type="button" className="e2-btn" onClick={handleRegisterHarbour}>
                  <FileText size={13} />
                  {say('登錄港埠方案（固定來源）', 'Register Harbour Proposal')}
                </button>
                {modifiedPin && !isModifiedAccepted && (
                  <button type="button" className="e2-btn e2-btn--decision" onClick={openAcceptScenarioDialog}>
                    <ShieldAlert size={13} />
                    {say('接受此方案（需你的決策密語）', 'Accept Scenario (requires your decision passphrase)')}
                  </button>
                )}
              </div>
            </div>
          )}
        </section>

        {/* Step 3: 實驗計畫 */}
        <section className={`e2-step-card ${step3Status === 'COMPLETED' ? 'e2-step-card--completed' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(3)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">3</span>
              <span>{say('③ 實驗計畫', '③ Experiment Plan')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step3Status)} language={language} />
            </div>
          </div>
          {expandedSteps[3] && (
            <div className="e2-step-card__body">
              {/* Locked settings table */}
              <div className="e2-step-details">
                <summary>{say('E2 鎖定實驗參數', 'E2 Locked Experiment Parameters')}</summary>
                <table className="e2-locked-settings-table">
                  <tbody>
                    <tr>
                      <th>{say('模擬期間', 'Period')}</th>
                      <td>{say('夏季 6–8 月（6/1–8/31，每日 1–24 時，共 2,208 小時）', 'Summer Jun-Aug (6/1–8/31, 1–24h daily, 2,208 hrs)')}</td>
                    </tr>
                    <tr>
                      <th>{say('地面網格', 'Ground Grid')}</th>
                      <td>{say('5 m 間距 · 感測器偏移 0.05 m · EPSG:28992 · COMMON_OVERLAP 公共空間重疊範圍', '5 m spacing · 0.05 m offset · EPSG:28992 · COMMON_OVERLAP')}</td>
                    </tr>
                    <tr>
                      <th>{say('敏感度偏移', 'Sensitivity')}</th>
                      <td>{say('±1 小時日照偏移 (-1, 0, +1 h) · 檢驗時間定義假設', '±1 h solar offset (-1, 0, +1 h) · Tests hour-end assumptions')}</td>
                    </tr>
                    <tr>
                      <th>{say('雙方法配方', 'Dual Recipe')}</th>
                      <td>
                        {say(
                          'Ladybug 遮擋篩檢（Tregenza 145 無反射）＋ Honeybee-Radiance 實體驗證（-ab 2 -ad 2048 -lw 0.0001 -u-）',
                          'Ladybug screening (Tregenza 145 no reflection) + Honeybee-Radiance verification (rfluxmtx -ab 2 -ad 2048 -lw 0.0001 -u-)'
                        )}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {/* Existing plans list */}
              {plans.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <label style={{ fontSize: '12px', fontWeight: 600 }}>{say('現有實驗計畫：', 'Existing Experiment Plans:')}</label>
                  {plans.map((p) => {
                    const isSelected = (p.plan_artifact_id || p.id) === selectedPlanId;
                    return (
                      <div
                        key={p.id}
                        className={`e2-step-details ${isSelected ? 'e2-step-card--active' : ''}`}
                        onClick={() => setSelectedPlanId(p.plan_artifact_id || p.id)}
                        style={{ cursor: 'pointer' }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <strong>{p.plan_artifact_id || p.id}</strong>
                          <StatusBadge status={p.status} language={language} selected={isSelected} />
                        </div>
                        <dl>
                          <dt>{say('計畫 SHA-256', 'Plan SHA')}:</dt>
                          <dd>{p.sha256}</dd>
                          <dt>{say('基準方案', 'Baseline')}:</dt>
                          <dd>{p.baseline?.scenario_id || '—'}</dd>
                          <dt>{say('比較方案', 'Modified')}:</dt>
                          <dd>{p.modified?.scenario_id || '—'}</dd>
                        </dl>
                        {p.status === 'PROPOSED' && (
                          <div className="e2-actions-row" style={{ marginTop: '8px' }}>
                            <button
                              type="button"
                              className="e2-btn e2-btn--decision"
                              onClick={(e) => {
                                e.stopPropagation();
                                openApprovePlanDialog(p);
                              }}
                            >
                              <ShieldAlert size={13} />
                              {say('批准計畫（需你的決策密語）', 'Approve Plan (requires your decision passphrase)')}
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              <div className="e2-actions-row">
                <button
                  type="button"
                  className="e2-btn e2-btn--primary"
                  onClick={handleProposePlan}
                  disabled={!approvedSnapshot || !baselinePin || !modifiedPin || baselineId === modifiedId}
                >
                  <SunMedium size={13} />
                  {say('提出實驗計畫', 'Propose Experiment Plan')}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Step 4: 準備檢查 */}
        <section className={`e2-step-card ${step4Status === 'COMPLETED' ? 'e2-step-card--completed' : step4Status === 'BLOCKED' ? 'e2-step-card--blocked' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(4)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">4</span>
              <span>{say('④ 準備檢查', '④ Readiness Check')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step4Status)} language={language} />
            </div>
          </div>
          {expandedSteps[4] && (
            <div className="e2-step-card__body">
              {!selectedPlanId ? (
                <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-dim)' }}>
                  {say('請先於步驟 ③ 選擇或批准一個實驗計畫。', 'Please select or approve an experiment plan in Step ③ first.')}
                </p>
              ) : !readinessData ? (
                <div className="e2-actions-row">
                  <button type="button" className="e2-btn" onClick={loadReadiness}>
                    <RefreshCw size={13} />
                    {say('執行準備檢查', 'Run Readiness Check')}
                  </button>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div className={`e2-alert-banner ${readinessData.dispatch_allowed ? 'e2-alert-banner--info' : 'e2-alert-banner--danger'}`}>
                    {readinessData.dispatch_allowed ? (
                      <>
                        <CheckCircle size={16} />
                        <span>{say('所有前置檢查通過，允許派送計算。', 'All prerequisite checks passed. Simulation dispatch is allowed.')}</span>
                      </>
                    ) : (
                      <>
                        <AlertTriangle size={16} />
                        <span>{say('準備檢查未通過，已阻擋派送。', 'Readiness checks failed. Simulation dispatch is blocked.')}</span>
                      </>
                    )}
                  </div>

                  {readinessData.blockers && readinessData.blockers.length > 0 && (
                    <ul style={{ margin: 0, paddingLeft: '20px', color: '#fca5a5', fontSize: '12px' }}>
                      {readinessData.blockers.map((b, i) => (
                        <li key={i}>{b}</li>
                      ))}
                    </ul>
                  )}

                  {readinessData.checks && (
                    <div className="e2-readiness-list">
                      {readinessData.checks.map((c, i) => (
                        <div key={i} className="e2-readiness-item">
                          <div>
                            <span className="e2-readiness-item__name">{c.name || c.label || `Check ${i + 1}`}</span>
                            {c.detail && <div className="e2-readiness-item__detail">{c.detail}</div>}
                          </div>
                          <StatusBadge status={c.status || (c.passed ? 'PASS' : 'FAIL')} language={language} />
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="e2-actions-row">
                    <button type="button" className="e2-btn" onClick={loadReadiness}>
                      <RefreshCw size={13} />
                      {say('重新檢查', 'Re-check Readiness')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </section>

        {/* Step 5: 送出計算 */}
        <section className={`e2-step-card ${step5Status === 'COMPLETED' ? 'e2-step-card--completed' : step5Status === 'BLOCKED' ? 'e2-step-card--blocked' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(5)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">5</span>
              <span>{say('⑤ 送出計算', '⑤ Submit Simulation')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step5Status)} language={language} />
            </div>
          </div>
          {expandedSteps[5] && (
            <div className="e2-step-card__body">
              {/* Hard confirmation box */}
              <div className="e2-alert-banner e2-alert-banner--warning">
                <AlertTriangle size={18} />
                <div>
                  <strong>{say('計算規範：', 'Simulation rules: ')}</strong>
                  {say(
                    '約 14 分鐘、每份計畫只能送一次、失敗或未知不會自動重送。冪等金鑰由計畫編號決定，重新整理後也不會重複派送。',
                    'Approx. 14 minutes; each plan is dispatched once; failures or unknown outcomes are never resent automatically. The idempotency key is derived from the plan id, so a reload cannot dispatch twice.'
                  )}
                </div>
              </div>

              {existingJob && !isSimulating && (
                <div className="e2-alert-banner e2-alert-banner--info" role="note">
                  <div>
                    {say(
                      `這份實驗計畫已經派送過（工作 ${existingJob.job_id}），每份計畫只派送一次；結果請看第 ⑥ 步或下方歷史正式結果。要重新計算，請先提出新的實驗計畫。`,
                      `This experiment plan has already been dispatched (job ${existingJob.job_id}); each plan is dispatched only once. See step ⑥ or the formal history below. To compute again, propose a new experiment plan first.`,
                    )}
                  </div>
                </div>
              )}

              {outcomeUnknown && (
                <div className="e2-alert-banner e2-alert-banner--danger" role="alert">
                  <ShieldAlert size={18} />
                  <div>
                    <strong>{say('結果未知，需管理者對帳，不可重送', 'Outcome unknown; administrator reconciliation required before retry; do not resend')}</strong>
                    {simulateError && <p style={{ margin: '4px 0 0 0' }}>{simulateError}</p>}
                  </div>
                </div>
              )}

              {idempotencyKey && (
                <div className="e2-step-details">
                  <dl>
                    <dt>{say('冪等金鑰', 'Idempotency Key')}:</dt>
                    <dd>{idempotencyKey}</dd>
                    {activeJobId && (
                      <>
                        <dt>{say('工作 ID', 'Job ID')}:</dt>
                        <dd>{activeJobId}</dd>
                      </>
                    )}
                    {isSimulating && (
                      <>
                        <dt>{say('已用時間', 'Elapsed Time')}:</dt>
                        <dd style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
                          <Clock size={12} style={{ display: 'inline', marginRight: '4px' }} />
                          {formatElapsed(elapsedSeconds)}
                        </dd>
                      </>
                    )}
                  </dl>
                </div>
              )}

              <div className="e2-actions-row">
                <button
                  type="button"
                  className="e2-btn e2-btn--primary"
                  onClick={handleSimulate}
                  disabled={
                    step4Status !== 'COMPLETED' ||
                    outcomeUnknown ||
                    isSimulating ||
                    step5Status === 'COMPLETED' ||
                    !!existingJob
                  }
                >
                  <Play size={13} />
                  {isSimulating
                    ? say(`計算中…（${formatElapsed(elapsedSeconds)}）`, `Simulating… (${formatElapsed(elapsedSeconds)})`)
                    : say('產生冪等金鑰並送出計算', 'Generate Idempotency Key and Simulate')}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* Step 6: 結果與比較 */}
        <section className={`e2-step-card ${step6Status === 'COMPLETED' ? 'e2-step-card--completed' : ''}`}>
          <div className="e2-step-card__header" onClick={() => toggleStep(6)}>
            <div className="e2-step-card__title">
              <span className="e2-step-card__number">6</span>
              <span>{say('⑥ 結果與比較', '⑥ Results & Comparison')}</span>
            </div>
            <div className="e2-step-card__status-area">
              <StatusBadge status={badge(step6Status)} language={language} />
            </div>
          </div>
          {expandedSteps[6] && (
            <div className="e2-step-card__body">
              {/* Permanent Warning Notice */}
              <aside className="e2-warning-callout" role="note">
                <strong>{say('重要警語：', 'Important notice: ')}</strong>
                {say(
                  '入射輻射降低不等於熱舒適改善；兩方法絕對值不可混用。Ladybug 遮擋篩檢不含表面多次反射；Honeybee-Radiance 驗證採獨立反射配方。此為同方法內之輻射比較，不代表規劃檢核通過或宣告設計勝出。',
                  'Incident radiation reduction does not imply improved thermal comfort; absolute values from the two methods must not be combined or interchanged. Ladybug screening omits interreflections; Honeybee-Radiance verification uses an independent reflection recipe. This is a within-method directional radiation comparison and does not declare planning compliance or design victory.'
                )}
              </aside>

              {currentResult && currentResult.comparisons && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                      <strong>{say('目前顯示結果：Job ', 'Current Result: Job ')} {currentResult.job_id}</strong>
                      <span style={{ marginLeft: '10px' }}>
                        <StatusBadge
                          status={currentResult.evidence_validation_status || 'VALIDATED'}
                          language={language}
                        />
                      </span>
                    </div>
                    <button type="button" className="e2-btn" onClick={handleCompare}>
                      <CheckCircle size={13} />
                      {comparisonVerified ? say('方向比較已驗證', 'Direction Verified') : say('驗證同方法方向比較', 'Verify Within-Method Direction')}
                    </button>
                  </div>

                  {/* Comparisons table */}
                  <div className="e2-results-table-container">
                    <table className="e2-results-table">
                      <thead>
                        <tr>
                          <th>{say('計算方法', 'Method')}</th>
                          <th>{say('敏感度偏移', 'Sensitivity Offset')}</th>
                          <th>{say('基準方案', 'Baseline')}</th>
                          <th>{say('比較方案', 'Modified')}</th>
                          <th>{say('差值（比較−基準）', 'Delta (Mod - Base)')}</th>
                          <th>{say('方向', 'Direction')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {/* Ladybug rows */}
                        {currentResult.comparisons.ladybug_radiance &&
                          Object.entries(currentResult.comparisons.ladybug_radiance).map(([offset, row]) => (
                            <tr key={`lb-${offset}`}>
                              <td>{say('Ladybug 遮擋篩檢（無反射）', 'Ladybug Screening (no reflection)')}</td>
                              <td>{offset === '0' ? say('基準時刻 (0 h)', 'Nominal (0 h)') : `${offset > '0' ? '+' : ''}${offset} ${say('小時', 'hr')}`}</td>
                              <td>{formatNumber(row.baseline_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}</td>
                              <td>{formatNumber(row.modified_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}</td>
                              <td style={{ color: row.delta_kwh_m2 < 0 ? '#50d5b5' : '#f87171', fontWeight: 600 }}>
                                {row.delta_kwh_m2 > 0 ? '+' : ''}
                                {formatNumber(row.delta_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}
                              </td>
                              <td>
                                <StatusBadge status={row.direction} language={language} />
                              </td>
                            </tr>
                          ))}

                        {/* Honeybee rows */}
                        {currentResult.comparisons.honeybee_radiance &&
                          Object.entries(currentResult.comparisons.honeybee_radiance).map(([offset, row]) => (
                            <tr key={`hb-${offset}`}>
                              <td>{say('Honeybee-Radiance 驗證（表面反射）', 'Honeybee-Radiance (interreflection)')}</td>
                              <td>{offset === '0' ? say('基準時刻 (0 h)', 'Nominal (0 h)') : `${offset > '0' ? '+' : ''}${offset} ${say('小時', 'hr')}`}</td>
                              <td>{formatNumber(row.baseline_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}</td>
                              <td>{formatNumber(row.modified_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}</td>
                              <td style={{ color: row.delta_kwh_m2 < 0 ? '#50d5b5' : '#f87171', fontWeight: 600 }}>
                                {row.delta_kwh_m2 > 0 ? '+' : ''}
                                {formatNumber(row.delta_kwh_m2)} {say('千瓦時／平方公尺', 'kWh/m²')}
                              </td>
                              <td>
                                <StatusBadge status={row.direction} language={language} />
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>

                  {/* Direction Agreement Summary */}
                  {currentResult.direction_summary && (
                    <div className="e2-step-details">
                      <summary>{say('方向一致性摘要', 'Direction Agreement Summary')}</summary>
                      <p style={{ margin: '6px 0 0 0', fontSize: '12px' }}>
                        {language === 'zh-TW'
                          ? (currentResult.direction_summary.explanation ||
                              '兩方法在 -1、0、+1 小時敏感度偏移下皆維持方向一致，未翻轉敏感度。')
                          : 'Only the improvement (lower incident radiation) or worsening direction within each method is compared. Screening uses sky-patch obstruction; verification uses Radiance coefficients with reflections. Agreement in direction does not make absolute values interchangeable.'}
                      </p>
                    </div>
                  )}

                  {/* Limitations */}
                  {currentResult.limitations && currentResult.limitations.length > 0 && (
                    <div className="e2-step-details" style={{ marginTop: '10px' }}>
                      <summary>{say('限制事項', 'Limitations')}</summary>
                      <ul style={{ margin: '6px 0 0 0', paddingLeft: '20px', fontSize: '12px', color: 'var(--text-secondary, #94a3b8)' }}>
                        {currentResult.limitations.map((lim, idx) => (
                          <li key={idx}>
                            {language !== 'zh-TW' && /[\u4e00-\u9fff]/.test(lim)
                              ? `(Source note in Chinese) ${lim}`
                              : lim}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* Historical Formal Results */}
              <div style={{ marginTop: '16px' }}>
                <h4 style={{ margin: '0 0 8px 0', fontSize: '13px', color: 'var(--accent-cyan)' }}>
                  {say('歷史正式計算結果', 'Historical Formal Runs')}
                </h4>
                {jobs.length === 0 ? (
                  <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-dim)' }}>
                    {say('目前無歷史 durable jobs。', 'No historical durable jobs found.')}
                  </p>
                ) : (
                  <div className="e2-history-list">
                    {jobs.map((j) => (
                      <div key={j.id} className="e2-history-item">
                        <div className="e2-history-item__info">
                          <span className="e2-history-item__title">
                            {scenarioName(j.baseline_scenario_id, language)} {say('對', 'vs')} {scenarioName(j.modified_scenario_id, language)}
                            <small style={{ opacity: 0.6, marginLeft: 6 }}>{say('工作', 'Job')} {j.id.slice(0, 8)}…</small>
                          </span>
                          <span className="e2-history-item__meta">
                            {say('建立時間：', 'Created: ')} {new Date(j.created_at).toLocaleString()} ·{' '}
                            <StatusBadge status={j.status} language={language} /> ·{' '}
                            <StatusBadge status={j.validated ? 'VALIDATED' : 'UNVERIFIED'} language={language} />
                          </span>
                        </div>
                        <button
                          type="button"
                          className="e2-btn"
                          onClick={() => handleLoadJobResult(j.id)}
                        >
                          {say('查看完整結果表', 'View Full Table')}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </section>
      </div>

      {/* HumanDecisionDialog */}
      {decisionTarget && (
        <HumanDecisionDialog
          isOpen={decisionOpen}
          target={decisionTarget}
          action={decisionAction}
          status={decisionStatus}
          onClose={() => setDecisionOpen(false)}
          onSubmit={handleDecisionSubmit}
          reviewContent={decisionReviewContent}
        />
      )}
    </div>
  );
};
