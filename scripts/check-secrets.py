"""Reject embedded API credentials without ever printing matched values."""
import io
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

GOOGLE = re.compile(rb'AI' + rb'za[A-Za-z0-9_-]{35}')
GOOGLE_NAME = re.compile(r'AI' + r'za[A-Za-z0-9_-]{35}')
TEXT = {'.js','.ts','.tsx','.cjs','.mjs','.json','.py','.md','.txt','.yaml','.yml','.html','.css','.asar'}

def inspect(data, name):
    findings=[]
    if GOOGLE.search(data):
        safe_name=GOOGLE_NAME.sub('[redacted credential]',str(name))
        findings.append(safe_name+': embedded Google API credential')
    return findings

def scan_file(path, name=None):
    name=name or path.name
    data=path.read_bytes()
    findings=inspect(data,name) if path.suffix.lower() in TEXT else []
    if name.endswith(('.tar.gz','.tgz')):
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
            for item in archive.getmembers():
                if item.isfile() and item.size<=16*1024*1024:
                    findings.extend(inspect(archive.extractfile(item).read(),name+'!'+item.name))
    elif path.suffix.lower()=='.zip':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for item in archive.infolist():
                if Path(item.filename).suffix.lower() in TEXT and item.file_size<=128*1024*1024:
                    findings.extend(inspect(archive.read(item),name+'!'+item.filename))
    return findings

def check(root, files=None):
    if files is None:
        result=subprocess.run(['git','ls-files','-z'],cwd=root,capture_output=True,check=True)
        files=[root/name.decode('utf-8') for name in result.stdout.split(b'\0') if name]
    findings=[]
    for path in files:
        if path.is_file(): findings.extend(scan_file(path,path.relative_to(root).as_posix()))
    if findings: raise ValueError('Secret scan failed:\n'+'\n'.join(findings))
    return len(files)

if __name__=='__main__':
    print('Secret scan passed for',check(Path(__file__).resolve().parents[1]),'tracked files')
