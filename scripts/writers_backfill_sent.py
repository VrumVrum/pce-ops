# -*- coding: utf-8 -*-
"""One-off repair (12 Nov 2026): data/outreach-writers.csv had no `sent` column, so the engine's mark() had
nowhere to write and every row stayed "unsent" on paper. Duplicates were still prevented by the sent log, but the
authority lane counted 48 unsent rows forever and never started the research fire that refills the list.
Adds the column and fills it from data/outreach-sent-*.jsonl (tag outreach-writers / the writer subject)."""
import csv, glob, io, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
D = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data') + os.sep
P = D + 'outreach-writers.csv'
sent = {}
for f in sorted(glob.glob(D + 'outreach-sent-*.jsonl')):
    for line in open(f, encoding='utf-8'):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('error') or 'rate dataset' not in (e.get('subject') or ''):
            continue
        sent.setdefault((e.get('to') or '').lower(), (e.get('ts') or '')[:10])
rows = list(csv.DictReader(open(P, encoding='utf-8', newline='')))
fields = list(rows[0].keys())
if 'sent' not in fields:
    fields.append('sent')
n = 0
for r in rows:
    d = sent.get((r.get('email') or '').strip().lower())
    r['sent'] = d or r.get('sent') or ''
    n += 1 if d else 0
with io.open(P + '.tmp', 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
os.replace(P + '.tmp', P)
print(f'{n} rows marked sent; {sum(1 for r in rows if r.get("email") and not r["sent"])} with an address still unsent; {len(rows)} rows')
