# Module Memory: node_2 — Collect Famous Things

## Necessity
This is the core data collection — the 100 famous things that form the entire dataset.
- **Counterfactual**: If removed, there is no data to visualize or rank. **Verdict: indispensable**

## Planned I/O
- **Input**: `{"cities": ["Paris", "Tokyo", ...], "criteria": "..."}`
- **Output**: `{"data": [{"city": "Paris", "things": ["Eiffel Tower", "Louvre Museum", "Notre-Dame", ...]}, ...]}` — 10 cities × 10 things = 100 items

## Actual I/O (from TaskGet)
- **Actual Input**: `{"cities": ["New York", "London", "Paris", "Tokyo", "Rome", "Dubai", "Sydney", "Cairo", "Rio de Janeiro", "Beijing"], "criteria": "Global Recognition, Cultural Significance, Tourism Popularity, Historical Importance"}`
- **Actual Output**: 10 city objects, each with 10 specific famous things. All 100 items unique.

## Comparison
| Field | Planned | Actual | Match |
|-------|---------|--------|-------|
| Cities in data | 10 | 10 | ✅ |
| Things per city | 10 | 10 | ✅ |
| Total items | 100 | 100 | ✅ |
| All unique | true | true (0 duplicates) | ✅ |
| Items are specific landmarks | true | true | ✅ |

**Notes**: Planned example showed only 2 cities for brevity. Actual output covered all 10 cities with well-chosen, globally recognized landmarks.

## Verification
- **Rule**: Output JSON has exactly 10 cities, each with exactly 10 string entries, total 100 unique items.
- **Result**: `10 cities returned, each with exactly 10 things. Total: 100 items. All items unique (0 duplicates). All items are strings.`

## Evidence Pointers
- `e:/graphyagent/example/example1/log/task_2_attempt1.md`

## Gate Status
- **Condition**: 100 items total, 10 per city
- **Status**: **OPEN** ✅
