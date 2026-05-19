#!/usr/bin/env python3
"""
Contact Enrichment Script
Adds: website, has_website, website_quality_score, website_quality_label,
      employees_est, revenue_est_annual, company_age_years, target_priority
"""
import pandas as pd
import requests
import re
import socket
import time
import json
from datetime import datetime
from bs4 import BeautifulSoup

INPUT_FILE = '/app/new_companies_2026-05-18.csv'
OUTPUT_FILE = '/app/new_companies_enriched_2026-05-18.csv'
SAMPLE_SIZE = 100  # Test on first 100 for speed, set to None for all

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ─── Domain candidates from company name ─────────────────────────────
def build_domain_candidates(company_name, city=''):
    clean = re.sub(r'[^a-z0-9\s]', '', company_name.lower())
    words = clean.split()
    stop = {
        'llc','inc','corp','co','company','the','and','of','texas','utah','services','group',
        'construction','contractor','contractors','power','mechanical','solutions','enterprises',
        'management','home','professional','quality','premier','elite','pro','all','best','top',
        'south','north','east','west','central','lone','star'
    }
    sig = [w for w in words if w not in stop and len(w) > 2]
    city_clean = re.sub(r'[^a-z]','',city.lower())[:6]

    if not sig:
        return []
    
    candidates = list(dict.fromkeys(filter(None, [
        ''.join(sig[:3]) + '.com',
        ''.join(sig[:2]) + '.com',
        sig[0] + sig[1] + '.com' if len(sig) > 1 else None,
        '-'.join(sig[:2]) + '.com',
        sig[0] + 'electric.com' if any(w in clean for w in ['electric','electrical']) else None,
        sig[0] + 'hvac.com' if any(w in clean for w in ['ac contractor','hvac','air condition']) else None,
        sig[0] + 'appliance.com' if 'appliance' in clean else None,
    ])))
    return candidates[:5]

# ─── Website probe ────────────────────────────────────────────────────
def probe_website(domain, phone=''):
    clean_phone = re.sub(r'\D', '', str(phone))
    for scheme in ['https', 'http']:
        try:
            r = requests.get(f'{scheme}://{domain}', timeout=6, headers=HEADERS,
                             allow_redirects=True)
            if r.status_code == 200 and len(r.text) > 400:
                # Check if phone matches
                page_phones = re.sub(r'\D','', r.text)
                confirmed = clean_phone in page_phones if clean_phone else False
                return f'{scheme}://{domain}', r, confirmed
        except:
            pass
    return None, None, False

# ─── Website quality scorer ──────────────────────────────────────────
def score_website(url, response=None, phone=''):
    if not url:
        return 0, 'No website'
    try:
        if response is None:
            response = requests.get(url, timeout=6, headers=HEADERS)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text()
        html = response.text.lower()
        score = 1.0
        notes = []

        if len(page_text) > 800:
            score = 2.0
            notes.append('has content')

        # Navigation
        nav_links = []
        for nav in soup.find_all(['nav','header']):
            nav_links.extend(nav.find_all('a'))
        if len(nav_links) > 3:
            score += 0.5; notes.append('navigation')

        # Phone on page
        if re.search(r'\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}', page_text):
            score += 0.5; notes.append('phone listed')

        # Contact form
        if soup.find('form'):
            score += 0.5; notes.append('contact form')

        # Images
        imgs = [i for i in soup.find_all('img') if len(i.get('src','')) > 5]
        if len(imgs) >= 4:
            score += 0.5; notes.append(f'{len(imgs)} images')

        # Mobile responsive
        if soup.find('meta', attrs={'name':'viewport'}):
            score += 0.5; notes.append('mobile ready')

        # Services described
        if any(w in html for w in ['service','installation','repair','commercial','residential','estimate','quote']):
            score += 0.5; notes.append('services listed')

        # Online booking / scheduling
        if any(w in html for w in ['book','schedule','appointment','request a quote','get a quote']):
            score += 0.5; notes.append('online booking')

        score = min(5.0, round(score, 1))
        label = 'Strong' if score >= 4 else 'Average' if score >= 3 else 'Basic' if score >= 2 else 'Poor'
        return score, f"{label} — {', '.join(notes[:4])}"
    except:
        return 1.0, 'Error loading'

