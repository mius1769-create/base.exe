"""Поправки к CSS макета для разметки NeSToR, тёмная тема и локальный скрипт переключения.

В макете тёмной темы нет: палитра ниже составлена на тех же цветах. Тема хранится в cookie
nestor_theme; без неё следует настройке системы. Скрипт только переключает тему без перезагрузки,
чтобы не терять результаты поиска; без скриптов работает обычная форма POST /theme.
"""

from __future__ import annotations

from .design_css import DESIGN_CSS

THEME_COOKIE = "nestor_theme"
THEMES = ("light", "dark")

PATCH_CSS = """
.navbar a{display:block;white-space:nowrap;position:relative;color:#7b858c;font-size:12px;font-weight:500;padding:8px 0 11px}
.navbar a:hover{text-decoration:none;color:var(--blue)} .navbar a.on{color:var(--blue)}
.navbar a.on:after{content:"";position:absolute;bottom:0;left:0;right:0;height:2px;background:var(--blue)}
.rolebar a{color:#78848d;font-size:11px;padding:5px 12px;font-weight:500;border-radius:6px} .rolebar a:hover{text-decoration:none}
.rolebar a.on{color:var(--ink);background:#fff;box-shadow:0 1px 4px #23334516}
.top-gap{margin-left:auto} .account form{margin:0} .theme-toggle{padding:4px 8px;font-size:13px;line-height:1.2}
.lead{font-size:13px;color:var(--muted);margin:7px 0 18px} .page-head .lead{margin:7px 0 0} .crumb{margin:9px 0 7px}
.card p,.help-body p{margin:0 0 10px} .card h2,.card h3{margin:0 0 10px} .card.flush>p{margin:8px 0} .card.flush h2{margin:0}
.filters>label{flex:1 1 130px} .filters>button{flex:0 0 auto} .filters.short>label:nth-child(3){flex:2 1 200px}
.tabs button.on{color:var(--blue);font-weight:600;box-shadow:none} .tabs button.on:after{content:"";height:2px;position:absolute;bottom:-1px;left:0;right:0;background:var(--blue)}
.card:not(.flush) .tabs{padding:0}
.gd.g-mid{background:#faf2df;color:#9d792e} .gd.g-far{background:#f5eaea;color:#a76464} .gd.g-near{background:#e9f4ec;color:#3c7e5a}
.pill.warn-pill{background:#fbf2e3;color:var(--amber);font-family:inherit;font-weight:500;letter-spacing:0}
table .sub{font-size:10px;color:#8b969e;margin-top:4px;line-height:1.5} .panel .sub{margin-top:6px}
.switch:disabled{cursor:default} .stat{font-size:12px;font-weight:550} a.stat{color:inherit} a.stat:hover{text-decoration:none}
.demo-strip{min-height:41px} .footer{min-height:76px}
.btn-link{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:7px 12px;font-size:12px;font-weight:550;white-space:nowrap}
a.btn-link:hover{text-decoration:none;background:#256887} .contextbar select{flex:0 1 auto;min-width:0}
a.quiet{font-size:12px} .panel-title a.quiet{font-size:11px} .tabs a{padding:10px 0;color:var(--muted);font-size:12px;position:relative;white-space:nowrap} .tabs a:hover{text-decoration:none}
.tabs a.active{color:var(--blue);font-weight:600} .tabs a.active:after{content:"";height:2px;position:absolute;bottom:-1px;left:0;right:0;background:var(--blue)}
.empty{text-align:center} .card .empty,.help-body .empty{padding:18px} .form-note{margin-top:14px}
.card{overflow-x:auto} .head-actions form{margin:0}
@media(max-width:760px){.account{display:flex;margin-left:auto}.account>span,.account .avatar{display:none}.filters>label{flex:1 1 100%}.filters.short>label:nth-child(-n+2){flex:1 1 40%}.filters>button{flex:1 1 100%}}
"""

