export const workflowMessages = {
  en: {
    title: 'Generation workflow', mode: 'Generation mode', SKELETON_FIRST: 'Skeleton first', FULL_SCHEME: 'Full scheme', STEPWISE: 'Stepwise',
    newWorkflow: 'New workflow', start: 'Start workflow', advance: 'Continue generation', refresh: 'Refresh receipt', reconcile: 'Reconcile after restart', cancel: 'Request cancellation',
    select: 'Select for this workflow', outputs: 'Stage outputs', status: 'Workflow status', publication: 'Authority publication',
    blocked: 'Blocked / Not ready — approved GenerationContext required.',
    boundary: 'Stage selection applies to this workflow only. Proposal acceptance remains a separate human decision.',
    fixture: 'Offline workflow; no authoritative proposal.',
    error: 'Request failed. Refresh and reconcile before sending another action.', unknown: 'Outcome unknown — reconcile before continuing.',
    job: 'Job receipt', selected: 'Selected output',
    checkingReadiness: 'Checking readiness…',
    viewInCompare: 'View in Compare',
    completed: 'Complete',
  },
  'zh-TW': {
    title: '生成流程', mode: '生成模式', SKELETON_FIRST: '骨架優先', FULL_SCHEME: '完整方案', STEPWISE: '逐步生成',
    newWorkflow: '建立新流程', start: '開始流程', advance: '繼續生成', refresh: '更新回執', reconcile: '重啟後核對', cancel: '要求取消',
    select: '選入本次流程', outputs: '階段輸出', status: '流程狀態', publication: '權威發布',
    blocked: '受阻／尚未就緒 — 需要已批准的 GenerationContext。',
    boundary: '階段選擇只適用於本次流程。方案接受仍需獨立的人類決策。',
    fixture: '離線流程；沒有權威方案。',
    error: '請求失敗。再次操作前請更新回執並核對結果。', unknown: '狀態未知 — 核對後才能繼續。',
    job: '工作回執', selected: '選擇輸出',
    checkingReadiness: '正在檢查生成準備度…',
    viewInCompare: '到比較分頁查看',
    completed: '已完成',
  },
} as const;
export type WorkflowLanguage = keyof typeof workflowMessages;
