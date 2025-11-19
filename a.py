from pymongo import MongoClient
import requests
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import io
import base64
import json
import os
from bson.son import SON

# ============= CONFIGURATION =============
API_KEY = "93422728e4501fcf10e7c914f76fd733"  # Your OpenWeatherMap API Key
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "weather_cache_db"
COLLECTION_NAME = "weather_data"
CACHE_HOURS = 1
PLOTS_DIR = "plots"
os.makedirs(PLOTS_DIR, exist_ok=True)
# =========================================

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# ---------------- (your existing fetch/cache/save/show functions) ----------------
# ... (copy your existing fetch_weather, get_cached, save_to_db, show_all_data, ensure_aqi_field, update_existing_records_with_aqi, export_data) ...
# For brevity in this file, assume they are included unchanged above (or copy-paste from your provided script).
# ---------------------------------------------------------------------------------

# ========== NEW / EXTENDED ANALYSIS FUNCTIONS ==========

def _to_iso_b64_img(fig, filename=None):
    """Save matplotlib figure to PNG buffer and return base64 string. Optionally save to plots dir."""
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    if filename:
        filepath = os.path.join(PLOTS_DIR, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64))
    plt.close(fig)
    return b64

def generate_plots(df, cities_selected):
    """Generate required plots from dataframe and return dict of base64 images (and optionally save files)."""
    images = {}

    # Ensure timestamp is datetime
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        df["timestamp"] = pd.to_datetime(df.get("date", pd.Series([])))

    # 1. Temperature Trend (Line Plot) - by city
    fig, ax = plt.subplots(figsize=(10,4))
    for city, g in df.groupby("city"):
        if (cities_selected is None) or (city in cities_selected):
            g_sorted = g.sort_values("timestamp")
            ax.plot(g_sorted["timestamp"], g_sorted["temperature"], label=city)
    ax.set_title("Temperature Trend")
    ax.set_xlabel("Date")
    ax.set_ylabel("Temperature (°C)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.legend()
    images["temperature_trend"] = _to_iso_b64_img(fig, "temperature_trend.png")

    # 2. AQI Trend
    fig, ax = plt.subplots(figsize=(10,4))
    if "aqi" in df.columns:
        for city, g in df.groupby("city"):
            if (cities_selected is None) or (city in cities_selected):
                g_sorted = g.sort_values("timestamp")
                ax.plot(g_sorted["timestamp"], g_sorted["aqi"], label=city)
    ax.set_title("AQI Trend")
    ax.set_xlabel("Date")
    ax.set_ylabel("AQI")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    ax.legend()
    images["aqi_trend"] = _to_iso_b64_img(fig, "aqi_trend.png")

    # 3. Monthly Rainfall (Bar Chart) - requires 'rain' or 'rainfall' column; try to infer 'rain' or 0
    if "rain" not in df.columns:
        df["rain"] = df.get("rainfall", 0)
        df["rain"] = df["rain"].fillna(0)
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    monthly_rain = df.groupby("month")["rain"].sum().reset_index()
    fig, ax = plt.subplots(figsize=(10,4))
    ax.bar(monthly_rain["month"], monthly_rain["rain"])
    ax.set_title("Monthly Total Rainfall")
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Rainfall")
    plt.xticks(rotation=45)
    images["monthly_rainfall"] = _to_iso_b64_img(fig, "monthly_rainfall.png")

    # 4. Box Plot for Outliers (temperature, humidity, aqi)
    fig, ax = plt.subplots(nrows=1, ncols=3, figsize=(12,4))
    metrics = ["temperature", "humidity", "aqi"]
    for i, m in enumerate(metrics):
        data = df[m].dropna() if m in df.columns else pd.Series([])
        ax[i].boxplot(data, vert=True)
        ax[i].set_title(m)
    images["box_plots"] = _to_iso_b64_img(fig, "box_plots.png")

    # 5. City-wise Comparison (Average Temp, Avg AQI, Total Rain)
    city_stats = df.groupby("city").agg({
        "temperature": "mean",
        "aqi": "mean",
        "rain": "sum",
        "humidity": "mean"
    }).reset_index().fillna(0)
    # We'll generate a grouped bar for avg temperature and avg AQI for selected cities
    fig, ax = plt.subplots(figsize=(10,5))
    x = np.arange(len(city_stats))
    width = 0.35
    ax.bar(x - width/2, city_stats["temperature"], width, label="Avg Temp")
    ax.bar(x + width/2, city_stats["aqi"], width, label="Avg AQI")
    ax.set_xticks(x)
    ax.set_xticklabels(city_stats["city"], rotation=45)
    ax.set_title("City-wise Comparison: Avg Temp vs Avg AQI")
    ax.legend()
    images["city_comparison"] = _to_iso_b64_img(fig, "city_comparison.png")

    return images

def detect_outliers_iqr(series):
    """Return boolean mask of outliers using IQR method."""
    if series.dropna().empty:
        return pd.Series([False]*len(series), index=series.index)
    q1 = series.quantile(0.25)
    q3 = series.quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    return (series < lower) | (series > upper)

def analyze_data(cities=None, start_date=None, end_date=None, save_json=True):
    """
    Perform full weather data analysis.
    - cities: list of city names (strings) to focus on; if None -> all cities
    - start_date, end_date: optional datetimes (inclusive)
    Returns: analysis_result (dict)
    """
    query = {}
    if cities:
        query["city"] = {"$in": [c.title() for c in cities]}
    if start_date or end_date:
        ts_query = {}
        if start_date:
            ts_query["$gte"] = pd.to_datetime(start_date)
        if end_date:
            ts_query["$lte"] = pd.to_datetime(end_date)
        query["timestamp"] = ts_query

    # fetch documents
    docs = list(collection.find(query, {"_id": 0}))
    if not docs:
        print("❌ No data available for analysis with the given filters.")
        return {}

    df = pd.DataFrame(docs)
    # ensure timestamp is datetime
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    else:
        # try common alternatives
        if "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"])
        else:
            df["timestamp"] = pd.to_datetime(df.index)

    # Basic summary
    total_records = len(df)
    unique_cities = sorted(df["city"].dropna().unique().tolist())
    earliest = df["timestamp"].min()
    latest = df["timestamp"].max()

    basic_summary = {
        "total_records": int(total_records),
        "unique_cities": unique_cities,
        "earliest_timestamp": str(earliest),
        "latest_timestamp": str(latest)
    }

    # City-level summary (for each selected city)
    city_summary = {}
    for city, g in df.groupby("city"):
        city_dict = {
            "average_temperature": float(g["temperature"].mean()) if "temperature" in g else None,
            "min_temperature": float(g["temperature"].min()) if "temperature" in g else None,
            "max_temperature": float(g["temperature"].max()) if "temperature" in g else None,
            "average_humidity": float(g["humidity"].mean()) if "humidity" in g else None,
            "average_wind_speed": float(g["wind_speed"].mean()) if "wind_speed" in g else None,
            "average_aqi": float(g["aqi"].mean()) if "aqi" in g else None,
            "total_rainfall": float(g.get("rain", g.get("rainfall", pd.Series([0]))).fillna(0).sum()),
            "condition_counts": g["condition"].value_counts().to_dict() if "condition" in g else {}
        }
        city_summary[city] = city_dict

    # Time-based summaries
    now = latest
    last_7 = df[df["timestamp"] >= (now - pd.Timedelta(days=7))]
    last_30 = df[df["timestamp"] >= (now - pd.Timedelta(days=30))]

    def make_time_summary(sub_df):
        if sub_df.empty:
            return {}
        month_avg_temp = sub_df.set_index("timestamp").resample("M")["temperature"].mean().dropna().to_dict()
        month_total_rain = sub_df.set_index("timestamp").resample("M").apply(lambda s: s.get("rain", s.get("rainfall", 0)).sum() if "rain" in s else 0)
        # simpler monthly rain using groupby month:
        monthly = sub_df.copy()
        monthly["month"] = monthly["timestamp"].dt.to_period("M").astype(str)
        month_total_rain = monthly.groupby("month").apply(lambda g: float(g.get("rain", g.get("rainfall", pd.Series([0]))).fillna(0).sum())).to_dict()
        month_avg_aqi = monthly.groupby("month")["aqi"].mean().dropna().to_dict() if "aqi" in monthly else {}
        return {
            "count": int(len(sub_df)),
            "avg_temperature": float(sub_df["temperature"].mean()) if "temperature" in sub_df else None,
            "avg_humidity": float(sub_df["humidity"].mean()) if "humidity" in sub_df else None,
            "avg_aqi": float(sub_df["aqi"].mean()) if "aqi" in sub_df else None,
            "monthly_avg_temperature": {k: float(v) for k,v in month_avg_temp.items()},
            "monthly_total_rainfall": {k: float(v) for k,v in month_total_rain.items()},
            "monthly_avg_aqi": {k: float(v) for k,v in month_avg_aqi.items()}
        }

    last_7_summary = make_time_summary(last_7)
    last_30_summary = make_time_summary(last_30)

    # Monthly aggregates over entire dataset
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    monthly_avg_temperature = df.groupby("month")["temperature"].mean().dropna().to_dict() if "temperature" in df else {}
    monthly_total_rainfall = df.groupby("month").apply(lambda g: float(g.get("rain", g.get("rainfall", pd.Series([0]))).fillna(0).sum())).to_dict()
    monthly_avg_aqi = df.groupby("month")["aqi"].mean().dropna().to_dict() if "aqi" in df else {}

    # Trend analysis: prepare small series objects (sampled / aggregated by day to keep size reasonable)
    df_day = df.set_index("timestamp").groupby("city").resample("D").mean().reset_index()
    # Temperature trend per city: for JSON, we can provide last N days values
    temp_trends = {}
    aqi_trends = {}
    rain_trends = {}
    humidity_trends = {}
    for city, g in df_day.groupby("city"):
        g_sorted = g.sort_values("timestamp")
        temp_trends[city] = [{"date": str(row["timestamp"].date()), "temperature": None if pd.isna(row["temperature"]) else float(row["temperature"])} for _, row in g_sorted.iterrows()]
        if "aqi" in g:
            aqi_trends[city] = [{"date": str(row["timestamp"].date()), "aqi": None if pd.isna(row["aqi"]) else float(row["aqi"])} for _, row in g_sorted.iterrows()]
        rain_trends[city] = [{"date": str(row["timestamp"].date()), "rain": None if "rain" not in row or pd.isna(row.get("rain")) else float(row.get("rain"))} for _, row in g_sorted.iterrows()]
        humidity_trends[city] = [{"date": str(row["timestamp"].date()), "humidity": None if pd.isna(row["humidity"]) else float(row["humidity"])} for _, row in g_sorted.iterrows()]

    # Extreme weather analysis
    hottest = df.loc[df["temperature"].idxmax()] if "temperature" in df else None
    coldest = df.loc[df["temperature"].idxmin()] if "temperature" in df else None
    highest_rain = df.loc[df["rain"].fillna(0).idxmax()] if "rain" in df or "rainfall" in df else None
    highest_aqi = df.loc[df["aqi"].idxmax()] if "aqi" in df else None
    lowest_aqi = df.loc[df["aqi"].idxmin()] if "aqi" in df else None

    def row_to_summary(row, fields):
        if row is None:
            return None
        return {f: (None if f not in row or pd.isna(row[f]) else (str(row[f]) if isinstance(row[f], (np.datetime64, pd.Timestamp)) else float(row[f]) if isinstance(row[f], (int, float, np.integer, np.floating)) else row[f])) for f in fields}

    extreme = {
        "hottest_day": row_to_summary(hottest, ["city", "temperature", "timestamp", "condition"]) if hottest is not None else None,
        "coldest_day": row_to_summary(coldest, ["city", "temperature", "timestamp", "condition"]) if coldest is not None else None,
        "highest_rainfall_day": row_to_summary(highest_rain, ["city", "rain", "timestamp", "condition"]) if highest_rain is not None else None,
        "highest_aqi_day": row_to_summary(highest_aqi, ["city", "aqi", "timestamp"]) if highest_aqi is not None else None,
        "lowest_aqi_day": row_to_summary(lowest_aqi, ["city", "aqi", "timestamp"]) if lowest_aqi is not None else None
    }

    # City comparison (if multiple cities provided or overall for all cities)
    comp_df = df.copy()
    comp_df["rain"] = comp_df.get("rain", comp_df.get("rainfall", 0)).fillna(0)
    city_comparison = comp_df.groupby("city").agg({
        "temperature": "mean",
        "aqi": "mean",
        "rain": "sum",
        "humidity": "mean"
    }).reset_index().fillna(0).to_dict(orient="records")

    # Data quality checks
    missing_values = df.isnull().sum().to_dict()
    null_fields = {k: int(df[k].isnull().sum()) for k in df.columns}
    outliers = {
        "temperature_outliers_count": int(detect_outliers_iqr(df["temperature"]).sum()) if "temperature" in df else 0,
        "humidity_outliers_count": int(detect_outliers_iqr(df["humidity"]).sum()) if "humidity" in df else 0,
        "aqi_outliers_count": int(detect_outliers_iqr(df["aqi"]).sum()) if "aqi" in df else 0,
    }

    # Generate plots
    images = generate_plots(df, cities_selected=[c.title() for c in cities] if cities else None)

    # Build the final JSON result
    analysis_result = {
        "basic_summary": basic_summary,
        "city_summary": city_summary,
        "time_based": {
            "last_7_days": last_7_summary,
            "last_30_days": last_30_summary,
            "monthly_avg_temperature": {k: float(v) for k,v in monthly_avg_temperature.items()},
            "monthly_total_rainfall": {k: float(v) for k,v in monthly_total_rainfall.items()},
            "monthly_avg_aqi": {k: float(v) for k,v in monthly_avg_aqi.items()}
        },
        "trends": {
            "temperature_trends": temp_trends,
            "aqi_trends": aqi_trends,
            "rain_trends": rain_trends,
            "humidity_trends": humidity_trends
        },
        "extremes": extreme,
        "city_comparison": city_comparison,
        "data_quality": {
            "missing_values": missing_values,
            "null_fields": null_fields,
            "outlier_counts": outliers
        },
        "plots_base64": images
    }

    # Save to JSON file
    if save_json:
        with open("analysis_result.json", "w") as f:
            json.dump(analysis_result, f, indent=2, default=str)

    # Print a concise human summary
    print("\n======== BASIC SUMMARY ========")
    print(f"Total records: {basic_summary['total_records']}")
    print(f"Cities: {', '.join(basic_summary['unique_cities'])}")
    print(f"Date range: {basic_summary['earliest_timestamp']} → {basic_summary['latest_timestamp']}")

    print("\n======== SAMPLE CITY SUMMARY (first 3) ========")
    for i, (city, cs) in enumerate(city_summary.items()):
        if i >= 3: break
        print(f"\nCity: {city}")
        print(f" Avg Temp: {cs['average_temperature']}")
        print(f" Avg AQI: {cs['average_aqi']}")
        print(f" Total Rain: {cs['total_rainfall']}")
        print(f" Conditions (top 5): {list(cs['condition_counts'].items())[:5]}")

    print("\n======== EXTREMES ========")
    for k, v in extreme.items():
        print(f"{k}: {v}")

    print("\nPlots saved to the 'plots/' directory and also embedded as base64 in the JSON output.")

    return analysis_result

