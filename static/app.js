/* ======================== 常量 & 状态 ======================== */
const API_BASE = '';
const POLL_INTERVAL = 2000;
const MAX_POLL_COUNT = 300;

const state = {
  userId: null,
  phone: null,
  token: null,
  profile: null,
  taskId: null,
  selectedFile: null,
  srtContent: null,
  outputUrl: null,
  pollingTimer: null,
  pollCount: 0,
  startTime: null,
  elapsedTimer: null,
  packages: null,
  styles: [],
  selectedStyleId: 1,
  isEditingSrt: false,
};

/* ======================== Toast ======================== */
function showToast(msg, type) {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = 'toast ' + (type || 'info');
  const icons = {success:'<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" style="color:var(--color-success)"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',error:'<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" style="color:var(--color-error)"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',info:'<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2" style="color:var(--brand-primary)"><path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"/></svg>'};
  t.innerHTML = icons[type]||icons.info;
  const span = document.createElement('span');
  span.textContent = String(msg);
  t.appendChild(span);
  c.appendChild(t);
  setTimeout(() => { t.style.opacity='0'; t.style.transform='translateX(20px)'; t.style.transition='all 0.3s ease'; setTimeout(()=>t.remove(),300); }, 3000);
}

function authHeaders(extra) {
  const h = Object.assign({}, extra || {});
  if (state.token) h.Authorization = 'Bearer ' + state.token;
  return h;
}

function apiFetch(url, options) {
  const opts = options || {};
  opts.headers = authHeaders(opts.headers);
  return fetch(API_BASE + url, opts).then(function(r){
    return r.json().catch(function(){ return {}; }).then(function(d){
      if(!r.ok) throw new Error(d.detail || d.message || ('请求失败：' + r.status));
      return d;
    });
  });
}

function downloadFile(url, filename) {
  fetch(API_BASE + url, {headers:authHeaders()})
    .then(function(r){
      if(!r.ok) return r.json().catch(function(){return {};}).then(function(d){throw new Error(d.detail || '下载失败');});
      return r.blob();
    })
    .then(function(blob){
      const href=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=href;
      a.download=filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(href);
    })
    .catch(function(e){showToast(e.message,'error');});
}

function playSuccessSound() {
  try {
    const ctx = new (window.AudioContext||window.webkitAudioContext)();
    [523.25,659.25,783.99].forEach((f,i) => {
      const o=ctx.createOscillator(),g=ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.frequency.value=f; o.type='sine';
      g.gain.setValueAtTime(0,i*0.15);
      g.gain.linearRampToValueAtTime(0.25,i*0.15+0.05);
      g.gain.exponentialRampToValueAtTime(0.001,i*0.15+0.4);
      o.start(i*0.15); o.stop(i*0.15+0.4);
    });
  } catch(e) {}
}

function showNotification(title, body) {
  if (!('Notification' in window)) return;
  if (Notification.permission==='granted') new Notification(title,{body});
  else if (Notification.permission!=='denied') Notification.requestPermission();
}

function showModal(html) {
  document.getElementById('modalContent').innerHTML = html;
  document.getElementById('modalOverlay').classList.remove('hidden');
}
function closeModal() { document.getElementById('modalOverlay').classList.add('hidden'); }
document.getElementById('modalOverlay').addEventListener('click', function(e) { if(e.target===this) closeModal(); });

/* ======================== 登录 ======================== */
function sendCode() {
  const phone = document.getElementById('phoneInput').value.trim();
  if (!phone) { showToast('请输入手机号','error'); return; }
  const btn = document.getElementById('sendCodeBtn');
  btn.disabled = true;
  fetch(API_BASE+'/send-code',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone})})
    .then(r=>r.json()).then(()=>{
      showToast('Mock 验证码：123456','info');
      let r=30; btn.textContent=r+'s';
      const iv=setInterval(()=>{if(--r<=0){clearInterval(iv);btn.textContent='重新获取';btn.disabled=false;}else btn.textContent=r+'s';},1000);
    }).catch(()=>{btn.disabled=false;btn.textContent='获取验证码';showToast('发送失败','error');});
}

