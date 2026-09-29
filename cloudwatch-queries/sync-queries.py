#!/usr/bin/env python3
"""Sync the jambonz.cloud CloudWatch Logs Insights saved queries from queries.json.

Dry run by default: prints what would be created or updated and changes nothing.
Pass --apply to write. Saved queries are matched by name; the script never deletes
anything, it only reports saved queries under the prefix that queries.json does
not manage.

Usage:
  python sync-queries.py                  # show the plan
  python sync-queries.py --apply          # create/update saved queries
  python sync-queries.py --profile prod   # use a named AWS CLI profile
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def aws(args, region, profile):
    cmd = ['aws', 'logs', *args, '--region', region, '--output', 'json']
    if profile:
        cmd += ['--profile', profile]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f'aws {" ".join(args[:1])} failed: {res.stderr.strip()}')
    return json.loads(res.stdout) if res.stdout.strip() else {}


def normalize(q):
    """The fields we manage, in a comparable form."""
    return {
        'queryString': q['queryString'].strip(),
        'logGroupNames': sorted(q.get('logGroupNames') or []),
        'parameters': sorted(
            [{k: p[k] for k in ('name', 'defaultValue', 'description') if p.get(k)}
             for p in q.get('parameters') or []],
            key=lambda p: p['name']),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--file', default=os.path.join(HERE, 'queries.json'))
    p.add_argument('--region', default='us-east-1')
    p.add_argument('--profile')
    p.add_argument('--apply', action='store_true', help='write changes (default: dry run)')
    args = p.parse_args()

    with open(args.file) as f:
        spec = json.load(f)
    prefix = spec['namePrefix']
    wanted = spec['queries']
    for q in wanted:
        if not q['name'].startswith(prefix):
            sys.exit(f'query "{q["name"]}" does not start with prefix "{prefix}"')

    existing = aws(['describe-query-definitions', '--query-definition-name-prefix', prefix],
                   args.region, args.profile).get('queryDefinitions', [])
    by_name = {}
    for d in existing:
        if d['name'] in by_name:
            sys.exit(f'more than one saved query named "{d["name"]}"; resolve that in the console first')
        by_name[d['name']] = d

    changes = 0
    for q in wanted:
        cur = by_name.get(q['name'])
        if cur and normalize(cur) == normalize(q):
            print(f'  unchanged  {q["name"]}')
            continue
        action = 'update' if cur else 'create'
        print(f'  {action:9}  {q["name"]}')
        changes += 1
        if not args.apply:
            continue
        put = ['put-query-definition', '--query-language', 'CWLI',
               '--name', q['name'], '--query-string', q['queryString'],
               '--log-group-names', *q['logGroupNames'],
               '--parameters', json.dumps(q.get('parameters') or [])]
        if cur:
            put += ['--query-definition-id', cur['queryDefinitionId']]
        aws(put, args.region, args.profile)

    managed = {q['name'] for q in wanted}
    for name in sorted(set(by_name) - managed):
        print(f'  unmanaged  {name} (left alone)')

    if changes and not args.apply:
        print(f'\n{changes} change(s) pending; re-run with --apply to write them.')


if __name__ == '__main__':
    main()
