#!/usr/bin/env python3
"""Pull REAL organoid-protocol paper accessions from Europe PMC (no fabricated IDs)."""
import urllib.request, urllib.parse, json, time, csv, re

BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest/search'

# system -> (canonical organoid_type label, list of phrase variants)
SYSTEMS = {
    'intestinal':  ['intestinal organoid','gut organoid','colon organoid','colonic organoid'],
    'gastric':     ['gastric organoid','stomach organoid'],
    'cerebral':    ['cerebral organoid','brain organoid','cortical organoid'],
    'kidney':      ['kidney organoid','renal organoid','nephron organoid'],
    'liver':       ['liver organoid','hepatic organoid','hepatocyte organoid'],
    'lung':        ['lung organoid','airway organoid','alveolar organoid'],
    'retinal':     ['retinal organoid','optic cup organoid','eye organoid'],
    'pancreatic':  ['pancreatic organoid','pancreas organoid','islet organoid'],
    'cardiac':     ['cardiac organoid','heart organoid','cardiac microtissue'],
    'vascular':    ['vascular organoid','blood vessel organoid'],
}
METHODS = '(protocol OR differentiation OR generation OR establishment OR derivation OR culture OR "step-by-step")'
FILT = '(OPEN_ACCESS:Y AND IN_EPMC:Y AND HAS_FT:Y AND SRC:MED)'

def search(query, n=50, sort='CITED desc'):
    params = {'query': query, 'format':'json','pageSize':n,'sort':sort,'resultType':'core'}
    url = BASE+'?'+urllib.parse.urlencode(params)
    for _ in range(3):
        try:
            return json.load(urllib.request.urlopen(url, timeout=90))
        except Exception as e:
            time.sleep(2)
    return {'resultList':{'result':[]}}

def journal_of(r):
    ji = r.get('journalInfo') or {}
    j = (ji.get('journal') or {}).get('title')
    return j or r.get('journalTitle') or ''

def norm_license(l):
    if not l: return 'unknown'
    l = l.lower().replace(' ','-')
    if 'cc-by-nc' in l or 'cc-by-nc' in l: return 'CC-BY-NC'
    if l.startswith('cc-by') or l=='cc0' or 'cc-0' in l: return 'CC-BY' if l!='cc0' else 'CC0'
    if 'cc' in l: return l.upper()
    return l

PROTO_JOURNALS = re.compile(r'protoc|star protoc|bio.?protoc|methods? in', re.I)

rows = {}   # pmcid -> row
for otype, phrases in SYSTEMS.items():
    phrase_q = ' OR '.join(f'"{p}"' for p in phrases)
    q = f'({phrase_q}) AND {METHODS} AND {FILT}'
    # two sorts: citations (seminal) + recency (current protocols)
    seen_this = 0
    for sort in ['CITED desc','P_PDATE_D desc']:
        d = search(q, n=40, sort=sort)
        for r in d.get('resultList',{}).get('result',[]):
            pmcid = r.get('pmcid')
            if not pmcid: continue
            title = (r.get('title') or '').strip().rstrip('.')
            tl = title.lower()
            # relevance guard: require an organoid/organ term actually in the title
            if 'organoid' not in tl and not any(p.split()[0] in tl for p in phrases):
                continue
            if pmcid in rows:
                continue
            j = journal_of(r)
            cit = int(r.get('citedByCount') or 0)
            au = (r.get('authorString') or '').split(',')[0].split(' ')[0].strip()
            is_proto = bool(PROTO_JOURNALS.search(j))
            rows[pmcid] = {
                'organoid_type': otype,
                'doi': r.get('doi') or '',
                'pmcid': pmcid,
                'pmid': r.get('pmid') or '',
                'first_author': au,
                'year': r.get('pubYear') or '',
                'journal': j,
                'title': title,
                'cited_by': cit,
                'species': 'tbd',
                'source_cell_type': 'tbd',
                'license': norm_license(r.get('license')),
                'has_methods': 'yes',     # HAS_FT:Y guarantees full text in EPMC
                'has_supplement': 'tbd',
                'gold_candidate': 'yes' if (is_proto or cit>200) else 'tbd',
                'flags': ';'.join(filter(None,[
                    'protocol-journal' if is_proto else '',
                    'high-cited' if cit>500 else ''])) or 'tbd',
                'notes': 'auto: europepmc CITED/recency pull',
            }
            seen_this += 1
        time.sleep(0.4)
    print(f'{otype:12s} collected so far +{seen_this}')

print(f'\nTOTAL unique pmcid: {len(rows)}')
# save raw
with open('corpus_candidates_raw.json','w') as f:
    json.dump(list(rows.values()), f, indent=2)
print('wrote corpus_candidates_raw.json')

# --- INGEST CONTRACT (verified 2026-06-20) -------------------------------
# Full text (JATS XML):  https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<NUMERIC_PMCID>
# License + figure/suppl package (authoritative):
#                        https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC<...>   -> .tar.gz
# NOTE: PMC OA service license is authoritative; the EPMC `license` field can disagree
#       (e.g. PMC3033971: EPMC has a value, OA service reports license="none" = author MS).
#       Verify license via oa.fcgi BEFORE pulling figures (CC-BY/CC0 = reuse OK; NC = non-commercial; none = text-only).