function login() {
  const phone=document.getElementById('phoneInput').value.trim(), code=document.getElementById('codeInput').value.trim();
  if(!phone||!code){showToast('请填写手机号和验证码','error');return;}
  fetch(API_BASE+'/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({phone,code})})
    .then(r=>r.json()).then(d=>{
      if(d.user_id&&d.access_token){state.userId=d.user_id;state.phone=phone;state.token=d.access_token;showMain();showToast('登录成功','success');}
      else showToast(d.detail||'登录失败','error');
    }).catch(e=>showToast('登录失败: '+e.message,'error'));
}

function logout() {
  clearInterval(state.pollingTimer); clearInterval(state.elapsedTimer);
  state.userId=null;state.phone=null;state.token=null;state.taskId=null;state.selectedFile=null;
  document.getElementById('mainView').classList.add('hidden');
  document.getElementById('loginView').classList.remove('hidden');
  showToast('已退出登录','info');
}

function showMain() {
  document.getElementById('loginView').classList.add('hidden');
  document.getElementById('mainView').classList.remove('hidden');
  document.getElementById('userInfo').textContent=state.phone;
  refreshProfile();
  loadPackages();
  loadStyles();
  switchTab('home');
}

/* ======================== Tab ======================== */
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));
  document.querySelector('.tab-btn[data-tab="'+name+'"]').classList.add('active');
  document.getElementById('tab-'+name).classList.add('active');
  if(name==='history') loadHistory();
  if(name==='shop'){refreshProfile();loadPackages();}
}

/* ======================== 用户信息 ======================== */
function refreshProfile() {
  if(!state.userId) return;
  apiFetch('/user/'+state.userId+'/profile')
    .then(p=>{state.profile=p;updateUI();updateBurnFeature();}).catch(function(){});
}

function updateUI() {
  const p=state.profile; if(!p) return;
  const badge=document.getElementById('memberBadge');
  const tier=p.membership_tier||'free';
  const tierNames={free:'Free',professional:'专业会员',premium:'高级会员'};
  badge.textContent=tierNames[tier]||'Free';
  badge.className='badge-'+tier+' text-xs px-2 py-0.5 rounded-full font-medium shrink-0';

  const q=p.quota_seconds;
  document.getElementById('quotaDisplay').classList.remove('hidden');
  document.getElementById('quotaNum').textContent=q;
  document.getElementById('quotaDetail').textContent=q+' 秒';

  document.getElementById('currentTierDisplay').textContent=tierNames[tier]||'Free';
  document.getElementById('currentQuotaDisplay').textContent=q+'s';
  document.getElementById('currentUsedDisplay').textContent=(p.total_used_seconds||0)+'s';
  document.getElementById('currentRetentionDisplay').textContent=(p.retention_days||3)+'天';

  if(q<60&&tier==='free') document.getElementById('quotaBar').style.borderColor='var(--color-warning)';
  else document.getElementById('quotaBar').style.borderColor='';

  // 字幕编辑权限
  if(p.can_edit_subtitles) {
    document.getElementById('editSrtBtn').classList.remove('hidden');
  } else {
    document.getElementById('editSrtBtn').classList.add('hidden');
  }
}

function updateBurnFeature() {
  var p=state.profile;
  if(!p) return;
  // 烧录区
  var lock=document.getElementById('burnFeatureLock');
  var unlock=document.getElementById('burnFeatureUnlock');
  var desc=document.getElementById('burnFeatureDesc');
  if(lock) lock.classList[p.can_burn?'add':'remove']('hidden');
  if(unlock) unlock.classList[p.can_burn?'remove':'add']('hidden');
  if(desc) desc.textContent=p.can_burn?'已解锁 · 将字幕嵌入视频文件':'将字幕嵌入视频文件';
  // 样式展示区
  var slog=document.getElementById('styleShowcaseLock');
  var sunl=document.getElementById('styleShowcaseUnlock');
  if(slog) slog.classList[p.can_custom_style?'add':'remove']('hidden');
  if(sunl) sunl.classList[p.can_custom_style?'remove':'add']('hidden');
  renderHomeStyles();
  // 烧录按钮
  var burnBtn=document.getElementById('burnBtn');
  if(!burnBtn) return;
  if(!p.can_burn) {
    burnBtn.disabled=true;
    burnBtn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5a6 6 0 11-12 0 6 6 0 0112 0z"/></svg> 升级会员以烧录';
  } else {
    burnBtn.disabled=false;
    burnBtn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg> 生成带字幕视频';
  }
  // 结果区的样式选择面板
  var styleArea=document.getElementById('styleSelectorArea');
  if(styleArea) styleArea.classList[p.can_custom_style?'remove':'add']('hidden');
}

