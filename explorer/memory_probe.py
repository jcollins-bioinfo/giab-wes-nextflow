#!/usr/bin/env python3
"""Exercise the running synthetic app; measure the container's cgroup peak in CI."""
import argparse
import concurrent.futures
import json
import urllib.request
from container_smoke import check

def visit(index, base):
    for path in ('','_dash-layout','_dash-dependencies','evidence.json','readyz','managed/evidence.json','managed/readyz','infrastructure/evidence.json'):
        with urllib.request.urlopen(base+path,timeout=15) as response:
            assert response.status==200
            response.read()
    payload={'output':'task-table.children','outputs':{'id':'task-table','property':'children'},
             'inputs':[{'id':'process','property':'value','value':'all'}],
             'state':[],'changedPropIds':['process.value']}
    request=urllib.request.Request(base+'_dash-update-component',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response:
        assert response.status==200
        response.read()

    managed_payload={'output':'..managed-timeline.figure...managed-task-detail.children..',
                     'outputs':[{'id':'managed-timeline','property':'figure'},{'id':'managed-task-detail','property':'children'}],
                     'inputs':[{'id':'managed-task','property':'value','value':'CLOUD_DEEPVARIANT_CALL:1:1' if index % 2 else 'all'}],
                     'state':[],'changedPropIds':['managed-task.value']}
    request=urllib.request.Request(base+'_dash-update-component',data=json.dumps(managed_payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response:
        assert response.status==200
        result=json.load(response)
        assert 'managed-timeline' in result['response']
        assert 'managed-task-detail' in result['response']

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8050')
    args=parser.parse_args()
    check(args.base_url)
    base=args.base_url.rstrip('/')+'/giab-wes-nextflow/'
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: visit(i,base),range(40)))
    print('400 HTTP requests completed with 4 concurrent clients; synthetic, managed nonhuman and declaration views')

if __name__=='__main__':
    main()
