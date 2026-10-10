"""Extract verified ZIPs into a new directory; never merge with existing data."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


def extract(archive, destination, expected_sha256, *, max_bytes, max_files):
    archive = Path(archive)
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Extraction destination already exists; refusing merge')
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64:
        raise ValueError('Expected full SHA-256 required')
    for limit in (max_bytes, max_files):
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError('Positive integer extraction limits required')
    digest = hashlib.sha256()
    # Keep the same open file for hashing and extraction.
    with archive.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError('Archive SHA-256 mismatch')
        stream.seek(0)
        with zipfile.ZipFile(stream) as bundle:
            members = bundle.infolist()
            if len(members) > max_files or sum(m.file_size for m in members) > max_bytes:
                raise ValueError('Archive exceeds extraction limits')
            names = set()
            for member in members:
                name = member.orig_filename
                if name != member.filename:
                    raise ValueError('Archive entry was normalized by platform')
                path = PurePosixPath(name)
                mode = member.external_attr >> 16
                if (not name or chr(92) in name or ':' in name or path.is_absolute()
                        or '..' in path.parts or name in names
                        or stat.S_ISLNK(mode) or member.flag_bits & 1
                        or path.parts[0] == '.extraction-receipt.json'):
                    raise ValueError('Unsafe or duplicate archive entry')
                if path.as_posix().rstrip('/') != name.rstrip('/'):
                    raise ValueError('Noncanonical archive entry')
                names.add(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix='.extract-', dir=destination.parent))
            try:
                for member in members:
                    target = staging / member.filename
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(member) as source, target.open('xb') as output:
                        # Reading to EOF verifies ZIP CRC; declared sizes were bounded above.
                        shutil.copyfileobj(source, output, 1024 * 1024)
                    if target.stat().st_size != member.file_size:
                        raise ValueError('Extracted member size mismatch')
                receipt = {'archive_sha256': expected_sha256, 'crc_verified': True,
                           'files': sum(not m.is_dir() for m in members),
                           'bytes': sum(m.file_size for m in members),
                           'dataset_coverage_verified': False}
                (staging / '.extraction-receipt.json').write_text(json.dumps(receipt, indent=2))
                if destination.exists():
                    raise ValueError('Extraction destination appeared')
                staging.rename(destination)
                return receipt
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