/* ======================== 字幕样式 ======================== */
function loadStyles() {
  fetch(API_BASE+'/styles')
    .then(r=>r.json()).then(d=>{
      state.styles=d.styles||[];
      state.selectedStyleId=1;
      renderStyleChips();
    }).catch(function(){});
}

function renderStyleChips() {
  var container=document.getElementById('styleChips');
  if(container) {
    container.innerHTML='';
    state.styles.forEach(function(s){
      var chip=document.createElement('button');
      chip.className='style-chip'+(s.id===state.selectedStyleId?' active':'');
      chip.textContent=s.name;
      chip.title=s.description;
      chip.onclick=function(){selectStyle(s.id);};
      container.appendChild(chip);
    });
  }
  renderHomeStyles();
}

function renderHomeStyles() {
  var container=document.getElementById('homeStyleChips');
  if(!container) return;
  container.innerHTML='';
  var canCustom=state.profile&&state.profile.can_custom_style;
  state.styles.forEach(function(s){
    var chip=document.createElement('button');
    chip.className='style-chip'+(s.id===state.selectedStyleId?' active':'');
    chip.textContent=s.name;
    chip.title=s.description+(canCustom?' (点击选择)':' (需要高级会员)');
    chip.style.opacity=canCustom?'1':'0.55';
    chip.onclick=function(){
      if(!canCustom) { showToast('请升级高级会员以使用自定义字幕样式','error'); return; }
      selectStyle(s.id);
    };
    container.appendChild(chip);
  });
}

function selectStyle(id) {
  if(state.profile&&!state.profile.can_custom_style) {
    showToast('请升级高级会员以使用自定义字幕样式','error');
    return;
  }
  state.selectedStyleId=id;
  document.querySelectorAll('#styleChips .style-chip, #homeStyleChips .style-chip').forEach(function(c,i){
    var s=state.styles[i];
    c.className='style-chip'+(s&&s.id===id?' active':'');
  });
  var s=state.styles.find(function(x){return x.id===id;});
  if(s) {
    var el=document.getElementById('stylePreviewText');
    if(el) el.textContent=s.description+' · '+s.font+' '+s.font_size+'px';
  }
}

/* ======================== 上传 ======================== */
function handleFile(file) {
  if(!file) return;
  document.getElementById('uploadPlaceholder').classList.add('hidden');
  document.getElementById('uploadFileInfo').classList.remove('hidden');
  document.getElementById('fileName').textContent=file.name;
  document.getElementById('fileSize').textContent=formatSize(file.size);
  state.selectedFile=file;
  document.getElementById('uploadBtn').disabled=false;
}

function resetUpload() {
  state.selectedFile=null;
  document.getElementById('fileInput').value='';
  document.getElementById('uploadPlaceholder').classList.remove('hidden');
  document.getElementById('uploadFileInfo').classList.add('hidden');
  document.getElementById('uploadBtn').disabled=true;
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('dropZone').classList.remove('dragover');
  const file=e.dataTransfer.files[0];
  if(file&&file.type.startsWith('video/')) handleFile(file);
  else showToast('请拖入视频文件','error');
}

function formatSize(bytes) {
  if(bytes<1024*1024) return (bytes/1024).toFixed(1)+' KB';
  return (bytes/(1024*1024)).toFixed(1)+' MB';
}

