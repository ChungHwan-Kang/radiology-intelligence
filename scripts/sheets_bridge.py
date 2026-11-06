#!/usr/bin/env python3
"""Bridge existing connected Sheets values to private CSV, offline and without OAuth.
Caller exports the two existing sheets via its connected Drive connector to JSON.
This script never queries Google on its own or alters its source tabs.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,os,re,sys
from pathlib import Path
ALLOWED=("Master_Index","MRI_Research_Watch")
NEEDED={"Master_Index":{"ID","DOI","Content Stage"},"MRI_Research_Watch":{"Title","DOI","RI Article Candidate","Priority","Existing Master ID"}}

def _table(item,key):
    rows=item.get('values') if isinstance(item,dict) else item
    if not isinstance(rows,list) or len(rows)<1 or not isinstance(rows[0],list):
        raise ValueError(f'{key}: INVALID_TABLE')
    headers=[str(x).strip() for x in rows[0]]
    if not NEEDED[key].issubset(headers):
        raise ValueError(f'{key}: MISSING_HEADERS: {sorted(NEEDED[key]-set(headers))}')
    # Preserve both physical columns when a non-key header appears twice.
    # Required semantic headers must remain unambiguous for DOI/ID selection.
    seen=set();renames=[]
    for i,header in enumerate(headers):
        if not header:
            raise ValueError(f'{key}: EMPTY_HEADER_COL_{i+1}')
        if header in seen:
            if header in NEEDED[key]:
                raise ValueError(f'{key}: AMBIGUOUS_REQUIRED_HEADER: {header}')
            n=i+1;letters=''
            while n:
                n,mod=divmod(n-1,26);letters=chr(65+mod)+letters
            renamed=f'{header} [COL_{letters}]'
            if renamed in seen or renamed in headers:
                raise ValueError(f'{key}: HEADER_DISAMBIGUATION_COLLISION: {header}')
            headers[i]=renamed
            renames.append({'column':letters,'original':header,'csv_header':renamed})
        seen.add(headers[i])
    filled=[]
    for original_row,cells in enumerate(rows[1:],start=2):
        if not isinstance(cells,list) or len(cells)>len(headers):
            raise ValueError(f'{key}: BAD_ROW_{original_row}')
        record={h:str(cells[i]) if i<len(cells) and cells[i] is not None else '' for i,h in enumerate(headers)}
        if key=='MRI_Research_Watch':
            reference=record.get('Existing Master ID','').strip()
            priority=record.get('Priority','').strip().upper()
            if reference and not re.fullmatch(r'RI-[0-9]{3}',reference):
                raise ValueError(f'{key}: INVALID_MASTER_REFERENCE_ROW_{original_row}')
            if priority and priority not in ('HIGH','MEDIUM','LOW'):
                raise ValueError(f'{key}: INVALID_PRIORITY_ROW_{original_row}')
        if key=='MRI_Research_Watch' and not record.get('Watch Row'):
            record['Watch Row']=str(original_row)
        filled.append(record)
    fields=headers+(['Watch Row'] if key=='MRI_Research_Watch' and 'Watch Row' not in headers else [])
    return fields,filled,renames

def bridge(data,output_dir):
    if not isinstance(data,dict) or not set(ALLOWED).issubset(data):
        raise ValueError('MISSING_REQUIRED_TWO_TABS')
    out=output_dir.resolve()
    for part in (out,*out.parents):
        if (part/'.git').exists():
            raise ValueError('PRIVATE_OUTPUT_INSIDE_GIT_REPOSITORY')
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    counts={};digests={};header_disambiguations={}
    for key in ALLOWED:
        headers,rows,renames=_table(data[key],key)
        header_disambiguations[key]=renames
        path=out/(key+'.csv');tmp=out/(key+'.csv.tmp')
        with tmp.open('w',encoding='utf-8-sig',newline='') as fh:
            writer=csv.DictWriter(fh,fieldnames=headers)
            writer.writeheader();writer.writerows(rows)
        os.replace(tmp,path)
        counts[key]=len(rows);digests[key]=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest={'status':'SNAPSHOT_CREATED','source':'EXISTING_CONNECTED_GOOGLE_SHEETS_VALUES','tabs':counts,'sha256':digests,'header_disambiguations':header_disambiguations,'public_write_permitted':False,'automatic_google_read':False,'source_write_performed':False}
    (out/'snapshot_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--values-json',required=True,type=Path);p.add_argument('--private-dir',required=True,type=Path)
    args=p.parse_args()
    try:
        result=bridge(json.loads(args.values_json.read_text(encoding='utf-8')),args.private_dir)
        print(json.dumps(result,ensure_ascii=False));return 0
    except (ValueError,OSError,json.JSONDecodeError) as exc:
        print('ERROR: '+str(exc),file=sys.stderr);return 3
if __name__=='__main__':sys.exit(main())
