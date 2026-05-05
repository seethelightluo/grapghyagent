import re, sys

results = []

# Check world_top10_cities_famous_things.txt
with open('world_top10_cities_famous_things.txt', 'r', encoding='utf-8') as f:
    cb = f.read()

scores_b = re.findall(r'\|\s*(\d+\.\d+)\s*$', cb, re.MULTILINE)
results.append('Scores B count: %d' % len(scores_b))
if scores_b:
    results.append('B range: %s - %s' % (min(float(s) for s in scores_b), max(float(s) for s in scores_b)))

cities_b = re.findall(r'\u251c\u2500\u2500 \d+\. (.+)', cb) + re.findall(r'\u2514\u2500\u2500 \d+\. (.+)', cb)
results.append('Cities B: %s' % repr(cities_b))

# Check cities_famous_things.txt
with open('cities_famous_things.txt', 'r', encoding='utf-8') as f:
    cc = f.read()

scores_c = re.findall(r'\[(\d+)\u5206\]', cc)
results.append('Scores C count: %d' % len(scores_c))
if scores_c:
    results.append('C range: %s - %s' % (min(int(s) for s in scores_c), max(int(s) for s in scores_c)))

# Cities from C tree (top-level = no number prefix)
cities_c = []
for line in cc.split('\n'):
    s = line.strip()
    if (s.startswith('\u251c') or s.startswith('\u2514')) and '\u2500\u2500 ' in s:
        rest = s.split('\u2500\u2500 ', 1)[1] if '\u2500\u2500 ' in s else ''
        if rest and '(' not in rest and not rest[0].isdigit():
            cities_c.append(rest)
results.append('Cities C: %s' % repr(cities_c))

mem = ['New York', 'London', 'Paris', 'Tokyo', 'Shanghai', 'Beijing', 'Dubai', 'Sydney', 'Rome', 'Singapore']
results.append('Memory cities: %s' % repr(mem))
results.append('Mem vs B exact match: %s' % (set(mem) == set(cities_b)))
results.append('Mem vs C exact match: %s' % (set(mem) == set(cities_c)))

if set(cities_b) != set(mem):
    results.append('B has but mem lacks: %s' % repr(set(cities_b) - set(mem)))
    results.append('Mem has but B lacks: %s' % repr(set(mem) - set(cities_b)))

if set(cities_c) != set(mem):
    results.append('C has but mem lacks: %s' % repr(set(cities_c) - set(mem)))
    results.append('Mem has but C lacks: %s' % repr(set(mem) - set(cities_c)))

# Write results
with open('_audit_results.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))
