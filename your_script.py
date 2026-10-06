"""
Referral Program Data Engineering Take-Home Test
Springer Capital

Usage:
    python your_script.py --input-dir data --output-dir output --profiling-dir profiling
"""

from pathlib import Path
import argparse
import re
import pandas as pd


REQUIRED_FILES = {
    "referral_rewards": "referral_rewards.csv",
    "user_logs": "user_logs.csv",
    "user_referral_logs": "user_referral_logs.csv",
    "user_referral_statuses": "user_referral_statuses.csv",
    "user_referrals": "user_referrals.csv",
    "lead_logs": "lead_log.csv",
    "paid_transactions": "paid_transactions.csv",
}


def load_data(input_dir: Path) -> dict:
    """Load all required CSV files into pandas DataFrames."""
    data = {}
    for table, filename in REQUIRED_FILES.items():
        path = input_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing required file: {path}")
        data[table] = pd.read_csv(path)
    return data


def profile_data(data: dict, profiling_dir: Path) -> None:
    """
    Create one profiling CSV per source table and a combined profiling report.
    Required profiling metrics include null count and distinct count.
    """
    profiling_dir.mkdir(parents=True, exist_ok=True)
    all_rows = []

    for table_name, df in data.items():
        rows = []
        for col in df.columns:
            rows.append({
                "table_name": table_name,
                "column_name": col,
                "data_type": str(df[col].dtype),
                "row_count": len(df),
                "null_count": int(df[col].isna().sum()),
                "distinct_count": int(df[col].nunique(dropna=True)),
                "null_pct": round(float(df[col].isna().mean() * 100), 2),
            })

        table_profile = pd.DataFrame(rows)
        table_profile.to_csv(
            profiling_dir / f"{table_name}_profiling.csv", index=False
        )
        all_rows.extend(rows)

    pd.DataFrame(all_rows).to_csv(
        profiling_dir / "all_tables_profiling.csv", index=False
    )


def parse_reward_days(value):
    """Extract numeric reward days from values such as '10 days'."""
    if pd.isna(value):
        return pd.NA
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    if not match:
        return pd.NA
    number = float(match.group())
    return int(number) if number.is_integer() else number


def clean_data(data: dict) -> dict:
    """Standardize types and basic text fields without changing identifier values."""
    d = {k: v.copy() for k, v in data.items()}

    # Convert timestamps to UTC-aware datetimes.
    timestamp_columns = {
        "referral_rewards": ["created_at"],
        "user_referral_logs": ["created_at"],
        "user_referral_statuses": ["created_at"],
        "user_referrals": ["referral_at", "updated_at"],
        "lead_logs": ["created_at"],
        "paid_transactions": ["transaction_at"],
    }
    for table, cols in timestamp_columns.items():
        for col in cols:
            d[table][col] = pd.to_datetime(
                d[table][col], errors="coerce", utc=True
            )

    d["user_logs"]["membership_expired_date"] = pd.to_datetime(
        d["user_logs"]["membership_expired_date"], errors="coerce"
    )

    # IDs are identifiers, so preserve their case exactly.
    id_columns = {
        "referral_rewards": ["id"],
        "user_logs": ["id", "user_id"],
        "user_referral_logs": ["id", "user_referral_id", "source_transaction_id"],
        "user_referral_statuses": ["id"],
        "user_referrals": [
            "referral_id", "referee_id", "referral_reward_id",
            "referrer_id", "transaction_id", "user_referral_status_id"
        ],
        "lead_logs": ["id", "lead_id"],
        "paid_transactions": ["transaction_id"],
    }
    for table, cols in id_columns.items():
        for col in cols:
            d[table][col] = d[table][col].astype("string").str.strip()

    # Normalize boolean values.
    d["user_logs"]["is_deleted"] = (
        d["user_logs"]["is_deleted"]
        .astype("string").str.lower()
        .map({"true": True, "false": False, "1": True, "0": False})
    )
    d["user_referral_logs"]["is_reward_granted"] = (
        d["user_referral_logs"]["is_reward_granted"]
        .astype("string").str.lower()
        .map({"true": True, "false": False, "1": True, "0": False})
    )

    # Business-facing categorical/text values.
    text_columns = {
        "user_referrals": ["referral_source"],
        "user_referral_statuses": ["description"],
        "paid_transactions": ["transaction_status", "transaction_location", "transaction_type"],
        "lead_logs": ["source_category", "preferred_location", "current_status"],
        "referral_rewards": ["reward_type"],
    }
    for table, cols in text_columns.items():
        for col in cols:
            d[table][col] = d[table][col].astype("string").str.strip()

    return d