function uploadVideo() {
  if(!state.selectedFile) return;
  const btn=document.getElementById('uploadBtn');
  btn.disabled=true;
  btn.innerHTML='<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg> 上传中...';

  const fd=new FormData();
  fd.append('video',state.selectedFile);
  fd.append('user_id',state.userId);

  fetch(API_BASE+'/upload',{method:'POST',headers:authHeaders(),body:fd})
    .then(function(r){return r.json().then(function(d){return{status:r.status,data:d};});})
    .then(function(resp){
      if(resp.status===200&&resp.data.task_id){
        state.taskId=resp.data.task_id;
        state.pollCount=0;
        state.startTime=Date.now();
        state.isEditingSrt=false;
        _hide('uploadArea');
        _hide('resultSection');
        _hide('bottomActions');
        _show('taskSection');
        document.getElementById('progressBar').style.width='10%';
        document.getElementById('progressBar').classList.add('active');
        document.getElementById('statusDot').className='status-dot active';
        updateTaskStatus('任务已提交');
        startPolling();
        startElapsedTimer();
      } else {
        btn.disabled=false;
        btn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg> 开始上传';
        showToast(resp.data.detail||'上传失败','error');
        refreshProfile();
      }
    })
    .catch(function(e){
      btn.disabled=false;
      btn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg> 开始上传';
      showToast('上传失败: '+e.message,'error');
    });
}

/* 重置所有（新建任务） */
function resetAll() {
  clearInterval(state.pollingTimer);
  clearInterval(state.elapsedTimer);
  state.taskId=null;
  state.srtContent=null;
  state.outputUrl=null;
  state.isEditingSrt=false;
  _hide('taskSection');
  _hide('resultSection');
  _hide('bottomActions');
  _show('uploadArea');
  resetUpload();
}

/* 安全地显示/隐藏DOM元素 */
function _show(id){var e=document.getElementById(id);if(e)e.classList.remove('hidden');}
function _hide(id){var e=document.getElementById(id);if(e)e.classList.add('hidden');}

/* ======================== 轮询 ======================== */
function startPolling() {
  if(state.pollingTimer) clearInterval(state.pollingTimer);
  state.pollingTimer=setInterval(pollTask,POLL_INTERVAL);
}

function updateTaskStatus(t){document.getElementById('taskStatusText').textContent=t;}
function updateProgress(w){document.getElementById('progressBar').style.width=w+'%';}

function pollTask() {
  state.pollCount++;
  if(state.pollCount>MAX_POLL_COUNT){
    clearInterval(state.pollingTimer);clearInterval(state.elapsedTimer);
    updateTaskStatus('任务超时');
    document.getElementById('progressBar').classList.remove('active');
    document.getElementById('statusDot').className='status-dot error';
    showResult('fail','任务可能失败，请联系支持');
    return;
  }
  apiFetch('/task/'+state.taskId)
    .then(d=>{
      const pct=Math.min(15+(state.pollCount/MAX_POLL_COUNT)*70,85);
      switch(d.status){
        case'pending':updateTaskStatus('排队等待中');updateProgress(pct);break;
        case'processing':updateTaskStatus('AI 语音识别中');updateProgress(pct+5);break;
        case'done':
          clearInterval(state.pollingTimer);clearInterval(state.elapsedTimer);
          updateTaskStatus('转写完成');updateProgress(100);
          document.getElementById('progressBar').classList.remove('active');
          document.getElementById('statusDot').className='status-dot success';
          showResult('success',d.srt_content||'(空字幕)');
          state.srtContent=d.srt_content;
          state.outputUrl=d.output_video_url;
          playSuccessSound();
          showNotification('智影字幕','视频转写已完成！');
          showToast('转写完成！','success');
          refreshProfile();
          loadHistory();
          break;
        case'failed':
          clearInterval(state.pollingTimer);clearInterval(state.elapsedTimer);
          updateTaskStatus('处理失败');
          document.getElementById('progressBar').classList.remove('active');
          document.getElementById('progressBar').style.background='#D4A9A9';
          document.getElementById('statusDot').className='status-dot error';
          updateProgress(100);
          showResult('fail',d.error_message||'未知错误');
          refreshProfile();
          loadHistory();
          break;
      }
    });
}

