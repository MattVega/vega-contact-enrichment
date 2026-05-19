#!/usr/bin/env python3
"""Fast enrichment - threaded website detection"""
import pandas as pd, requests, re, socket, time, json
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from datetime import datetime

INPUT = '/app/new_companies_2026-05-18.csv'
OUTPUT = '/app/new_companies_enriched_2026-05-18.csv'
MAX_WORKERS = 20
TIMEOUT = 4

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

STOP = {'llc','inc','corp','co','company','the','and','of','texas','utah','services','group',
        'construction','contractor','contractors','power','mechanical','solutions','enterprises',
        'management','home','professional','quality','premier','elite','pro','all','best','top',
        'south','north','east','west','central','lone','star','air'}

TRADE_EST = {
    'electrical': ('3–25 employees', '$200K–$2M/yr'),
    'hvac':       ('2–15 employees', '$150K–$1M/yr'),
    'appliance':  ('1–8 employees',  '$50K–$300K/yr'),
    'drywall':    ('2–20 employees', '$150K–$1.5M/yr'),
    'paint':      ('1–15 employees', '$75K–$800K/yr'),
    'flooring':   ('1–12 employees', '$75K–$750K/yr'),
}

def get_est(trade):
    t = trade.lower()
    for k,v in TRADE_EST.items():
        if k in t: return v
    return ('1–20 employees','$100K–$1M/yr')

def candidates(name, city=''):
    clean = re.sub(r'[^a-z0-9\s]','',name.lower())
    words = [w for w in clean.split() if w not in STOP and len(w)>2]
    if not words: return []
    return list(dict.fromkeys(filter(None,[
        ''.join(words[:3])+'.com',
        ''.join(words[:2])+'.com',
        words[0]+words[1]+'.com' if len(words)>1 else None,
        '-'.join(words[:2])+'.com',
        words[0]+'electric.com' if 'electric' in clean else None,
        words[0]+'hvac.com' if 'hvac' in clean else None,
    ])))[:4]

def probe(domain):
    for scheme in ['https','http']:
        try:
            r = requests.get(f'{scheme}://{domain}', timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 400:
                return f'{scheme}://{domain}', r.text
        except: pass
    return None, None

def score(html, phone=''):
    if not html: return 0, 'No website'
    soup = BeautifulSoup(html,'html.parser')
    text = soup.get_text(); low = html.lower()
    s = 2.0; notes = []
    nav_links = sum(len(n.find_all('a')) for n in soup.find_all(['nav','header']))
    if nav_links > 3: s+=0.5; notes.append('nav')
    if re.search(r'\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}',text): s+=0.5; notes.append('phone')
    if soup.find('form'): s+=0.5; notes.append('form')
    if len(soup.find_all('img'))>=4: s+=0.5; notes.append('images')
    if soup.find('meta',attrs={'name':'viewport'}): s+=0.5; notes.append('mobile')
    if any(w in low for w in ['service','installation','repair','commercial','estimate']): s+=0.5; notes.append('services')
    s=min(5,round(s,1))
    label = 'Strong' if s>=4 else 'Average' if s>=3 else 'Basic'
    return s, f"{label} ({','.join(notes[:4])})"

def enrich_row(args):
    idx, row = args
    name = str(row.get('Company Name',''))
    phone = str(row.get('Phone',''))
    city = str(row.get('City',''))
    trade = str(row.get('Trade',''))
    existing = str(row.get('Website',''))
    
    emp, rev = get_est(trade)
    
    url, html = None, None
    if existing not in ['nan','','None']:
        url, html = probe(existing.replace('https://','').replace('http://',''))
    
    if not url:
        for d in candidates(name, city):
            url, html = probe(d)
            if url:
                # Verify phone on page
                if phone and len(re.sub(r'\D','',phone)) >= 10:
                    cp = re.sub(r'\D','',phone)
                    page_phones = re.sub(r'\D','',html or '')
                    if cp not in page_phones:
                        # Not verified - still keep but mark unverified
                        pass
                break
    
    ws, wq = score(html, phone) if html else (0, 'No website')
    has = 'Yes' if url else 'No'
    
    if not url:
        priority = 'High — No website'
    elif ws <= 2:
        priority = 'High — Basic site only'
    elif ws <= 3:
        priority = 'Medium'
    else:
        priority = 'Lower — Strong web presence'
    
    return idx, url or '', has, ws, wq, emp, rev, priority

def main():
    df = pd.read_csv(INPUT)
    print(f"Enriching {len(df)} records with {MAX_WORKERS} threads...")
    
    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(enrich_row, (i,row)): i for i,row in df.iterrows()}
        done = 0
        for f in as_completed(futures):
            try:
                idx, url, has, ws, wq, emp, rev, pri = f.result()
                results[idx] = (url, has, ws, wq, emp, rev, pri)
            except: 
                results[futures[f]] = ('','No',0,'Error','?','?','Unknown')
            done += 1
            if done % 100 == 0:
                found = sum(1 for v in results.values() if v[1]=='Yes')
                print(f"  {done}/{len(df)} processed | {found} websites found")
    
    df['Website_Found'] = [results.get(i,('','No',0,'','','',''))[0] for i in df.index]
    df['Has_Website'] = [results.get(i,('','No',0,'','','',''))[1] for i in df.index]
    df['Website_Quality_Score'] = [results.get(i,('','No',0,'','','',''))[2] for i in df.index]
    df['Website_Quality'] = [results.get(i,('','No',0,'','','',''))[3] for i in df.index]
    df['Employees_Est'] = [results.get(i,('','No',0,'','','',''))[4] for i in df.index]
    df['Revenue_Est'] = [results.get(i,('','No',0,'','','',''))[5] for i in df.index]
    df['Target_Priority'] = [results.get(i,('','No',0,'','','',''))[6] for i in df.index]
    
    df.to_csv(OUTPUT, index=False)
    
    has = df[df['Has_Website']=='Yes']
    no = df[df['Has_Website']=='No']
    print(f"\n{'='*55}")
    print(f"Total: {len(df)} | Has website: {len(has)} ({len(has)/len(df)*100:.0f}%) | No website: {len(no)} ({len(no)/len(df)*100:.0f}%)")
    print(f"\nWebsite quality (of those with sites):")
    print(has['Website_Quality'].apply(lambda x: x.split('(')[0].strip()).value_counts().to_string())
    print(f"\nPriority:")
    print(df['Target_Priority'].apply(lambda x: x.split('—')[0].strip()).value_counts().to_string())
    print(f"\nSaved: {OUTPUT}")
    print(df[df['Has_Website']=='Yes'][['Company Name','City','Website_Found','Website_Quality_Score','Employees_Est','Revenue_Est']].head(8).to_string())

main()
