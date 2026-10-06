# Referral Program Data Engineering Take-Home

## Objective
Profile the seven supplied referral CSV tables, clean and join them, convert UTC timestamps to local time, apply the specified referral business rules, and generate the required 46-row report.

Implementation: **Python + Pandas**.

## Structure
```text
data/       source CSV files
profiling/  generated profiling CSV files
output/     referral_business_logic_report.csv
docs/       data_dictionary.xlsx
your_script.py
requirements.txt
Dockerfile
README.md
```

## Local Windows setup
Open CMD in this project folder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python your_script.py --input-dir data --output-dir output --profiling-dir profiling
```

The report is:
```text
output\referral_business_logic_report.csv
```

The profiling results are under:
```text
profiling\
```

## Pipeline steps
1. Load all seven CSV files.
2. Profile every column: data type, row count, null count, distinct count and null percentage.
3. Clean timestamp, boolean and business text fields.
4. Deduplicate `user_logs` by `user_id`; since the source has no snapshot timestamp, the highest log `id` is treated as the latest available snapshot.
5. Join referral statuses, referrer details, lead source category, rewards, transactions and referral logs.
6. Apply the required source-category mapping:
   - User Sign Up -> Online
   - Draft Transaction -> Offline
   - Lead -> lead_log.source_category
7. Convert UTC timestamps to local time using the referrer home-club timezone where available; transaction timezone is used as a fallback for referral/updated timestamps.
8. Apply valid and invalid business rules.
9. Export one row per referral.

## Business rules
A successful reward is valid when reward > 0, status is Berhasil, transaction exists, transaction is PAID and NEW, transaction occurs after referral creation and in the same month, the referrer membership has not expired, the account is not deleted, and the reward was granted.

A pending/failed referral is valid when status is Menunggu or Tidak Berhasil and no reward value is assigned.

Explicit invalid conditions from the assignment are also checked. These explicit invalid conditions take precedence.

## Docker
Build:
```bat
docker build -t referral-data-pipeline .
```

Run and keep generated files on the host:
```bat
docker run --rm -v "%cd%\data:/app/data" -v "%cd%\output:/app/output" -v "%cd%\profiling:/app/profiling" referral-data-pipeline
```

## Data assumptions
- `user_logs` has repeated snapshots but no snapshot timestamp, so maximum `id` per `user_id` is used.
- For Lead referrals, `user_referrals.referee_id` matches `lead_log.lead_id` in the supplied data.
- Human-readable values are InitCap'd; club names and identifier-like anonymized 32-character hex values are preserved.
- Final missing values are represented as `Not Available`, rather than blank CSV cells, so business users can distinguish missing source data from an actual empty value.

## Submission checklist
- Python script
- Dockerfile
- requirements.txt
- profiling outputs
- 46-row report
- Excel data dictionary
- README
