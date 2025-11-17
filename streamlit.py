import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pymongo import MongoClient
from datetime import datetime, timedelta
from bson.binary import Binary
import io

# -----------------------------
# STREAMLIT PAGE SETTINGS
# -----------------------------
st.set_page_config(
    page_title="Weather Insights Dashboard",
    layout="wide",
    page_icon="⛅"
)

# -----------------------------
# STYLES
# -----------------------------
st.markdown("""
<style>
/* Main Background */
body {
    background-color: #f2f5f9;
}

/* Card Style */
.metric-card {
    padding: 20px;
    border-radius: 12px;
    background: linear-gradient(135deg, #e3f2fd, #ffffff);
    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    text-align: center;
}

.section-title {
    font-size: 26px;
    color: #0d47a1;
    font-weight: 600;
    margin-bottom: 10px;
}

hr {
    border: 1px solid #90caf9;
}
</style>
""", unsafe_allow_html=True)

# -----------------------------
# MONGO CONNECTION
# -----------------------------
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "weather_cache_db"
COLLECTION_NAME = "weather_data"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]


# -----------------------------
# FUNCTIONS
# -----------------------------
@st.cache_data
def load_data():
    docs = list(collection.find({}, {"_id": 0}))
    df = pd.DataFrame(docs)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['city'] = df['city'].str.title()
    df['heat_index'] = df['temperature'] + (0.1 * df['humidity'])
    return df