# ========== MAIN PROGRAM (menu) ==========
def main():
    # Ensure 'aqi' field exists on existing documents to avoid KeyErrors
    try:
        ensure_aqi_field()
    except NameError:
        # define a minimal ensure_aqi_field here if it's missing from imports
        def ensure_aqi_field():
            """Ensure all existing documents have an 'aqi' field (set to None if missing)."""
            try:
                result = collection.update_many({"aqi": {"$exists": False}}, {"$set": {"aqi": None}})
                if getattr(result, 'modified_count', 0):
                    print(f"🔧 Updated {result.modified_count} documents to include 'aqi' field.")
                else:
                    print("🔧 All documents already have an 'aqi' field or collection is empty.")
            except Exception as e:
                print(f"⚠️ Failed to ensure 'aqi' field on documents: {e}")

        # call the fallback implementation
        ensure_aqi_field()

    while True:
        print("\n======== 🌦️ Weather MongoDB App ========")
        print("1️⃣  Check weather for your city")
        print("2️⃣  View all stored data")
        print("3️⃣  Analyze stored data (extended)")
        print("4️⃣  Export data as CSV")
        print("5️⃣  Exit")
        
        choice = input("\nEnter your choice (1-5): ").strip()
        
        if choice == "1":
            city = input("Enter city name: ").strip()
            if not city:
                print("⚠️ Please enter a valid city name.")
                continue
            
            cached = get_cached(city)
            if cached:
                print(f"✅ Using cached data for {city.title()}")
                data = cached
            else:
                print(f"🌐 Fetching live data for {city.title()}...")
                data = fetch_weather(city)
                if data:
                    save_to_db(data)
            
            if data:
                print("\nCurrent Weather:")
                print(f"City: {data['city']}")
                print(f"Temperature: {data['temperature']}°C")
                print(f"Humidity: {data['humidity']}%")
                print(f"Condition: {data['condition']}")
                aqi_val = data.get('aqi') if isinstance(data, dict) else None
                if aqi_val is not None:
                    print(f"AQI: {aqi_val}")
                print(f"Last Updated: {data['timestamp']}")
        
        elif choice == "2":
            show_all_data()
        
        elif choice == "3":
            # ask for optional city filter
            city_input = input("Enter city names separated by comma (leave blank for all): ").strip()
            cities = [c.strip() for c in city_input.split(",")] if city_input else None
            # optional date filters
            sd = input("Start date (YYYY-MM-DD) or blank: ").strip()
            ed = input("End date (YYYY-MM-DD) or blank: ").strip()
            start_date = pd.to_datetime(sd) if sd else None
            end_date = pd.to_datetime(ed) if ed else None
            result = analyze_data(cities=cities, start_date=start_date, end_date=end_date)
            print("\n✅ Analysis complete. Summary saved to analysis_result.json")
        
        elif choice == "4":
            export_data()
        
        elif choice == "5":
            print("👋 Goodbye! Have a great day!")
            break
        
        else:
            print("⚠️ Invalid choice. Please select a number between 1–5.")

if __name__ == "__main__":
    main()
