let newsItems=[];
let activeType='전체';
let visibleCount=15;
const PAGE_SIZE=15;
const search=document.getElementById('news-search');
const list=document.getElementById('news-list');
const note=document.querySelector('.news-note');

function escapeHtml(value){const el=document.createElement('div');el.textContent=value||'';return el.innerHTML}

function getFiltered(){
  const q=search.value.trim().toLowerCase();
  return newsItems.filter(n=>(activeType==='전체'||n.type===activeType)&&`${n.agency} ${n.title} ${(n.tags||[]).join(' ')}`.toLowerCase().includes(q));
}

function render(){
  const filtered=getFiltered();
  const visible=filtered.slice(0,visibleCount);

  if(!filtered.length){
    list.innerHTML='<div class="news-empty">조건에 맞는 보도자료가 없습니다.</div>';
    return;
  }

  const cards=visible.map((n,i)=>`<article class="news-card"><div class="news-mark">${escapeHtml(n.agency.slice(0,2))}</div><div class="news-main"><div class="news-meta"><b>${escapeHtml(n.agency)}</b><span>${escapeHtml(n.type||'공공기관')}</span><time>${escapeHtml(n.date||'')}</time></div><h3>${escapeHtml(n.title)}</h3><div class="news-tags">${(n.tags||[]).map(t=>`<span>#${escapeHtml(t)}</span>`).join('')}</div></div><a class="news-link" href="${escapeHtml(n.url)}" target="_blank" rel="noopener noreferrer" aria-label="원문 보기">↗</a>${i===0&&visibleCount<=PAGE_SIZE?'<i>NEW</i>':''}</article>`).join('');

  const hasMore=filtered.length>visibleCount;
  const moreButton=hasMore?`<button class="news-load-more" id="news-load-more">더보기 (${filtered.length-visibleCount}건 더 있음)</button>`:'';

  list.innerHTML=cards+moreButton;

  if(hasMore){
    document.getElementById('news-load-more').addEventListener('click',()=>{
      visibleCount+=PAGE_SIZE;
      render();
    });
  }
}

function resetAndRender(){
  visibleCount=PAGE_SIZE;
  render();
}

async function loadNews(){
  list.innerHTML='<div class="news-empty">최신 보도자료를 불러오는 중입니다.</div>';
  try{
    const response=await fetch('../data/news.json',{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();
    newsItems=Array.isArray(data.items)?data.items:[];
    const updated=data.generatedAt?new Date(data.generatedAt).toLocaleString('ko-KR'):'확인되지 않음';
    const connected=data.configuredAgencyCount??0,total=data.totalAgencyCount??0;
    note.textContent=`최근 갱신: ${updated} · 공식 보도자료 게시판 직접 연결 ${connected}/${total}개 기관 · 제목을 누르면 기관 원문으로 이동합니다.`;
    resetAndRender();
  }catch(error){
    list.innerHTML='<div class="news-empty">보도자료 데이터를 불러오지 못했습니다. GitHub Actions의 ‘보도자료 자동 갱신’을 한 번 실행해주세요.</div>';
    note.textContent='데이터 연결 준비가 필요합니다. 저장소의 Actions 탭에서 보도자료 자동 갱신을 수동 실행할 수 있습니다.';
  }
}

search.addEventListener('input',resetAndRender);
document.getElementById('news-filters').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;activeType=b.dataset.type;document.querySelectorAll('.news-filters button').forEach(x=>x.classList.toggle('active',x===b));resetAndRender()});
loadNews();
