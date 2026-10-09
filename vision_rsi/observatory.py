"""Static, inspectable dashboard generated from canonical SQLite events."""
import json


def dashboard(ledger):
    events = ledger.events()
    serialized = json.dumps(events, ensure_ascii=False).replace('<', '\\u003c')
    document = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Vision RSI · Observatory</title>
<style>body{background:#0b1220;color:#e2e8f0;font:16px system-ui;margin:0;padding:30px;line-height:1.65}main{max-width:1200px;margin:auto}h1{margin-bottom:4px}small{color:#94a3b8}.notice{color:#fbbf24}.cards{display:flex;gap:12px;margin:20px 0}.card,article{background:#182438;border-radius:10px;padding:16px;margin:10px 0}.card{flex:1}b{display:block;font-size:26px;color:#5eead4}button,input{background:#22324a;color:#fff;border:1px solid #475569;padding:10px;border-radius:6px;margin:4px}button{cursor:pointer}button[aria-pressed=true]{border-color:#5eead4;color:#5eead4}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}summary{cursor:pointer}label{display:block;margin:12px 0}.kind{color:#7dd3fc}#objective{font-size:20px}a{color:#5eead4}</style>
<main><h1>Vision RSI · 研究观测台</h1><small>持久目标 · 证据链 · 行动与结果 · 自我改进提案</small>
<p class="notice">历史记录快照：真实 LLM / SSH 基础设施证据，指标为合成值。尚未进行真实视觉研究或 RSI 效果验证。</p>
<div id="objective"></div><div class="cards"><div class="card">研究状态<b id="status"></b></div><div class="card">事件数<b id="count"></b></div><div class="card">待回收行动<b id="pending"></b></div><div class="card">自我修改已采用<b>0</b></div></div>
<p>当前阻塞：COCO 数据路径、真实训练预算及开放研究执行器尚未接入。预算：此历史 Demo 实际 GPU 小时为 0；未配置研究总预算。</p>
<nav><button data-view="all" aria-pressed="true">研究时间线</button><button data-view="knowledge">证据与假设</button><button data-view="execution">行动与结果</button><button data-view="self">自我改进</button></nav>
<label>搜索摘要、任务或证据 <input id="search" placeholder="输入关键词" aria-label="搜索事件"></label><div id="events"></div>
<p><small>详情包含完整结构化记录和引用。暂停只改变研究调度意图，不取消已启动任务。本页为只读快照；CLI 更新后重新生成并刷新页面。无后台自主循环。</small></p></main>
<script>const events=EVENTS;let view='all';const groups={knowledge:['evidence','hypothesis'],execution:['action','result'],self:['self_change','reflection']};
const labels={objective:'研究目标',evidence:'证据',hypothesis:'假设',action:'行动',result:'结果',reflection:'反思',self_change:'自我修改提案',paused:'暂停',resumed:'恢复'};
document.querySelector('#objective').textContent=events[0]?.payload.summary||'尚未创建研究目标';
document.querySelector('#count').textContent=events.length;
const controls=events.filter(e=>['paused','resumed'].includes(e.kind));document.querySelector('#status').textContent=controls.at(-1)?.kind==='paused'?'已暂停':'可继续（无自主执行器）';
const finished=new Set(events.filter(e=>e.kind==='result').map(e=>e.payload.action));document.querySelector('#pending').textContent=events.filter(e=>e.kind==='action'&&!finished.has(e.key)).length;
function render(){let root=document.querySelector('#events');root.replaceChildren();const term=document.querySelector('#search').value.toLowerCase();let rows=events.filter(e=>(view==='all'||groups[view].includes(e.kind))&&JSON.stringify(e).toLowerCase().includes(term));
if(!rows.length){let p=document.createElement('p');p.textContent='暂无记录。自我修改不会自动采用，需要后续独立对照验证。';root.append(p)}
for(const e of rows){let a=document.createElement('article');a.id='event-'+e.seq;let tag=document.createElement('div');tag.className='kind';tag.textContent='#'+e.seq+' · '+labels[e.kind]+' · '+new Date(e.created_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});a.append(tag);let p=document.createElement('p');p.textContent=e.payload.summary;a.append(p);
for(const ref of [...(e.payload.refs||[]),...(e.payload.action?[e.payload.action]:[])]){let target=events.find(x=>x.key===ref);if(target){let link=document.createElement('a');link.href='#event-'+target.seq;link.textContent='引用 #'+target.seq+' ';link.onclick=()=>{view='all';document.querySelector('#search').value='';sync();render();};a.append(link)}}
let details=document.createElement('details');let summary=document.createElement('summary');summary.textContent='查看证据、命令与完整记录';let pre=document.createElement('pre');pre.textContent=JSON.stringify(e,null,2);details.append(summary,pre);a.append(details);root.append(a)}}
function sync(){document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)))}document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;sync();render()});document.querySelector('#search').oninput=render;render();</script></html>'''.replace('EVENTS', serialized)
    path = ledger.directory / 'observatory.html'
    path.write_text(document, encoding='utf-8')
    return str(path.resolve())
