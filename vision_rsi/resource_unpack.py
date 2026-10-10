"""Bounded, journaled ZIP extraction; completion is not dataset/model acceptance."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import time
import zipfile

from .campaign import lease
from .runner import atomic_json, digest


class Deadline(Exception):
    pass


def checksum(stream, deadline):
    value=hashlib.sha256()
    while True:
        if time.monotonic()>=deadline:raise Deadline()
        block=stream.read(1024*1024)
        if not block:return value.hexdigest()
        value.update(block)


def regular(path):
    mode=path.lstat()
    if not stat.S_ISREG(mode.st_mode) or getattr(mode,'st_file_attributes',0)&0x400:
        raise ValueError('Nonregular extraction file')
    return mode.st_size


def safe_path(root, name, create=True):
    path=root
    for component in PurePosixPath(name).parts[:-1]:
        path=path/component
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_dir() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
                raise ValueError('Unsafe extraction parent')
        elif create:path.mkdir()
        else:raise ValueError('Saved extraction parent missing')
    return root/name


def members(bundle,max_bytes,max_files):
    rows=bundle.infolist();names=set()
    if len(rows)>max_files or sum(row.file_size for row in rows)>max_bytes:
        raise ValueError('Archive exceeds extraction limits')
    for row in rows:
        name=row.orig_filename;path=PurePosixPath(name);mode=row.external_attr>>16
        if (name!=row.filename or not name or not path.parts or '\\' in name or ':' in name
                or path.is_absolute() or '..' in path.parts or name in names
                or path.parts[0]=='.extraction-receipt.json' or row.flag_bits&1
                or stat.S_IFMT(mode) not in (0,stat.S_IFREG,stat.S_IFDIR)
                or path.as_posix().rstrip('/')!=name.rstrip('/')):
            raise ValueError('Unsafe or duplicate archive entry')
        names.add(name)
    return rows


def step(archive,destination,expected_sha256,*,seconds=240,max_new_files=15000,max_bytes=30000000000,max_files=120000):
    for value,maximum in ((seconds,240),(max_new_files,120000),(max_bytes,10**12),(max_files,1000000)):
        if type(value) is not int or not 1<=value<=maximum:raise ValueError('Invalid bounded extraction limit')
    if not isinstance(expected_sha256,str) or len(expected_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Pinned archive SHA-256 required')
    deadline=time.monotonic()+seconds
    archive=Path(archive).resolve();destination=Path(destination).absolute()
    destination=destination.parent.resolve()/destination.name
    control=destination.with_name(destination.name+'.unpack')
    if any(p.is_symlink() or ((p.exists()) and getattr(p.lstat(),'st_file_attributes',0)&0x400) for p in (destination,control)):
        raise ValueError('Unsafe extraction destination')
    result={'status':'partial','phase':'verifying_archive','destination':str(destination),'archive_sha256':expected_sha256,
            'dataset_ready':False,'training_started':False,'gpu_used':False,'pixel_decode_verified':False}
    try:
        with archive.open('rb') as stream:
            if checksum(stream,deadline)!=expected_sha256:raise ValueError('Archive SHA-256 mismatch')
            stream.seek(0)
            with zipfile.ZipFile(stream) as bundle:
                rows=members(bundle,max_bytes,max_files)
                identity=digest({'protocol':1,'archive':str(archive),'archive_sha256':expected_sha256,
                    'destination':str(destination),'max_bytes':max_bytes,'max_files':max_files,
                    'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
                if not control.exists():
                    if destination.exists():raise ValueError('Refusing to merge existing destination')
                    control.mkdir();(control/'payload').mkdir()
                    with closing(sqlite3.connect(control/'journal.sqlite3')) as db,db:
                        db.execute('CREATE TABLE meta(identity TEXT,phase TEXT,receipt TEXT)')
                        db.execute('INSERT INTO meta VALUES (?,\'extracting\',NULL)',(identity,))
                        db.execute('CREATE TABLE entries(idx INTEGER PRIMARY KEY,name TEXT,size INTEGER,sha TEXT)')
                if not (control/'journal.sqlite3').is_file():raise ValueError('Incomplete extraction initialization; reconcile before reuse')
                regular(control/'journal.sqlite3')
                if (control/'unpack.lock').exists() or (control/'unpack.lock').is_symlink():regular(control/'unpack.lock')
                with lease(control/'unpack.lock'),closing(sqlite3.connect(control/'journal.sqlite3')) as db,db:
                    saved=db.execute('SELECT identity,phase,receipt FROM meta').fetchall()
                    if len(saved)!=1 or saved[0][0]!=identity:raise ValueError('Extraction identity changed')
                    phase=saved[0][1];payload=control/'payload'
                    if phase not in ('extracting','finalizing','completed'):raise ValueError('Invalid extraction phase')
                    if destination.exists():
                        if phase=='extracting' or payload.exists():raise ValueError('Unexpected destination; refusing merge')
                        base=destination
                    else:
                        if phase=='completed' or not payload.is_dir() or payload.is_symlink() or getattr(payload.lstat(),'st_file_attributes',0)&0x400:
                            raise ValueError('Missing or unsafe extraction payload')
                        base=payload
                    done=db.execute('SELECT idx,name,size,sha FROM entries ORDER BY idx').fetchall()
                    result.update(phase='checking_saved_files',completed_entries=len(done),total_entries=len(rows))
                    for index,(idx,name,size,sha) in enumerate(done):
                        if idx!=index or idx>=len(rows) or name!=rows[idx].filename or size!=rows[idx].file_size:
                            raise ValueError('Extraction journal is not a contiguous archive prefix')
                        path=safe_path(base,name,False)
                        if rows[idx].is_dir():
                            if sha is not None or path.is_symlink() or not path.is_dir() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
                                raise ValueError('Saved extraction directory changed')
                        else:
                            if regular(path)!=size:raise ValueError('Saved extraction file changed')
                            with path.open('rb') as file:
                                if checksum(file,deadline)!=sha:raise ValueError('Saved extraction file changed')
                    count=0;result['phase']='extracting'
                    for index in range(len(done),len(rows)):
                        if time.monotonic()>=deadline or count>=max_new_files:break
                        row=rows[index];target=safe_path(base,row.filename)
                        if row.is_dir():
                            if target.is_symlink() or (target.exists() and getattr(target.lstat(),'st_file_attributes',0)&0x400):
                                raise ValueError('Unsafe extraction directory')
                            target.mkdir(exist_ok=True);sha=None
                        else:
                            pending=control/'pending.bin'
                            if pending.exists() or pending.is_symlink():regular(pending);pending.unlink()
                            with bundle.open(row) as source,pending.open('xb') as output:
                                value=hashlib.sha256();size=0
                                while block:=source.read(1024*1024):
                                    if time.monotonic()>=deadline:raise Deadline()
                                    size+=len(block)
                                    if size>row.file_size:raise ValueError('Archive member grew')
                                    output.write(block);value.update(block)
                            if size!=row.file_size:raise ValueError('Archive member size differs')
                            sha=value.hexdigest()
                            if target.exists() or target.is_symlink():
                                if regular(target)!=size:raise ValueError('Unjournaled extraction file differs')
                                with target.open('rb') as file:
                                    if checksum(file,deadline)!=sha:raise ValueError('Unjournaled extraction file differs')
                                pending.unlink()
                            else:pending.rename(target)
                            count+=1
                        db.execute('INSERT INTO entries VALUES (?,?,?,?)',(index,row.filename,row.file_size,sha))
                        if (index+1)%100==0:db.commit()
                    db.commit()
                    completed=db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]
                    result.update(completed_entries=completed,total_entries=len(rows))
                    if completed!=len(rows):return result
                    receipt={'archive_sha256':expected_sha256,'crc_verified':True,'files':sum(not r.is_dir() for r in rows),
                        'bytes':sum(r.file_size for r in rows),'dataset_coverage_verified':False,'extraction_identity':identity,
                        'files_manifest_sha256':digest(db.execute('SELECT idx,name,size,sha FROM entries ORDER BY idx').fetchall())}
                    if saved[0][2] is not None and json.loads(saved[0][2])!=receipt:raise ValueError('Extraction receipt changed')
                    db.execute('UPDATE meta SET phase=\'finalizing\',receipt=?',(json.dumps(receipt),));db.commit()
                    if base==payload:
                        atomic_json(payload/'.extraction-receipt.json',receipt)
                        if destination.exists():raise ValueError('Destination appeared before publication')
                        payload.rename(destination)
                    elif json.loads((destination/'.extraction-receipt.json').read_text())!=receipt:
                        raise ValueError('Published extraction receipt changed')
                    db.execute('UPDATE meta SET phase=\'completed\'');db.commit()
                    return dict(result,status='completed',phase='completed',extraction=receipt)
    except Deadline:
        return dict(result,deadline_reached=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True);parser.add_argument('--destination',required=True)
    parser.add_argument('--sha256',required=True);parser.add_argument('--seconds',type=int,default=240)
    args=parser.parse_args()
    print(json.dumps(step(args.archive,args.destination,args.sha256,seconds=args.seconds),indent=2))


if __name__=='__main__':main()