DARK_RULES = """
@{color-scheme:dark;--bg:#141a1f;--paper:#1c252c;--ink:#e3e9ed;--muted:#93a2ac;--line:#2f3b44;--blue:#6db3d8;--pale:#1d3442;--green:#6fc2a2;--amber:#d9ad68;--red:#e39393}
@ .site-header,@ .stat,@ .panel,@ .project,@ .contextbar,@ .card,@ .disclosure,@ .group-list details,@ .drawer,@ dialog{background:var(--paper)}
@ button,@ input,@ select,@ textarea{background:#20292f;color:var(--ink);border-color:#3a4852}
@ button:hover{background:#27323a;border-color:#4a5a66}
@ .primary,@ button.primary{background:#2f7aa3;border-color:#2f7aa3;color:#fff} @ .primary:hover,@ button.primary:hover{background:#3a8ab5;color:#fff}
@ .quiet,@ .quiet:hover,@ .tabs button,@ .tabs button:hover,@ .close,@ .cell-link{background:transparent;border-color:transparent}
@ .brand small,@ .demo-strip,@ .footer,@ .name-sub,@ .caption,@ .mini-label,@ th,@ table .sub,@ .navbar a,@ .rolebar a,@ .tabs button{color:var(--muted)}
@ .navbar a.on,@ .tabs button.on,@ .tabs a.active,@ .footer a{color:var(--blue)} @ .tabs a{color:var(--muted)}
@ .rolebar{background:#141a1f;border-color:var(--line)} @ .rolebar a.on{color:var(--ink);background:var(--paper);box-shadow:none}
@ .avatar{background:#27323a;color:#a9c0cd}
@ .stat:hover{background:var(--paper);border-color:#47606f;box-shadow:none}
@ .contextbar select{background:#20292f}
@ th{background:#222c33} @ td{border-top-color:var(--line)} @ tbody tr:hover{background:#222c33}
@ .pill,@ .state,@ .tag,@ .tabs .n,@ .navcount{background:#27323a;color:#a9b8c2}
@ .pill.green,@ .state.green{background:#1e3a30;color:var(--green)} @ .pill.blue,@ .tag-agg{background:var(--pale);color:var(--blue)}
@ .pill.amber,@ .state.amber,@ .tag-warn,@ .pill.warn-pill{background:#3a2f1c;color:var(--amber)} @ .pill.red,@ .state.red{background:#3f2525;color:var(--red)}
@ .pill.purple{background:#2e2740;color:#bda4dc}
@ .gd,@ .gd.g-near{background:#1e3a30;color:var(--green)} @ .gd.mid,@ .gd.g-mid{background:#3a2f1c;color:var(--amber)} @ .gd.far,@ .gd.g-far{background:#3f2525;color:var(--red)}
@ .info{background:#1d3442;color:#a6cbe0;border-color:#2c4a5c} @ .info.warm{background:#3a2f1c;color:#e0c48f;border-color:#4d3f27}
@ .settings-row,@ .timeline-row,@ .tree-row{border-color:var(--line)} @ .switch{background:#3a4852} @ .switch:before{background:#dfe6ea}
@ .filters,@ .drop{background:#20292f} @ code,@ pre{background:#27323a;color:var(--ink)} @ summary.btn{color:var(--ink)}
@ .bar{background:#2c3840} @ .locus{background:#20292f} @ .predictor{background:#20292f;border-color:var(--line)}
@ .chat-body{background:#182026} @ .bubble{background:#27323a} @ .bubble.self{background:var(--pale)} @ .thread.active{background:var(--pale)}
@ .result-summary{background:var(--paper)} @ .result-summary:hover{background:#222c33}
@ .filters label,@ .row label,@ .forms label{color:var(--muted)}
"""


def _dark(prefix: str) -> str:
    return DARK_RULES.replace("@", prefix)


THEME_CSS = (DESIGN_CSS + PATCH_CSS + ":root[data-theme=light]{color-scheme:light}\n"
             + _dark(":root[data-theme=dark]")
             + "@media (prefers-color-scheme:dark){" + _dark(":root:not([data-theme=light])") + "}\n")

THEME_JS = """(function () {
  var kit = document.getElementById('active-kit');
  var apply = document.getElementById('kit-apply');
  if (kit && apply) {
    apply.hidden = true;
    kit.addEventListener('change', function () { kit.form.submit(); });
  }
  var button = document.getElementById('theme-toggle');
  if (!button || !button.form) return;
  button.form.addEventListener('submit', function (event) {
    event.preventDefault();
    var root = document.documentElement;
    var dark = root.dataset.theme ? root.dataset.theme === 'dark'
                                  : window.matchMedia('(prefers-color-scheme: dark)').matches;
    var next = dark ? 'light' : 'dark';
    root.dataset.theme = next;
    document.cookie = 'nestor_theme=' + next + '; path=/; max-age=31536000; SameSite=Strict';
  });
})();
"""
