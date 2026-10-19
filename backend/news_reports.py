"""Period-aligned news digest exports. No internal links/notes or credentials."""
import csv
import html
import io
import json
from datetime import datetime, timezone
from .reports import safe_url


def export_workspace(workspace, kind, snapshot_id):
    rows = workspace.get('rows', [])
    def text(value):
        if isinstance(value,list):
            return ' · '.join(str(v) for v in value)
        return str(value if value is not None else '')
    escape = lambda v: html.escape(text(v),quote=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    if kind == 'news-csv':
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['발행시각','매체','기사제목','기업(매칭후보)','사업(매칭후보)','사업분류','국가','도시','요약','확인범위','변경표시','기사URL'])
        for row in rows:
            values = [row.get('published_at'),row.get('publisher'),row.get('title'),row.get('company_names',[]),row.get('project_names',[]),row.get('categories',[]),row.get('country'),row.get('city'),row.get('summary'),row.get('access_status'),row.get('change_label'),safe_url(row.get('url',''))]
            writer.writerow(["'"+text(v) if text(v).lstrip().startswith(('=','+','-','@')) else text(v) for v in values])
        return ('\ufeff'+output.getvalue()).encode('utf-8'),'text/csv; charset=utf-8',f'AIDC-ATLAS-news-{stamp}.csv'
    if kind != 'news-report':
        raise ValueError('Unsupported news export')
    filters = workspace.get('filters',{})
    summaries = ''.join('<li>'+escape(item.get('text',''))+'<small> · 근거 '+escape(', '.join(item.get('article_ids',[])))+'</small></li>' for item in workspace.get('summary',[]))
    changes = ''.join('<li><strong>'+escape(h.get('label',h.get('field','변경')))+':</strong> '+escape(h.get('before','최초 발견'))+' → <mark>'+escape(h.get('after'))+'</mark> · '+escape(h.get('changed_at'))+'</li>' for h in workspace.get('highlights',[]))
    body = ''
    for row in rows:
        url = safe_url(row.get('url',''))
        title = '<a href="'+escape(url)+'" rel="noopener noreferrer">'+escape(row.get('title'))+'</a>' if url else escape(row.get('title'))
        body += '<tr><td>'+escape(row.get('published_at'))+'<br>'+escape(row.get('publisher'))+'</td><td>'+title+'<br><small>'+escape(row.get('access_status'))+'</small></td><td>'+escape(row.get('company_names',[]))+'<br>'+escape(row.get('project_names',[]))+'</td><td>'+escape(row.get('categories',[]))+'</td><td>'+escape(row.get('summary'))+'</td></tr>'
    limitations = ' · '.join(text(x) for x in workspace.get('limitations',[]))
    document = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIDC ATLAS 기사 종합</title><style>body{{font:14px/1.7 'Malgun Gothic',sans-serif;color:#152238;max-width:1280px;margin:30px auto;padding:20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #cbd5e1;padding:10px;text-align:left;vertical-align:top}}a{{color:#0f766e}}small{{color:#53657b}}mark{{background:#fff1ad}}@media print{{body{{margin:0}}tr{{break-inside:avoid}}}}</style></head><body><p>AIDC ATLAS · 기사 중심 인텔리전스</p><h1>선택 기간 기사 종합 요약·통합표</h1><p>기간: {escape(filters.get('label',filters.get('period')))} · {escape(filters.get('start'))} ~ {escape(filters.get('end'))}<br>스냅샷: {escape(snapshot_id)} · 기사 {len(rows)}개</p><p>공개 기사 메타데이터 기반 종합입니다. 기업·사업 이름 매칭은 후보이며 본문이 미확인된 기사의 수치·역할을 확정하지 않습니다. 사내 링크·직접 메모는 제외했습니다.</p><h2>기사 종합</h2><ul>{summaries}</ul><h2>변경 하이라이트</h2><ul>{changes}</ul><h2>근거 기사 통합표</h2><table><thead><tr><th>발행·매체</th><th>제목·기사 링크</th><th>기업·사업 후보</th><th>분류</th><th>요약</th></tr></thead><tbody>{body}</tbody></table><p>{escape(limitations)}</p><p>검색 작업 완료는 모든 기사의 확보를 뜻하지 않습니다.</p></body></html>'''
    return document.encode('utf-8'),'text/html; charset=utf-8',f'AIDC-ATLAS-news-{stamp}.html'