function showResult(type,content) {
  _hide('taskSection');
  _show('resultSection');
  _hide('resultSuccess');
  _hide('resultFail');
  _hide('downloadSection');
  _show('bottomActions');

  if(type==='success'){
    _show('resultSuccess');
    var srtDisp=document.getElementById('srtPreviewDisplay');
    if(srtDisp) srtDisp.textContent=content;
    if(srtDisp) srtDisp.classList.remove('hidden');
    document.getElementById('srtEditor').classList.add('hidden');
    state.isEditingSrt=false;
    document.getElementById('editSrtBtn').classList.remove('hidden');
    document.getElementById('saveSrtBtn').classList.add('hidden');
    document.getElementById('cancelSrtBtn').classList.add('hidden');
    // 更新烧录按钮
    updateBurnFeature();
    // 默认选中白色经典样式
    state.selectedStyleId=1;
    renderStyleChips();
  }else{
    document.getElementById('resultFail').classList.remove('hidden');
    document.getElementById('errorMessage').textContent=content;
  }
}

function startElapsedTimer() {
  if(state.elapsedTimer) clearInterval(state.elapsedTimer);
  state.elapsedTimer=setInterval(function(){
    const e=Math.floor((Date.now()-state.startTime)/1000);
    document.getElementById('taskElapsed').textContent=Math.floor(e/60)+'分'+(e%60)+'秒';
  },1000);
}

/* ======================== 字幕编辑 ======================== */
function toggleSrtEdit() {
  if(!state.profile||!state.profile.can_edit_subtitles){
    showToast('请升级专业会员以编辑字幕','error');
    return;
  }
  _hide('srtPreviewDisplay');
  _show('srtEditor');
  var editor=document.getElementById('srtEditor');
  var display=document.getElementById('srtPreviewDisplay');
  if(editor) editor.value=state.srtContent||(display?display.textContent:'');
  _hide('editSrtBtn');
  _show('saveSrtBtn');
  _show('cancelSrtBtn');
  state.isEditingSrt=true;
}

function cancelSrtEdit() {
  _show('srtPreviewDisplay');
  _hide('srtEditor');
  _show('editSrtBtn');
  _hide('saveSrtBtn');
  _hide('cancelSrtBtn');
  state.isEditingSrt=false;
}

function saveSrtEdit() {
  const newContent=document.getElementById('srtEditor').value;
  if(!newContent.trim()){showToast('字幕内容不能为空','error');return;}
  apiFetch('/task/'+state.taskId+'/srt',{
    method:'PUT',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({srt_content:newContent})
  }).then(function(d){
    if(d.message==='ok'){
      state.srtContent=newContent;
      document.getElementById('srtPreviewDisplay').textContent=newContent;
      cancelSrtEdit();
      showToast('字幕已保存','success');
    }else{
      showToast(d.detail||'保存失败','error');
    }
  }).catch(function(e){showToast('保存失败: '+e.message,'error');});
}

/* ======================== 烧录 ======================== */
function burnSubtitles() {
  const btn=document.getElementById('burnBtn');
  btn.disabled=true;
  btn.innerHTML='<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/></svg> 生成中...';

  const body={task_id:state.taskId};
  if(state.selectedStyleId&&state.profile&&state.profile.can_custom_style){
    body.style_id=state.selectedStyleId;
  }

  apiFetch('/burn',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)
  }).then(d=>{
    if(d.output_video_url){
      _show('downloadSection');
      var dl=document.getElementById('downloadLink');
      if(dl) {
        dl.href='#';
        dl.onclick=function(e){
          e.preventDefault();
          downloadFile(d.output_video_url, 'zhiying_'+state.taskId.slice(0,8)+'_sub.mp4');
        };
      }
      btn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg> 生成带字幕视频';
      btn.disabled=false;
      showToast('字幕烧录完成！','success');
    }else{
      btn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg> 生成带字幕视频';
      btn.disabled=false;
      showToast(d.detail||'烧录失败','error');
    }
  }).catch(function(e){
    btn.innerHTML='<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.53 16.122a3 3 0 00-5.78 1.128 2.25 2.25 0 01-2.4 2.245 4.5 4.5 0 008.4-2.245c0-.399-.078-.78-.22-1.128zm0 0a15.998 15.998 0 003.388-1.62m-5.043-.025a15.994 15.994 0 011.622-3.395m3.42 3.42a15.995 15.995 0 004.764-4.648l3.876-5.814a1.151 1.151 0 00-1.597-1.597L14.146 6.32a15.996 15.996 0 00-4.649 4.763m3.42 3.42a6.776 6.776 0 00-3.42-3.42"/></svg> 生成带字幕视频';
    btn.disabled=false;
    showToast('烧录失败: '+e.message,'error');
  });
}

