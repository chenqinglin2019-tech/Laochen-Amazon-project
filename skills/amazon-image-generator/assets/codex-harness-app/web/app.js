"use strict";

/* ==========================================================
   飞鱼神图 · Codex Harness 自定义栏目
   ----------------------------------------------------------
   页面结构、设计令牌与交互复刻 assets/reference-page/feiyushentu-page.html，
   与该基线保持 1:1。差别只有传输层：这里不在浏览器里持有 Token，
   所有请求走本栏目的同源后端，由后端调用 CLI 与飞鱼神图通信。
   ========================================================== */

const API_ROOT = "/custom-api/amazon-image-generator";
let csrfToken = null;

async function loadSession(force = false) {
  if (csrfToken && !force) return csrfToken;
  const response = await fetch("/api/v1/session", { headers: { accept: "application/json" } });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("请先登录 Codex Harness。");
  }
  if (!response.ok) throw new Error("无法读取登录状态。");
  let envelope = null;
  try { envelope = await response.json(); } catch (_error) { /* handled below */ }
  if (!envelope || typeof envelope !== "object" || !envelope.data) {
    throw new Error("登录接口返回异常，请刷新页面；若仍失败，请检查 Codex Harness 服务。");
  }
  const session = envelope.data;
  if (!session || session.role !== "root") throw new Error("飞鱼神图栏目当前仅对管理员开放。");
  csrfToken = session.csrfToken;
  return csrfToken;
}

async function api(path, options = {}, retryCsrf = true) {
  const init = { ...options, headers: { accept: "application/json", ...(options.headers || {}) } };
  const method = (init.method || "GET").toUpperCase();
  if (method !== "GET") {
    init.headers["x-csrf-token"] = await loadSession();
  }
  const response = await fetch(API_ROOT + path, init);
  let envelope = null;
  try { envelope = await response.json(); } catch (_error) { /* handled below */ }
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("请先登录 Codex Harness。");
  }
  if (response.status === 403 && envelope?.error?.code === "csrf_invalid" && retryCsrf) {
    await loadSession(true);
    return api(path, options, false);
  }
  if (!response.ok) {
    const error = new Error(envelope?.error?.message || `请求失败（HTTP ${response.status}）`);
    error.code = envelope?.error?.code || "request_failed";
    throw error;
  }
  if (!envelope || typeof envelope !== "object" || !Object.prototype.hasOwnProperty.call(envelope, "data") || envelope.data === null) {
    const error = new Error("飞鱼神图 API 未正确连接，请重新运行安装修复后刷新页面。");
    error.code = "invalid_api_response";
    throw error;
  }
  return envelope.data;
}

/* ==========================================================
   选项归一化：显示读 name，提交读 value
   ----------------------------------------------------------
   接口里 name 是给人看的名称，value 才是回传的取值，两者必须分开。
   其余字段名只作为兜底，接口换形状时不至于直接空白。
   契约见 references/api.md 的 “Option Shape”。
   纯函数，放在模块顶层以便回归测试。
   ========================================================== */
function has(x) { return x !== undefined && x !== null && x !== ""; }

function pair(o) {
  if (o && typeof o === "object") {
    const v = has(o.value) ? o.value
            : has(o.key)   ? o.key
            : has(o.id)    ? o.id
            : has(o.name)  ? o.name
            : o.label;
    const t = has(o.name)  ? o.name
            : has(o.label) ? o.label
            : has(o.title) ? o.title
            : v;
    return { value: String(v), label: String(t) };
  }
  return { value: String(o), label: String(o) };
}

function modelName(m) {
  return String(has(m.name) ? m.name : has(m.label) ? m.label : m.value);
}

/* ==========================================================
   页面：全部 DOM 逻辑都在 boot 内，模块加载本身不触碰 document
   ========================================================== */
