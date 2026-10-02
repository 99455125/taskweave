"""Shared desktop visual tokens and responsive layout; no business behavior."""

STYLE = """
:root { --tw-blue:#2563eb; --tw-ink:#172544; --tw-muted:#718096; --tw-line:#e2e9f3; --tw-bg:#f6f8fc; }
body { background:var(--tw-bg); color:var(--tw-ink); font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
.nicegui-content { padding:24px; gap:20px; max-width:1920px; width:100%; margin:auto; }
.tw-panel { background:#fff; border:1px solid var(--tw-line); border-radius:12px; padding:20px; box-shadow:0 2px 8px #22365503; }
.tw-content { min-width:0; flex:1; }
.tw-header { min-height:72px; padding:12px 24px; gap:20px; box-shadow:none; border-bottom:1px solid var(--tw-line); }
.tw-brand { color:#172544; font-size:20px; font-weight:750; letter-spacing:-.5px; white-space:nowrap; }
.tw-main-nav { flex:1; min-width:0; flex-wrap:wrap; gap:4px; }
.q-btn { box-shadow:none; border-radius:7px; text-transform:none; font-weight:500; min-height:36px; }
.tw-button { background:white!important; color:var(--tw-blue)!important; border:1px solid #d6e1f3!important; padding:6px 14px; }
.tw-button:hover { background:#f0f5ff!important; border-color:#a8c2fa!important; }
.tw-primary { background:var(--tw-blue)!important; color:white!important; border-color:var(--tw-blue)!important; }
.tw-button.tw-primary,.tw-button.tw-primary .q-btn__content { color:#fff!important; }
.tw-primary:hover { background:#1d4ed8!important; }
.tw-nav { border-color:transparent!important; color:#526079!important; background:transparent!important; }
.tw-nav-active { color:var(--tw-blue)!important; background:#edf3ff!important; border-color:transparent!important; }
.tw-selected { background:#edf4ff!important; border-color:#92b4ff!important; color:#173e81!important; }
.tw-danger { color:#dc2626!important; border-color:#fecaca!important; }
.tw-save-state { min-width:7rem; text-align:right; }
.tw-code { white-space:pre-wrap; overflow-wrap:anywhere; font-family:ui-monospace,monospace; }
.q-field--outlined .q-field__control:before { border-color:#dce4ef; }
.q-field__control { border-radius:7px; }
.q-tab { text-transform:none; min-height:44px; }
.q-dialog__inner > .q-card { border-radius:14px; padding:24px; }
.tw-execution-layout { display:grid; grid-template-columns:290px minmax(0,1fr); gap:20px; width:100%; align-items:start; }
.tw-run-list { position:sticky; top:90px; max-height:calc(100vh - 140px); overflow:auto; gap:10px; }
.tw-run-card { border:1px solid var(--tw-line); border-radius:10px; padding:16px; width:100%; background:white; }
.tw-run-card .q-btn { text-align:left; justify-content:flex-start; width:100%; padding:0!important; border:0!important; background:transparent!important; color:var(--tw-ink)!important; }
.tw-executions-master { display:grid!important; grid-template-columns:276px minmax(0,1fr); gap:20px; align-items:start; }
.tw-execution-filters { width:276px!important; min-width:0; }
.tw-executions-master { width:100%; min-width:0; }
.tw-executions-main { width:100%; min-width:0; }
.tw-executions-main > * { min-width:0; max-width:100%; }
.tw-execution-list-title { margin:8px 0 0; }
.tw-run-list { width:100%; max-height:calc(100vh - 500px); min-height:180px; overflow:auto; }
.tw-executions-main { display:flex; min-width:0; flex-direction:column; gap:14px; }
.tw-executions-toolbar { min-height:42px; }
.tw-run-detail-area { min-width:0; }
.tw-run-summary-card,.tw-run-progress-card,.tw-current-results,.tw-run-history { background:#fff; border:1px solid var(--tw-line); border-radius:12px; box-shadow:none; padding:18px 20px; }
.tw-run-tabs { border-bottom:1px solid var(--tw-line); color:var(--tw-blue); }
.tw-run-tab-panels { background:transparent; }
.tw-run-step-detail { margin-top:12px; }
.tw-selected-step-card { background:#fff; border:1px solid var(--tw-line); border-radius:12px; box-shadow:none; padding:18px 20px; }
.tw-empty-step-state { padding:14px; border-radius:8px; background:#f5f8fd; color:#6b7a90; }
.tw-step-detail-tabs { border-bottom:1px solid var(--tw-line); }
.tw-run-card { align-items:stretch; }
.tw-run-name .q-btn__content { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--tw-ink)!important; text-align:left; }
.tw-run-status { flex:0 0 auto; margin-top:3px; }
.tw-step-track { justify-content:flex-start; }
.tw-summary-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
.tw-summary-card { min-width:0; flex:1; background:white; border:1px solid var(--tw-line); border-radius:12px; padding:16px 20px; }
.tw-home-grid { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr); gap:20px; }
.tw-home-task,.tw-home-run { padding:12px 0; border-bottom:1px solid var(--tw-line); }
.tw-home-task:last-child,.tw-home-run:last-child { border-bottom:0; }
.tw-status { display:inline-flex; border-radius:6px; padding:3px 9px; font-size:12px; background:#eef2f7; color:#64748b; }
.tw-status-running { background:#eaf1ff; color:#2563eb; }
.tw-status-succeeded { background:#e7f8f0; color:#13845b; }
.tw-status-failed { background:#fff0f0; color:#d54444; }
.tw-status-unknown,.tw-status-paused,.tw-status-interrupted { background:#fff7e5; color:#a56912; }
.tw-step-track { display:flex; flex-wrap:nowrap; width:100%; overflow-x:auto; padding:20px 4px 18px; gap:0; scrollbar-width:thin; }
.tw-step-node { position:relative; flex:0 0 140px; display:flex; flex-direction:column; align-items:center; gap:8px; padding:6px; }
.tw-step-node:not(:last-child):after { content:""; position:absolute; left:calc(50% + 21px); top:24px; width:calc(100% - 42px); height:2px; background:#e3eaf5; }
.tw-step-dot { width:36px; height:36px; min-height:36px; border-radius:50%!important; padding:0!important; background:#f3f6fb!important; border:1px solid #dce5f1!important; color:#8190a9!important; z-index:1; }
.tw-step-node.is-succeeded .tw-step-dot { background:#e7f8f0!important; border-color:#a6dfc9!important; color:#168b63!important; }
.tw-step-node.is-running .tw-step-dot { background:#eaf1ff!important; border-color:#78a4fb!important; color:#2563eb!important; }
.tw-step-node.is-failed .tw-step-dot { background:#fff0f0!important; border-color:#f6b7b7!important; color:#d54444!important; }
.tw-step-node.is-unknown .tw-step-dot { background:#fff7e5!important; border-color:#efd29a!important; color:#a56912!important; }
.tw-step-node.is-pending .tw-step-dot { background:#fff!important; border-color:#cfdae9!important; color:#718096!important; }
.tw-step-node.is-selected { background:#f3f7ff; border-radius:10px; }
.tw-step-node.is-selected .tw-step-dot { outline:3px solid #dbe8ff; outline-offset:2px; }
.tw-step-name { padding:0 4px!important; border:0!important; background:transparent!important; color:#526174!important; font-size:13px; min-height:38px; width:100%; }
.tw-step-node .tw-step-name .q-btn__content { color:#526174!important; white-space:normal; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.tw-editor-layout { display:grid!important; grid-template-columns:174px minmax(0,1fr); gap:16px; flex-wrap:nowrap!important; align-items:stretch!important; }
.tw-editor-layout > .tw-step-sidebar { width:174px!important; min-width:0; padding:12px; }
.tw-editor-panel { padding:16px; }
.tw-editor-body { min-width:0; }
.tw-debug-drawer { border:1px solid var(--tw-line)!important; border-radius:10px; box-shadow:-6px 0 24px #22365508; background:white; }
.tw-master-layout { display:flex; width:100%; align-items:flex-start; gap:20px; flex-wrap:nowrap; }
.tw-list-sidebar { width:280px; flex-shrink:0; }
.tw-plugin-detail { min-width:0; max-width:100%; overflow:hidden; }
.tw-plugin-detail-heading { min-height:48px; }
.tw-plugin-heading-icon { box-sizing:border-box; width:48px; height:48px; padding:12px; border-radius:10px; background:#edf3ff; color:#3f7af0; font-size:24px; flex:0 0 48px; }
.tw-plugin-detail .nicegui-code, .tw-plugin-detail .nicegui-markdown { min-width:0; max-width:100%; overflow-x:auto; }
.tw-plugin-detail pre { max-width:100%; overflow-x:auto; }
.tw-plugin-section,.tw-plugin-load-state { border:1px solid var(--tw-line); border-radius:12px; box-shadow:none; padding:18px; }
.tw-plugin-capability-card { border:1px solid var(--tw-line); border-radius:9px; padding:4px 10px; }
.tw-marketplace { min-width:0; }
.tw-market-hero { min-height:230px; padding:48px; border:1px solid #dbe8ff; border-radius:12px; background:linear-gradient(120deg,#fff,#edf4ff); }
.tw-market-status { display:inline-flex; width:max-content; padding:5px 10px; border-radius:999px; color:#2563eb!important; background:#e8f0ff; font-size:13px; font-weight:600; }
.tw-market-hero-icon { box-sizing:border-box; flex:0 0 auto; width:48px; height:48px; padding:12px; font-size:24px; border-radius:50%; color:#2563eb; background:#dfeaff; }
.tw-market-resource-grid { display:grid!important; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
.tw-market-resource-card { min-width:0; padding:20px; border:1px solid var(--tw-line); border-radius:12px; box-shadow:none; }
.tw-market-resource-icon { box-sizing:border-box; width:44px; height:44px; padding:10px; font-size:24px; color:#4779d8; background:#edf4ff; border-radius:9px; }
.tw-market-closed-badge { display:inline-flex; width:max-content; padding:3px 8px; border-radius:999px; color:#526174!important; background:#f0f3f8; font-size:12px; }
.tw-market-local-links { padding-top:4px; }
.tw-task-workspace { gap:18px; }
.tw-task-sidebar { width:260px; max-height:calc(100vh - 150px); overflow:auto; position:sticky; top:90px; }
.tw-task-nav-card { display:flex; flex-direction:column; border:1px solid var(--tw-line); border-radius:9px; padding:10px 12px; background:#fff; cursor:pointer; }
.tw-task-nav-card:focus-visible { outline:2px solid var(--tw-blue); outline-offset:2px; }
.tw-task-nav-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-task-nav-card.tw-selected { border-color:#92b4ff; }
.tw-task-tabs { border-bottom:1px solid var(--tw-line); }
.tw-plan-list-card { display:flex; flex-direction:column; gap:4px; text-align:left; cursor:pointer; border:1px solid var(--tw-line); border-radius:9px; padding:10px 12px; background:#fff; }
.tw-plan-list-card:focus-visible { outline:2px solid var(--tw-blue); outline-offset:2px; }
.tw-plan-list-name { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-plan-web-dialog { display:flex; flex-direction:column; max-height:calc(100dvh - 32px); overflow:auto; }
.tw-plan-prompt textarea,.tw-plan-response textarea { height:clamp(150px, 24vh, 280px)!important; max-height:32vh!important; overflow:auto!important; }
.tw-plan-web-dialog .q-field { margin:0; }
.tw-editor-panel { display:grid!important; grid-template-columns:minmax(0,1fr); column-gap:16px; }
.tw-editor-layout.tw-debug-open { grid-template-columns:174px minmax(0,1fr) 320px; }
.tw-step-config-heading { grid-column:1; grid-row:1; }
.tw-editor-body { grid-column:1; grid-row:2; min-width:0; }
.tw-debug-column { grid-column:3; grid-row:1; min-width:0; }
.tw-debug-log-body { max-height:360px; overflow:auto; }
.tw-debug-log-body pre { white-space:pre-wrap; overflow-wrap:anywhere; }
.tw-debug-drawer > * { max-width:100%; min-width:0; }
.tw-debug-drawer .q-expansion-item.border { border-color:var(--tw-line)!important; border-radius:8px!important; }
.tw-debug-drawer .q-item__section--avatar { min-width:30px; padding-right:8px; }
.tw-debug-drawer .q-expansion-item__content { min-width:0; }
.tw-debug-drawer { grid-column:2; grid-row:1 / span 2; align-self:stretch; width:100%!important; min-width:0; }
.tw-status-chip { border:1px solid var(--tw-line); border-radius:7px; background:#f8faff; padding:5px 10px; font-size:13px; color:#526079; }
.tw-settings-nav { color:#26364e!important; border:1px solid transparent!important; border-radius:8px!important; }
.tw-settings-nav .q-btn__content,.tw-settings-nav .q-btn__content * { color:#26364e!important; justify-content:flex-start; }
.tw-settings-sidebar .tw-settings-nav.tw-settings-nav-active { color:#2563eb!important; background:#edf4ff!important; border:1px solid #cbdcff!important; }
.tw-settings-nav-active .q-btn__content,.tw-settings-nav-active .q-btn__content * { color:#2563eb!important; }
.tw-header .tw-nav-active .q-btn__content,.tw-header .tw-nav-active .q-btn__content *,.tw-header .tw-nav-active .q-icon { color:#2563eb!important; }
.tw-environment-detail-heading { min-height:40px; }
.tw-environment-sidebar-heading { margin-bottom:2px; }
.tw-environment-name { color:#26364e!important; }
.tw-environment-name .q-btn__content,.tw-environment-name .q-btn__content * { color:#26364e!important; justify-content:flex-start; text-align:left; }
.tw-environment-list-item.tw-selected { background:#edf4ff!important; border-color:#92b4ff!important; }
.tw-environment-detail { flex:1 1 auto; }
.tw-env-variable-row { display:grid!important; grid-template-columns:minmax(150px,25%) minmax(220px,37%) minmax(180px,1fr) 72px; align-items:end; }
.tw-env-variable-row .tw-env-key,.tw-env-variable-row .tw-env-value,.tw-env-variable-row .tw-env-description { width:100%; min-width:0; }
.tw-info-note { background:#eef5ff; border:1px solid #d5e5ff; border-radius:8px; padding:10px 12px; color:#31578e; }
.tw-danger,.tw-danger .q-btn__content { color:#dc2626!important; border-color:#fecaca!important; }
.tw-step-execution-overview { display:grid!important; grid-template-columns:minmax(0,1fr) minmax(0,1fr); }
@media(min-width:851px) {
 .tw-settings-sidebar .tw-settings-nav-options { display:flex!important; flex-direction:column!important; align-items:stretch!important; }
 .tw-settings-sidebar .tw-settings-nav-options > .q-btn { flex:0 0 auto!important; }
 .tw-settings-sidebar .tw-settings-nav .q-btn__content { flex-direction:row!important; justify-content:flex-start!important; }
}
.tw-run-logs .nicegui-code,.tw-run-logs pre { max-height:270px!important; overflow:auto!important; overscroll-behavior:contain; }
.tw-run-logs pre { white-space:pre!important; }
.tw-run-logs { box-shadow:none!important; }
.tw-run-logs .nicegui-code { background:#172b46!important; color:#e8eef7!important; border-radius:8px; }
.tw-run-logs .nicegui-code pre,.tw-run-logs .nicegui-code code { background:transparent!important; color:#e8eef7!important; }
.tw-run-logs .nicegui-code .c,.tw-run-logs .nicegui-code .c1,.tw-run-logs .nicegui-code .cm,.tw-run-logs .nicegui-code .w { color:#9aacc2!important; }
.tw-run-logs .nicegui-code .nt,.tw-run-logs .nicegui-code .na { color:#9fe0ae!important; }
.tw-run-logs .nicegui-code .s,.tw-run-logs .nicegui-code .s1,.tw-run-logs .nicegui-code .s2 { color:#ffb3a7!important; }
.tw-run-logs .nicegui-code .k,.tw-run-logs .nicegui-code .kc,.tw-run-logs .nicegui-code .kd,.tw-run-logs .nicegui-code .kn,.tw-run-logs .nicegui-code .kp,.tw-run-logs .nicegui-code .kr,.tw-run-logs .nicegui-code .kt { color:#c7a9ff!important; }
.tw-run-logs .nicegui-code .m,.tw-run-logs .nicegui-code .mi,.tw-run-logs .nicegui-code .mf { color:#f0c875!important; }
.tw-run-logs .nicegui-code .nb,.tw-run-logs .nicegui-code .nf,.tw-run-logs .nicegui-code .nv { color:#8fcaff!important; }
.tw-run-log-fulltext textarea { max-height:65vh!important; overflow:auto!important; }
.tw-step-effective-input,.tw-step-execution-info { padding:12px; border:1px solid var(--tw-line); border-radius:9px; background:#fbfcfe; }
.tw-run-history { display:flex; flex-direction:column; gap:8px; }
.tw-history-attempt { border:1px solid var(--tw-line); border-radius:8px; padding:8px 10px; }
@media(max-width:1100px) {
 .tw-header { gap:12px; padding:12px 16px; }
 .tw-brand { font-size:18px; }
 .tw-execution-layout { grid-template-columns:240px minmax(0,1fr); gap:12px; }
 .tw-home-grid { grid-template-columns:minmax(0,1fr); }
 .tw-list-sidebar { width:230px; }
 .tw-task-sidebar { position:static; width:230px; max-height:calc(100vh - 150px); }
 .tw-editor-body { width:100%!important; }
 .tw-debug-drawer { position:relative!important; width:100%!important; border-left:0!important; border-top:1px solid var(--tw-line); }
}
@media(max-width:780px) {
 .nicegui-content { padding:12px; }
 .tw-header { position:relative; }
 .tw-main-nav { order:3; flex-basis:100%; }
 .tw-panel { padding:14px; }
 .tw-execution-layout { grid-template-columns:minmax(0,1fr); }
 .tw-summary-grid { grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
 .tw-summary-card { padding:12px; }
 .tw-run-list { position:static; max-height:300px; overflow:auto; }
 .tw-master-layout { flex-wrap:wrap; }
 .tw-task-workspace { gap:12px; }
 .tw-task-detail { width:100%; }
 .tw-task-sidebar { width:100%; max-height:260px; }
 .tw-task-tabs .q-tab { padding:0 10px; }
 .tw-list-sidebar { width:100%; max-height:260px; overflow:auto; }
 .tw-step-track { display:flex; flex-wrap:nowrap; overflow-x:auto; overscroll-behavior-x:contain; }
 .tw-step-node { flex:0 0 112px; min-width:0; }
}
/* Shared visual baseline aligned to the accepted interactive prototype. */
:root { --tw-blue:#2563eb; --tw-ink:#1b2b45; --tw-muted:#7b899e; --tw-line:#e6ecf4; --tw-bg:#f5f7fb; --tw-green:#11966d; }
body { background:var(--tw-bg); color:var(--tw-ink); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; }
.nicegui-content { padding:0; gap:0; max-width:none; }
.tw-header { min-height:76px; padding:12px 28px; gap:28px; flex-wrap:wrap; background:#fff; }
.tw-brand-mark { padding:9px; color:#fff!important; background:var(--tw-blue); border-radius:11px; box-shadow:0 4px 12px #2563eb22; }
.tw-brand { color:var(--tw-ink); font-size:23px; font-weight:760; letter-spacing:-.7px; }
.tw-main-nav { flex:1; min-width:0; gap:4px; flex-wrap:nowrap; }
.tw-local-indicator { color:var(--tw-muted); font-size:12px; white-space:nowrap; }
.tw-app-content { width:100%; max-width:1760px; margin:0 auto; padding:25px 28px 32px; gap:20px; }
.q-btn { box-shadow:none!important; border-radius:7px; text-transform:none; min-height:36px; font-size:13px; font-weight:500; letter-spacing:.1px; }
.q-btn:before { box-shadow:none!important; }
.tw-button { background:#fff!important; color:#526780!important; border:1px solid #dce4f0!important; padding:5px 12px; }
.tw-button:hover { background:#f7faff!important; }
.tw-button.tw-primary { background:var(--tw-blue)!important; color:#fff!important; border-color:var(--tw-blue)!important; }
.tw-button.tw-primary:hover { background:#1d4ed8!important; }
.tw-button.tw-ghost { background:transparent!important; border-color:transparent!important; color:#6f8098!important; }
.tw-nav { padding:8px 10px; color:#65758b!important; }
.tw-nav-active { background:#edf3ff!important; color:var(--tw-blue)!important; font-weight:650; }
.tw-header .tw-button.tw-ghost,.tw-header .tw-nav:not(.tw-nav-active),.tw-header .tw-button.tw-ghost .q-icon,.tw-header .tw-nav:not(.tw-nav-active) .q-icon,.tw-header .tw-button.tw-ghost .q-btn__content,.tw-header .tw-nav:not(.tw-nav-active) .q-btn__content { color:#65758b!important; }
.tw-header .tw-nav-active,.tw-header .tw-nav-active .q-icon,.tw-header .tw-nav-active .q-btn__content { color:var(--tw-blue)!important; }
.tw-header .tw-nav-active { background:#edf3ff!important; }
.tw-header .tw-nav-active:before { background:transparent!important; opacity:0!important; }
@media(min-width:851px) {
 .tw-header .tw-main-nav { flex-wrap:nowrap!important; gap:0!important; overflow:visible; }
 .tw-header .tw-main-nav > .q-btn { flex:0 0 auto!important; white-space:nowrap; font-size:13px!important; padding-left:3px!important; padding-right:3px!important; }
 .tw-header .tw-main-nav > .q-btn .q-btn__content { display:flex!important; flex-direction:row!important; flex-wrap:nowrap!important; align-items:center!important; gap:2px; white-space:nowrap!important; }
 .tw-header .tw-main-nav > .q-btn .q-icon { font-size:19px!important; }
}
.tw-panel { padding:22px; border-color:var(--tw-line); border-radius:12px; box-shadow:none; }
.q-field__control { border:1px solid #e1e7f0; border-radius:7px!important; }
.q-field__control:before,.q-field__control:after { border:0!important; }
.q-field--focused .q-field__control { border-color:#8eb4ff!important; }
.q-field:not(.q-field--auto-height) .q-field__control { min-height:38px; }
.q-field--dense .q-field__control,.q-field--dense .q-field__marginal { height:38px; }
.q-field input,.q-field textarea { font-size:13px; }
.q-field__label { font-size:13px; }
.tw-page-title { font-size:26px; font-weight:720; letter-spacing:-.7px; line-height:1.5; }
.tw-detail-header { margin:6px 0 16px; }
.tw-detail-title { font-size:23px; font-weight:720; letter-spacing:-.5px; line-height:1.5; }
.tw-page-subtitle { color:var(--tw-muted); font-size:13px; margin-top:3px; }
.tw-section-title { font-size:17px; font-weight:650; }
.tw-section-heading { margin-bottom:18px; }
.tw-home-heading { margin-bottom:0; }
.tw-home-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; margin:3px 0 0; }
.tw-home-stat { display:flex; min-width:0; gap:15px; padding:18px 21px; }
.tw-home-stat-icon { width:38px; height:38px; flex:0 0 38px; display:flex; align-items:center; justify-content:center; border-radius:10px; background:#edf3ff; color:#3f7af0; }
.tw-home-icon-green { background:#eaf8f1; color:#23a87b; }
.tw-home-icon-purple { background:#f3effe; color:#9a77d5; }
.tw-home-icon-amber { background:#fff6e8; color:#e3a145; }
.tw-home-stat-label,.tw-home-stat-note { color:var(--tw-muted); font-size:12px; line-height:1.7; }
.tw-home-stat-value { color:var(--tw-ink); font-size:28px; line-height:1.2; font-weight:710; letter-spacing:-.8px; margin:2px 0; }
.tw-home-grid { display:grid; grid-template-columns:1.04fr 1fr; gap:20px; align-items:start; }
.tw-home-bottom { display:grid; grid-template-columns:1.45fr 1fr; gap:20px; margin-top:0; }
.tw-home-panel { min-width:0; overflow:hidden; }
.tw-home-task { display:flex; flex-wrap:nowrap; min-width:0; gap:12px; padding:17px 0; border-bottom:1px solid #edf1f6; }
.tw-home-task:last-child { border-bottom:0; }
.tw-home-task-icon { width:38px; height:38px; flex:0 0 38px; display:flex; align-items:center; justify-content:center; border-radius:10px; background:#edf3ff; color:#3f7af0; }
.tw-home-task-copy { flex:1 1 auto; min-width:0; }
.tw-home-task-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:14px; line-height:1.5; font-weight:620; }
.tw-home-task-description { display:block; min-width:0; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#7b899e; font-size:12px; line-height:1.7; }
.tw-home-task-meta { color:#8a98aa; font-size:11px; line-height:1.5; }
.tw-home-tag { padding:3px 8px; border-radius:5px; background:#f0f3f8; color:#748399; white-space:nowrap; }
.tw-home-task-actions { flex:0 0 auto; flex-wrap:nowrap; white-space:nowrap; }
.tw-home-runs { align-self:start; }
.tw-home-run { padding:16px 0; border-bottom:1px solid #edf1f6; }
.tw-home-run:last-of-type { border-bottom:0; }
.tw-status { flex:0 0 auto; border-radius:5px; padding:3px 8px; font-size:11px; white-space:nowrap; }
.tw-status-running { background:#edf3ff; color:#3874df; }
.tw-status-paused,.tw-status-interrupted { background:#fff5e2; color:#b48226; }
.tw-status-failed { background:#fff0f1; color:#d45060; }
.tw-home-progress { height:5px; width:100%; overflow:hidden; border-radius:10px; background:#edf1f7; }
.tw-home-progress > div { height:100%; border-radius:10px; background:var(--tw-blue); }
.tw-home-run-meta { color:#8a97aa; font-size:12px; line-height:1.6; }
.tw-home-pending-heading { padding-top:14px; border-top:1px solid var(--tw-line); }
.tw-section-subtitle { color:#64748b; font-size:13px; font-weight:620; }
.tw-home-pending { padding:12px 0; border-bottom:1px solid #edf1f6; }
.tw-home-pending:last-child { border-bottom:0; }
.tw-home-empty { padding:20px 0; color:#8b9bb1; font-size:13px; }
.tw-home-results .q-table th { background:#f8fafd; color:#8492a7; font-weight:500; }
.tw-home-results .q-table__container,.tw-home-results .q-table__card { box-shadow:none!important; }
.tw-home-results .q-table { border:1px solid var(--tw-line); border-radius:7px; }
.tw-home-results .q-table td,.tw-home-results .q-table th { height:42px; padding:8px 12px; border-color:#edf1f7; font-size:12px; }
.tw-home-quick-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.tw-home-quick-grid .q-btn { justify-content:flex-start; height:auto; min-height:46px; border-radius:8px; }
.tw-task-nav-name .q-btn__content { display:block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-align:left; }
.tw-task-nav-name,.tw-task-nav-name .q-btn__content { color:var(--tw-ink)!important; text-align:left!important; }
.tw-task-nav-name { justify-content:flex-start!important; }
.tw-task-nav-meta { min-width:0; overflow:hidden; white-space:nowrap; color:#8a98aa; font-size:11px; }
.tw-task-summary { display:block; min-width:0; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-task-tabs .q-tabs__content { justify-content:flex-start; }
.tw-task-tabs .q-tab--active,.tw-task-tabs .q-tab--active .q-tab__content,.tw-task-tabs .q-tab--active .q-icon { color:var(--tw-blue)!important; }
.tw-task-tabs .q-tab--active { background:transparent!important; }
.tw-task-tabs .q-tab.q-tab--active { background-color:transparent!important; box-shadow:none!important; }
.tw-task-tabs .q-tab__indicator { background:var(--tw-blue)!important; height:2px; }
.tw-task-variable-table .q-table__container,.tw-task-variable-table .q-table__middle,.tw-task-variable-table .q-table { width:100%; }
.tw-task-variable-table .q-table th { background:#f6f8fc; color:#7b899e; font-weight:500; }
.tw-task-variable-table .q-table td,.tw-task-variable-table .q-table th { height:44px; border-color:#edf1f6; }
.tw-task-header-actions { flex:0 0 auto!important; flex-wrap:nowrap!important; white-space:nowrap; }
.tw-task-header-actions .q-btn { flex:0 0 auto; white-space:nowrap; }
.tw-task-overview-description { white-space:pre-line; line-height:1.9; }
.tw-task-overview-bottom { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.tw-task-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }
.tw-task-stat { min-width:0; padding:12px; background:#f8faff; border-radius:8px; }
.tw-task-stat .text-sm { white-space:nowrap; }
.tw-task-stat-value { font-size:22px; line-height:1.2; font-weight:700; color:var(--tw-ink); }
.tw-plan-list-card { border:1px solid var(--tw-line); border-radius:9px; padding:8px; background:white; }
.tw-plan-list-card.tw-selected { border-color:#92b4ff; background:#edf4ff; }
.tw-plan-list-name .q-btn__content { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-plan-header-summary { display:block; min-width:0; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-plan-layout { display:block; width:100%; min-width:0; }
.tw-plan-form { min-width:0; }
.tw-plan-assist { align-self:start; }
.tw-step-list-item { min-height:38px; padding:7px 9px!important; border:1px solid transparent!important; border-radius:7px!important; background:transparent!important; color:#526079!important; }
.tw-step-list-item .q-btn__content { justify-content:flex-start; text-align:left; white-space:nowrap; overflow:hidden; }
.tw-step-list-item .q-btn__content { display:flex; flex-wrap:nowrap; min-width:0; }
.tw-step-list-item .q-btn__content > span.block { flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-step-list-item .q-btn__content > .q-icon { flex:0 0 auto; }
.tw-editor-panel .q-expansion-item.border { border-color:var(--tw-line)!important; border-radius:8px!important; }
.tw-step-list-heading { margin-bottom:8px; }
.tw-step-list-toolbar .q-btn { width:30px; min-width:30px; min-height:30px; padding:0!important; }
.tw-step-editor-footer { margin-top:8px; }
.tw-plan-history-content { border:1px solid var(--tw-line); border-radius:12px; background:white; padding:16px; }
.tw-plan-history-table-head,.tw-plan-history-row { display:grid; grid-template-columns:minmax(0,1fr) 180px 120px; gap:12px; align-items:center; padding:9px 10px; }
.tw-plan-history-table-head { color:#64748b; font-size:12px; font-weight:600; border-bottom:1px solid var(--tw-line); }
.tw-plan-history-row { border-bottom:1px solid #edf0f5; }
.tw-step-count { min-width:22px; text-align:center; padding:2px 6px; border-radius:10px; color:#718096; background:#f1f4f8; font-size:12px; }
.tw-debug-actions { display:flex; flex-direction:column; }
.tw-debug-action { justify-content:center!important; min-height:38px!important; }
.tw-debug-action-flow { background:white!important; color:var(--tw-blue)!important; border:1px solid #b8cef9!important; }
.tw-debug-action-end { background:#f5f7fb!important; color:#526079!important; border:1px solid var(--tw-line)!important; }
.tw-step-list-item .q-icon { color:#1b9b70!important; }
.tw-step-list-item.tw-selected { background:#edf4ff!important; border-color:#cfdefa!important; color:#2563eb!important; box-shadow:none!important; }
.tw-step-list-item.tw-selected .q-btn__content,.tw-step-list-item.tw-selected .q-icon { color:#2563eb!important; }
.tw-task-nav-name .q-btn__content { display:flex; min-width:0; overflow:hidden; }
.tw-task-nav-name .q-btn__content > span { display:block; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
@media(max-width:1250px) {
 .tw-header { gap:15px; padding:12px 20px; }
 .tw-app-content { padding:22px 20px; }
 .tw-local-indicator { display:none; }
 .tw-home-stats { gap:12px; }
 .tw-home-stat { padding:16px; gap:11px; }
 .tw-home-task { gap:9px; }
 .tw-home-task-actions { gap:5px; }
}
@media(max-width:850px) {
 .tw-header { gap:12px; padding:12px 14px; }
 .tw-main-nav { order:3; flex-basis:100%; overflow-x:auto; }
 .tw-nav { padding:5px 10px; flex:0 0 auto; }
 .tw-app-content { padding:18px 14px 26px; }
 .q-page-container { padding-top:0!important; }
 .tw-home-stats { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
 .tw-home-grid,.tw-home-bottom { grid-template-columns:minmax(0,1fr); gap:14px; }
 .tw-home-task { flex-wrap:nowrap; gap:7px; }
 .tw-home-task-icon { width:32px; height:32px; flex-basis:32px; }
 .tw-home-task-copy { flex:1 1 0; min-width:0; }
 .tw-home-task-actions { margin-left:0; gap:4px; }
 .tw-home-task-actions .q-btn { min-height:30px; padding:3px 7px; font-size:12px; }
 .tw-home-run-footer { flex-wrap:wrap; }
 .tw-task-overview-bottom { grid-template-columns:minmax(0,1fr); }
 .tw-task-stat-grid { grid-template-columns:repeat(4,minmax(0,1fr)); gap:6px; }
 .tw-task-stat { padding:8px 4px; text-align:center; align-items:center; }
 .tw-task-stat-value { font-size:20px; }
}
@media(max-width:1250px) { .tw-market-resource-grid { grid-template-columns:minmax(0,1fr); } }
@media(max-width:850px) { .tw-market-hero { min-height:0; padding:28px; } }
@media(max-width:1390px) { .tw-plan-layout { grid-template-columns:minmax(0,1fr); } }
@media(max-width:1390px) {
 .tw-editor-layout { grid-template-columns:140px minmax(0,1fr); }
 .tw-editor-layout > .tw-step-sidebar { width:140px!important; }
 .tw-editor-layout.tw-debug-open { grid-template-columns:140px minmax(0,1fr) 280px; column-gap:12px; }
}
@media(max-width:900px) {
 .tw-editor-layout.tw-debug-open { grid-template-columns:140px minmax(0,1fr); }
 .tw-editor-panel { min-height:0!important; height:auto!important; overflow:visible!important; }
 .tw-editor-body { width:100%!important; height:auto!important; }
 .tw-debug-column { grid-column:2; grid-row:2; }
 .tw-debug-drawer { position:relative!important; inset:auto!important; width:100%!important; height:auto!important; max-height:420px; }
}
@media(min-width:901px) and (max-width:1199px) {
 .tw-task-workspace:has(.tw-editor-layout.tw-debug-open) > .tw-task-sidebar { width:170px!important; padding:16px; }
 .tw-editor-layout.tw-debug-open { grid-template-columns:110px minmax(0,1fr) 260px; }
 .tw-editor-layout.tw-debug-open > .tw-step-sidebar { width:110px!important; padding:10px; }
 .tw-editor-layout.tw-debug-open > .tw-editor-panel { padding:16px; }
 .tw-editor-layout.tw-debug-open .tw-debug-drawer { padding:14px; }
}
@media(max-width:1100px) { .tw-executions-master { grid-template-columns:230px minmax(0,1fr); gap:12px; } .tw-execution-filters { width:230px!important; } }
@media(max-width:780px) {
 .tw-executions-master { grid-template-columns:minmax(0,1fr); gap:12px; }
 .tw-execution-filters { width:100%!important; max-height:none; overflow:visible; }
 .tw-run-list { max-height:300px; overflow:auto; }
 .tw-run-summary-card,.tw-run-progress-card,.tw-current-results,.tw-run-history { padding:14px; }
 .tw-env-variable-row { grid-template-columns:repeat(2,minmax(0,1fr)); }
}
@media(max-width:850px) {
 .tw-settings-nav-options { display:grid!important; grid-template-columns:repeat(4,minmax(0,1fr)); gap:4px; }
 .tw-settings-sidebar { width:100%!important; }
 .tw-settings-nav { min-width:0!important; padding:5px 3px!important; font-size:11px!important; }
 .tw-settings-nav .q-btn__content { justify-content:center!important; white-space:normal; text-align:center; }
 .tw-settings-sidebar .tw-settings-nav.tw-settings-nav-active { background:#edf4ff!important; border-color:#9dbbff!important; }
 .tw-step-execution-overview { grid-template-columns:minmax(0,1fr); }
}
@media(max-width:850px) {
 .tw-step-editor-tabs .q-tabs__content { display:grid!important; grid-template-columns:repeat(2,minmax(0,1fr)); height:auto!important; min-height:80px; }
 .tw-step-editor-tabs .q-tab { min-width:0!important; min-height:40px; padding:3px 4px!important; }
 .tw-step-editor-tabs .q-tab__content { width:100%; min-width:0; white-space:normal!important; }
 .tw-step-editor-tabs .q-tab__label { max-width:100%; white-space:normal!important; text-align:center; line-height:1.2; }
}
@media(max-width:1100px) {
 .tw-plan-sidebar-heading { justify-content:space-between; }
 .tw-plan-category-toolbar { justify-content:flex-start!important; }
}
@media(max-width:520px) {
 .tw-page-title { font-size:23px; }
 .tw-home-stat { padding:12px; gap:10px; }
 .tw-home-stat-value { font-size:24px; }
 .tw-home-stat-icon { width:34px; height:34px; flex-basis:34px; }
 .tw-home-task-actions { margin-left:0; }
 .tw-home-quick-grid { grid-template-columns:minmax(0,1fr); }
}
.tw-planning-workspace { display:flex!important; flex-direction:column; align-items:stretch; gap:12px; width:100%; }
.tw-planning-columns { display:grid!important; grid-template-columns:minmax(0,1fr) minmax(270px,320px); align-items:start; gap:16px; }
.tw-planning-main { width:100%; min-width:0; }
.tw-plan-materials,.tw-plan-history,.tw-plan-layout { width:100%; min-width:0; }
.tw-plan-assist { width:100%; min-width:0; max-height:calc(100vh - 108px); overflow:auto; position:sticky; top:90px; }
.tw-context-cards { width:100%; min-width:0; }
.tw-context-heading { padding:2px 0 6px; }
.tw-context-group { background:#fff; border-color:var(--tw-line)!important; }
.tw-context-group-heading { min-width:0; }
.tw-context-index,.tw-context-capture-index { display:inline-flex; justify-content:center; min-width:24px; padding:2px 6px; border-radius:6px; color:#536680; background:#f0f4fa; font-size:12px; }
.tw-context-group-name,.tw-context-capture-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tw-context-provider { padding:3px 8px; border-radius:6px; background:#eef3ff; color:#4166a7; font-size:12px; }
.tw-context-notes { overflow-wrap:anywhere; }
.tw-context-capture-row { border-top:1px solid var(--tw-line); padding:8px 0 4px; }
.tw-context-capture-meta { color:var(--tw-muted); font-size:11px; }
.tw-context-capture-preview { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; }
.tw-context-empty { padding:12px; border:1px dashed var(--tw-line); border-radius:8px; }
/* Context surfaces share presentation; capture state stays in the page controllers. */
.tw-context-group { border-radius:12px; padding:16px; gap:10px; }
.tw-context-group-heading { gap:8px; }
.tw-context-group-name { font-weight:600; }
.tw-context-provider { font-size:11px; background:#f3f5f9; color:var(--tw-muted); }
.tw-context-notes { color:var(--tw-muted); font-size:13px; line-height:1.6; }
.tw-context-capture-row { padding:8px 0; }
.tw-context-capture-index { background:transparent; color:var(--tw-muted); }
.tw-context-group-actions .q-btn,.tw-context-capture-actions .q-btn { font-size:12px; }
.tw-context-staged-row { border:1px solid var(--tw-line); border-radius:10px; padding:10px 12px; background:#fafbfd; }
.tw-context-staged-label { flex:1 1 220px; min-width:160px; }
.tw-context-staged-row .q-btn { font-size:12px; }
.tw-context-preview-dialog { width:min(1100px,calc(100vw - 48px)); max-width:none!important; max-height:calc(100dvh - 48px)!important; padding:0!important; gap:0; overflow:hidden; }
.tw-context-preview-header { flex:none; padding:20px 24px 16px; border-bottom:1px solid var(--tw-line); }
.tw-context-preview-body { min-height:0; flex:1 1 auto; overflow:auto; padding:20px 24px; gap:20px; }
.tw-context-preview-body > * { flex-shrink:0; min-width:0; }
.tw-context-preview-media { flex-shrink:0; }
.tw-context-preview-media .q-img { flex:none; border:1px solid var(--tw-line); border-radius:8px; background:#f6f8fb; }
.tw-context-preview-media .q-img__image { object-fit:contain!important; }
.tw-context-raw { border:1px solid var(--tw-line); border-radius:8px; background:#f8fafc; }
.tw-context-raw pre { max-height:320px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; }
.tw-context-preview-footer { flex:none; padding:12px 24px; border-top:1px solid var(--tw-line); background:white; }
@media(max-width:800px) {
 .tw-context-preview-dialog { width:calc(100vw - 24px); max-height:calc(100dvh - 24px)!important; }
 .tw-context-preview-header,.tw-context-preview-body,.tw-context-preview-footer { padding:14px 16px; }
 .tw-context-staged-label { flex-basis:100%; }
}
.tw-context-collection-dialog { display:flex; flex-direction:column; max-height:calc(100dvh - 32px); overflow-y:auto; }
.tw-context-dialog-note { padding:10px 12px; border:1px solid #cfe0ff; border-radius:8px; background:#f3f7ff; color:#476a9e; font-size:13px; }
.tw-context-dialog-actions { position:sticky; bottom:0; padding-top:8px; background:#fff; }
.tw-context-dialog-fields > * { flex:1 1 0; }
.tw-repair-mode-dialog { display:flex; flex-direction:column; gap:14px; max-height:calc(100dvh - 32px); overflow:auto; }
.tw-repair-dialog-header { flex:0 0 auto; }
.tw-repair-evidence { padding:12px; border:1px solid var(--tw-line); border-radius:8px; background:#f8faff; }
.tw-repair-no-evidence { padding:12px; border:1px solid #efd8a0; border-radius:8px; background:#fff9eb; color:#785b20; }
.tw-repair-supplement textarea { min-height:110px; max-height:32vh; overflow:auto; }
.tw-repair-dialog-actions { flex:0 0 auto; }
@media(max-width:1100px) {
 .tw-planning-columns { grid-template-columns:minmax(0,1fr) minmax(245px,32%); gap:12px; }
 .tw-plan-assist { padding:14px; }
}
@media(max-width:850px) {
 .tw-planning-columns { grid-template-columns:minmax(0,1fr); }
 .tw-plan-assist { position:static; max-height:none; }
 .tw-context-group-heading { align-items:flex-start; }
 .tw-context-group-actions,.tw-context-capture-actions { justify-content:flex-start; }
 .tw-context-dialog-fields { flex-wrap:wrap; }
 .tw-context-dialog-fields > * { flex-basis:100%; }
 .tw-context-collection-dialog { width:calc(100vw - 24px)!important; max-width:none!important; padding:16px!important; }
 .tw-repair-mode-dialog { width:calc(100vw - 24px)!important; max-width:none!important; padding:16px!important; }
}
@media(prefers-reduced-motion:reduce) { * { scroll-behavior:auto!important; transition:none!important; animation:none!important; } }
"""
