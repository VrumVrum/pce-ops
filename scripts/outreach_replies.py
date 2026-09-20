# -*- coding: utf-8 -*-
"""Read-only scan of Thunderbird for replies to the agency outreach: the local
'Project Cost Estimator' Inbox (where hello@ mail is filed) and the Gmail INBOX
(before the filter moves it). Matches on the agency domains and on the outreach
subject. Prints sender, date, subject and the first lines; writes nothing."""
import os, re, sys, csv, email, glob, datetime
from email.header import decode_header, make_header
sys.stdout.reconfigure(encoding='utf-8')
PROF = os.path.join(os.environ['APPDATA'], 'Thunderbird', 'Profiles', '3vcu35zk.default-release')
BOXES = [os.path.join(PROF, 'Mail', 'ProjectCostEstimator', 'Inbox'), os.path.join(PROF, 'ImapMail', 'imap.gmail.com', 'INBOX-1')]
CSV = 'C:/Users/Flo/Downloads/pce-ops/data/outreach-agencies-2026-09-20.csv'
SINCE = datetime.datetime(2026, 9, 20, 17, 0, tzinfo=datetime.timezone.utc)

rows = [r for r in csv.DictReader(open(CSV, encoding='utf-8')) if r.get('sent')]
domains = {r['email'].split('@')[1].lower(): r['name'] for r in rows if r.get('email')}

def dec(v):
    try: return str(make_header(decode_header(v))) if v else ''
    except Exception: return v or ''

def body_of(m):
    for part in m.walk():
        if part.get_content_type() == 'text/plain':
            try: return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
            except Exception: return ''
    return ''

hits = []
for P in BOXES:
    if not os.path.exists(P): continue
    size = os.path.getsize(P)
    with open(P, 'rb') as f:
        f.seek(max(0, size - 30 * 1024 * 1024)); data = f.read()
    for raw in re.split(rb'\r?\n(?=From - )', data)[1:]:
        try: m = email.message_from_bytes(raw)
        except Exception: continue
        frm = dec(m.get('From', '')); subj = dec(m.get('Subject', ''))
        try: d = email.utils.parsedate_to_datetime(m.get('Date', ''))
        except Exception: d = None
        if d and d.tzinfo is None: d = d.replace(tzinfo=datetime.timezone.utc)
        if d and d < SINCE: continue
        addr = (email.utils.parseaddr(frm)[1] or '').lower()
        dom = addr.split('@')[-1]
        if dom in domains or 'free listing for' in subj.lower() or 'quote requests with a budget' in subj.lower():
            if addr.endswith('projectcostestimator.com'): continue
            hits.append((d.isoformat() if d else '', domains.get(dom, dom), frm, subj, re.sub(r'\s+', ' ', body_of(m))[:300], os.path.basename(P)))
hits.sort()
print('replies found:', len(hits))
for h in hits:
    print('\n'.join(['---', h[0] + ' | ' + h[1] + ' | ' + h[5], 'From: ' + h[2], 'Subject: ' + h[3], h[4]]))
