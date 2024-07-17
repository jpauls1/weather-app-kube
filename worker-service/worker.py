#!/usr/bin/env python3

import json
import boto3
import requests
import logging
import pymysql
import redis
from config import REDIS_HOST, REDIS_PORT, SQS_QUEUE_URL, API_KEY, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s:%(message)s')
logging.debug("Starting the worker.py script for constant polling")

# Establish connection for SQS client
sqs_client = boto3.client('sqs', region_name='us-east-1')

# Initialize Redis connection
redis_client = redis.StrictRedis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

# Function to get location coordinates from OpenWeatherMap API
def get_location(city, state=None, country=None):
    logging.debug(f"Fetching location for city: {city}, state: {state}, country: {country}")
    location_url = "http://api.openweathermap.org/geo/1.0/direct"
    
    if state and not country:
        country = "US"  # Default country to US if state is selected
    
    params = {
        'q': f"{city},{state},{country}" if state and country else f"{city},{state}" if state else f"{city},{country}" if country else city,
        'limit': 1,
        'appid': API_KEY
    }
    
    try:
        response = requests.get(location_url, params=params)
        response.raise_for_status()
        locations = response.json()
        logging.debug(f"Location data fetched successfully: {locations}")
        return locations
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching location data: {e}")
        return []

# Function to get weather data from OpenWeatherMap API
def get_weather(lat, lon, state, country):
    logging.debug(f"Fetching weather for latitude: {lat}, longitude: {lon}")
    weather_url = "http://api.openweathermap.org/data/2.5/weather"
    params = {
        'lat': lat,
        'lon': lon,
        'appid': API_KEY,
        'units': 'metric'
    }
    try:
        response = requests.get(weather_url, params=params)
        response.raise_for_status()
        weather_data = response.json()
        logging.debug(f"Weather data fetched successfully: {weather_data}")
        return {
            'success': True,
            'city': weather_data['name'],
            'main': weather_data['weather'][0]['main'],
            'description': weather_data['weather'][0]['description'],
            'temp': weather_data['main']['temp'],
            'feels_like': weather_data['main']['feels_like'],
            'temp_min': weather_data['main']['temp_min'],
            'temp_max': weather_data['main']['temp_max'],
            'pressure': weather_data['main']['pressure'],
            'humidity': weather_data['main']['humidity'],
            'visibility': weather_data.get('visibility', None),
            'wind_speed': weather_data['wind']['speed'],
            'wind_deg': weather_data['wind']['deg'],
            'clouds_all': weather_data['clouds']['all'],
            'coord_lat': weather_data['coord']['lat'],
            'coord_lon': weather_data['coord']['lon'],
            'state': state,
            'country': country
        }
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching weather data: {e}")
        return {
            'success': False,
            'error': str(e)
        }

# Function to process SQS messages
def process_message(message_body):
    try:
        message = json.loads(message_body)
        city = message.get('city')
        state = message.get('state', None)
        country = message.get('country', None)

        if not city:
            raise ValueError("City must be provided")

        logging.debug(f"Parsed message - City: {city}, State: {state}, Country: {country}")
        return city, state, country
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON message: {e}")
        return None, None, None
    except ValueError as e:
        logging.error(f"Invalid message content: {e}")
        return None, None, None

# Function to save weather data to the RDS database
def save_weather_data(weather_data):
    try:
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor()
        add_weather = ("INSERT INTO weather_data "
                       "(city, state, country, main, description, temp, feels_like, temp_min, temp_max, pressure, humidity, visibility, wind_speed, wind_deg, clouds_all, coord_lat, coord_lon) "
                       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)")
        data_weather = (
            weather_data['city'], weather_data.get('state', ''), weather_data.get('country', ''),
            weather_data['main'], weather_data['description'], weather_data['temp'], weather_data['feels_like'],
            weather_data['temp_min'], weather_data['temp_max'], weather_data['pressure'], weather_data['humidity'],
            weather_data['visibility'], weather_data['wind_speed'], weather_data['wind_deg'],
            weather_data['clouds_all'], weather_data['coord_lat'], weather_data['coord_lon']
        )
        cursor.execute(add_weather, data_weather)
        conn.commit()
        cursor.close()
        conn.close()
        logging.debug("Weather data saved to the database.")
    except pymysql.MySQLError as err:
        logging.error(f"Error: {err}")
        return {
            'success': False,
            'error': str(err)
        }

def main():
    logging.debug("Worker is beginning to poll SQS")
    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=SQS_QUEUE_URL,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=10
            )

            if 'Messages' not in response:
                logging.debug("No messages to process")
                continue

            for message in response['Messages']:
                receipt_handle = message['ReceiptHandle']
                body = message['Body']
                logging.debug(f"Received message: {body}")

                city, state, country = process_message(body)
                if city:
                    locations = get_location(city, state, country)
                    if locations:
                        weather_data = get_weather(locations[0]['lat'], locations[0]['lon'], state, country)
                        if weather_data['success']:
                            save_weather_data(weather_data)
                            cache_key = f"{city},{state},{country}"
                            redis_client.delete(cache_key)  # Invalidate cache

                        sqs_client.delete_message(
                            QueueUrl=SQS_QUEUE_URL,
                            ReceiptHandle=receipt_handle
                        )
                        logging.debug(f"Deleted message with receipt handle: {receipt_handle}")
                    else:
                        logging.error("Location not found, deleting message")
                        sqs_client.delete_message(
                            QueueUrl=SQS_QUEUE_URL,
                            ReceiptHandle=receipt_handle
                        )
                        logging.debug(f"Deleted message with receipt handle: {receipt_handle} due to location not found")
                else:
                    logging.error("Invalid message, deleting from queue")
                    sqs_client.delete_message(
                        QueueUrl=SQS_QUEUE_URL,
                        ReceiptHandle=receipt_handle
                    )
                    logging.debug(f"Deleted invalid message with receipt handle: {receipt_handle}")
        except Exception as e:
            logging.error(f"Error in main loop: {e}")

if __name__ == "__main__":
    main()
