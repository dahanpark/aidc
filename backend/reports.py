"""Offline exports from a single JSON snapshot. Internal notes are never included."""
import csv
import html
import io
import json
from datetime import datetime, timezone
from .security import assert_safe_url


def safe_url(value):
    try:
        return assert_safe_url(value)
    except ValueError:
        pass
    return ""


def export(snapshot, kind, project_ids=None, article_ids=None, charter=None):
    datasets = snapshot["datasets"]
    projects = list(datasets.get("projects", {}).values())
    articles = list(datasets.get("articles", {}).values())
    if project_ids is not None:
        projects = [p for p in projects if p["id"] in project_ids]
        linked = {aid for p in projects for aid in p.get("article_ids", [])}
        if article_ids is None:
            articles = [a for a in articles if a["id"] in linked]
    if article_ids is not None:
        articles = [a for a in articles if a["id"] in article_ids]
    e = lambda value: html.escape(str(value if value is not None else "미확인"), quote=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if kind == "charter":
        raw = json.dumps(charter, ensure_ascii=False, allow_nan=False, indent=2)
        return raw.encode("utf-8"), "application/json; charset=utf-8", "AIDC-ATLAS-charter.json"
    if kind == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["사업명", "범위", "국가", "계층", "상태", "공개규모(종류/기준별 분리)", "발표기준", "근거URL"])
        for p in projects:
            capacities = "; ".join(f"{c.get('metric', '')}: {c.get('value', '미확인')} {c.get('unit', '')} / {c.get('basis', '')}" for c in p.get("capacities", []))
            urls = "; ".join(safe_url(datasets.get("articles", {}).get(aid, {}).get("url", "")) for aid in p.get("article_ids", []))
            row = [p.get("name"), p.get("scope"), p.get("country"), p.get("entity_level"), p.get("status"), capacities, p.get("latest_change_at"), urls]
            # Prevent spreadsheet formula injection, including leading whitespace.
            writer.writerow([("'" + str(v)) if str(v or "").lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
        return ("\ufeff" + output.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"AIDC-ATLAS-projects-{stamp}.csv"
    if kind not in ("report", "newsletter"):
        raise ValueError("Unknown export kind")
    title = "사업 인텔리전스 보고서" if kind == "report" else "선택 기사 뉴스레터"
    sections = []
    if kind == "report":
        for p in projects:
            capacities = "".join(f"<li>{e(c.get('metric'))}: {e(c.get('value'))} {e(c.get('unit'))} · {e(c.get('basis'))} · {e(c.get('scope'))}</li>" for c in p.get("capacities", []))
            lines = "".join(f"<li>{e(line)}</li>" for line in p.get("summary", []))
            sections.append(f"<section><h2>{e(p.get('name'))}</h2><p>{e(p.get('country'))} · {e(p.get('entity_level'))} · {e(p.get('status'))}</p><ul>{lines}</ul><ul>{capacities}</ul></section>")
    for article in articles:
        url = safe_url(article.get("url"))
        source = f'<a href="{e(url)}" rel="noopener noreferrer">공개 원문 열기</a>' if url else "원문 URL 미확인"
        summary = article.get("summary", "")
        if isinstance(summary, list):
            summary = " · ".join(str(s) for s in summary)
        sections.append(f"<section><h2>{e(article.get('title'))}</h2><p>{e(article.get('publisher'))} · {e(article.get('published_at'))} · {e(article.get('access_status'))}</p><p>{e(summary)}</p><p>{source}</p></section>")
    body = "".join(sections) or "<p>선택된 자료가 없습니다.</p>"
    # Inline-only styling also works in mail clients; no scripts, keys, or private notes.
    document = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIDC ATLAS · {title}</title></head>
<body style="margin:0;background:#f4f6fa;color:#152238;font:15px/1.8 'Malgun Gothic',sans-serif"><main style="max-width:960px;margin:24px auto;padding:32px;background:#fff"><p style="color:#0f766e;font-weight:bold">AIDC ATLAS</p><h1>{title}</h1><p>JSON 스냅샷: {e(snapshot['generation'])}<br>자료 기준: {e(snapshot['as_of'])}</p><p style="padding:12px;border:1px solid #cbd5e1">공식 공개자료의 고정 사례 + 수동 정답·모의 응답 기반 파일럿입니다. 최신 운영상태와 실제 AI 품질은 미검증입니다. Program과 포함 Site/Phase, 용량 종류·계획/실제는 합산하지 않습니다. 사내 링크·직접 메모·인증정보는 제외했습니다.</p>{body}</main></body></html>'''
    return document.encode("utf-8"), "text/html; charset=utf-8", f"AIDC-ATLAS-{kind}-{stamp}.html"
