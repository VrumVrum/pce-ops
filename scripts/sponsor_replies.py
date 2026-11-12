# -*- coding: utf-8 -*-
"""Sponsor lane, reply desk. Reads replies to the sponsor offers, answers them, tracks every thread and
tells the owner when a company accepts.
  python scripts/sponsor_replies.py            read new replies, answer, record, notify
  python scripts/sponsor_replies.py --dry      same, but sends nothing and records nothing (prints what it would do)
  python scripts/sponsor_replies.py --status   the pipeline: counts per stage and every open thread

Owner, 11 Nov 2026: "tu trebuie sa raspunzi la emails. Si sa ai tracking la tot. Mie imi dai email pe
florin.florea84@gmail.com cand ai un contract." Prices agreed the same day (PRICES below).

How it works
  * Inbound mail is read from the local Thunderbird mboxes (the only place hello@ replies land); a message counts
    when its sender's address or domain belongs to a company we wrote to. Each Message-ID is handled once
    (data/sponsor-threads.jsonl is the record of every inbound and outbound message).
  * A model drafts the answer and names the stage; code decides whether it may be sent:
      - the only dollar amounts allowed are the agreed prices for THAT page; anything else -> held for the owner
      - no audience figures of any kind (visitors, traffic, impressions, clicks, rankings) -> held
      - the model says needs_owner for anything outside the script (legal terms, discounts, exclusivity beyond
        the article, invoices, complaints) -> held
    A held thread is not answered; the owner gets an email with the message and the reason.
  * Stage per company in data/sponsor-prospects.csv (`status`): sent, replied, quoted, accepted, assets, declined,
    bounced, held. `accepted` and `assets` email the owner at once: that is the contract.
  * Bounces and auto-replies are recorded and never answered. "no"/unsubscribe is honoured: status declined.
Nothing here activates a card or issues an invoice; those stay with the owner's session.
"""
import csv, datetime, email, email.utils, glob, io, json, os, re, subprocess, sys, time, urllib.request
from email.header import decode_header, make_header
sys.stdout.reconfigure(encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
D = os.path.join(HERE, '..', 'data') + os.sep
LIST = D + 'sponsor-prospects.csv'
THREADS = D + 'sponsor-threads.jsonl'
OWNER = 'florin.florea84@gmail.com'
FROM = 'Florin Florea (Project Cost Estimator) <hello@projectcostestimator.com>'
REPLY_TO = 'hello@projectcostestimator.com'
CLAUDE = os.path.join(os.environ.get('USERPROFILE', ''), '.local', 'bin', 'claude.exe')
PROF = os.path.join(os.environ.get('APPDATA', ''), 'Thunderbird', 'Profiles', '3vcu35zk.default-release')
BOXES = [os.path.join(PROF, 'Mail', 'ProjectCostEstimator', 'Inbox'), os.path.join(PROF, 'ImapMail', 'imap.gmail.com', 'INBOX-1')]
SINCE = datetime.datetime(2026, 11, 11, 12, 0, tzinfo=datetime.timezone.utc)
DRY = '--dry' in sys.argv
ROOT_PAGES = {'shopify-store-cost', 'ecommerce-cost-calculator', 'wordpress-website-cost', 'saas-cost-estimator', 'marketplace-cost-estimator', 'freelance-website-cost'}
AUDIENCE = re.compile(r'(?i)\b(visitors?|traffic|impressions?|page ?views?|sessions?|click-?through|ctr|rankings?|monthly (readers|users)|unique (users|visitors)|search console|analytics)\b')
AUTO = re.compile(r'(?i)(out of (the )?office|automatic reply|auto-?reply|autoreply|on (annual )?leave|away from (my|the) (desk|office)|vacation)')
BOUNCE = re.compile(r'(?i)(mailer-daemon|postmaster|delivery (status|failure)|undeliver|returned mail|address not found)')


def prices(slug):
    """The agreed card: (12-month price, 6-month price) for this page."""
    if slug in ROOT_PAGES:
        return 900, None
    if re.search(r'-vs-', slug):
        return 500, 250
    return 400, 250


def key():
    for p in (r'C:\Users\Flo\Downloads\scopebit\.env.local', r'C:\Users\Flo\Downloads\scopebit\.env.vercel'):
        try:
            m = re.search(r'^RESEND_API_KEY="?([^"\r\n]+)"?', open(p, encoding='utf-8').read(), re.M)
            if m:
                return m.group(1).strip()
        except OSError:
            pass
    return os.environ.get('RESEND_API_KEY', '')


def resend(to, subject, body, headers=None, tag='sponsor-reply'):
    payload = {'from': FROM, 'to': [to], 'reply_to': REPLY_TO, 'subject': subject, 'text': body, 'tags': [{'name': 'campaign', 'value': tag}]}
    if headers:
        payload['headers'] = headers
    req = urllib.request.Request('https://api.resend.com/emails', data=json.dumps(payload).encode(),
                                 headers={'Authorization': 'Bearer ' + key(), 'Content-Type': 'application/json', 'User-Agent': 'pce-outreach/1.0'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def dec(v):
    try:
        return str(make_header(decode_header(v))) if v else ''
    except Exception:
        return v or ''


def body_of(m):
    for part in m.walk():
        if part.get_content_type() == 'text/plain':
            try:
                return part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
            except Exception:
                return ''
    for part in m.walk():
        if part.get_content_type() == 'text/html':
            try:
                h = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', 'replace')
                return re.sub(r'\s+\n', '\n', re.sub(r'<[^>]+>', ' ', re.sub(r'(?i)<br\s*/?>|</p>', '\n', h)))
            except Exception:
                return ''
    return ''


def fresh_part(text):
    """The sender's own words: everything above the quoted original."""
    out = []
    for line in text.replace('\r', '').split('\n'):
        if line.startswith('>') or re.match(r'^(On .{5,80} wrote:|-----Original Message-----|From: .*hello@projectcostestimator)', line.strip()):
            break
        out.append(line)
    return '\n'.join(out).strip()[:4000]


def load_rows():
    rows = list(csv.DictReader(open(LIST, encoding='utf-8', newline='')))
    fields = list(rows[0].keys()) if rows else []
    for c in ('status', 'last_in', 'last_out', 'quoted', 'note'):
        if c not in fields:
            fields.append(c)
    for r in rows:
        for c in fields:
            r.setdefault(c, '')
    return rows, fields


def save_rows(rows, fields):
    """Read-modify-write: the sender marks `sent` in this file while we run, so only the reply columns of the rows
    we touched are written onto a fresh copy; nothing we loaded at start is written back wholesale."""
    mine = {r['email'].lower(): r for r in rows if r.get('email') and (r.get('status') or r.get('last_in') or r.get('note'))}
    fresh, _f = load_rows()
    for r in fresh:
        m = mine.get((r.get('email') or '').lower())
        if m:
            for c in ('status', 'last_in', 'last_out', 'quoted', 'note'):
                r[c] = m.get(c, '')
    with io.open(LIST + '.tmp', 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(fresh)
    for attempt in range(6):
        try:
            os.replace(LIST + '.tmp', LIST); break
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(2)


def seen_ids():
    ids = set()
    if os.path.exists(THREADS):
        for line in open(THREADS, encoding='utf-8'):
            try:
                ids.add(json.loads(line).get('message_id'))
            except ValueError:
                pass
    return ids


def record(entry):
    if DRY:
        return
    entry['ts'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with io.open(THREADS, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def thread_so_far(addr_or_dom):
    out = []
    if os.path.exists(THREADS):
        for line in open(THREADS, encoding='utf-8'):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get('company_key') == addr_or_dom:
                out.append(f"[{e.get('dir')}] {e.get('ts', '')[:16]}\n{(e.get('text') or '')[:1500]}")
    return '\n\n'.join(out[-6:])


def original_offer(to):
    for p in sorted(glob.glob(D + 'outreach-sent-*.jsonl'), reverse=True):
        for line in open(p, encoding='utf-8'):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if (e.get('to') or '').lower() == to.lower() and 'sponsor spot' in (e.get('subject') or ''):
                return e.get('subject', ''), e.get('body', '')
    return '', ''


def ask_model(row, inbound, history, offer_body):
    p12, p6 = prices(row['page_slug'])
    url = 'https://projectcostestimator.com/' + ('' if row['page_slug'] in ROOT_PAGES else 'blog/') + row['page_slug']
    six = f"If they want a shorter trial: ${p6} for 6 months. " if p6 else "No shorter option on this page. "
    prompt = f"""You answer one email for Florin Florea, founder of Project Cost Estimator (projectcostestimator.com), about a sponsor card on one article. Output ONLY a JSON object, no prose around it.

THE OFFER (fixed, do not change any of it)
- Page: {url}  (topic: {row['topic']})
- One sponsor card on that page: logo, headline (up to 70 characters), two short lines of copy, a button, a link to their site. Labelled "Sponsored"; the link carries rel="sponsored". One sponsor per page.
- Price: ${p12} for 12 months. {six}Flat fee, nothing else.
- Payment: by PayPal invoice, sent AFTER the card is live. Card goes live within one working day of receiving the material.
- To go live we need: a square logo (PNG or SVG), headline, two lines of copy, button text, destination URL, and the email address the invoice should go to.
- Live example of a card: https://projectcostestimator.com/blog/klaviyo-cost-2026

HARD RULES
- Never state or estimate any audience figure (visitors, traffic, impressions, page views, clicks, rankings). If they ask for one, say plainly that we do not share audience figures for the site and that this is why the fee is flat and payable only after the card is live, so they can judge it running; they can cancel before paying.
- Never offer a discount, a different price, extra placements, do-follow links, guest posts, link exchanges or anything not in THE OFFER. If they push on price, the only move allowed is a longer term at the same price (15 months instead of 12).
- Never invent facts about the site, its readers or other sponsors beyond the live example.
- Plain, short, first person singular ("I"), no marketing language, no exclamation marks, no emoji. At most 110 words. Sign exactly:
Florin Florea
founder, Project Cost Estimator
- If the message is a refusal or asks to stop: do not reply (reply = null), stage "declined".
- If it is an auto-reply or a bounce: reply = null, stage "auto" or "bounced".
- If they accept or say yes/let's do it: thank them in one line, list the material needed, stage "accepted".
- If they send the material (logo/copy/URL): confirm receipt and that the card goes up within one working day, stage "assets".
- If they ask the price or how it works: answer with the price and the payment rule, stage "quoted".
- Anything you cannot answer strictly from THE OFFER (contracts, legal terms, invoices with tax details, complaints, proposals of their own, questions about the company): reply = null, needs_owner = true, stage "held".

JSON shape:
{{"stage": "quoted|accepted|assets|declined|auto|bounced|held|replied", "needs_owner": true|false, "reply": "text or null", "summary": "one sentence in Romanian: what they wrote and what you did"}}

OUR FIRST MESSAGE TO THEM
{offer_body[:1800]}

EARLIER MESSAGES IN THIS THREAD
{history or '(none)'}

THEIR NEW MESSAGE (from {inbound['from']}, subject "{inbound['subject']}")
{inbound['text']}
"""
    try:
        p = subprocess.run([CLAUDE, '-p', '--model', 'sonnet', '--max-turns', '1', '--output-format', 'json', '--no-session-persistence'],
                           input=prompt.encode('utf-8'), capture_output=True, timeout=240)
        out = json.loads(p.stdout.decode('utf-8', 'replace'))
        txt = out.get('result') or ''
        m = re.search(r'\{.*\}', txt, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # noqa: BLE001
        print('model call failed:', str(e)[:120])
        return None


def allowed(reply, slug):
    """Code has the last word on what leaves: agreed prices only, no audience talk."""
    p12, p6 = prices(slug)
    ok_amounts = {str(p12)} | ({str(p6)} if p6 else set())
    for amt in re.findall(r'\$\s?([\d,]+(?:\.\d+)?)', reply):
        if amt.replace(',', '').split('.')[0] not in ok_amounts:
            return False, f'amount ${amt} is not an agreed price for this page'
    for mm in AUDIENCE.finditer(reply):
        ctx = reply[max(0, mm.start() - 80): mm.end() + 40].lower()
        if not re.search(r'do not share|don.t share|not share', ctx):
            return False, f'mentions "{mm.group(0)}" outside the no-figures sentence'
    if re.search(r'\d[\d,.]*\s*(k\b|thousand|million|%)', reply.lower()):
        return False, 'contains a quantity that looks like a metric'
    if len(reply.split()) > 170:
        return False, 'too long'
    return True, ''


def notify_owner(subject, lines):
    body = '\n'.join(lines) + '\n\n(trimis automat de linia de sponsori PCE; conversatia completa: pce-ops/data/sponsor-threads.jsonl)'
    if DRY:
        print('WOULD EMAIL OWNER:', subject); print(body); return
    try:
        resend(OWNER, subject, body, tag='sponsor-owner')
    except Exception as e:  # noqa: BLE001
        print('owner email failed:', str(e)[:160])


def status():
    rows, _ = load_rows()
    by = {}
    for r in rows:
        st = r.get('status') or ('sent' if r.get('sent') else ('queued' if r.get('email') else 'no-email'))
        by[st] = by.get(st, 0) + 1
    print(json.dumps(by, ensure_ascii=False))
    for r in rows:
        if r.get('status') in ('replied', 'quoted', 'accepted', 'assets', 'held'):
            print(f"  {r['status']:9} {r['name']} <{r['email']}> | {r['page_slug']} | in {r.get('last_in', '')[:16]} out {r.get('last_out', '')[:16]} | {r.get('note', '')[:120]}")


def main():
    if '--status' in sys.argv:
        return status()
    rows, fields = load_rows()
    # Since 12 Nov the offers are sent by the Vercel cron, whose record is the marker rows in Supabase, not this
    # csv. Without them the desk would not recognise a reply from a company the cron wrote to.
    try:
        import sponsor_export
        mk = sponsor_export.markers()
        for r in rows:
            m = mk.get((r.get('email') or '').strip().lower())
            if m and m[0] == 'sponsor-offer' and not r.get('sent'):
                r['sent'] = m[1]
    except Exception as e:  # noqa: BLE001
        print('markers unreadable, using the csv only:', str(e)[:100])
    sent = [r for r in rows if r.get('sent') and r.get('email')]
    by_addr = {r['email'].lower(): r for r in sent}
    by_dom = {r['email'].split('@')[1].lower(): r for r in sent if r['email'].split('@')[1].lower() not in ('gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'icloud.com')}
    newest = max([os.path.getmtime(x) for x in BOXES if os.path.exists(x)] or [0])
    age_h = (time.time() - newest) / 3600 if newest else 9999
    print(f'reply source age: {age_h:.1f} h; companies written to: {len(sent)}')
    done = seen_ids()
    new = []
    for P in BOXES:
        if not os.path.exists(P):
            continue
        size = os.path.getsize(P)
        with open(P, 'rb') as f:
            f.seek(max(0, size - 40 * 1024 * 1024)); data = f.read()
        for raw in re.split(rb'\r?\n(?=From - )', data)[1:]:
            try:
                m = email.message_from_bytes(raw)
            except Exception:
                continue
            mid = (m.get('Message-ID') or '').strip()
            if not mid or mid in done:
                continue
            try:
                d = email.utils.parsedate_to_datetime(m.get('Date', ''))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                continue
            if d < SINCE:
                continue
            frm = dec(m.get('From', '')); addr = email.utils.parseaddr(frm)[1].lower(); subj = dec(m.get('Subject', ''))
            text = body_of(m)
            row = by_addr.get(addr) or by_dom.get(addr.split('@')[-1])
            if not row and BOUNCE.search(frm + ' ' + subj):
                hit = next((r for r in sent if r['email'].lower() in text.lower()), None)
                row = hit
            if not row:
                continue
            done.add(mid)
            new.append({'row': row, 'mid': mid, 'from': frm, 'addr': addr, 'subject': subj, 'date': d.isoformat(), 'text': fresh_part(text), 'full': text,
                        'refs': (m.get('References') or '').strip()})
    print(f'new inbound: {len(new)}')
    for it in sorted(new, key=lambda x: x['date']):
        row = it['row']; ck = row['email'].split('@')[1].lower()
        record({'dir': 'in', 'company_key': ck, 'company': row['name'], 'page_slug': row['page_slug'], 'message_id': it['mid'], 'from': it['from'], 'subject': it['subject'], 'text': it['text']})
        row['last_in'] = it['date']
        if BOUNCE.search(it['from'] + ' ' + it['subject']):
            row['status'] = 'bounced'; print('bounced:', row['name']); continue
        if AUTO.search(it['subject']) or AUTO.search(it['text'][:300]):
            print('auto-reply, ignored:', row['name']); continue
        _subj, offer_body = original_offer(row['email'])
        ans = ask_model(row, it, thread_so_far(ck), offer_body)
        if not ans:
            row['status'] = 'held'; row['note'] = 'model gave no usable answer'
            notify_owner(f"[PCE sponsor] De raspuns manual: {row['name']}", [f"Companie: {row['name']} <{it['addr']}>", f"Pagina: {row['page_slug']}", '', 'Mesajul lor:', it['text'][:1500], '', 'Motiv: nu am putut formula un raspuns sigur.'])
            continue
        stage = (ans.get('stage') or 'replied').strip().lower(); reply = ans.get('reply'); summary = (ans.get('summary') or '')[:300]
        row['note'] = summary
        if stage in ('declined', 'auto', 'bounced'):
            row['status'] = stage if stage != 'auto' else (row.get('status') or 'sent'); print(stage + ':', row['name']); continue
        ok, why = (False, 'held by the model') if (ans.get('needs_owner') or not reply or stage == 'held') else allowed(reply, row['page_slug'])
        if not ok:
            row['status'] = 'held'
            notify_owner(f"[PCE sponsor] De raspuns manual: {row['name']}", [f"Companie: {row['name']} <{it['addr']}>", f"Pagina: {row['page_slug']}", f"Rezumat: {summary}", '', 'Mesajul lor:', it['text'][:1500], '',
                                                                           f'Motiv pentru care nu am raspuns singur: {why}', '', 'Ciorna respinsa:', (reply or '(niciuna)')[:1200]])
            print('held:', row['name'], '-', why); continue
        subj = it['subject'] if it['subject'].lower().startswith('re:') else 'Re: ' + it['subject']
        hdr = {'In-Reply-To': it['mid'], 'References': (it['refs'] + ' ' + it['mid']).strip()}
        if DRY:
            print('=' * 60); print('WOULD REPLY to', it['addr'], '|', stage); print(reply)
        else:
            try:
                res = resend(it['addr'], subj, reply, hdr)
            except Exception as e:  # noqa: BLE001
                row['status'] = 'held'; row['note'] = 'send failed: ' + str(e)[:100]; print('send failed:', row['name']); continue
            record({'dir': 'out', 'company_key': ck, 'company': row['name'], 'page_slug': row['page_slug'], 'message_id': 'out-' + str(res.get('id')), 'subject': subj, 'text': reply, 'stage': stage})
        row['status'] = stage; row['last_out'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        p12, _p6 = prices(row['page_slug'])
        if stage == 'quoted':
            row['quoted'] = str(p12)
        print('replied:', row['name'], '->', stage)
        if stage in ('accepted', 'assets'):
            what = 'A ACCEPTAT' if stage == 'accepted' else 'A TRIMIS MATERIALELE'
            notify_owner(f"[PCE sponsor] {row['name']} {what} - {row['page_slug']}",
                         [f"Companie: {row['name']} <{it['addr']}>", f"Pagina: https://projectcostestimator.com/{'' if row['page_slug'] in ROOT_PAGES else 'blog/'}{row['page_slug']}",
                          f"Pret: ${p12} pe 12 luni, plata dupa ce cardul e live.", f"Rezumat: {summary}", '', 'Mesajul lor:', it['text'][:1500], '', 'Ce le-am raspuns:', reply, '',
                          ('Urmeaza: astept materialele (logo, titlu, doua randuri, buton, URL, adresa pentru factura).' if stage == 'accepted'
                           else 'Urmeaza: cardul trebuie urcat (scripts/activate-sponsor.ts) si factura PayPal trimisa de tine.')])
    if not DRY:
        save_rows(rows, fields)
    status()


if __name__ == '__main__':
    main()
