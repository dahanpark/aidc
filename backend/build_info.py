"""Fingerprint public runtime files only; never operational or private config."""
import hashlib
from pathlib import Path


def runtime_build(root):
    root=Path(root);digest=hashlib.sha256()
    files=[*root.glob('backend/*.py'),*root.glob('frontend/*.js'),*root.glob('frontend/*.css'),*root.glob('frontend/*.html')]
    files.extend(p for p in (root/'run_atlas.py',root/'config/news_sources.json') if p.is_file())
    for p in sorted(files):
        digest.update(p.relative_to(root).as_posix().encode());digest.update(b'\0');digest.update(p.read_bytes())
    return digest.hexdigest()[:20]
