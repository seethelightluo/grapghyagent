# Graph Plan: World Top 10 University Rankings Across 10 Disciplines

## Graph Structure

```
node_1 (Define Univ & Disciplines)
   │
   ▼
node_2 (Collect Rankings Data)
   │
   ▼
node_3 (Validate Data)
   │
   ├──────────────┐
   ▼              ▼
node_4           node_5
(Calc FP Error)  (Gen Statistics)
   │              │
   └──────┬───────┘
          ▼
       node_6
    (Gen TXT Output)
```

## Node Details

### node_1: Define Universities & Disciplines
- **Input**: none (seed node)
- **Output**: `{"universities": ["MIT", "Stanford", "Harvard", "Caltech", "Oxford", "Cambridge", "ETH Zurich", "UCL", "Imperial College London", "University of Chicago"], "disciplines": ["Computer Science", "Engineering", "Physics", "Mathematics", "Chemistry", "Biology", "Medicine", "Economics", "Law", "Philosophy"]}`
- **Gate**: 10 universities AND 10 disciplines returned
- **Necessity**: Foundation — defines scope of entire analysis
- **Necessity Audit**: If removed, downstream nodes have no input data. **Verdict: indispensable**
- **Verification Rule**: Output contains exactly 10 universities and 10 disciplines as arrays
- **Evidence Pointers**: `["log/task_1_attempt1.md"]`

### node_2: Collect Rankings Data
- **Input**: universities + disciplines from node_1
- **Output**: `{"rankings": [{"university": "MIT", "overall_rank": 1, "disciplines": {"Computer Science": 1, "Engineering": 2, "Physics": 3, "Mathematics": 5, "Chemistry": 7, "Biology": 8, "Medicine": 12, "Economics": 6, "Law": 15, "Philosophy": 20}}, ...]}`
- **Gate**: 10 universities, each with 10 discipline rankings + 1 overall rank
- **Necessity**: Core data — without this, no rankings to analyze
- **Necessity Audit**: If removed, no data exists for validation or analysis. **Verdict: indispensable**
- **Verification Rule**: Output contains 10 entries, each with university name, overall_rank, and 10 discipline entries
- **Evidence Pointers**: `["log/task_2_attempt1.md"]`

### node_3: Validate Data
- **Input**: raw rankings from node_2
- **Output**: `{"validation_status": true, "total_universities": 10, "disciplines_count": 10, "duplicates_found": 0, "validated_data": [...]}`
- **Gate**: validation_status == true
- **Necessity**: Ensures data integrity before analysis
- **Necessity Audit**: If removed, corrupted data could propagate to error analysis. **Verdict: indispensable**
- **Verification Rule**: validation_status is true, total_universities == 10, disciplines_count == 10, duplicates_found == 0
- **Evidence Pointers**: `["log/task_3_attempt1.md"]`

### node_4: Calculate Floating-Point Error Analysis
- **Input**: validated data from node_3
- **Output**: `{"analysis": [{"university": "MIT", "overall_rank": 1, "avg_discipline_rank": 7.7, "error": 6.7, "error_pct": 670.0}, ...]}`
- **Gate**: 10 universities with error calculations
- **Necessity**: Core analytical computation — compares overall vs average discipline rank
- **Necessity Audit**: If removed, no error analysis exists. **Verdict: indispensable**
- **Verification Rule**: Output contains 10 analysis entries, each with error and error_pct calculated correctly
- **Evidence Pointers**: `["log/task_4_attempt1.md"]`

### node_5: Generate Statistics Summary
- **Input**: validated data from node_3
- **Output**: `{"stats": {"mean_error": ..., "std_error": ..., "max_positive_error": ..., "max_negative_error": ..., "universities_overestimated": ..., "universities_underestimated": ...}}`
- **Gate**: all stat fields present and non-null
- **Necessity**: Provides statistical context for error analysis
- **Necessity Audit**: If removed, the final report lacks aggregate statistics. **Verdict: indispensable** (enriches the analysis)
- **Verification Rule**: All 6 stat fields present, mean_error is a float, counts are integers
- **Evidence Pointers**: `["log/task_5_attempt1.md"]`

### node_6: Generate TXT Output
- **Input**: error analysis from node_4 + statistics from node_5
- **Output**: `{"txt_content": "WORLD TOP 10 UNIVERSITY RANKINGS..."}`
- **Gate**: non-empty txt_content with all required sections
- **Necessity**: Final deliverable — produces the output file
- **Necessity Audit**: If removed, no final file is produced. **Verdict: indispensable**
- **Verification Rule**: txt_content is non-empty and contains university names, discipline rankings, error analysis, and statistics
- **Evidence Pointers**: `["log/task_6_attempt1.md"]`

## Edges

| From | To | Relation |
|------|-----|----------|
| node_1 | node_2 | blocked_by |
| node_2 | node_3 | blocked_by |
| node_3 | node_4 | blocked_by |
| node_3 | node_5 | blocked_by |
| node_4 | node_6 | blocked_by |
| node_5 | node_6 | blocked_by |

## Execution Order

```
node_1 → node_2 → node_3 → [node_4, node_5 (parallel)] → node_6
```
