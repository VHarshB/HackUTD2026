"""Offline scoring against the answer keys. Never imported by the running app.

Reports what matters for judging: did we find every event, did we invent any,
how long after onset did we raise the alarm, and how does our plan cost compare
with the reference plan at each snapshot's "now".
"""
import json

from backend.dataset import ROOT
from backend.engine import analyze, load

FOLDERS = ['full_week', 'snapshot_2026-10-08T1200', 'snapshot_2026-10-09T0330',
           'snapshot_2026-10-10T0900']


def score_detection(folder: str) -> None:
    analysis = load(f'history/{folder}')
    labels = json.loads((ROOT / f'history/{folder}/answer_key.json').read_text())
    found = list(analysis.events)
    hits, latencies = 0, []
    for label in labels:
        match = next((e for e in found
                      if e.facility_id == label['facility']
                      and e.category == label['category']
                      and abs(e.onset_unix - label['onset_unix']) < 6 * 3600), None)
        if match is None:
            print(f'  MISSED  {label["id"]:9s} {label["category"]:17s} {label["facility"]}')
            continue
        found.remove(match)
        hits += 1
        latencies.append((match.alarm_unix - label['onset_unix']) / 60)
    for extra in found:
        print(f'  INVENTED {extra.category:17s} {extra.facility_id}')
    median_latency = sorted(latencies)[len(latencies) // 2] if latencies else 0
    print(f'  detected {hits}/{len(labels)}, invented {len(found)}, '
          f'median alarm latency {median_latency:+.0f} min')


def score_plans(folder: str) -> None:
    labels = json.loads((ROOT / f'history/{folder}/answer_key.json').read_text())
    ongoing = [e for e in labels if e['status'] == 'ongoing' and e['category'] == 'pump_failure']
    if not ongoing:
        return
    view = analyze(f'history/{folder}')
    ours = sum(a['recommendation']['cost'] for a in view['alerts']
               if a['category'] == 'pump_failure')
    # The reference cost is written into each event's text, e.g. "(~$1,298)".
    import re
    reference = sum(float(re.search(r'~\$([\d,]+)', e['reference_action']).group(1).replace(',', ''))
                    for e in ongoing if '~$' in e['reference_action'])
    print(f'  live pump-failure plan cost ${ours:,.0f} vs reference ${reference:,.0f}')
    order = [a['facility_id'] for a in view['alerts'] if a['category'] == 'pump_failure']
    expected = [e['facility'] for e in sorted(ongoing, key=lambda e: e['order'])]
    print(f'  alert order {"matches" if order == expected else "DIFFERS from"} the key: {order}')


if __name__ == '__main__':
    for folder in FOLDERS:
        print(f'=== {folder} ===')
        score_detection(folder)
        score_plans(folder)
    print('\nThis is an offline check against labels, not a guarantee on unseen data.')