/* ======================== 历史记录 ======================== */
function loadHistory() {
  if(!state.userId) return;
  const list=document.getElementById('historyList');
  const empty=document.getElementById('historyEmpty');
  const loading=document.getElementById('historyLoading');
  list.classList.add('hidden');
  empty.classList.add('hidden');
  loading.classList.remove('hidden');

  apiFetch('/user/'+state.userId+'/tasks')
    .then(d=>{
      loading.classList.add('hidden');
      const tasks=d.tasks||[];
      if(tasks.length===0){empty.classList.remove('hidden');return;}
      list.classList.remove('hidden');
      list.innerHTML='';
      if(state.profile) document.getElementById('historyNote').textContent='保留 '+state.profile.retention_days+' 天';

      tasks.forEach(function(t){
        const div=document.createElement('div');
        div.className='history-item';
        const statMap={pending:['等待中','active'],processing:['处理中','active'],done:['已完成','success'],failed:['失败','error']};
        const st=statMap[t.status]||['未知',''];
        const ts=formatTime(t.created_at);
        let acts='';
        if(t.status==='done'){
          if(t.has_srt) acts+='<button onclick="downloadFile(\'/download/srt/'+t.task_id+'\',\'zhiying_'+t.task_id.slice(0,8)+'.srt\')" class="btn-ghost rounded-lg text-xs px-2 py-1" title="下载 SRT"><svg class="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/></svg> SRT</button>';
          if(t.has_video) acts+='<button onclick="downloadFile(\'/download/video/'+t.task_id+'\',\'zhiying_'+t.task_id.slice(0,8)+'_sub.mp4\')" class="btn-ghost rounded-lg text-xs px-2 py-1" title="下载视频"><svg class="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z"/></svg> 视频</button>';
        }
        div.innerHTML='<div class="flex-1 min-w-0"><div class="flex items-center gap-2 mb-1"><span class="status-dot '+st[1]+'"></span><span class="text-xs font-medium">'+st[0]+'</span>'+(t.duration_seconds?'<span class="text-xs" style="color:var(--text-muted)">'+t.duration_seconds+'s</span>':'')+'</div><div class="text-xs" style="color:var(--text-muted)">'+ts+'</div></div><div class="flex items-center gap-1 shrink-0">'+acts+'</div>';
        list.appendChild(div);
      });
    })
    .catch(function(){
      loading.classList.add('hidden');
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent='加载失败，请重试';
    });
}

function formatTime(isoStr) {
  if(!isoStr) return '';
  try{
    const d=new Date(isoStr.replace(' ','T')+(isoStr.includes('Z')?'':'Z'));
    if(isNaN(d.getTime())) return isoStr;
    return String(d.getMonth()+1).padStart(2,'0')+'/'+String(d.getDate()).padStart(2,'0')+' '+String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');
  }catch(e){return isoStr;}
}

/* ======================== 套餐 & 商店 ======================== */
function loadPackages() {
  fetch(API_BASE+'/packages')
    .then(r=>r.json()).then(d=>{state.packages=d;renderPlans(d);})
    .catch(function(){showToast('加载套餐失败','error');});
}

