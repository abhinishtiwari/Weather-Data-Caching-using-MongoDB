from pymongo import MongoClient
import requests
from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt

# ============= CONFIGURATION =============
API_KEY = "93422728e4501fcf10e7c914f76fd733"  # Your OpenWeatherMap API Key
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "weather_cache_db"
COLLECTION_NAME = "weather_data"
CACHE_HOURS = 1
# =========================================

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# ========== FETCH DATA FROM API ==========
def fetch_weather(city):
    """Fetch live weather data from OpenWeatherMap"""
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={API_KEY}&units=metric"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"❌ Error fetching data for {city} ({response.status_code})")
        return None
    data = response.json()
    # Try to fetch air quality (AQI) using the coordinates from the weather response
    aqi = None
    try:
        lat = data.get("coord", {}).get("lat")
        lon = data.get("coord", {}).get("lon")
        if lat is not None and lon is not None:
            pollution_url = f"https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={API_KEY}"
            p_resp = requests.get(pollution_url)
            if p_resp.status_code == 200:
                p_json = p_resp.json()
                # OpenWeatherMap returns AQI in p_json['list'][0]['main']['aqi'] (1-5)
                aqi = p_json.get("list", [{}])[0].get("main", {}).get("aqi")
    except Exception:
        # If anything goes wrong fetching AQI, leave it as None
        aqi = None

    return {
        "city": city.title(),
        "temperature": data["main"]["temp"],
        "humidity": data["main"]["humidity"],
        "condition": data["weather"][0]["description"],
        "aqi": aqi,
        "timestamp": datetime.utcnow()
    }

# ========== CACHE HANDLING ==========
def get_cached(city):
    """Check if city data exists in cache (valid for 1 hour)"""
    one_hour_ago = datetime.utcnow() - timedelta(hours=CACHE_HOURS)
    cached = collection.find_one({
        "city": city.title(),
        "timestamp": {"$gte": one_hour_ago}
    })
    return cached

# ========== SAVE TO MONGODB ==========
def save_to_db(data):
    """Save or update city weather data"""
    collection.update_one({"city": data["city"]}, {"$set": data}, upsert=True)

# ========== SHOW ALL DATA ==========
def show_all_data():
    """Display all stored weather data"""
    docs = list(collection.find({}, {"_id": 0}))
    if not docs:
        print("❌ No records found in MongoDB.")
    else:
        df = pd.DataFrame(docs)
        print("\n📦 Stored Weather Data:")
        print(df.to_string(index=False))

# ========== ANALYZE DATA ==========
def analyze_data():
    """Perform weather data analysis"""
    df = pd.DataFrame(list(collection.find({}, {"_id": 0})))
    if df.empty:
        print("❌ No data available for analysis.")
        return
    
    avg_temp = df.groupby("city")["temperature"].mean()
    max_temp = df.loc[df["temperature"].idxmax()]
    min_temp = df.loc[df["temperature"].idxmin()]
    max_humid = df.loc[df["humidity"].idxmax()]
    common_cond = df["condition"].mode()[0]
    
    print("\n📊 Weather Data Analysis:")
    print("Average Temperature by City:")
    print(avg_temp)
    print(f"\n🔥 Hottest City: {max_temp['city']} ({max_temp['temperature']}°C)")
    print(f"❄️ Coldest City: {min_temp['city']} ({min_temp['temperature']}°C)")
    print(f"💧 Most Humid City: {max_humid['city']} ({max_humid['humidity']}%)")
    print(f"🌤️ Most Common Condition: {common_cond}")

    # Optional: Graph for PPT
    avg_temp.plot(kind="bar", color="skyblue", title="Average Temperature by City")
    plt.ylabel("Temperature (°C)")
    plt.tight_layout()
    plt.show()

# ========== EXPORT DATA ==========
def export_data(filename="export.csv"):
    """Export all MongoDB data to CSV"""
    df = pd.DataFrame(list(collection.find({}, {"_id": 0})))
    if df.empty:
        print("❌ No data to export.")
        return
    df.to_csv(filename, index=False)
    print(f"✅ Data exported to {filename}")

# ========== MAIN PROGRAM ==========
def main():
    while True:
        print("\n======== 🌦️ Weather MongoDB App ========")
        print("1️⃣  Check weather for your city")
        print("2️⃣  View all stored data")
        print("3️⃣  Analyze stored data")
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
                # AQI may not be available for older records or if fetching failed
                aqi_val = data.get('aqi') if isinstance(data, dict) else None
                if aqi_val is not None:
                    print(f"AQI: {aqi_val}")
                print(f"Last Updated: {data['timestamp']}")
        
        elif choice == "2":
            show_all_data()
        
        elif choice == "3":
            analyze_data()
        
        elif choice == "4":
            export_data()
        
        elif choice == "5":
            print("👋 Goodbye! Have a great day!")
            break
        
        else:
            print("⚠️ Invalid choice. Please select a number between 1–5.")

# ========== RUN APP ==========
if __name__ == "__main__":
    main()
