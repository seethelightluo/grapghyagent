# Module Memory: node_2 — Collect Rankings Data

## Necessity
If removed, no ranking data exists for validation or analysis. The pipeline has nothing to process. Verdict: indispensable.

## Planned I/O
- **Input**:
```json
{
  "universities": "array of strings",
  "disciplines": "array of strings"
}
```
- **Output**:
```json
{
  "rankings": "array of objects with university, overall_rank, disciplines"
}
```

## Actual I/O (from TaskGet)
- **Actual Input**:
```json
{
  "universities": [
    "MIT",
    "Stanford University",
    "Harvard University",
    "California Institute of Technology",
    "University of Oxford",
    "University of Cambridge",
    "ETH Zurich",
    "UCL",
    "Imperial College London",
    "University of Chicago"
  ],
  "disciplines": [
    "Computer Science",
    "Engineering",
    "Natural Sciences",
    "Mathematics",
    "Physics",
    "Chemistry",
    "Biology",
    "Medicine",
    "Economics",
    "Law"
  ]
}
```
- **Actual Output**:
```json
{
  "rankings": [
    {
      "university": "MIT",
      "overall_rank": 1,
      "disciplines": {
        "Computer Science": 1,
        "Engineering": 1,
        "Natural Sciences": 3,
        "Mathematics": 2,
        "Physics": 1,
        "Chemistry": 3,
        "Biology": 5,
        "Medicine": 7,
        "Economics": 3,
        "Law": 8
      }
    },
    {
      "university": "Stanford University",
      "overall_rank": 2,
      "disciplines": {
        "Computer Science": 2,
        "Engineering": 2,
        "Natural Sciences": 5,
        "Mathematics": 4,
        "Physics": 5,
        "Chemistry": 5,
        "Biology": 3,
        "Medicine": 4,
        "Economics": 4,
        "Law": 3
      }
    },
    {
      "university": "Harvard University",
      "overall_rank": 3,
      "disciplines": {
        "Computer Science": 7,
        "Engineering": 9,
        "Natural Sciences": 7,
        "Mathematics": 5,
        "Physics": 7,
        "Chemistry": 6,
        "Biology": 1,
        "Medicine": 1,
        "Economics": 2,
        "Law": 1
      }
    },
    {
      "university": "California Institute of Technology",
      "overall_rank": 4,
      "disciplines": {
        "Computer Science": 8,
        "Engineering": 4,
        "Natural Sciences": 4,
        "Mathematics": 7,
        "Physics": 2,
        "Chemistry": 6,
        "Biology": 6,
        "Medicine": 8,
        "Economics": 10,
        "Law": 10
      }
    },
    {
      "university": "University of Oxford",
      "overall_rank": 5,
      "disciplines": {
        "Computer Science": 4,
        "Engineering": 6,
        "Natural Sciences": 2,
        "Mathematics": 3,
        "Physics": 4,
        "Chemistry": 2,
        "Biology": 4,
        "Medicine": 2,
        "Economics": 5,
        "Law": 4
      }
    },
    {
      "university": "University of Cambridge",
      "overall_rank": 6,
      "disciplines": {
        "Computer Science": 3,
        "Engineering": 5,
        "Natural Sciences": 1,
        "Mathematics": 1,
        "Physics": 3,
        "Chemistry": 1,
        "Biology": 2,
        "Medicine": 3,
        "Economics": 6,
        "Law": 5
      }
    },
    {
      "university": "ETH Zurich",
      "overall_rank": 7,
      "disciplines": {
        "Computer Science": 5,
        "Engineering": 3,
        "Natural Sciences": 6,
        "Mathematics": 6,
        "Physics": 6,
        "Chemistry": 4,
        "Biology": 7,
        "Medicine": 9,
        "Economics": 7,
        "Law": 7
      }
    },
    {
      "university": "UCL",
      "overall_rank": 8,
      "disciplines": {
        "Computer Science": 9,
        "Engineering": 8,
        "Natural Sciences": 8,
        "Mathematics": 9,
        "Physics": 9,
        "Chemistry": 8,
        "Biology": 8,
        "Medicine": 5,
        "Economics": 8,
        "Law": 6
      }
    },
    {
      "university": "Imperial College London",
      "overall_rank": 9,
      "disciplines": {
        "Computer Science": 10,
        "Engineering": 7,
        "Natural Sciences": 9,
        "Mathematics": 10,
        "Physics": 10,
        "Chemistry": 9,
        "Biology": 9,
        "Medicine": 6,
        "Economics": 9,
        "Law": 9
      }
    },
    {
      "university": "University of Chicago",
      "overall_rank": 10,
      "disciplines": {
        "Computer Science": 6,
        "Engineering": 10,
        "Natural Sciences": 10,
        "Mathematics": 8,
        "Physics": 8,
        "Chemistry": 10,
        "Biology": 10,
        "Medicine": 10,
        "Economics": 1,
        "Law": 2
      }
    }
  ]
}
```

## Comparison
| Field | Spec | Actual | Match |
|-------|------|--------|-------|
| rankings | defined | present | ✅ |

## Verification
- **Rule**: Output must have 10 rankings, each with university name, overall_rank (int), and disciplines object with exactly 10 key-value pairs.
- **Result**: all checks passed

## Evidence Pointers
- No evidence pointers.

## Gate Status
- **Condition**: rankings.length == 10 AND each ranking has overall_rank AND each ranking has exactly 10 discipline entries
- **Status**: **open** ✅
