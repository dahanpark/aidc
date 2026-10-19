"""Isolated real HTTP host for browser tests; never mutates the user's store."""
import shutil
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.server import AtlasApplication, make_server
from backend import news
from datetime import datetime, timezone, timedelta

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='atlas-browser-') as folder:
        target = Path(folder)
        for name in ('fixtures', 'config', 'frontend'):
            shutil.copytree(root / name, target / name)
        app = AtlasApplication(target)
        if '--news' in sys.argv:
            def seed(ds):
                published = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
                for aid,title in [('browser-kr','Oracle 울산 데이터센터 냉각 투자'),
                                  ('browser-ca','Oracle Canada AI data center expansion'),
                                  ('browser-daejeon','Microsoft Daejeon South Korea data center design')]:
                    ds['articles'][aid] = {'id':aid,'url':'https://example.com/'+aid,'title':title,
                        'publisher':'격리 브라우저 테스트 자료','published_at':published,'collected_at':published,
                        'first_seen_at':published,'project_ids':[],'mode':'live_metadata',
                        'access_status':'feed_metadata_only','summary_method':'metadata_digest'}
                news.enrich_articles(ds,['browser-kr','browser-ca','browser-daejeon'])
                ds['news_jobs'] = {'browser-job':{'id':'browser-job','status':'partial','can_resume':True,
                    'filters':news.normalize_filters({'period':'1m'}),'pending_windows':[{'id':'pending'}],
                    'updated_at':published,'new_articles':3,'request_count':1}}
            app.repo.transact(seed)
        if '--visual' in sys.argv:
            def seed_visual(ds):
                # Explicit test preferences only. These are not a user decision.
                ds['settings']['app']['visualization']={'map_mode':'split','position_policy':'approximate','ack_scope':'items'}
            app.repo.transact(seed_visual)
        server = make_server(app, 18765)
        print('Isolated browser fixture ready: http://127.0.0.1:18765', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