function boot() {
  /* ==========================================================
     0 · 基础
     ========================================================== */
  const $  = (id) => document.getElementById(id);
  const te = new TextEncoder();
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
  const pad = (n) => String(n).padStart(2,"0");

  const RECOMMEND_MODEL = "1|nano-banana-2";
  const RECOMMEND_STYLE = "亚马逊风格";
  const FIXED_DEFAULTS  = { language:"en", style:RECOMMEND_STYLE, scene:"混合 (以使用场景为主)" };
  const FIELD_CN = { aspect_ratio:"尺寸", resolution:"像素", style:"风格", language:"目标语言", scene:"场景" };

  const POLL_INTERVAL = 5000, POLL_MAX = 120, POLL_DEADLINE = 10*60*1000;
  const MAX_FILES = 6, MAX_FILE_BYTES = 12*1024*1024;

  const state = {
    tokenOk:false,
    config:null, model:null, modelSetting:{}, fixedSetting:{},
    refs:[], refSeq:0,
    tasks:[], shots:[], lastPayload:null,
    running:false, polling:false,
    lb:{items:[],index:0,taskId:"",title:""},
    his:{page:1,size:5,start:"",end:"",range:"all",total:0,loading:false}
  };

  /* ==========================================================
     1 · 提示
     ========================================================== */
  /* 全部提示都走弹出式 toast，页面本体不再插入提示模块 */
  const TST_IC = {
    ok  : '<path d="M4.5 12.4 9.6 17.5 19.5 7"/>',
    bad : '<path d="M12 6.5v7"/><path d="M12 17.4h.01"/>',
    info: '<path d="M12 10.6v6.8"/><path d="M12 6.7h.01"/>'
  };
  const toastBox = $("toasts");
  /* toast(msg, kind, opts)
     msg  : 允许少量行内 HTML（调用方负责转义）
     kind : "ok" | "bad" | 空（默认信息）
     opts : { action:{label,onClick}, timeout:ms（0 = 常驻）, key:去重键 } */
  function toast(msg, kind, opts){
    opts = opts || {};
    if(opts.key) toastBox.querySelectorAll('[data-key="'+opts.key+'"]').forEach(n => n.remove());
    const el = document.createElement("div");
    el.className = "tst" + (kind ? " " + kind : "");
    if(opts.key) el.dataset.key = opts.key;
    el.innerHTML =
      '<span class="tst-i"><svg viewBox="0 0 24 24" aria-hidden="true">' +
        (TST_IC[kind] || TST_IC.info) + '</svg></span>' +
      '<span class="tst-t"></span>' +
      (opts.action ? '<button class="tst-a" type="button"></button>' : '') +
      '<button class="tst-x" type="button" aria-label="关闭提示">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>';
    el.querySelector(".tst-t").innerHTML = msg;
    let timer = null;
    const kill = () => {
      clearTimeout(timer);
      el.classList.add("out");
      setTimeout(() => el.remove(), 220);
    };
    el.querySelector(".tst-x").addEventListener("click", kill);
    if(opts.action){
      const b = el.querySelector(".tst-a");
      b.textContent = opts.action.label;
      b.addEventListener("click", () => { kill(); opts.action.onClick(); });
    }
    toastBox.appendChild(el);
    while(toastBox.children.length > 4) toastBox.firstElementChild.remove();
    const ms = opts.timeout === undefined ? (kind === "bad" ? 6500 : 3400) : opts.timeout;
    if(ms > 0){
      timer = setTimeout(kill, ms);
      el.addEventListener("mouseenter", () => clearTimeout(timer));
      el.addEventListener("mouseleave", () => { timer = setTimeout(kill, 1600); });
    }
    return kill;
  }
  function clearToasts(key){
    const sel = key ? '[data-key="'+key+'"]' : ".tst";
    toastBox.querySelectorAll(sel).forEach(n => n.remove());
  }

  function werr(id, msg){
    const el = $(id); if(!el) return;
    el.textContent = msg || "";
    el.classList.toggle("on", !!msg);
  }

  /* ==========================================================
     2 · API
     ========================================================== */
  /* 所有请求都走本栏目的同源后端；Token 只在服务端保存，浏览器不持有。 */
  const TOKEN_CODES = ["token_required","token_invalid","token_save_failed"];

  function onApiError(err){
    if(err && TOKEN_CODES.indexOf(err.code) >= 0){
      setToken(false);
      toast(esc(err.message || "请先配置 Token。"), "bad", { key:"token", timeout:0,
        action:{ label:"配置 Token", onClick:() => $("token-btn").click() } });
    }else{
      toast(esc((err && err.message) || "请求失败"), "bad");
    }
  }

  /* ==========================================================
     3 · ZIP（纯手写 · store 模式 · 零依赖）
     ========================================================== */
  const CRC_T = (function(){
    const t = new Uint32Array(256);
    for(let n=0;n<256;n++){ let c=n; for(let k=0;k<8;k++) c = (c&1) ? (0xEDB88320 ^ (c>>>1)) : (c>>>1); t[n]=c>>>0; }
    return t;
  })();
  function crc32(buf){
    let c = 0xFFFFFFFF;
    for(let i=0;i<buf.length;i++) c = CRC_T[(c ^ buf[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }
  function makeZip(files){
    const now = new Date();
    const dtime = ((now.getHours()<<11) | (now.getMinutes()<<5) | (now.getSeconds()>>1)) & 0xFFFF;
    const ddate = (((now.getFullYear()-1980)<<9) | ((now.getMonth()+1)<<5) | now.getDate()) & 0xFFFF;
    const parts = [], central = [];
    let offset = 0, cdSize = 0;

    for(const f of files){
      const name = te.encode(f.name), data = f.data;
      const crc = crc32(data), size = data.length;

      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0,0x04034b50,true); lh.setUint16(4,20,true); lh.setUint16(6,0x0800,true);
      lh.setUint16(8,0,true); lh.setUint16(10,dtime,true); lh.setUint16(12,ddate,true);
      lh.setUint32(14,crc,true); lh.setUint32(18,size,true); lh.setUint32(22,size,true);
      lh.setUint16(26,name.length,true); lh.setUint16(28,0,true);
      parts.push(new Uint8Array(lh.buffer), name, data);

      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0,0x02014b50,true); ch.setUint16(4,20,true); ch.setUint16(6,20,true);
      ch.setUint16(8,0x0800,true); ch.setUint16(10,0,true);
      ch.setUint16(12,dtime,true); ch.setUint16(14,ddate,true);
      ch.setUint32(16,crc,true); ch.setUint32(20,size,true); ch.setUint32(24,size,true);
      ch.setUint16(28,name.length,true); ch.setUint16(30,0,true); ch.setUint16(32,0,true);
      ch.setUint16(34,0,true); ch.setUint16(36,0,true); ch.setUint32(38,0,true);
      ch.setUint32(42,offset,true);
      central.push(new Uint8Array(ch.buffer), name);
      cdSize += 46 + name.length;
      offset += 30 + name.length + size;
    }

    const eo = new DataView(new ArrayBuffer(22));
    eo.setUint32(0,0x06054b50,true); eo.setUint16(4,0,true); eo.setUint16(6,0,true);
    eo.setUint16(8,files.length,true); eo.setUint16(10,files.length,true);
    eo.setUint32(12,cdSize,true); eo.setUint32(16,offset,true); eo.setUint16(20,0,true);

    return new Blob(parts.concat(central, [new Uint8Array(eo.buffer)]), {type:"application/zip"});
  }

  /* ---------- 下载 ---------- */
  function saveBlob(blob, filename){
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 5000);
  }
  function extOf(url, mime){
    const m = /\.(png|jpe?g|webp|gif)(?:$|\?)/i.exec(url || "");
    if(m) return m[1].toLowerCase() === "jpeg" ? "jpg" : m[1].toLowerCase();
    if(mime && mime.indexOf("/") > 0) return mime.split("/")[1].split("+")[0];
    return "png";
  }
  async function fetchBytes(url){
    const r = await fetch(url, {mode:"cors"});
    if(!r.ok) throw new Error("HTTP " + r.status);
    const blob = await r.blob();
    return { bytes:new Uint8Array(await blob.arrayBuffer()), mime:blob.type };
  }
  async function downloadOne(url, filename){
    try{
      const got = await fetchBytes(url);
      saveBlob(new Blob([got.bytes],{type:got.mime||"image/png"}), filename);
      return true;
    }catch(e){
      window.open(url, "_blank", "noopener");
      return false;
    }
  }
  async function downloadZip(urls, zipName, btn){
    if(!urls || !urls.length) return;
    const old = btn ? btn.innerHTML : "";
    if(btn){ btn.disabled = true; btn.innerHTML = '<span class="spin" style="border-color:rgba(0,0,0,.18);border-top-color:currentColor"></span>打包中'; }
    const files = [], failed = [];
    for(let i=0;i<urls.length;i++){
      try{
        const got = await fetchBytes(urls[i]);
        files.push({ name: zipName + "_" + pad(i+1) + "." + extOf(urls[i], got.mime), data: got.bytes });
      }catch(e){ failed.push(urls[i]); }
    }
    if(btn){ btn.disabled = false; btn.innerHTML = old; }

    if(!files.length){
      toast("图片域名未开放跨域，无法在浏览器内打包。已改为逐张打开，可右键另存。", "bad");
      urls.forEach(u => window.open(u, "_blank", "noopener"));
      return;
    }
    saveBlob(makeZip(files), zipName + ".zip");
    if(failed.length) toast("已打包 " + files.length + " 张，" + failed.length + " 张抓取失败已单独打开。", "bad");
    else toast("已打包下载 " + files.length + " 张图片", "ok");
  }

  /* ==========================================================
     4 · Token
     ========================================================== */
  function setToken(ok){
    state.tokenOk = ok;
    $("token-state").textContent = ok ? "已配置" : "未配置";
    $("token-dot").className = "dot " + (ok ? "ok" : "");
    $("token-btn").dataset.on = ok ? "1" : "0";
    gate();
  }
  const tkDlg = $("tk-dlg");
  function insecureTransport(){
    return !window.isSecureContext &&
           ["localhost","127.0.0.1","::1"].indexOf(window.location.hostname) < 0;
  }
  $("token-btn").addEventListener("click", () => {
    werr("e-token",""); $("tk-in").value = "";
    const insecure = insecureTransport();
    $("tk-ack").hidden = !insecure;
    $("tk-ack-box").checked = false;
    tkDlg.showModal(); $("tk-in").focus();
  });
  $("tk-cancel").addEventListener("click", () => tkDlg.close());
  tkDlg.addEventListener("close", () => { $("tk-in").value = ""; });

  $("tk-save").addEventListener("click", async () => {
    const v = $("tk-in").value.trim();
    if(!v){ werr("e-token","请输入飞鱼神图的token"); $("tk-in").focus(); return; }
    const insecure = !$("tk-ack").hidden;
    if(insecure && !$("tk-ack-box").checked){
      werr("e-token","请先确认 HTTP 明文传输风险。"); $("tk-ack-box").focus(); return;
    }
    const btn = $("tk-save"), lab = $("tk-save-l");
    btn.disabled = true; lab.textContent = "验证中…"; werr("e-token","");
    try{
      const headers = { "content-type":"application/json" };
      if(insecure) headers["x-insecure-token-ack"] = "confirmed";
      await api("/api/token", { method:"POST", headers:headers, body: JSON.stringify({ token: v }) });
      $("tk-in").value = "";
      setToken(true);
      tkDlg.close(); clearToasts("token");
      toast("Token 已保存", "ok");
      await loadConfig();
    }catch(err){
      werr("e-token", err.message || "验证失败");
    }finally{
      btn.disabled = false; lab.textContent = "保存并验证";
    }
  });

  /* 配置：后端用 CLI 拉取，返回 build_config_summary 的结构 */
  async function loadConfig(){
    try{
      const data = await api("/api/config");
      applyConfig(normalizeSummary(data.summary || {}));
    }catch(err){ onApiError(err); }
  }
  /* summary 把 fixedSetting[].value 重命名成了 options，这里还原成页面使用的结构 */
  function normalizeSummary(summary){
    return {
      fixedSetting: (summary.fixedSetting || []).map(it => ({
        title: it.title, field: it.field, default: it.default, value: it.options || []
      })),
      model: summary.model || []
    };
  }

  /* ==========================================================
     5 · 配置渲染
     ========================================================== */
  /* 把已提交的取值翻译回名称，用于摘要与历史展示 */
  function labelOfFixed(key, val){
    const items = (state.config && state.config.fixedSetting) || [];
    const it = items.find(x => x.field === key);
    const opts = it && Array.isArray(it.value) ? it.value.map(pair) : [];
    const hit = opts.find(o => o.value === String(val));
    return hit ? hit.label : String(val);
  }

  /* ---------- 自定义下拉：面板挂到 body，fixed 定位，永不被卡片裁切 ---------- */
  const selPop = document.createElement("div");
  selPop.className = "sel-pop"; selPop.id = "sel-pop";
  selPop.setAttribute("role","listbox"); selPop.hidden = true;
  document.body.appendChild(selPop);
  let openSel = null;

  function closeSel(){
    if(!openSel) return;
    openSel.btn.setAttribute("aria-expanded","false");
    openSel.btn.removeAttribute("aria-activedescendant");
    selPop.hidden = true; selPop.innerHTML = "";
    openSel = null;
  }
  function placePop(){
    if(!openSel) return;
    const r = openSel.btn.getBoundingClientRect();
    const vh = window.innerHeight, gapv = 6, edge = 10;
    selPop.style.width = Math.max(r.width, 132) + "px";
    selPop.style.maxHeight = "320px";
    const ph = Math.min(selPop.scrollHeight + 2, 320);
    const below = vh - r.bottom - gapv - edge;
    const above = r.top - gapv - edge;
    if(below >= ph || below >= above){
      selPop.dataset.dir = "down";
      selPop.style.maxHeight = Math.max(120, Math.min(320, below)) + "px";
      selPop.style.top = Math.round(r.bottom + gapv) + "px";
    }else{
      selPop.dataset.dir = "up";
      const h = Math.max(120, Math.min(320, above));
      selPop.style.maxHeight = h + "px";
      selPop.style.top = Math.round(r.top - gapv - Math.min(ph, h)) + "px";
    }
    const w = parseFloat(selPop.style.width);
    selPop.style.left = Math.round(Math.min(Math.max(edge, r.left), window.innerWidth - w - edge)) + "px";
    // 兜底：无论触发器在哪，面板始终留在视口内
    const top = parseFloat(selPop.style.top);
    const hh = Math.min(parseFloat(selPop.style.maxHeight), selPop.scrollHeight + 2);
    selPop.style.top = Math.round(Math.min(Math.max(edge, top), Math.max(edge, vh - hh - edge))) + "px";
  }
  function paintPop(){
    const s = openSel;
    selPop.innerHTML = s.options.map((o,i) =>
      '<div class="sel-opt'+(o.value===s.value?" on":"")+(i===s.active?" hi":"")+'" role="option" ' +
        'id="sel-opt-'+i+'" data-i="'+i+'" aria-selected="'+(o.value===s.value)+'">' +
        '<span class="t">'+esc(o.label)+'</span>' +
        (o.badge ? '<span class="b">'+esc(o.badge)+'</span>' : '') +
        '<svg class="ck" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>' +
      '</div>').join("");
    s.btn.setAttribute("aria-activedescendant", "sel-opt-" + s.active);
    const hi = selPop.querySelector(".sel-opt.hi");
    if(hi) hi.scrollIntoView({block:"nearest"});
  }
  selPop.addEventListener("mousedown", e => {
    const el = e.target.closest("[data-i]"); if(!el || !openSel) return;
    e.preventDefault();
    openSel.pick(Number(el.dataset.i));
  });
  selPop.addEventListener("mousemove", e => {
    const el = e.target.closest("[data-i]"); if(!el || !openSel) return;
    const i = Number(el.dataset.i);
    if(i !== openSel.active){ openSel.active = i; paintPop(); }
  });
  document.addEventListener("mousedown", e => {
    if(openSel && !selPop.contains(e.target) && !openSel.btn.contains(e.target)) closeSel();
  });
  window.addEventListener("scroll", () => { if(openSel) placePop(); }, true);
  window.addEventListener("resize", closeSel);

  function createSelect(cfg){
    const wrap = document.createElement("div");
    wrap.className = "sel";
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "sel-btn";
    btn.setAttribute("role","combobox");
    btn.setAttribute("aria-haspopup","listbox");
    btn.setAttribute("aria-expanded","false");
    btn.setAttribute("aria-controls","sel-pop");
    if(cfg.id) btn.id = cfg.id;
    if(cfg.labelledby) btn.setAttribute("aria-labelledby", cfg.labelledby + (cfg.id ? " " + cfg.id : ""));
    btn.innerHTML = '<span class="sel-val"></span>' +
      '<svg class="sel-chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    wrap.appendChild(btn);

    const api = {
      el: wrap, btn: btn,
      options: (cfg.options || []).slice(),
      value: cfg.value !== undefined ? String(cfg.value) : "",
      placeholder: cfg.placeholder || "请选择",
      onChange: cfg.onChange || function(){},
      active: 0,
      paint(){
        const o = this.options.find(x => x.value === this.value);
        const v = btn.querySelector(".sel-val");
        v.textContent = o ? o.label : this.placeholder;
        v.classList.toggle("ph", !o);
        const old = btn.querySelector(".sel-tag");
        if(old) old.remove();
        if(o && o.badge){
          const t = document.createElement("span");
          t.className = "sel-tag"; t.textContent = o.badge;
          btn.insertBefore(t, btn.querySelector(".sel-chev"));
        }
      },
      setOptions(list, value){
        this.options = list.slice();
        if(value !== undefined) this.value = String(value);
        if(!this.options.some(x => x.value === this.value)) this.value = this.options.length ? this.options[0].value : "";
        this.paint();
      },
      setValue(v){ this.value = String(v); this.paint(); },
      setDisabled(d){ btn.disabled = !!d; if(d && openSel === this) closeSel(); },
      open(){
        if(btn.disabled || !this.options.length) return;
        if(openSel && openSel !== this) closeSel();
        openSel = this;
        this.active = Math.max(0, this.options.findIndex(x => x.value === this.value));
        btn.setAttribute("aria-expanded","true");
        selPop.hidden = false;
        paintPop(); placePop();
      },
      pick(i){
        const o = this.options[i]; if(!o) return;
        const changed = o.value !== this.value;
        this.value = o.value; this.paint(); closeSel(); btn.focus();
        if(changed) this.onChange(o.value, o);
      },
      move(d){
        if(!openSel){ this.open(); return; }
        this.active = (this.active + d + this.options.length) % this.options.length;
        paintPop();
      }
    };

    btn.addEventListener("click", () => { if(openSel === api) closeSel(); else api.open(); });
    btn.addEventListener("keydown", e => {
      const isOpen = openSel === api;
      if(e.key === "ArrowDown"){ e.preventDefault(); isOpen ? api.move(1) : api.open(); }
      else if(e.key === "ArrowUp"){ e.preventDefault(); isOpen ? api.move(-1) : api.open(); }
      else if(e.key === "Home" && isOpen){ e.preventDefault(); api.active = 0; paintPop(); }
      else if(e.key === "End" && isOpen){ e.preventDefault(); api.active = api.options.length-1; paintPop(); }
      else if(e.key === "Enter" || e.key === " "){ e.preventDefault(); isOpen ? api.pick(api.active) : api.open(); }
      else if(e.key === "Escape" && isOpen){ e.preventDefault(); closeSel(); }
      else if(e.key === "Tab" && isOpen){ closeSel(); }
    });

    api.paint();
    return api;
  }

  function applyConfig(data){
    state.config = {
      fixedSetting: Array.isArray(data.fixedSetting) ? data.fixedSetting : [],
      model:        Array.isArray(data.model)        ? data.model        : []
    };
    renderModels(); renderFixed(); gate();
  }

  /* ---------- 模型 ---------- */
  const modelSel = createSelect({
    id:"model-sel", labelledby:"l-model", placeholder:"配置 Token 后加载",
    onChange:(v) => selectModel((state.config ? state.config.model : []).find(m => String(m.value) === v))
  });
  modelSel.setDisabled(true);
  $("model-host").appendChild(modelSel.el);

  function renderModels(){
    const models = state.config ? state.config.model : [];
    if(!models.length){
      modelSel.setOptions([], ""); modelSel.placeholder = "接口未返回可用模型";
      modelSel.setDisabled(true); modelSel.paint(); return;
    }
    const pick = models.find(m => m.value === RECOMMEND_MODEL) || models[0];
    modelSel.setOptions(models.map(m => ({
      value:String(m.value),
      label:modelName(m),
      badge:(m.value === RECOMMEND_MODEL) ? "推荐" : ((m.points !== undefined && m.points !== null && m.points !== "") ? (m.points + " 积分") : "")
    })), pick.value);
    modelSel.setDisabled(false);
    selectModel(pick);
  }
  function selectModel(m){
    state.model = m || null;
    state.modelSetting = {};
    const tip = $("model-tip");
    if(m){
      const bits = ['<span class="mono">' + esc(m.value) + '</span>'];
      if(m.points !== undefined && m.points !== null && m.points !== "") bits.push(esc(m.points) + " 积分 / 张");
      if(m.value === RECOMMEND_MODEL) bits.push("推荐");
      tip.innerHTML = bits.join("　·　");
    }else tip.textContent = "建议使用 1|nano-banana-2。";
    renderModelSet(); werr("e-model",""); gate();
  }

  /* ---------- 动态设置字段 ---------- */
  function buildField(cfg){
    const box = document.createElement("div");
    box.className = "fld" + (cfg.wide ? " wide" : "");
    const lab = document.createElement("span");
    lab.className = "lab";
    lab.id = "lab-" + cfg.key.replace(/[^a-z0-9_-]/gi,"");
    lab.innerHTML = esc(cfg.label) + (cfg.required ? ' <span class="req" aria-hidden="true">*</span>' : '');
    box.appendChild(lab);

    if(cfg.options && cfg.options.length){
      const sel = createSelect({
        id:"sel-" + cfg.key.replace(/[^a-z0-9_-]/gi,""),
        labelledby:lab.id, value:cfg.value,
        options:cfg.options.map(o => ({
          value:o.value, label:o.label, badge:(o.value === RECOMMEND_STYLE ? "推荐" : "")
        })),
        onChange:cfg.onChange
      });
      box.appendChild(sel.el);
    }else{
      const inp = document.createElement("input");
      inp.className = "in"; inp.type = "text"; inp.autocomplete = "off";
      inp.value = cfg.value || "";
      inp.setAttribute("aria-labelledby", lab.id);
      inp.addEventListener("input", () => cfg.onChange(inp.value));
      box.appendChild(inp);
    }
    return box;
  }

  function renderModelSet(){
    const wrap = $("model-set");
    wrap.innerHTML = "";
    if(!state.model) return;
    const fields = (state.model.setting || []).filter(f => {
      const k = f.field_key || f.field || ""; return k && k !== "images";
    });
    if(!fields.length) return;

    const grid = document.createElement("div");
    grid.className = "gset";
    fields.forEach(f => {
      const key = f.field_key || f.field;
      const label = FIELD_CN[key] || f.field_name || f.title || f.label || f.name || key;
      const req = f.is_required === 1 || f.is_required === true || f.is_required === "1";
      const opts = Array.isArray(f.field_option) ? f.field_option.map(pair) : [];
      const def = (f.default_value !== undefined && f.default_value !== null && f.default_value !== "")
        ? String(f.default_value) : (opts.length ? opts[0].value : "");
      state.modelSetting[key] = def;
      grid.appendChild(buildField({
        key:key, label:label, required:req, options:opts, value:def, wide:!opts.length,
        onChange:(v) => {
          state.modelSetting[key] = v;
          if(key === "aspect_ratio") applyAspect(v);
          gate();
        }
      }));
    });
    wrap.appendChild(grid);
    if(state.modelSetting.aspect_ratio) applyAspect(state.modelSetting.aspect_ratio);
  }

  function renderFixed(){
    const wrap = $("fixed-set");
    wrap.innerHTML = ""; state.fixedSetting = {};
    const items = state.config ? state.config.fixedSetting : [];
    if(!items.length) return;

    const grid = document.createElement("div");
    grid.className = "gset";
    items.forEach(it => {
      const key = it.field;
      const label = FIELD_CN[key] || it.title || it.name || it.label || key;
      const opts = Array.isArray(it.value) ? it.value.map(pair) : [];
      let def = (it.default !== undefined && it.default !== null && it.default !== "") ? String(it.default) : "";
      if(FIXED_DEFAULTS[key] && opts.some(o => o.value === FIXED_DEFAULTS[key])) def = FIXED_DEFAULTS[key];
      if(!def && opts.length) def = opts[0].value;
      state.fixedSetting[key] = def;
      grid.appendChild(buildField({
        key:key, label:label, required:!!opts.length, options:opts, value:def, wide:!opts.length,
        onChange:(v) => { state.fixedSetting[key] = v; }
      }));
    });
    wrap.appendChild(grid);
  }

  function applyAspect(r){
    const p = String(r || "1:1").split(":");
    const w = parseFloat(p[0]) || 1, h = parseFloat(p[1]) || 1;
    document.documentElement.style.setProperty("--ar", w + " / " + h);
  }

  /* ==========================================================
     6 · 参考图
     ========================================================== */
  function renderThumbs(){
    const wrap = $("thumbs");
    wrap.innerHTML = state.refs.map((r, i) => {
      let cls = "", txt = r.kind === "url" ? "链接" : "本地";
      if(r.status === "uploading"){ cls = "up"; txt = "上传中…"; }
      if(r.status === "error"){ cls = "bad"; txt = "失败"; }
      return '<div class="th">' +
        '<img src="'+esc(r.previewUrl)+'" alt="" loading="lazy">' +
        '<button class="th-open" type="button" data-open="'+i+'" aria-label="预览商品图 '+esc(r.name)+'"></button>' +
        '<button class="th-x" type="button" data-rm="'+esc(r.id)+'" aria-label="移除商品图 '+esc(r.name)+'">' +
          '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg></button>' +
        '<span class="th-tag '+cls+'">'+esc(txt)+'</span></div>';
    }).join("");
    wrap.querySelectorAll("[data-open]").forEach(b => b.addEventListener("click", () => {
      openLB(state.refs.map(r => r.previewUrl), Number(b.dataset.open), "", "商品图");
    }));
    wrap.querySelectorAll("[data-rm]").forEach(b => b.addEventListener("click", e => {
      e.stopPropagation();
      const id = b.getAttribute("data-rm");
      const it = state.refs.find(r => r.id === id);
      if(it && it.previewUrl.startsWith("blob:")) URL.revokeObjectURL(it.previewUrl);
      state.refs = state.refs.filter(r => r.id !== id);
      renderThumbs(); gate();
    }));
    $("img-count").textContent = state.refs.length + "/" + MAX_FILES;
  }

  function addFiles(list){
    werr("e-img","");
    for(const file of Array.from(list || [])){
      if(state.refs.length >= MAX_FILES){ werr("e-img","最多 "+MAX_FILES+" 张参考图。"); break; }
      if(!/^image\/(jpeg|png|webp)$/.test(file.type)){ werr("e-img","仅支持 JPG、PNG、WEBP。"); continue; }
      if(file.size > MAX_FILE_BYTES){ werr("e-img","单张不超过 12MB："+file.name); continue; }
      state.refs.push({ id:"r"+(++state.refSeq), kind:"file", name:file.name, file:file,
                        previewUrl:URL.createObjectURL(file), publicUrl:"", status:"ready" });
    }
    renderThumbs(); gate();
  }
  $("file-input").addEventListener("change", e => { addFiles(e.target.files); e.target.value = ""; });

  const dz = $("dz");
  ["dragenter","dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("hot"); }));
  ["dragleave","drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("hot"); }));
  dz.addEventListener("drop", e => { if(e.dataTransfer) addFiles(e.dataTransfer.files); });

  function addUrl(){
    const inp = $("url-input"), v = inp.value.trim();
    werr("e-img","");
    if(!v) return;
    if(!/^https?:\/\/\S+$/i.test(v)){ werr("e-img","请填写 http(s) 开头的公网图片链接。"); return; }
    if(state.refs.length >= MAX_FILES){ werr("e-img","最多 "+MAX_FILES+" 张参考图。"); return; }
    state.refs.push({ id:"r"+(++state.refSeq), kind:"url", name:(v.split("/").pop()||"image"),
                      previewUrl:v, publicUrl:v, status:"ready" });
    inp.value = ""; renderThumbs(); gate();
  }
  /* ---------- 商品图来源：上传 / 链接 二选一 ---------- */
  function setSource(i){
    const seg = $("src-seg");
    seg.dataset.i = String(i);
    $("seg-up").setAttribute("aria-selected", i === 0 ? "true" : "false");
    $("seg-link").setAttribute("aria-selected", i === 1 ? "true" : "false");
    $("seg-up").tabIndex   = i === 0 ? 0 : -1;
    $("seg-link").tabIndex = i === 1 ? 0 : -1;
    $("pane-up").hidden   = i !== 0;
    $("pane-link").hidden = i !== 1;
    werr("e-img","");
    if(i === 1) $("url-input").focus({preventScroll:true});
  }
  $("seg-up").addEventListener("click", () => setSource(0));
  $("seg-link").addEventListener("click", () => setSource(1));
  $("src-seg").addEventListener("keydown", e => {
    if(e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const next = e.key === "ArrowRight" ? 1 : 0;
    setSource(next);
    (next === 0 ? $("seg-up") : $("seg-link")).focus();
  });

  $("url-add").addEventListener("click", addUrl);
  $("url-input").addEventListener("keydown", e => { if(e.key === "Enter"){ e.preventDefault(); addUrl(); } });

  /* 本地文件不在浏览器里上传，随表单一起交给本栏目后端处理。 */

  /* ==========================================================
     7 · 校验 / 闸门 / 积分预估
     ========================================================== */
  const generationCounts = Array.from({length:15}, (_, index) => index + 1);
  const totalSel = createSelect({
    id:"p-total", labelledby:"l-total", value:"2",
    options:generationCounts.map(n => ({ value:String(n), label:"生成 " + n + " 张" })),
    onChange:() => gate()
  });
  $("total-host").appendChild(totalSel.el);

  function form(){
    return { title:$("p-title").value.trim(), desc:$("p-desc").value.trim(), total:String(totalSel.value||"") };
  }
  function estimate(){
    const n = parseInt(form().total,10) || 0;
    const p = state.model && state.model.points !== undefined && state.model.points !== null && state.model.points !== ""
      ? Number(state.model.points) : NaN;
    $("est-pts").textContent = (!isNaN(p) && n) ? (p*n + " 积分") : "—";
  }
  function gate(){
    const f = form(), n = parseInt(f.total,10);
    const ready = !!state.tokenOk && !!f.title && !!f.desc && n >= 1 && n <= 15 &&
                  !!state.model && state.refs.length > 0 && !state.running;
    $("go").disabled = !ready;
    let h;
    if(state.running)                       h = "任务进行中，完成后可再次提交。";
    else if(!state.tokenOk)                h = "请先配置 Token。";
    else if(!state.refs.length)             h = "请先上传至少一张商品图。";
    else if(!f.title || !f.desc)            h = "请填写商品标题与商品描述。";
    else if(!state.model)                   h = "请选择模型。";
    else                                    h = "参数就绪，可以开始生成。";
    $("go-hint").textContent = h;
    estimate();
  }
  ["p-title","p-desc"].forEach(id => $(id).addEventListener("input", () => {
    if(id === "p-desc") $("desc-count").textContent = $("p-desc").value.length + "/3000";
    gate();
  }));

  function validate(){
    let ok = true; const f = form();
    ["e-title","e-desc","e-total","e-model","e-img"].forEach(i => werr(i,""));
    if(!f.title){ werr("e-title","请填写商品标题。"); ok = false; }
    if(!f.desc){ werr("e-desc","请填写商品描述。"); ok = false; }
    if(!(parseInt(f.total,10) >= 1 && parseInt(f.total,10) <= 15)){ werr("e-total","请选择 1–15 张的生成数量。"); ok = false; }
    if(!state.model){ werr("e-model","请选择模型。"); ok = false; }
    if(!state.refs.length){ werr("e-img","请至少上传一张商品图。"); ok = false; }
    (state.model && state.model.setting ? state.model.setting : []).forEach(fd => {
      const k = fd.field_key || fd.field;
      const req = fd.is_required === 1 || fd.is_required === true || fd.is_required === "1";
      if(k && k !== "images" && req && !state.modelSetting[k]){
        werr("e-model","模型设置「"+(FIELD_CN[k]||fd.field_name||k)+"」为必填。"); ok = false;
      }
    });
    return ok;
  }

  /* ==========================================================
     8 · 结果面板
     ========================================================== */
  function resSub(t){ $("res-sub").textContent = t; }
  function showEmpty(on){ $("res-empty").style.display = on ? "" : "none"; }

  function renderTasks(){
    const w = $("tasks");
    if(!state.tasks.length){ w.innerHTML = ""; return; }
    showEmpty(false);
    w.innerHTML = state.tasks.map(t => {
      let cls="q", txt="已排队", bar="";
      if(t.status === 2){ cls="g"; txt="生成中"; bar="live"; }
      if(t.status === 3){ cls="s"; txt="已完成"; bar="s"; }
      if(t.status === -1){ cls="f"; txt="失败"; bar="f"; }
      const pct = t.status === 3 ? 100 : Math.max(0, Math.min(100, Number(t.progress)||0));
      return '<div class="tk">' +
        '<div class="tk-top"><span class="tk-id">'+esc(t.id)+'</span><span class="tk-st '+cls+'">'+txt+'</span></div>' +
        '<div class="pbar '+bar+'"><i style="width:'+pct+'%"></i></div>' +
        '<div class="tk-note">进度 '+pct+'%　·　status '+esc(t.status)+'</div></div>';
    }).join("");
  }
  function renderSkeleton(n){
    showEmpty(false);
    $("gal").innerHTML = Array.from({length:n}, (_,i) =>
      '<div class="sk"><span>生成中 '+pad(i+1)+'</span></div>').join("");
  }
  function renderShots(){
    const g = $("gal");
    if(!state.shots.length){ g.innerHTML = ""; return; }
    showEmpty(false);
    g.innerHTML = state.shots.map((s,i) =>
      '<figure class="sh" style="margin:0" tabindex="0" role="button" data-open="'+i+'" aria-label="预览第 '+(i+1)+' 张生成图">' +
        '<img src="'+esc(s.url)+'" alt="生成图 '+(i+1)+'" loading="lazy">' +
        '<span class="sh-i">'+pad(i+1)+' · '+esc(s.taskId)+'</span>' +
        '<span class="sh-a">' +
          '<button class="mini" type="button" data-dl="'+i+'" aria-label="下载第 '+(i+1)+' 张">' +
            '<svg viewBox="0 0 24 24"><path d="M12 3.5v11"/><path d="m7.5 11 4.5 4.5 4.5-4.5"/><path d="M5 20h14"/></svg></button>' +
        '</span></figure>').join("");

    g.querySelectorAll("[data-open]").forEach(el => {
      const open = () => openLB(state.shots.map(s => s.url), Number(el.dataset.open), state.shots[0].taskId, "本次生成");
      el.addEventListener("click", e => { if(!e.target.closest("[data-dl]")) open(); });
      el.addEventListener("keydown", e => { if(e.key === "Enter" || e.key === " "){ e.preventDefault(); open(); } });
    });
    g.querySelectorAll("[data-dl]").forEach(b => b.addEventListener("click", async e => {
      e.stopPropagation();
      const i = Number(b.dataset.dl), s = state.shots[i];
      const okd = await downloadOne(s.url, s.taskId + "_" + pad(i+1) + "." + extOf(s.url));
      if(!okd) toast("图片域名未开放跨域，已在新标签页打开，可右键另存。", "bad");
    }));

    const ids = Array.from(new Set(state.shots.map(s => s.taskId))).join("-");
    $("res-tools").innerHTML =
      '<button class="btn sm" type="button" id="zip-all">' +
        '<svg viewBox="0 0 24 24"><path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h4l2 2.2h5A2.5 2.5 0 0 1 20 9.7v7.8A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5v-10Z"/><path d="M12 11v4.5M10 13.5h4"/></svg>' +
        '全部下载 .zip</button>';
    $("zip-all").addEventListener("click", e =>
      downloadZip(state.shots.map(s => s.url), "feiyushentu_" + ids, e.currentTarget));
  }

  /* ==========================================================
     9 · 提交与轮询
     ========================================================== */
  $("gen-form").addEventListener("submit", async e => {
    e.preventDefault();
    if(!validate()) return;
    clearToasts("token");

    const f = form();
    state.running = true; gate();
    $("go-label").textContent = "生成图片中";
    $("go-ic").outerHTML = '<span class="spin" id="go-ic"></span>';
    resSub("生成图片中…");
    state.tasks = []; state.shots = []; $("res-tools").innerHTML = "";
    renderTasks(); renderShots(); renderSkeleton(parseInt(f.total,10));

    try{
      const payload = {
        total: f.total, title: f.title, desc: f.desc,
        fixedSetting: Object.assign({}, state.fixedSetting),
        aiModel: state.model.value,
        setting: Object.assign({}, state.modelSetting)
      };
      state.lastPayload = payload;

      const job = await submitJob(payload);
      resSub("生成中，正在查询任务状态…");
      $("go-label").textContent = "生成中";
      await pollJob(job, payload);

    }catch(err){
      resSub("生成失败");
      $("gal").innerHTML = ""; showEmpty(state.shots.length === 0 && state.tasks.length === 0);
      $("res-tools").innerHTML = '<button class="btn sm" type="button" id="retry">重新生成</button>';
      $("retry").addEventListener("click", () => $("gen-form").requestSubmit());
      onApiError(err);
    }finally{
      state.running = false; state.polling = false;
      $("go-label").textContent = "开始生成";
      const ic = $("go-ic");
      if(ic && ic.tagName !== "svg") ic.outerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" id="go-ic"><path d="m13 2-8 11h6l-1 9 8-11h-6l1-9Z"/></svg>';
      gate();
    }
  });

  const ACTIVE = ["queued","uploading","generating","archive_retrying"];
  const JOB_SUB = {
    queued:"已排队，等待处理…", uploading:"正在准备商品图…", generating:"生成中，正在查询任务状态…",
    archive_retrying:"正在重新归档生成结果…", success:"完成",
    generation_failed:"生成失败", timeout:"超时",
    archive_partial:"图片已生成，部分文件归档失败", archive_failed:"图片已生成，但本地归档失败"
  };

  /* 表单连同本地文件一起交给后端；后端负责上传、提交与轮询飞鱼神图。 */
  async function submitJob(payload){
    const fd = new FormData();
    fd.append("title", payload.title);
    fd.append("description", payload.desc);
    fd.append("total", payload.total);
    fd.append("ai_model", payload.aiModel);
    fd.append("fixed_setting", JSON.stringify(payload.fixedSetting));
    fd.append("setting", JSON.stringify(payload.setting));
    const urls = [];
    state.refs.forEach(r => {
      if(r.kind === "file" && r.file) fd.append("images", r.file, r.name);
      else if(r.publicUrl) urls.push(r.publicUrl);
    });
    if(urls.length) fd.append("image_urls", JSON.stringify(urls));
    state.refs.forEach(r => { if(r.kind === "file") r.status = "uploading"; });
    renderThumbs();
    try{
      const data = await api("/api/jobs", { method:"POST", body: fd });
      state.refs.forEach(r => { r.status = "ready"; });
      renderThumbs();
      return data.job;
    }catch(err){
      state.refs.forEach(r => { if(r.kind === "file") r.status = "error"; });
      renderThumbs();
      throw err;
    }
  }

  function paintJob(job){
    const ids = (job.task_ids && job.task_ids.length) ? job.task_ids : [job.id];
    state.tasks = ids.map(id => ({
      id: id,
      status: job.status === "success" ? 3 : (ACTIVE.indexOf(job.status) >= 0 ? 2 : -1),
      progress: job.status === "success" ? 100 : (job.status === "generating" ? 60 : 15),
      images: []
    }));
    renderTasks();
  }

  async function pollJob(job, payload){
    state.polling = true;
    const t0 = Date.now();
    let current = job;
    paintJob(current);
    for(let attempt = 1; attempt <= POLL_MAX; attempt++){
      if(!state.polling){ resSub("已停止查询"); return; }
      if(ACTIVE.indexOf(current.status) < 0) break;
      if(Date.now() - t0 > POLL_DEADLINE){ current = null; break; }
      await sleep(POLL_INTERVAL);
      current = (await api("/api/jobs/" + encodeURIComponent(job.id))).job;
      resSub(JOB_SUB[current.status] || "处理中…");
      paintJob(current);
    }
    state.polling = false;
    if(!current){ failResult("超时", "超过查询上限任务仍未完成。任务仍在后台推进，可稍后在生图历史中查看。"); return; }
    if(current.status === "success" || current.status === "archive_partial" || current.status === "archive_failed"){
      finish(current, payload);
      if(current.status !== "success") toast(JOB_SUB[current.status], "bad");
      return;
    }
    failResult(JOB_SUB[current.status] || "生成失败", current.error || "生成失败。可以用上一次确认的参数重新提交。");
  }

  function failResult(sub, message){
    resSub(sub);
    $("gal").innerHTML = "";
    $("res-tools").innerHTML = '<button class="btn sm" type="button" id="retry">重新生成</button>';
    $("retry").addEventListener("click", () => $("gen-form").requestSubmit());
    toast(esc(message), "bad", {timeout:0});
  }

  function finish(job, payload){
    state.shots = (job.images || [])
      .map(im => ({ url: im.download_url || im.source_url, taskId: (job.task_ids || []).join(",") || job.id }))
      .filter(sh => sh.url);
    resSub("完成 · 共 " + state.shots.length + " 张");
    renderShots();
    HistoryStore.prepend(toHistoryItem(job));
    toast("生成完成，共 " + state.shots.length + " 张", "ok");
  }

  /* ==========================================================
     10 · 生图历史
     ----------------------------------------------------------
     历史列表由「调用方网站」提供，不是飞鱼神图的接口。飞鱼神图只出图，
     任务号、参数、状态、图片地址等由调用方落在自己的数据库里
     （见 references/ui-design.md 的 Persistence 规则）。
     此处约定统一的请求与返回结构，各接入方照此实现即可同质。

       GET  {HISTORY_API}?page=&size=&start=&end=
         page  : 从 1 开始
         size  : 每页条数
         start : YYYY-MM-DD，含当天，可空
         end   : YYYY-MM-DD，含当天，可空
         resp  : { code:200, data:{ list:HistoryItem[], total:Number, page:Number, size:Number } }

       HistoryItem = {
         task_id       : String,          // 任务号，多个用英文逗号连接
         created_at    : String,          // "YYYY-MM-DD HH:mm:ss"
         title         : String,          // 商品标题
         desc          : String,          // 商品描述
         ai_model      : String,          // model[].value（提交值）
         model_label   : String,          // model[].name（显示名称）
         fixed         : { style, language, scene },   // fixedSetting 的提交值
         fixed_label   : { style, language, scene },   // 对应的显示名称，列表展示读这个
         setting       : { aspect_ratio, resolution, ... },
         points        : Number,          // 本次消耗积分
         source_images : String[],        // 商品原图
         images        : String[]         // 生成结果
       }

     分页、日期过滤、倒序排序都在服务端完成，前端只负责传参和渲染。
     ========================================================== */
  /* 本栏目的历史就是 jobs 表，路径与返回外壳按 Harness 约定，
     字段与上面的 HistoryItem 契约一一对应。 */
  const HistoryStore = {
    /* 本次会话刚生成、服务端读取尚未跟上的记录，先垫在第一页最前面 */
    pending: [],
    async list(q){
      const qs = "page=" + encodeURIComponent(q.page) + "&size=" + encodeURIComponent(q.size) +
                 "&start=" + encodeURIComponent(q.start || "") + "&end=" + encodeURIComponent(q.end || "");
      const data = await api("/api/jobs?" + qs);
      let list = (data.jobs || []).map(toHistoryItem);
      const page = Number(data.page) || q.page;
      if(page === 1 && this.pending.length){
        const seen = {};
        list.forEach(r => { seen[r.task_id] = 1; });
        list = this.pending.filter(r => !seen[r.task_id]).concat(list).slice(0, q.size);
      }
      return { list:list, total:Number(data.total) || list.length, page:page, size:Number(data.size) || q.size };
    },
    prepend(rec){ this.pending.unshift(rec); }
  };

  /* created_at 后端存的是 UTC ISO，这里转成契约要求的本地 "YYYY-MM-DD HH:mm:ss" */
  function localStamp(iso){
    const d = new Date(iso);
    if(isNaN(d.getTime())) return String(iso || "").replace("T", " ").replace("Z", "");
    return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())+" "+
           pad(d.getHours())+":"+pad(d.getMinutes())+":"+pad(d.getSeconds());
  }

  function toHistoryItem(job){
    const fixed = job.fixed_setting || {};
    const fixedLabel = {};
    Object.keys(fixed).forEach(k => { fixedLabel[k] = labelOfFixed(k, fixed[k]); });
    const models = (state.config && state.config.model) || [];
    const hit = models.find(m => String(m.value) === String(job.ai_model));
    const setting = Object.assign({}, job.setting || {}); delete setting.images;
    const pts = hit && has(hit.points) ? Number(hit.points) : 0;
    return {
      task_id: (job.task_ids && job.task_ids.length) ? job.task_ids.join(",") : job.id,
      created_at: localStamp(job.created_at),
      title: job.title || "",
      desc: job.description || "",
      ai_model: job.ai_model || "",
      model_label: hit ? modelName(hit) : (job.ai_model || ""),
      fixed: fixed,
      fixed_label: fixedLabel,
      setting: setting,
      points: pts * (Number(job.total) || 0),
      source_images: job.source_images || [],
      images: (job.images || []).map(im => im.download_url || im.source_url).filter(Boolean)
    };
  }

  const hisTip = $("his-tip");
  let hisTipAnchor = null, hisTipPinned = false, hisTipTimer = 0, hisTipFrame = 0;
  function positionHisTip(){
    if(hisTip.hidden || !hisTipAnchor || !hisTipAnchor.isConnected) return;
    const pad = 12, gap = 8;
    const viewport = window.visualViewport;
    const vw = viewport ? viewport.width : document.documentElement.clientWidth;
    const vh = viewport ? viewport.height : window.innerHeight;
    const rect = hisTipAnchor.getBoundingClientRect();
    hisTip.style.left = pad + "px"; hisTip.style.top = pad + "px";
    const width = hisTip.offsetWidth, height = hisTip.offsetHeight;
    const left = Math.max(pad, Math.min(rect.left, vw - width - pad));
    const below = vh - rect.bottom - pad, above = rect.top - pad;
    const top = below >= height || below >= above ? rect.bottom + gap : rect.top - height - gap;
    hisTip.style.left = Math.round(left) + "px";
    hisTip.style.top = Math.round(Math.max(pad, Math.min(top, vh - height - pad))) + "px";
  }
  function scheduleHisTipPosition(){
    cancelAnimationFrame(hisTipFrame);
    hisTipFrame = requestAnimationFrame(positionHisTip);
  }
  function hideHisTip(){
    clearTimeout(hisTipTimer);
    if(hisTipAnchor){
      hisTipAnchor.setAttribute("aria-expanded", "false");
      hisTipAnchor.removeAttribute("aria-describedby");
    }
    hisTipAnchor = null; hisTipPinned = false; hisTip.hidden = true;
  }
  function showHisTip(anchor, pinned){
    clearTimeout(hisTipTimer);
    if(hisTipAnchor && hisTipAnchor !== anchor){
      hisTipAnchor.setAttribute("aria-expanded", "false");
      hisTipAnchor.removeAttribute("aria-describedby");
    }
    hisTipAnchor = anchor; hisTipPinned = !!pinned;
    hisTip.textContent = anchor.dataset.hisTip || "";
    hisTip.hidden = false;
    anchor.setAttribute("aria-expanded", "true");
    anchor.setAttribute("aria-describedby", "his-tip");
    scheduleHisTipPosition();
  }
  function scheduleHisTipHide(){
    clearTimeout(hisTipTimer);
    if(!hisTipPinned) hisTipTimer = setTimeout(hideHisTip, 120);
  }
  function bindHistoryTips(scope){
    scope.querySelectorAll("[data-his-tip]").forEach(el => {
      el.addEventListener("pointerenter", e => {
        if(e.pointerType !== "touch" && !hisTipPinned) showHisTip(el, false);
      });
      el.addEventListener("pointerleave", scheduleHisTipHide);
      el.addEventListener("focus", () => { if(!hisTipPinned) showHisTip(el, false); });
      el.addEventListener("blur", scheduleHisTipHide);
      el.addEventListener("click", e => {
        e.stopPropagation();
        if(hisTipAnchor === el && hisTipPinned) hideHisTip();
        else showHisTip(el, true);
      });
    });
  }
  hisTip.addEventListener("pointerenter", () => clearTimeout(hisTipTimer));
  hisTip.addEventListener("pointerleave", scheduleHisTipHide);
  hisTip.addEventListener("click", e => e.stopPropagation());
  document.addEventListener("pointerdown", e => {
    const target = e.target;
    if(hisTip.hidden || hisTip.contains(target) || (target.closest && target.closest("[data-his-tip]"))) return;
    hideHisTip();
  });
  document.addEventListener("keydown", e => { if(e.key === "Escape" && !hisTip.hidden) hideHisTip(); });
  window.addEventListener("resize", scheduleHisTipPosition);
  window.addEventListener("scroll", scheduleHisTipPosition, true);

  function hisSkeleton(n){
    $("hlist").innerHTML = Array.from({length:n}, () =>
      '<div class="card hsk">' +
        '<div class="shim" style="aspect-ratio:1"></div>' +
        '<div style="display:flex;flex-direction:column;gap:11px">' +
          '<div class="shim" style="height:22px;width:56%"></div>' +
          '<div class="shim" style="height:56px"></div>' +
          '<div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px">' +
            '<div class="shim" style="aspect-ratio:1"></div><div class="shim" style="aspect-ratio:1"></div>' +
            '<div class="shim" style="aspect-ratio:1"></div><div class="shim" style="aspect-ratio:1"></div>' +
          '</div></div></div>').join("");
  }

  function renderHistory(res){
    const list = $("hlist");
    hideHisTip();
    if(!res.list.length){
      list.innerHTML = '<div class="card hempty">' +
        '<span class="empty-i" aria-hidden="true"><svg viewBox="0 0 24 24" stroke="currentColor" fill="none" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 2.6-6.4"/><path d="M3 4v5h5"/><path d="M12 8v4.5l3 1.8"/></svg></span>' +
        '<p>该时间范围内没有生成记录</p></div>';
      $("pager").hidden = true;
      return;
    }

    list.innerHTML = res.list.map((r, ri) => {
      const src = (r.source_images && r.source_images[0]) || "";
      const tags = [];
      if(r.model_label) tags.push(r.model_label);
      if(r.setting && r.setting.aspect_ratio) tags.push(r.setting.aspect_ratio);
      if(r.setting && r.setting.resolution) tags.push(r.setting.resolution);
      const fl = r.fixed_label || r.fixed || {};
      if(fl.style) tags.push(fl.style);
      if(fl.language) tags.push(fl.language);

      return '<article class="card hrow rz" style="animation-delay:'+(ri*45)+'ms">' +
        '<div class="hsrc" data-hsrc="'+ri+'" role="button" tabindex="0" aria-label="预览原图">' +
          (src ? '<img src="'+esc(src)+'" alt="原图" loading="lazy">' : '') +
          '<span class="hsrc-b">原图</span>' +
          ((r.source_images && r.source_images.length > 1) ? '<span class="hsrc-n">'+r.source_images.length+' 张</span>' : '') +
        '</div>' +
        '<div class="hbody">' +
          '<div class="hmeta">' +
            '<span class="htime"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 1.8"/></svg>'+esc(r.created_at)+'</span>' +
            '<span class="hstats">' +
              '<span class="stat n"><svg viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2.5"/><path d="m4 17 4.6-4.4 3 2.8 3.4-3.4L20 17"/></svg><span class="mono">'+r.images.length+'</span> 张</span>' +
              '<span class="stat p"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.8v8.4M9.8 9.9h3.4a1.6 1.6 0 0 1 0 3.2H9.8h3.7"/></svg><span class="mono">'+esc(r.points)+'</span> 积分</span>' +
              '<button class="btn sm" type="button" data-zip="'+ri+'">' +
                '<svg viewBox="0 0 24 24"><path d="M4 7.5A2.5 2.5 0 0 1 6.5 5h4l2 2.2h5A2.5 2.5 0 0 1 20 9.7v7.8A2.5 2.5 0 0 1 17.5 20h-11A2.5 2.5 0 0 1 4 17.5v-10Z"/><path d="M12 11v4.5M10 13.5h4"/></svg>' +
                '全部下载</button>' +
            '</span>' +
          '</div>' +
          '<div class="hprompt">' +
            '<button class="htext ttl" type="button" data-his-tip="'+esc(r.title)+'" aria-controls="his-tip" aria-expanded="false">'+esc(r.title)+'</button>' +
            '<button class="htext dsc" type="button" data-his-tip="'+esc(r.desc)+'" aria-controls="his-tip" aria-expanded="false">'+esc(r.desc)+'</button>' +
          '</div>' +
          '<div class="hmodel">'+tags.map(t => '<span class="tagm">'+esc(t)+'</span>').join("")+
            '<span class="tagm">'+esc(r.task_id)+'</span></div>' +
          '<div class="houts">' + r.images.map((u,i) =>
            '<div class="hout" data-hout="'+ri+'" data-i="'+i+'" role="button" tabindex="0" aria-label="预览第 '+(i+1)+' 张生成图">' +
              '<img src="'+esc(u)+'" alt="生成图 '+(i+1)+'" loading="lazy"></div>').join("") +
          '</div>' +
        '</div></article>';
    }).join("");

    bindHistoryTips(list);

    list.querySelectorAll("[data-zip]").forEach(b => b.addEventListener("click", e => {
      const r = res.list[Number(b.dataset.zip)];
      downloadZip(r.images, "feiyushentu_" + r.task_id.replace(/,/g,"-"), e.currentTarget);
    }));
    const openOut = (el) => {
      const r = res.list[Number(el.dataset.hout)];
      openLB(r.images, Number(el.dataset.i), r.task_id, r.title);
    };
    list.querySelectorAll("[data-hout]").forEach(el => {
      el.addEventListener("click", () => openOut(el));
      el.addEventListener("keydown", e => { if(e.key==="Enter"||e.key===" "){ e.preventDefault(); openOut(el); } });
    });
    const openSrc = (el) => {
      const r = res.list[Number(el.dataset.hsrc)];
      if(r.source_images && r.source_images.length) openLB(r.source_images, 0, r.task_id, r.title + " · 原图");
    };
    list.querySelectorAll("[data-hsrc]").forEach(el => {
      el.addEventListener("click", () => openSrc(el));
      el.addEventListener("keydown", e => { if(e.key==="Enter"||e.key===" "){ e.preventDefault(); openSrc(el); } });
    });

    renderPager(res);
  }

  function renderPager(res){
    const max = Math.max(1, Math.ceil(res.total / res.size));
    state.his.page = res.page; state.his.total = res.total;
    $("pager").hidden = false;
    $("pg-total").textContent = res.total;
    $("pg-cur").textContent = res.page;
    $("pg-max").textContent = max;

    const nums = [];
    const push = (n) => nums.push(
      '<button class="pgb" type="button" data-p="'+n+'"'+(n===res.page?' aria-current="page"':'')+'>'+n+'</button>');
    const el = () => nums.push('<span class="pgb el" aria-hidden="true">…</span>');

    if(max <= 7){ for(let i=1;i<=max;i++) push(i); }
    else{
      push(1);
      if(res.page > 3) el();
      for(let i = Math.max(2, res.page-1); i <= Math.min(max-1, res.page+1); i++) push(i);
      if(res.page < max-2) el();
      push(max);
    }

    $("pg-nav").innerHTML =
      '<button class="pgb" type="button" data-p="'+(res.page-1)+'" '+(res.page<=1?"disabled":"")+' aria-label="上一页">' +
        '<svg viewBox="0 0 24 24"><path d="m14.5 5-7 7 7 7"/></svg></button>' +
      nums.join("") +
      '<button class="pgb" type="button" data-p="'+(res.page+1)+'" '+(res.page>=max?"disabled":"")+' aria-label="下一页">' +
        '<svg viewBox="0 0 24 24"><path d="m9.5 5 7 7-7 7"/></svg></button>';

    $("pg-nav").querySelectorAll("[data-p]").forEach(b => b.addEventListener("click", () => {
      const p = Number(b.dataset.p);
      if(p >= 1 && p <= max && p !== res.page){ state.his.page = p; loadHistory(); window.scrollTo({top:0,behavior:"smooth"}); }
    }));
  }

  async function loadHistory(){
    if(state.his.loading) return;
    state.his.loading = true;
    hisSkeleton(Math.min(state.his.size, 3));
    try{
      const res = await HistoryStore.list({ page:state.his.page, size:state.his.size, start:state.his.start, end:state.his.end });
      renderHistory(res);
      $("his-sub").textContent = "按时间倒序展示每一次生成任务　·　共 " + res.total + " 条记录";
    }catch(err){
      $("hlist").innerHTML = '<div class="card hempty"><p>历史加载失败：'+esc(err.message||"未知错误")+'</p></div>';
      $("pager").hidden = true;
    }finally{ state.his.loading = false; }
  }

  /* ---------- 筛选 ---------- */
  function ymd(d){ return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate()); }
  function setRange(kind){
    const today = new Date();
    let s = "", e = "";
    if(kind === "all"){ s = ""; e = ""; }
    else if(kind === "0"){ s = e = ymd(today); }
    else if(kind === "1"){ const y = new Date(today.getTime()-864e5); s = e = ymd(y); }
    else { const n = Number(kind); const from = new Date(today.getTime()-(n-1)*864e5); s = ymd(from); e = ymd(today); }
    state.his.range = kind; state.his.start = s; state.his.end = e;
    $("dt-start").value = s; $("dt-end").value = e;
    document.querySelectorAll("#range-chips .chip").forEach(c =>
      c.setAttribute("aria-pressed", c.dataset.range === kind ? "true" : "false"));
  }
  document.querySelectorAll("#range-chips .chip").forEach(c => c.addEventListener("click", () => {
    setRange(c.dataset.range); state.his.page = 1; loadHistory();
  }));
  ["dt-start","dt-end"].forEach(id => $(id).addEventListener("change", () => {
    state.his.start = $("dt-start").value; state.his.end = $("dt-end").value;
    state.his.range = "";
    document.querySelectorAll("#range-chips .chip").forEach(c => c.setAttribute("aria-pressed","false"));
  }));
  $("his-query").addEventListener("click", () => {
    state.his.start = $("dt-start").value; state.his.end = $("dt-end").value;
    state.his.page = 1; loadHistory();
  });
  const pgSizeSel = createSelect({
    id:"pg-size", labelledby:"l-pgsize", value:"5",
    options:[3,5,10].map(n => ({ value:String(n), label:n + " 条" })),
    onChange:(v) => { state.his.size = Number(v) || 5; state.his.page = 1; loadHistory(); }
  });
  $("pgsize-host").appendChild(pgSizeSel.el);

  /* ==========================================================
     11 · 灯箱
     ========================================================== */
  const lb   = $("lb");
  const lbBox = $("lb-box");
  const lbFig = $("lb-fig");
  const ZOOMS = [0.4, 0.6, 0.8, 1, 1.3, 1.7, 2.2, 3];
  const Z0 = 3;                                    /* ZOOMS[3] === 1 */

  function openLB(items, index, taskId, title){
    state.lb = { items:items.slice(), index:index||0, taskId:taskId||"", title:title||"预览",
                 z:Z0, rot:0, x:0, y:0 };
    closeSel();
    if(!lb.open) lb.showModal();
    paintLB();
    lbBox.focus({preventScroll:true});
  }
  function fitLBImage(){
    const img = $("lb-img");
    if(!img.naturalWidth || !img.naturalHeight) return;
    const style = getComputedStyle(lbBox);
    const px = name => parseFloat(style[name]) || 0;
    const viewport = window.visualViewport;
    const boxWidth = lbBox.clientWidth || (viewport ? viewport.width : window.innerWidth);
    const boxHeight = lbBox.clientHeight || (viewport ? viewport.height : window.innerHeight);
    const visibleWidth = viewport ? Math.min(boxWidth, viewport.width) : boxWidth;
    const visibleHeight = viewport ? Math.min(boxHeight, viewport.height) : boxHeight;
    const availableWidth = Math.max(1, visibleWidth - px("paddingLeft") - px("paddingRight"));
    const availableHeight = Math.max(1, visibleHeight - px("paddingTop") - px("paddingBottom"));
    const fit = Math.min(1, availableWidth / img.naturalWidth, availableHeight / img.naturalHeight);
    img.style.width = Math.max(1, Math.floor(img.naturalWidth * fit)) + "px";
    img.style.height = Math.max(1, Math.floor(img.naturalHeight * fit)) + "px";
    img.style.maxWidth = Math.floor(availableWidth) + "px";
    img.style.maxHeight = Math.floor(availableHeight) + "px";
    lbFig.style.width = Math.floor(availableWidth) + "px";
    lbFig.style.height = Math.floor(availableHeight) + "px";
  }
  function applyTransform(){
    const s = state.lb;
    lbFig.style.transform = "translate(" + s.x + "px," + s.y + "px) scale(" + ZOOMS[s.z] + ") rotate(" + s.rot + "deg)";
    lbBox.dataset.zoom = ZOOMS[s.z] > 1 ? "2" : "1";
    $("lb-in").disabled  = s.z >= ZOOMS.length - 1;
    $("lb-out").disabled = s.z <= 0;
    $("lb-reset").disabled = isResetLB(s);
  }
  function isResetLB(s){
    const rot = ((s.rot % 360) + 360) % 360;
    return s.z === Z0 && rot === 0 && s.x === 0 && s.y === 0;
  }
  function resetLB(){
    const s = state.lb;
    s.z = Z0; s.rot = 0; s.x = 0; s.y = 0;
    applyTransform();
  }
  function paintLB(){
    const s = state.lb, url = s.items[s.index] || "";
    const img = $("lb-img");
    img.style.width = img.style.height = img.style.maxWidth = img.style.maxHeight = "";
    img.onload = () => { fitLBImage(); applyTransform(); };
    img.src = url;
    img.alt = s.title + " 第 " + (s.index + 1) + " 张，共 " + s.items.length + " 张";
    img.style.animation = "none"; void img.offsetWidth; img.style.animation = "";
    lbFig.style.transition = "none"; resetLB();
    void lbFig.offsetWidth; lbFig.style.transition = "";
    const many = s.items.length > 1;
    $("lb-prev").hidden = !many;
    $("lb-next").hidden = !many;
  }
  let fitFrame = 0;
  function refitLBViewport(){
    if(!lb.open) return;
    cancelAnimationFrame(fitFrame);
    fitFrame = requestAnimationFrame(() => { fitLBImage(); applyTransform(); });
  }
  window.addEventListener("resize", refitLBViewport);
  if(window.visualViewport) window.visualViewport.addEventListener("resize", refitLBViewport);
  function stepLB(d){
    const s = state.lb; if(!s.items.length) return;
    s.index = (s.index + d + s.items.length) % s.items.length;
    paintLB();
  }
  function zoomLB(d){
    const s = state.lb;
    const nz = Math.min(ZOOMS.length - 1, Math.max(0, s.z + d));
    if(nz === s.z) return;
    s.z = nz;
    if(ZOOMS[s.z] <= 1){ s.x = 0; s.y = 0; }
    applyTransform();
  }

  $("lb-prev").addEventListener("click", () => stepLB(-1));
  $("lb-next").addEventListener("click", () => stepLB(1));
  $("lb-close").addEventListener("click", () => lb.close());
  $("lb-in").addEventListener("click",  () => zoomLB(1));
  $("lb-out").addEventListener("click", () => zoomLB(-1));
  $("lb-reset").addEventListener("click", resetLB);
  $("lb-rot").addEventListener("click", () => { state.lb.rot += 90; applyTransform(); });
  $("lb-dl").addEventListener("click", async () => {
    const s = state.lb;
    const okd = await downloadOne(s.items[s.index], (s.taskId || "image") + "_" + pad(s.index + 1) + "." + extOf(s.items[s.index]));
    if(!okd) toast("图片域名未开放跨域，已在新标签页打开，可右键另存。", "bad");
  });
  /* 滚轮缩放 · 双击切换 · 放大后拖拽 */
  lbBox.addEventListener("wheel", e => { e.preventDefault(); zoomLB(e.deltaY < 0 ? 1 : -1); }, {passive:false});
  $("lb-img").addEventListener("dblclick", e => {
    e.stopPropagation();
    const s = state.lb;
    if(!isResetLB(s)) resetLB();
    else zoomLB(2);
  });
  let drag = null;
  $("lb-img").addEventListener("pointerdown", e => {
    if(ZOOMS[state.lb.z] <= 1) return;
    drag = { id:e.pointerId, sx:e.clientX, sy:e.clientY, ox:state.lb.x, oy:state.lb.y, moved:false };
    lbBox.classList.add("drag");
    e.currentTarget.setPointerCapture(e.pointerId);
  });
  $("lb-img").addEventListener("pointermove", e => {
    if(!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if(Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
    state.lb.x = drag.ox + dx; state.lb.y = drag.oy + dy;
    applyTransform();
  });
  ["pointerup","pointercancel"].forEach(ev => $("lb-img").addEventListener(ev, e => {
    if(!drag || e.pointerId !== drag.id) return;
    lbBox.classList.remove("drag");
    const moved = drag.moved; drag = null;
    if(moved) lbBox.dataset.justDragged = "1", setTimeout(() => delete lbBox.dataset.justDragged, 0);
  }));

  /* 点击图片以外的区域关闭 */
  lbBox.addEventListener("click", e => {
    if(lbBox.dataset.justDragged) return;
    if(e.target === lbBox || e.target === lbFig) lb.close();
  });
  lb.addEventListener("keydown", e => {
    if(e.key === "ArrowLeft"){ e.preventDefault(); stepLB(-1); }
    if(e.key === "ArrowRight"){ e.preventDefault(); stepLB(1); }
    if(e.key === "+" || e.key === "="){ e.preventDefault(); zoomLB(1); }
    if(e.key === "-" || e.key === "_"){ e.preventDefault(); zoomLB(-1); }
    if(e.key === "0"){ e.preventDefault(); resetLB(); }
  });

  /* ==========================================================
     12 · 路由 & 初始化
     ========================================================== */
  function route(){
    const his = (location.hash || "").indexOf("history") >= 0;
    $("view-gen").hidden = his;
    $("view-his").hidden = !his;
    if(his){ $("tab-his").setAttribute("aria-current","page"); $("tab-gen").removeAttribute("aria-current"); }
    else   { $("tab-gen").setAttribute("aria-current","page"); $("tab-his").removeAttribute("aria-current"); }
    if(his) loadHistory();
  }
  window.addEventListener("hashchange", route);

  setToken(false);
  renderThumbs();
  applyAspect("1:1");
  setRange("all");
  gate();
  route();

  /* Token 状态由后端给出，页面永远不持有也不回显 Token 值 */
  (async () => {
    try{
      const data = await api("/api/bootstrap");
      setToken(!!data.token_configured);
      if(data.token_configured) await loadConfig();
      else toast("尚未配置 Token。", "", { key:"token", timeout:0,
             action:{ label:"配置 Token", onClick:() => $("token-btn").click() } });
    }catch(err){ onApiError(err); }
  })();
}

if (typeof document !== "undefined" && typeof document.addEventListener === "function") {
  document.addEventListener("DOMContentLoaded", boot);
}
