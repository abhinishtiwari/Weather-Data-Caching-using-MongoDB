"""
MongoDB Weather App - Complete Implementation
All data operations use MongoDB queries only (no pandas for analysis)
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
from pymongo import MongoClient
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Configuration
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "weather_app"
COLLECTION_NAME = "weather_data"
OPENWEATHER_API_KEY = "93422728e4501fcf10e7c914f76fd733"
TIMEZONE = ZoneInfo("Asia/Kolkata")
CACHE_DURATION = timedelta(hours=1)

# Default cities to track
DEFAULT_CITIES = ["Delhi", "Mumbai", "Bangalore", "Chennai", "Kolkata"]

# Initialize MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

# Create indexes for better performance
collection.create_index([("city", 1), ("timestamp", -1)])
collection.create_index("timestamp")


def get_current_time():
    """Get current time in Asia/Kolkata timezone"""
    return datetime.now(TIMEZONE)


def is_cache_valid(timestamp):
    """Check if cached data is less than 1 hour old"""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=TIMEZONE)
    return (get_current_time() - timestamp) < CACHE_DURATION


def fetch_openweather_data(city):
    """Fetch weather data from OpenWeatherMap API"""
    try:
        # Current weather
        weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={OPENWEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url, timeout=10)
        weather_response.raise_for_status()
        weather_data = weather_response.json()
        
        # Air quality with components
        lat = weather_data['coord']['lat']
        lon = weather_data['coord']['lon']
        aqi_url = f"http://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
        
        aqi_value = None
        aqi_category = None
        pm25 = None
        pm10 = None
        
        try:
            aqi_response = requests.get(aqi_url, timeout=10)
            aqi_response.raise_for_status()
            aqi_data = aqi_response.json()
            
            if aqi_data and 'list' in aqi_data and len(aqi_data['list']) > 0:
                aqi_info = aqi_data['list'][0]
                aqi_value = aqi_info['main']['aqi']
                
                # AQI categories (OpenWeatherMap scale: 1-5)
                aqi_categories = {
                    1: "Good",
                    2: "Fair",
                    3: "Moderate",
                    4: "Poor",
                    5: "Very Poor"
                }
                aqi_category = aqi_categories.get(aqi_value, "Unknown")
                
                # Get PM2.5 and PM10 values
                components = aqi_info.get('components', {})
                pm25 = components.get('pm2_5')
                pm10 = components.get('pm10')
                
        except Exception as aqi_error:
            print(f"Warning: Could not fetch AQI data for {city}: {aqi_error}")
        
        return {
            'city': city,
            'temperature': weather_data['main']['temp'],
            'humidity': weather_data['main']['humidity'],
            'condition': weather_data['weather'][0]['description'],
            'aqi': aqi_value,
            'aqi_category': aqi_category,
            'pm25': pm25,
            'pm10': pm10,
            'timestamp': get_current_time()
        }
    except Exception as e:
        print(f"Error fetching data for {city}: {e}")
        return None


def check_weather(city):
    """Option 1: Check weather with 1-hour caching"""
    print(f"\n🌤️  Checking weather for {city}...")
    
    # Query MongoDB for latest record
    latest_record = collection.find_one(
        {"city": city},
        sort=[("timestamp", -1)]
    )
    
    # Check if cache is valid
    if latest_record and is_cache_valid(latest_record['timestamp']):
        print("✅ Using cached data (less than 1 hour old)")
        data = latest_record
    else:
        print("🔄 Fetching fresh data from API...")
        data = fetch_openweather_data(city)
        if data:
            collection.insert_one(data)
            print("💾 Data stored in MongoDB")
        else:
            print("❌ Failed to fetch data")
            return
    
    # Display weather information
    print(f"\n📍 City: {data['city']}")
    print(f"🌡️  Temperature: {data['temperature']}°C")
    print(f"💧 Humidity: {data['humidity']}%")
    print(f"☁️  Condition: {data['condition']}")
    
    if data['aqi']:
        print(f"🏭 AQI: {data['aqi']} ({data['aqi_category']})")
        if data['pm25']:
            print(f"   PM2.5: {data['pm25']:.1f} µg/m³")
        if data['pm10']:
            print(f"   PM10: {data['pm10']:.1f} µg/m³")
    else:
        print(f"🏭 AQI: N/A")
    
    print(f"🕐 Timestamp: {data['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")


def basic_summary():
    """Option 2: Basic summary using MongoDB aggregation"""
    print("\n📊 BASIC SUMMARY")
    
    # Check if we need fresh data
    latest_doc = collection.find_one(sort=[("timestamp", -1)])
    
    if not latest_doc or not is_cache_valid(latest_doc['timestamp']):
        print("🔄 Database empty or outdated. Fetching fresh data for all cities...")
        for city in DEFAULT_CITIES:
            data = fetch_openweather_data(city)
            if data:
                collection.insert_one(data)
        print("✅ Fresh data inserted\n")
    
    # MongoDB aggregation pipeline
    pipeline = [
        {
            "$group": {
                "_id": None,
                "total_records": {"$sum": 1},
                "cities": {"$addToSet": "$city"},
                "earliest": {"$min": "$timestamp"},
                "latest": {"$max": "$timestamp"}
            }
        }
    ]
    
    result = list(collection.aggregate(pipeline))
    
    if result:
        summary = result[0]
        print(f"📝 Total Records: {summary['total_records']}")
        print(f"🌍 Unique Cities: {len(summary['cities'])}")
        print(f"   Cities: {', '.join(sorted(summary['cities']))}")
        print(f"📅 Earliest Entry: {summary['earliest'].strftime('%Y-%m-%d %I:%M:%S %p')}")
        print(f"📅 Latest Entry: {summary['latest'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    else:
        print("❌ No data in database")


def city_level_summary(city):
    """Option 3: City-level summary using MongoDB aggregation"""
    print(f"\n📊 CITY-LEVEL SUMMARY: {city}")
    
    # Check if we need fresh data for this city
    latest_record = collection.find_one(
        {"city": city},
        sort=[("timestamp", -1)]
    )
    
    if not latest_record or not is_cache_valid(latest_record['timestamp']):
        print("🔄 Fetching fresh data...")
        data = fetch_openweather_data(city)
        if data:
            collection.insert_one(data)
            print("✅ Fresh data inserted\n")
    
    # MongoDB aggregation pipeline
    pipeline = [
        {"$match": {"city": city}},
        {
            "$group": {
                "_id": "$city",
                "avg_temp": {"$avg": "$temperature"},
                "min_temp": {"$min": "$temperature"},
                "max_temp": {"$max": "$temperature"},
                "avg_humidity": {"$avg": "$humidity"},
                "avg_aqi": {"$avg": "$aqi"},
                "total_records": {"$sum": 1}
            }
        }
    ]
    
    result = list(collection.aggregate(pipeline))
    
    if result:
        summary = result[0]
        print(f"📝 Total Records: {summary['total_records']}")
        print(f"🌡️  Temperature: {summary['avg_temp']:.2f}°C (Min: {summary['min_temp']:.2f}°C, Max: {summary['max_temp']:.2f}°C)")
        print(f"💧 Average Humidity: {summary['avg_humidity']:.2f}%")
        if summary['avg_aqi']:
            print(f"🏭 Average AQI: {summary['avg_aqi']:.2f}")
        else:
            print(f"🏭 Average AQI: N/A")
    else:
        print(f"❌ No data found for {city}")


def extreme_weather_days():
    """Option 4: Extreme weather days using MongoDB queries"""
    print("\n🌡️  EXTREME WEATHER DAYS")
    
    # Get current date boundaries (today in Asia/Kolkata timezone)
    today_start = get_current_time().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = get_current_time().replace(hour=23, minute=59, second=59, microsecond=999999)
    
    # Check if we have today's data
    today_records = collection.count_documents({
        "timestamp": {"$gte": today_start, "$lte": today_end}
    })
    
    if today_records == 0 or not is_cache_valid(collection.find_one(sort=[("timestamp", -1)])['timestamp']):
        print("🔄 Fetching fresh data for all cities...")
        for city in DEFAULT_CITIES:
            data = fetch_openweather_data(city)
            if data:
                collection.insert_one(data)
        print("✅ Fresh data inserted\n")
    
    # Filter for today's records only
    today_filter = {"timestamp": {"$gte": today_start, "$lte": today_end}}
    
    # Hottest city today
    hottest = collection.find_one(
        today_filter,
        sort=[("temperature", -1)]
    )
    if hottest:
        print(f"🔥 HOTTEST TODAY (India): {hottest['city']} - {hottest['temperature']}°C")
        print(f"   Time: {hottest['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    # Coldest city today
    coldest = collection.find_one(
        today_filter,
        sort=[("temperature", 1)]
    )
    if coldest:
        print(f"\n❄️  COLDEST TODAY (India): {coldest['city']} - {coldest['temperature']}°C")
        print(f"   Time: {coldest['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    # Highest AQI today
    highest_aqi = collection.find_one(
        {**today_filter, "aqi": {"$ne": None}},
        sort=[("aqi", -1)]
    )
    if highest_aqi:
        aqi_display = f"{highest_aqi['aqi']} ({highest_aqi.get('aqi_category', 'N/A')})"
        print(f"\n🏭 HIGHEST AQI TODAY (India): {highest_aqi['city']} - {aqi_display}")
        if highest_aqi.get('pm25'):
            print(f"   PM2.5: {highest_aqi['pm25']:.1f} µg/m³, PM10: {highest_aqi.get('pm10', 0):.1f} µg/m³")
        print(f"   Time: {highest_aqi['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    # Lowest AQI today
    lowest_aqi = collection.find_one(
        {**today_filter, "aqi": {"$ne": None}},
        sort=[("aqi", 1)]
    )
    if lowest_aqi:
        aqi_display = f"{lowest_aqi['aqi']} ({lowest_aqi.get('aqi_category', 'N/A')})"
        print(f"\n🌿 LOWEST AQI TODAY (India): {lowest_aqi['city']} - {aqi_display}")
        if lowest_aqi.get('pm25'):
            print(f"   PM2.5: {lowest_aqi['pm25']:.1f} µg/m³, PM10: {lowest_aqi.get('pm10', 0):.1f} µg/m³")
        print(f"   Time: {lowest_aqi['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    # World extremes (fetch live)
    print("\n" + "="*60)
    print("🌍 WORLD EXTREMES (Live Data)")
    print("="*60)
    
    # Known hot and cold cities worldwide
    world_hot_cities = ["Kuwait City", "Dubai", "Phoenix", "Las Vegas", "Cairo"]
    world_cold_cities = ["Yakutsk", "Norilsk", "Anchorage", "Reykjavik", "Oslo"]
    
    print("\n🔥 Checking hottest cities worldwide...")
    world_hottest_temp = -999
    world_hottest_city = None
    
    for city in world_hot_cities:
        data = fetch_openweather_data(city)
        if data and data['temperature'] > world_hottest_temp:
            world_hottest_temp = data['temperature']
            world_hottest_city = data
    
    if world_hottest_city:
        print(f"🔥 HOTTEST (World): {world_hottest_city['city']} - {world_hottest_city['temperature']}°C")
        print(f"   Time: {world_hottest_city['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")
    
    print("\n❄️  Checking coldest cities worldwide...")
    world_coldest_temp = 999
    world_coldest_city = None
    
    for city in world_cold_cities:
        data = fetch_openweather_data(city)
        if data and data['temperature'] < world_coldest_temp:
            world_coldest_temp = data['temperature']
            world_coldest_city = data
    
    if world_coldest_city:
        print(f"❄️  COLDEST (World): {world_coldest_city['city']} - {world_coldest_city['temperature']}°C")
        print(f"   Time: {world_coldest_city['timestamp'].strftime('%Y-%m-%d %I:%M:%S %p')}")


def geocode_city(city):
    """Geocode city name to coordinates using OpenWeatherMap"""
    try:
        url = f"http://api.openweathermap.org/geo/1.0/direct?q={city}&limit=1&appid={OPENWEATHER_API_KEY}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data:
            return data[0]['lat'], data[0]['lon']
    except Exception as e:
        print(f"Error geocoding {city}: {e}")
    return None, None


def weekly_temperature_chart(city):
    """Option 5: Weekly temperature chart using Open-Meteo (no DB)"""
    print(f"\n📈 WEEKLY TEMPERATURE CHART: {city}")
    
    # Geocode city
    print("🔍 Geocoding city...")
    lat, lon = geocode_city(city)
    if not lat or not lon:
        print("❌ Could not geocode city")
        return
    
    print(f"📍 Coordinates: {lat}, {lon}")
    
    # Fetch 7 days of hourly data from Open-Meteo
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)
    
    url = f"https://archive-api.open-meteo.com/v1/archive"
    params = {
        'latitude': lat,
        'longitude': lon,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'hourly': 'temperature_2m',
        'timezone': 'Asia/Kolkata'
    }
    
    print("🔄 Fetching historical data from Open-Meteo...")
    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        hourly = data['hourly']
        times = [datetime.fromisoformat(t) for t in hourly['time']]
        temps = hourly['temperature_2m']
        
        # Calculate day and night temperatures
        days = []
        day_temps = []
        night_temps = []
        
        current_date = start_date
        while current_date <= end_date:
            day_hours = []
            night_hours = []
            
            for i, t in enumerate(times):
                if t.date() == current_date:
                    hour = t.hour
                    if 10 <= hour <= 17:  # Day: 10 AM - 5 PM
                        day_hours.append(temps[i])
                    elif hour >= 22 or hour <= 6:  # Night: 10 PM - 6 AM
                        night_hours.append(temps[i])
            
            if day_hours and night_hours:
                days.append(current_date)
                day_temps.append(max(day_hours))
                night_temps.append(min(night_hours))
            
            current_date += timedelta(days=1)
        
        # Create chart
        plt.figure(figsize=(12, 6))
        plt.plot(days, day_temps, marker='o', linewidth=2, label='Day (Max 10AM-5PM)', color='#FF6B6B')
        plt.plot(days, night_temps, marker='s', linewidth=2, label='Night (Min 10PM-6AM)', color='#4ECDC4')
        plt.fill_between(days, day_temps, night_temps, alpha=0.3, color='#95E1D3')
        
        plt.title(f'Weekly Temperature: {city}\nDay vs Night', fontsize=14, fontweight='bold')
        plt.xlabel('Date', fontsize=12)
        plt.ylabel('Temperature (°C)', fontsize=12)
        plt.legend(loc='best')
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        # Show chart
        print(f"✅ Displaying chart for {city}...")
        plt.show()
        
    except Exception as e:
        print(f"❌ Error: {e}")


def export_csv():
    """Option 6: Export data to CSV using Pandas"""
    print("\n💾 EXPORTING DATA TO CSV")
    
    # Fetch all data from MongoDB
    data = list(collection.find())
    
    if not data:
        print("❌ No data to export")
        return
    
    # Convert to DataFrame and export
    df = pd.DataFrame(data)
    
    # Remove MongoDB _id field
    if '_id' in df.columns:
        df = df.drop('_id', axis=1)
    
    # Format timestamp
    if 'timestamp' in df.columns:
        df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %I:%M:%S %p')
    
    filename = "weather_data.csv"
    df.to_csv(filename, index=False)
    print(f"✅ Data exported to: {filename}")
    print(f"📊 Total records exported: {len(df)}")


def main():
    """Main application menu"""
    print("=" * 60)
    print("🌤️  WEATHER APP - MongoDB Edition")
    print("=" * 60)
    
    while True:
        print("\n" + "=" * 60)
        print("MAIN MENU")
        print("=" * 60)
        print("1️⃣  Check Weather (Live + 1 Hour Cache)")
        print("2️⃣  Basic Summary")
        print("3️⃣  City-Level Summary")
        print("4️⃣  Extreme Weather Days")
        print("5️⃣  Weekly Temperature Chart (Day vs Night)")
        print("6️⃣  Export to CSV")
        print("7️⃣  Exit")
        print("=" * 60)
        
        choice = input("\nEnter your choice (1-7): ").strip()
        
        if choice == '1':
            city = input("Enter city name: ").strip()
            if city:
                check_weather(city)
            else:
                print("❌ City name cannot be empty")
        
        elif choice == '2':
            basic_summary()
        
        elif choice == '3':
            city = input("Enter city name: ").strip()
            if city:
                city_level_summary(city)
            else:
                print("❌ City name cannot be empty")
        
        elif choice == '4':
            extreme_weather_days()
        
        elif choice == '5':
            city = input("Enter city name: ").strip()
            if city:
                weekly_temperature_chart(city)
            else:
                print("❌ City name cannot be empty")
        
        elif choice == '6':
            export_csv()
        
        elif choice == '7':
            print("\n👋 Thank you for using Weather App!")
            break
        
        else:
            print("❌ Invalid choice. Please enter 1-7.")


if __name__ == "__main__":
    main()