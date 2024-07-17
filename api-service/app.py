from flask import Flask, request, jsonify
from flask_cors import CORS
import redis
import boto3
import logging
import json
import pymysql
import time
from config import REDIS_HOST, REDIS_PORT, SQS_QUEUE_URL, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s:%(message)s')

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialize Redis
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Initialize SQS
sqs_client = boto3.client('sqs', region_name='us-east-1')

# Function to get recent weather from RDS
def get_recent_weather_from_db(city, state, country):
    try:
        connection = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        query = """
            SELECT * FROM weather_data
            WHERE city=%s AND (state=%s OR %s IS NULL OR %s = '') AND (country=%s OR %s IS NULL OR %s = '')
            ORDER BY id DESC
            LIMIT 1
        """
        cursor.execute(query, (city, state, state, state, country, country, country))
        result = cursor.fetchone()
        connection.close()
        return result
    except pymysql.MySQLError as e:
        logging.error(f"MySQL Error: {e}")
        return None
    except Exception as e:
        logging.error(f"Error: {e}")
        return None

# Function to send location data to SQS
def send_message_to_sqs(city, state, country):
    try:
        message = {
            "city": city,
            "state": state,
            "country": country
        }
        response = sqs_client.send_message(
            QueueUrl=SQS_QUEUE_URL,
            MessageBody=json.dumps(message)
        )
        logging.debug(f"Sent message to SQS: {response}")
    except Exception as e:
        logging.error(f"Error sending message to SQS: {e}")

@app.route('/fetch_weather', methods=['GET'])
def fetch_weather():
    try:
        city = request.args.get('city')
        state = request.args.get('state')
        country = request.args.get('country')

        logging.debug(f"Received data - City: {city}, State: {state}, Country: {country}")

        if not city:
            return jsonify({"success": False, "error": "City is required."})

        # Ensure state and country are not 'None' in the URL
        state = state if state else ""
        country = country if country else ""

        # Check Redis cache first
        cache_key = f"{city}:{state}:{country}"
        cached_data = redis_client.get(cache_key)

        if cached_data and cached_data != "fetching":
            logging.debug(f"Cache hit for {cache_key}")
            weather_data = json.loads(cached_data)
            response = {
                "success": True,
                "city": weather_data["city"],
                "main": weather_data["main"],
                "description": weather_data["description"],
                "temp": weather_data["temp"],
                "feels_like": weather_data["feels_like"],
                "temp_min": weather_data["temp_min"],
                "temp_max": weather_data["temp_max"],
                "pressure": weather_data["pressure"],
                "humidity": weather_data["humidity"],
                "visibility": weather_data["visibility"],
                "wind_speed": weather_data["wind_speed"],
                "wind_deg": weather_data["wind_deg"],
                "clouds_all": weather_data["clouds_all"],
                "coord_lat": weather_data["coord_lat"],
                "coord_lon": weather_data["coord_lon"]
            }
        else:
            logging.debug(f"Cache miss for {cache_key}")
            redis_client.setex(cache_key, 30, "fetching")
            send_message_to_sqs(city, state, country)

            # Wait a bit to allow worker to process (simulating what you did with time.sleep in CGI)
            time.sleep(2)
            weather_data = get_recent_weather_from_db(city, state, country)
            if weather_data:
                redis_client.setex(cache_key, 600, json.dumps(weather_data))
                response = {
                    "success": True,
                    "city": weather_data["city"],
                    "main": weather_data["main"],
                    "description": weather_data["description"],
                    "temp": weather_data["temp"],
                    "feels_like": weather_data["feels_like"],
                    "temp_min": weather_data["temp_min"],
                    "temp_max": weather_data["temp_max"],
                    "pressure": weather_data["pressure"],
                    "humidity": weather_data["humidity"],
                    "visibility": weather_data["visibility"],
                    "wind_speed": weather_data["wind_speed"],
                    "wind_deg": weather_data["wind_deg"],
                    "clouds_all": weather_data["clouds_all"],
                    "coord_lat": weather_data["coord_lat"],
                    "coord_lon": weather_data["coord_lon"]
                }
            else:
                response = {
                    "success": False,
                    "error": "Data is being fetched. Please try again shortly."
                }

        return jsonify(response)

    except Exception as e:
        logging.error(f"Error occurred: {str(e)}", exc_info=True)
        return jsonify({'error': 'Internal Server Error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
