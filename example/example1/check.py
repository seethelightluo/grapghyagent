import re, os

fp = os.path.join('e:', os.sep, 'graphyagent', 'example', 'example1', 'cities_famous_things.txt')
with open(fp, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
print('Total lines:', len(lines))

# Check sections
print('Has tree section:', 'Tree Visualization' in content or '\u6811\u7ed3\u6784' in content)
print('Has ranking section:', 'Importance Ranking' in content or '\u91cd\u8981\u6027\u6392\u540d' in content)
print('Has summary:', 'Summary' in content or '\u7edf\u8ba1\u6458\u8981' in content)

# Extract ranks
rank_matches = re.findall(r'\|\s*(\d{1,3})\s*\|', content)
ranks = [int(r) for r in rank_matches]
print('Rank matches:', len(ranks))
if ranks:
    print('Range:', min(ranks), '-', max(ranks))
    print('Unique:', len(set(ranks)))
    dupes = [r for r in set(ranks) if ranks.count(r) > 1]
    print('Duplicates:', dupes if dupes else 'none')
    missing = set(range(1, 101)) - set(ranks)
    print('Missing:', sorted(missing) if missing else 'none')

# Count tree leaf items (├── or └── followed by number)
tree_items = 0
for line in lines:
    stripped = line.strip()
    if '├──' in stripped or '└──' in stripped:
        m = re.search(r'\d+\.\s+\S', stripped)
        if m:
            tree_items += 1
print('Tree leaf items:', tree_items)

# Count city nodes
city_count = 0
for line in lines:
    stripped = line.strip()
    if re.match(r'(├──|└──)\s+\d+\.\s+\w', stripped):
        city_count += 1
print('City nodes in tree:', city_count)