# ─── Employee & revenue estimates ────────────────────────────────────
TRADE_ESTIMATES = {
    'Electrical': {
        'employees_low': 3, 'employees_high': 25, 'employees_label': '3–25',
        'revenue_low': '200K', 'revenue_high': '2M', 'revenue_label': '$200K–$2M/yr'
    },
    'HVAC': {
        'employees_low': 2, 'employees_high': 15, 'employees_label': '2–15',
        'revenue_low': '150K', 'revenue_high': '1M', 'revenue_label': '$150K–$1M/yr'
    },
    'Appliance Installation': {
        'employees_low': 1, 'employees_high': 8, 'employees_label': '1–8',
        'revenue_low': '50K', 'revenue_high': '300K', 'revenue_label': '$50K–$300K/yr'
    },
    'Drywall': {
        'employees_low': 2, 'employees_high': 20, 'employees_label': '2–20',
        'revenue_low': '150K', 'revenue_high': '1.5M', 'revenue_label': '$150K–$1.5M/yr'
    },
    'Paint': {
        'employees_low': 1, 'employees_high': 15, 'employees_label': '1–15',
        'revenue_low': '75K', 'revenue_high': '800K', 'revenue_label': '$75K–$800K/yr'
    },
    'Flooring': {
        'employees_low': 1, 'employees_high': 12, 'employees_label': '1–12',
        'revenue_low': '75K', 'revenue_high': '750K', 'revenue_label': '$75K–$750K/yr'
    },
}

def get_estimates(trade):
    for key in TRADE_ESTIMATES:
        if key.lower() in trade.lower():
            est = TRADE_ESTIMATES[key]
            return est['employees_label'], est['revenue_label']
    return '1–20', '$100K–$1M/yr'

# ─── Target priority ──────────────────────────────────────────────────
def calc_priority(has_website, website_score, trade):
    """
    High priority = no website or poor website (most likely to need Vega)
    """
    if not has_website:
        return 'High — No website (likely manual estimating)'
    if website_score <= 2:
        return 'High — Basic site only'
    if website_score <= 3:
        return 'Medium — Average web presence'
    return 'Lower — Strong web presence (may already have tools)'

# ─── Main enrichment loop ─────────────────────────────────────────────
def main():
    df = pd.read_csv(INPUT_FILE)
    if SAMPLE_SIZE:
        df = df.head(SAMPLE_SIZE)
    
    print(f"Enriching {len(df)} records...")
    
    new_cols = {
        'Website_Found': [], 'Has_Website': [], 'Website_Quality_Score': [],
        'Website_Quality': [], 'Employees_Est': [], 'Revenue_Est': [],
        'Target_Priority': []
    }
    
    for i, row in df.iterrows():
        company = str(row.get('Company Name', ''))
        phone = str(row.get('Phone', ''))
        city = str(row.get('City', ''))
        trade = str(row.get('Trade', ''))
        
        # Check if website already in data
        existing_site = str(row.get('Website', ''))
        if existing_site and existing_site not in ['nan', '', 'None']:
            url = existing_site
            score, quality = score_website(url, phone=phone)
            has_web = True
        else:
            # Try to find website
            url = None
            score = 0
            quality = 'No website'
            has_web = False
            
            candidates = build_domain_candidates(company, city)
            for domain in candidates:
                found_url, response, confirmed = probe_website(domain, phone)
                if found_url and response:
                    url = found_url
                    score, quality = score_website(found_url, response, phone)
                    has_web = True
                    if confirmed:
                        quality = '✓ Verified — ' + quality
                    break
        
        emp_est, rev_est = get_estimates(trade)
        priority = calc_priority(has_web, score, trade)
        
        new_cols['Website_Found'].append(url if url else '')
        new_cols['Has_Website'].append('Yes' if has_web else 'No')
        new_cols['Website_Quality_Score'].append(score)
        new_cols['Website_Quality'].append(quality)
        new_cols['Employees_Est'].append(emp_est)
        new_cols['Revenue_Est'].append(rev_est)
        new_cols['Target_Priority'].append(priority)
        
        if (i + 1) % 10 == 0:
            has = sum(1 for x in new_cols['Has_Website'] if x == 'Yes')
            print(f"  [{i+1}/{len(df)}] {has} with websites found so far")
        
        time.sleep(0.15)
    
    # Add new columns to df
    for col, vals in new_cols.items():
        df[col] = vals
    
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\nDone! Saved to {OUTPUT_FILE}")
    
    # Summary
    has_site = df[df['Has_Website'] == 'Yes']
    print(f"\n{'='*50}")
    print(f"Total records: {len(df)}")
    print(f"Has website: {len(has_site)} ({len(has_site)/len(df)*100:.0f}%)")
    print(f"No website:  {len(df)-len(has_site)} ({(len(df)-len(has_site))/len(df)*100:.0f}%)")
    print(f"\nPriority breakdown:")
    print(df['Target_Priority'].apply(lambda x: x.split('—')[0].strip()).value_counts().to_string())
    print(f"\nWebsite quality:")
    print(df[df['Has_Website']=='Yes']['Website_Quality'].apply(lambda x: x.split('—')[0].strip() if '—' in x else x.split(' ')[0]).value_counts().to_string())

if __name__ == '__main__':
    main()