function renderPlans(data) {
  if(!data) return;
  const planList=document.getElementById('membershipPlanList');
  planList.innerHTML='';
  const planOrder=['professional','premium'];
  const planNames={professional:'专业会员',premium:'高级会员'};

  planOrder.forEach(function(key){
    const plan=data.membership_plans[key];
    if(!plan||plan.price===0) return;
    const isRecommended=key==='professional';
    const isActive=state.profile&&state.profile.membership_tier===key;
    const py=(plan.price/100).toFixed(0);
    const maxDur=plan.max_task_duration;

    const card=document.createElement('div');
    card.className='member-card'+(isRecommended?' recommended':'')+(isActive?' active-tier':'');
    const featuresHTML='<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs mb-4" style="color:var(--text-secondary)">'
      +'<span>'+(plan.can_burn?'✅':'❌')+' 字幕烧录</span>'
      +'<span>'+(plan.can_edit_subtitles?'✅':'❌')+' 字幕编辑</span>'
      +'<span>'+(plan.high_precision?'✅':'❌')+' 高精度识别</span>'
      +'<span>'+(plan.can_custom_style?'✅':'❌')+' 自定义样式</span>'
      +'<span>'+(plan.carryover_months>0?'✅':'❌')+' 配额结转</span>'
      +'<span>📁 保留 '+plan.retention_days+' 天</span>'
      +'<span>⏱️ 最长 '+maxDur+'s/任务</span>'
      +'</div>';

    card.innerHTML='<div class="flex items-start justify-between mb-2"><div><div class="font-semibold text-base">'+plan.name+'</div><div class="text-xs mt-0.5" style="color:var(--text-muted)">每月 '+plan.monthly_quota+'s 配额</div></div><div class="text-right"><span class="text-xl font-bold" style="color:var(--brand-primary-dark)">¥'+py+'</span><span class="text-xs" style="color:var(--text-muted)">/月</span></div></div>'
      +featuresHTML
      +(isActive?'<div class="text-xs font-medium mb-3" style="color:var(--color-success)">当前套餐</div>':'')
      +'<button onclick="buyMembership(\''+key+'\')" class="btn w-full '+(isRecommended?'btn-gold':'btn-primary')+' btn-sm"'+(isActive?' disabled':'')+'>'+(isActive?'当前使用中':'立即开通')+'</button>';
    planList.appendChild(card);
  });

  // 增量包
  const topupList=document.getElementById('topupPackageList');
  topupList.innerHTML='';
  if(data.topup_packages){
    Object.entries(data.topup_packages).forEach(function(entry){
      const key=entry[0],pkg=entry[1];
      const py=(pkg.price/100).toFixed(0);
      const div=document.createElement('div');
      div.className='member-card flex items-center justify-between';
      div.innerHTML='<div><div class="font-semibold text-sm">'+pkg.name+'</div><div class="text-xs mt-0.5" style="color:var(--text-muted)">'+pkg.seconds+' 秒配额</div></div><div class="flex items-center gap-3"><span class="text-lg font-bold" style="color:var(--brand-primary-dark)">¥'+py+'</span><button onclick="buyTopup(\''+key+'\')" class="btn btn-secondary btn-sm">购买</button></div>';
      topupList.appendChild(div);
    });
  }
}

/* ======================== 购买流程 ======================== */
function buyTopup(packageKey) {
  const pkg=state.packages?.topup_packages?.[packageKey];
  if(!pkg) return;
  const py=(pkg.price/100).toFixed(0);
  showModal('<h3 class="text-lg font-semibold mb-4" style="font-family:var(--font-display)">确认购买</h3><div class="card-compact rounded-xl p-4 mb-6 text-sm"><div class="flex justify-between mb-2"><span style="color:var(--text-secondary)">增量包</span><span class="font-medium">'+pkg.name+'</span></div><div class="flex justify-between mb-2"><span style="color:var(--text-secondary)">配额</span><span class="font-medium">'+pkg.seconds+' 秒</span></div><div class="flex justify-between pt-2" style="border-top:1px solid var(--border-light)"><span style="color:var(--text-secondary)">金额</span><span class="font-bold text-lg" style="color:var(--brand-primary-dark)">¥'+py+'</span></div></div><div class="flex gap-3"><button onclick="closeModal()" class="btn btn-secondary flex-1">取消</button><button onclick="confirmTopup(\''+packageKey+'\')" class="btn btn-primary flex-1">确认支付</button></div>');
}