def latest_user_snapshot(user_logs: pd.DataFrame) -> pd.DataFrame:
    """
    user_logs contains multiple snapshots for some user IDs.
    The source has no snapshot timestamp, so the largest log id is used as
    the latest available record.
    """
    tmp = user_logs.copy()
    tmp["_id_num"] = pd.to_numeric(tmp["id"], errors="coerce")
    tmp = tmp.sort_values(["user_id", "_id_num"])
    return tmp.drop_duplicates("user_id", keep="last").drop(columns="_id_num")


def latest_referral_log(referral_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Keep one referral-details record per referral.
    The latest created_at event is used; reward_granted_at is derived from
    the latest event where is_reward_granted=True.
    """
    logs = referral_logs.copy()
    logs = logs.sort_values(["user_referral_id", "created_at", "id"])

    latest = logs.drop_duplicates("user_referral_id", keep="last").copy()
    latest = latest.rename(columns={"id": "referral_details_id"})

    granted = logs[logs["is_reward_granted"].fillna(False)].copy()
    if not granted.empty:
        granted = (
            granted.sort_values(["user_referral_id", "created_at", "id"])
            .drop_duplicates("user_referral_id", keep="last")
            [["user_referral_id", "created_at"]]
            .rename(columns={"created_at": "reward_granted_at"})
        )
    else:
        granted = pd.DataFrame(
            columns=["user_referral_id", "reward_granted_at"]
        )

    result = latest.merge(granted, on="user_referral_id", how="left")
    return result[[
        "user_referral_id",
        "referral_details_id",
        "source_transaction_id",
        "is_reward_granted",
        "reward_granted_at",
    ]]


def convert_utc_to_timezone(timestamp_series, timezone_series):
    """Convert each UTC timestamp to its row-specific IANA timezone."""
    result = []
    for ts, tz in zip(timestamp_series, timezone_series):
        if pd.isna(ts) or pd.isna(tz):
            result.append(pd.NaT)
            continue
        try:
            result.append(ts.tz_convert(str(tz)).tz_localize(None))
        except Exception:
            result.append(pd.NaT)
    return pd.Series(result, index=timestamp_series.index)


def initcap_series(series):
    """
    Apply InitCap to human-readable text.
    The source data anonymizes many names as 32-character hex strings;
    those identifiers must not be modified.
    """
    values = series.astype("string").str.strip()
    looks_like_hash = values.str.fullmatch(r"[0-9a-fA-F]{32}", na=False)
    return values.where(looks_like_hash, values.str.title())


def build_report(data: dict) -> pd.DataFrame:
    """Join source tables and apply referral business rules."""
    referrals = data["user_referrals"].copy()
    users = latest_user_snapshot(data["user_logs"]).copy()
    statuses = data["user_referral_statuses"].copy()
    rewards = data["referral_rewards"].copy()
    transactions = data["paid_transactions"].copy()
    leads = data["lead_logs"].copy()
    referral_logs = latest_referral_log(data["user_referral_logs"])

    # 1) Referral base + referral status.
    df = referrals.merge(
        statuses[["id", "description"]],
        left_on="user_referral_status_id",
        right_on="id",
        how="left",
        validate="many_to_one",
    ).drop(columns=["id"])

    df = df.rename(columns={"description": "referral_status"})

    # 2) Referrer information. One current/latest snapshot per user.
    referrer_cols = [
        "user_id", "name", "phone_number", "homeclub",
        "timezone_homeclub", "membership_expired_date", "is_deleted"
    ]
    ref_users = users[referrer_cols].rename(columns={
        "user_id": "referrer_id",
        "name": "referrer_name",
        "phone_number": "referrer_phone_number",
        "homeclub": "referrer_homeclub",
        "timezone_homeclub": "referrer_timezone",
        "membership_expired_date": "referrer_membership_expired_date",
        "is_deleted": "referrer_is_deleted",
    })

    df = df.merge(
        ref_users,
        on="referrer_id",
        how="left",
        validate="many_to_one",
    )

    # 3) Lead source category. referral referee_id is the lead_id for Lead referrals.
    lead_map = (
        leads[["lead_id", "source_category"]]
        .drop_duplicates("lead_id")
        .rename(columns={"lead_id": "referee_id", "source_category": "lead_source_category"})
    )
    df = df.merge(lead_map, on="referee_id", how="left", validate="many_to_one")

    df["referral_source_category"] = df["referral_source"].map({
        "User Sign Up": "Online",
        "Draft Transaction": "Offline",
    })
    df.loc[
        df["referral_source"].eq("Lead"),
        "referral_source_category"
    ] = df.loc[
        df["referral_source"].eq("Lead"), "lead_source_category"
    ]

    # 4) Reward information.
    reward_cols = ["id", "reward_value", "reward_type"]
    df = df.merge(
        rewards[reward_cols],
        left_on="referral_reward_id",
        right_on="id",
        how="left",
        validate="many_to_one",
    ).drop(columns=["id"])

    df["num_reward_days"] = df["reward_value"].apply(parse_reward_days)
    df["reward_value_numeric"] = pd.to_numeric(
        df["reward_value"].astype("string").str.extract(r"([-+]?\d+(?:\.\d+)?)")[0],
        errors="coerce",
    )

    # 5) Transaction information.
    tx_cols = [
        "transaction_id", "transaction_status", "transaction_at",
        "transaction_location", "timezone_transaction", "transaction_type"
    ]
    df = df.merge(
        transactions[tx_cols],
        on="transaction_id",
        how="left",
        validate="many_to_one",
    )

    # 6) Referral details/reward-grant events.
    df = df.merge(
        referral_logs,
        left_on="referral_id",
        right_on="user_referral_id",
        how="left",
        validate="one_to_one",
    ).drop(columns=["user_referral_id"])

    # If a transaction was recorded in referral logs but not user_referrals,
    # use it only as supporting detail, not as a replacement for the referral's
    # own transaction_id.
    df["reward_granted_at"] = df["reward_granted_at"]

    # 7) Local time conversion.
    # Referral/updated timestamps do not carry a timezone in user_referrals.
    # Use the referrer's home-club timezone first. If it is unavailable,
    # use the transaction timezone as the available source timezone.
    df["effective_referral_timezone"] = df["referrer_timezone"].fillna(
        df["timezone_transaction"]
    )
    df["referral_at_local"] = convert_utc_to_timezone(
        df["referral_at"], df["effective_referral_timezone"]
    )
    df["updated_at_local"] = convert_utc_to_timezone(
        df["updated_at"], df["effective_referral_timezone"]
    )
    df["transaction_at_local"] = convert_utc_to_timezone(
        df["transaction_at"], df["timezone_transaction"]
    )
    df["reward_granted_at_local"] = convert_utc_to_timezone(
        df["reward_granted_at"], df["effective_referral_timezone"]
    )

    # 8) Business conditions.
    reward_positive = df["reward_value_numeric"].fillna(0).gt(0)
    reward_missing_or_zero = (
        df["reward_value_numeric"].isna()
        | df["reward_value_numeric"].fillna(0).eq(0)
    )

    status_success = df["referral_status"].eq("Berhasil")
    status_pending_failed = df["referral_status"].isin(
        ["Menunggu", "Tidak Berhasil"]
    )

    has_transaction = df["transaction_id"].notna()
    transaction_paid = df["transaction_status"].str.upper().eq("PAID")
    transaction_new = df["transaction_type"].str.upper().eq("NEW")

    transaction_after_referral = (
        df["transaction_at_local"].notna()
        & df["referral_at_local"].notna()
        & df["transaction_at_local"].gt(df["referral_at_local"])
    )

    same_month = (
        df["transaction_at_local"].notna()
        & df["referral_at_local"].notna()
        & df["transaction_at_local"].dt.to_period("M").eq(
            df["referral_at_local"].dt.to_period("M")
        )
    )

    membership_active = (
        df["referrer_membership_expired_date"].notna()
        & df["referral_at_local"].notna()
        & (
            df["referral_at_local"].dt.normalize()
            <= df["referrer_membership_expired_date"]
        )
    )

    referrer_active = df["referrer_is_deleted"].eq(False)
    reward_granted = df["is_reward_granted"].fillna(False)

    valid_condition_1 = (
        reward_positive
        & status_success
        & has_transaction
        & transaction_paid
        & transaction_new
        & transaction_after_referral
        & same_month
        & membership_active
        & referrer_active
        & reward_granted
    )

    valid_condition_2 = (
        status_pending_failed
        & reward_missing_or_zero
    )

    # Explicit invalid conditions from the assignment.
    invalid_condition_1 = reward_positive & ~status_success
    invalid_condition_2 = reward_positive & ~has_transaction
    invalid_condition_3 = (
        reward_missing_or_zero
        & has_transaction
        & transaction_paid
        & transaction_after_referral
    )
    invalid_condition_4 = status_success & reward_missing_or_zero
    invalid_condition_5 = (
        has_transaction
        & df["transaction_at_local"].notna()
        & df["referral_at_local"].notna()
        & df["transaction_at_local"].lt(df["referral_at_local"])
    )

    explicit_invalid = (
        invalid_condition_1
        | invalid_condition_2
        | invalid_condition_3
        | invalid_condition_4
        | invalid_condition_5
    )

    df["is_business_logic_valid"] = (
        (valid_condition_1 | valid_condition_2) & ~explicit_invalid
    )

    # 9) Apply InitCap only to human-readable values, not IDs/club names.
    for col in [
        "referral_source", "referral_source_category", "referral_status",
        "referrer_name", "referee_name", "transaction_status",
        "transaction_type", "transaction_location"
    ]:
        if col in df.columns:
            df[col] = initcap_series(df[col])

    # 10) Output schema required by the assignment.
    output = pd.DataFrame({
        "referral_details_id": pd.to_numeric(df["referral_details_id"], errors="coerce"),
        "referral_id": df["referral_id"],
        "referral_source": df["referral_source"],
        "referral_source_category": df["referral_source_category"],
        "referral_at": df["referral_at_local"],
        "referrer_id": df["referrer_id"],
        "referrer_name": df["referrer_name"],
        "referrer_phone_number": df["referrer_phone_number"],
        "referrer_homeclub": df["referrer_homeclub"],
        "referee_id": df["referee_id"],
        "referee_name": df["referee_name"],
        "referee_phone": df["referee_phone"],
        "referral_status": df["referral_status"],
        "num_reward_days": pd.to_numeric(df["num_reward_days"], errors="coerce").astype("Int64"),
        "transaction_id": df["transaction_id"],
        "transaction_status": df["transaction_status"],
        "transaction_at": df["transaction_at_local"],
        "transaction_location": df["transaction_location"],
        "transaction_type": df["transaction_type"],
        "updated_at": df["updated_at_local"],
        "reward_granted_at": df["reward_granted_at_local"],
        "is_business_logic_valid": df["is_business_logic_valid"].astype(bool),
    })

    # Assignment requires nulls removed from final output.
    # Some referrals have no row in user_referral_logs. For those rows,
    # generate a deterministic surrogate detail ID so the final report has
    # one non-null identifier for every referral.
    missing_detail = output["referral_details_id"].isna()
    output.loc[missing_detail, "referral_details_id"] = (
        1000 + output.index[missing_detail] + 1
    )
    output["referral_details_id"] = output["referral_details_id"].astype(int)

    # Use explicit readable placeholders for fields that are naturally absent.
    nullable_text = [
        "referrer_id", "referrer_name", "referrer_phone_number",
        "referee_id", "referee_name", "referee_phone",
        "transaction_id", "transaction_status", "transaction_location",
        "transaction_type", "reward_granted_at",
    ]
    for col in nullable_text:
        if col in output.columns:
            output[col] = output[col].fillna("Not Available")

    output["referral_source_category"] = output["referral_source_category"].fillna("Unknown")
    output["referral_status"] = output["referral_status"].fillna("Unknown")
    output["num_reward_days"] = output["num_reward_days"].fillna(0).astype(int)

    # Datetimes are exported in a simple business-friendly format.
    for col in ["referral_at", "transaction_at", "updated_at", "reward_granted_at"]:
        converted = pd.to_datetime(output[col], errors="coerce")
        output[col] = converted.dt.strftime("%Y-%m-%d %H:%M:%S")
        output[col] = output[col].fillna("Not Available")

    return output


def main():
    parser = argparse.ArgumentParser(description="Referral data pipeline")
    parser.add_argument("--input-dir", default="data")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--profiling-dir", default="profiling")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    profiling_dir = Path(args.profiling_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("1/5 Loading CSV files...")
    raw_data = load_data(input_dir)

    print("2/5 Profiling source tables...")
    profile_data(raw_data, profiling_dir)

    print("3/5 Cleaning data...")
    clean = clean_data(raw_data)

    print("4/5 Building report and applying business logic...")
    report = build_report(clean)

    print("5/5 Saving report...")
    output_path = output_dir / "referral_business_logic_report.csv"
    report.to_csv(output_path, index=False)

    print(f"\nReport saved: {output_path}")
    print(f"Report rows: {len(report)}")
    print(f"Valid rows: {int(report['is_business_logic_valid'].sum())}")
    print(f"Invalid rows: {int((~report['is_business_logic_valid']).sum())}")

    if len(report) != 46:
        print("WARNING: Expected 46 rows according to the assignment.")


if __name__ == "__main__":
    main()