def save_chart_to_mongo(name, fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    binary = Binary(buf.read())
    db["weather_charts"].update_one(
        {"chart_name": name},
        {"$set": {"image": binary, "timestamp": datetime.utcnow()}},
        upsert=True
    )


# -----------------------------
# LOAD DATA
# -----------------------------
df = load_data()
cities = sorted(df["city"].unique())

# -----------------------------
# SIDEBAR MENU
# -----------------------------
menu = st.sidebar.radio(
    "📌 Select Analysis Type",
    ["Dashboard Overview", "City-wise Analysis", "Compare Two Cities", "30-Day Trends", "Extreme Events"]
)

st.sidebar.info("Made With ❤️ Using Streamlit + MongoDB")

palette = ["#0D1B2A", "#1B263B", "#415A77", "#778DA9", "#E0E1DD"]


# ==========================================================
# 1️⃣ DASHBOARD OVERVIEW
# ==========================================================
if menu == "Dashboard Overview":
    st.markdown("<div class='section-title'>🌦 Weather Dashboard Overview</div>", unsafe_allow_html=True)

    col1, col2, col3, col4 = st.columns(4)
    col1.markdown("<div class='metric-card'>🏙 Cities<br><h2>%d</h2></div>" % df['city'].nunique(), unsafe_allow_html=True)
    col2.markdown("<div class='metric-card'>📊 Records<br><h2>%d</h2></div>" % len(df), unsafe_allow_html=True)
    col3.markdown("<div class='metric-card'>🌡 Avg Temp<br><h2>%.1f °C</h2></div>" % df['temperature'].mean(), unsafe_allow_html=True)
    col4.markdown("<div class='metric-card'>💧 Avg Humidity<br><h2>%.1f %%</h2></div>" % df['humidity'].mean(), unsafe_allow_html=True)

    st.markdown("### 🌡 Average Temperature by City")
    fig, ax = plt.subplots(figsize=(8,4))
    sns.barplot(data=df, x="city", y="temperature", estimator=np.mean, palette=palette, ax=ax)
    st.pyplot(fig)
    save_chart_to_mongo("avg_temp_all", fig)

    st.markdown("### 🌀 Condition Distribution")
    fig, ax = plt.subplots(figsize=(6,6))
    df["condition"].value_counts().plot(kind="pie", autopct="%1.1f%%", cmap="coolwarm", ax=ax)
    st.pyplot(fig)

    st.markdown("### 🔥 Heatmap of Temperature, Humidity, AQI")
    fig, ax = plt.subplots(figsize=(8,4))
    sns.heatmap(df[['temperature','humidity','aqi']].corr(), annot=True, cmap="YlGnBu", ax=ax)
    st.pyplot(fig)


# ==========================================================
# 2️⃣ CITY-WISE ANALYSIS
# ==========================================================
elif menu == "City-wise Analysis":
    st.markdown("<div class='section-title'>🏙 City-wise Weather Analysis</div>", unsafe_allow_html=True)

    city = st.selectbox("Choose a City", cities)
    df_city = df[df["city"] == city]

    col1, col2, col3 = st.columns(3)
    col1.metric("Avg Temp", f"{df_city['temperature'].mean():.1f} °C")
    col2.metric("Avg Humidity", f"{df_city['humidity'].mean():.1f}%")
    col3.metric("Avg AQI", f"{df_city['aqi'].mean():.1f}")

    st.markdown("### 🌡 Temperature Distribution")
    fig, ax = plt.subplots(figsize=(8,4))
    sns.histplot(df_city["temperature"], kde=True, color="orange", ax=ax)
    st.pyplot(fig)

    st.markdown("### 📈 Temperature Trend")
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(df_city["timestamp"], df_city["temperature"], marker="o", color="red")
    st.pyplot(fig)

    st.markdown("### 💧 Humidity Trend")
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(df_city["timestamp"], df_city["humidity"], marker="o", color="blue")
    st.pyplot(fig)


# ==========================================================
# 3️⃣ COMPARE TWO CITIES
# ==========================================================
elif menu == "Compare Two Cities":
    st.markdown("<div class='section-title'>🏙 Compare Two Cities</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    city1 = col1.selectbox("City 1", cities)
    city2 = col2.selectbox("City 2", cities)

    df1 = df[df["city"] == city1]
    df2 = df[df["city"] == city2]

    st.markdown("### 📈 Temperature Comparison")
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(df1["timestamp"], df1["temperature"], label=city1, marker="o")
    ax.plot(df2["timestamp"], df2["temperature"], label=city2, marker="o")
    ax.legend()
    st.pyplot(fig)

    st.markdown("### 💧 Humidity Comparison")
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(df1["timestamp"], df1["humidity"], label=city1, marker="o")
    ax.plot(df2["timestamp"], df2["humidity"], label=city2, marker="o")
    ax.legend()
    st.pyplot(fig)

    st.markdown("### 📊 Comparison Summary")
    comp = pd.DataFrame({
        "Metric": ["Avg Temp", "Avg Humidity", "Avg AQI"],
        city1: [
            df1["temperature"].mean(),
            df1["humidity"].mean(),
            df1["aqi"].mean()
        ],
        city2: [
            df2["temperature"].mean(),
            df2["humidity"].mean(),
            df2["aqi"].mean()
        ]
    })
    st.dataframe(comp.round(2))


# ==========================================================
# 4️⃣ LAST 30-DAY TRENDS
# ==========================================================
elif menu == "30-Day Trends":
    st.markdown("<div class='section-title'>📅 Last 30-Day Trends</div>", unsafe_allow_html=True)

    cutoff = datetime.utcnow() - timedelta(days=30)
    df30 = df[df["timestamp"] >= cutoff]

    st.markdown("### 🌡 Temperature Trend (Last 30 Days)")
    fig, ax = plt.subplots(figsize=(10,4))
    for city in cities:
        dfc = df30[df30["city"] == city]
        ax.plot(dfc["timestamp"], dfc["temperature"], marker="o", label=city)
    ax.legend()
    st.pyplot(fig)


# ==========================================================
# 5️⃣ EXTREME EVENTS
# ==========================================================
elif menu == "Extreme Events":
    st.markdown("<div class='section-title'>⚠ Extreme Weather Events</div>", unsafe_allow_html=True)

    hottest = df.loc[df['temperature'].idxmax()]
    coldest = df.loc[df['temperature'].idxmin()]
    humid = df.loc[df['humidity'].idxmax()]
    worst_aqi = df.loc[df['aqi'].idxmax()]

    st.write("### 🔥 Hottest Recorded:", hottest["city"], hottest["temperature"], "°C")
    st.write("### ❄ Coldest Recorded:", coldest["city"], coldest["temperature"], "°C")
    st.write("### 💧 Most Humid:", humid["city"], humid["humidity"], "%")
    st.write("### 🌫 Worst AQI:", worst_aqi["city"], worst_aqi["aqi"])

    st.write("---")

    st.markdown("### 🌡 Temperature vs Humidity Scatter")
    fig, ax = plt.subplots(figsize=(8,4))
    sns.scatterplot(data=df, x="temperature", y="humidity", hue="city", palette="tab10", ax=ax)
    st.pyplot(fig)