function confirmTopup(packageKey) {
  apiFetch('/create-topup-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId,package_key:packageKey})})
    .then(function(order){
      closeModal();
      showModal('<div class="text-center py-4"><svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" style="color:var(--brand-primary)"><path stroke-linecap="round" stroke-linejoin="round" d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 002.25-2.25V6.75A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25v10.5A2.25 2.25 0 004.5 19.5z"/></svg><h3 class="text-lg font-semibold mb-2" style="font-family:var(--font-display)">Mock 支付</h3><p class="text-sm mb-1" style="color:var(--text-secondary)">订单：'+order.order_id.slice(0,8)+'...</p><p class="text-sm" style="color:var(--text-secondary)">模拟线上支付流程</p><div class="flex gap-3 mt-6"><button onclick="closeModal()" class="btn btn-secondary flex-1">取消</button><button onclick="processPayment(\''+order.order_id+'\')" class="btn btn-success flex-1">确认支付 ¥'+(order.amount/100).toFixed(0)+'</button></div></div>');
    }).catch(function(e){closeModal();showToast('创建订单失败: '+e.message,'error');});
}

function buyMembership(tier) {
  const plan=state.packages?.membership_plans?.[tier];
  if(!plan) return;
  const py=(plan.price/100).toFixed(0);
  const planNames={professional:'专业会员',premium:'高级会员'};
  showModal('<h3 class="text-lg font-semibold mb-4" style="font-family:var(--font-display)">开通会员</h3><div class="card-compact rounded-xl p-4 mb-6 text-sm"><div class="flex justify-between mb-2"><span style="color:var(--text-secondary)">套餐</span><span class="font-medium">'+(planNames[tier]||tier)+'</span></div><div class="flex justify-between mb-2"><span style="color:var(--text-secondary)">配额</span><span class="font-medium">'+plan.monthly_quota+' 秒/月</span></div><div class="flex justify-between mb-2"><span style="color:var(--text-secondary)">文件保留</span><span class="font-medium">'+plan.retention_days+' 天</span></div><div class="flex justify-between pt-2" style="border-top:1px solid var(--border-light)"><span style="color:var(--text-secondary)">金额</span><span class="font-bold text-lg" style="color:var(--brand-primary-dark)">¥'+py+'</span></div></div><div class="flex gap-3"><button onclick="closeModal()" class="btn btn-secondary flex-1">取消</button><button onclick="confirmMembership(\''+tier+'\')" class="btn btn-gold flex-1">立即开通 ¥'+py+'</button></div>');
}

function confirmMembership(tier) {
  apiFetch('/create-membership-order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:state.userId,tier:tier})})
    .then(function(order){
      closeModal();
      showModal('<div class="text-center py-4"><svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5" style="color:var(--color-gold)"><path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z"/></svg><h3 class="text-lg font-semibold mb-2" style="font-family:var(--font-display)">Mock 支付</h3><p class="text-sm mb-1" style="color:var(--text-secondary)">订单：'+order.order_id.slice(0,8)+'...</p><p class="text-sm" style="color:var(--text-secondary)">模拟线上支付流程</p><div class="flex gap-3 mt-6"><button onclick="closeModal()" class="btn btn-secondary flex-1">取消</button><button onclick="processPayment(\''+order.order_id+'\')" class="btn btn-gold flex-1">确认支付 ¥'+(order.amount/100).toFixed(0)+'</button></div></div>');
    }).catch(function(e){closeModal();showToast('创建订单失败: '+e.message,'error');});
}

function processPayment(orderId) {
  closeModal();
  showToast('支付处理中...','info');
  apiFetch('/mock-pay/'+orderId,{method:'POST'})
    .then(function(d){
      showToast('支付成功！配额/会员已到账','success');
      playSuccessSound();
      refreshProfile();
      if(state.packages) loadPackages();
    }).catch(function(e){showToast('支付失败: '+e.message,'error');});
}

/* ======================== 启动 ======================== */
if('Notification' in window && Notification.permission==='default') Notification.requestPermission();
