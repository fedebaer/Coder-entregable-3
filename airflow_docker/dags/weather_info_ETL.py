import openmeteo_requests 
import requests_cache 
from retry_requests import retry
from airflow.models import DAG, Variable
from airflow.operators.python import PythonOperator
from airflow.hooks.base_hook import BaseHook
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
import logging
from datetime import datetime

def conectar_redshift():
    try:
        connection = BaseHook.get_connection("coder-redshift-fede")
        logging.info(f"Conectando a Redshift en {connection.host}:{connection.port}/{connection.schema}")
       
        conn = psycopg2.connect(
            host = connection.host,
            dbname = connection.schema,
            user = connection.login,
            password = connection.password,
            port = connection.port
        )
        return conn
        logging.info("Conectado a Redshift con éxito!")
    except Exception as e:
        logging.error(f"No es posible conectar a Redshift: {str(e)}")

def crear_tabla_en_bd():
    conn = conectar_redshift()
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fedebaer_coderhouse.daily_weather_3 (
                        m_date date NULL,
                        weather_code FLOAT NULL,
                        temperature_2m_max FLOAT NULL,
                        temperature_2m_min FLOAT NULL,
                        apparent_temperature_max FLOAT NULL,
                        apparent_temperature_min FLOAT NULL,
                        sunrise FLOAT NULL,
                        sunset FLOAT NULL,
                        daylight_duration FLOAT NULL,
                        sunshine_duration FLOAT NULL,
                        precipitation_sum FLOAT NULL,
                        rain_sum FLOAT NULL,
                        showers_sum FLOAT NULL,
                        snowfall_sum FLOAT NULL,
                        precipitation_hours FLOAT NULL,
                        precipitation_probability_max FLOAT NULL,
                        latitude FLOAT NULL,
                        longitude FLOAT NULL,
                        timezone VARCHAR(50) NULL,
                        city VARCHAR(50) NULL,
                        load_date DATE NULL,
                        PRIMARY KEY (m_date, load_date, city)
                    )
                """)
                conn.commit()
                logging.info("Tabla creada con éxito en Redshift.")
        except Exception as e:
            logging.error(f"No es posible crear tabla en Redshift: {str(e)}")
        finally:
            conn.close()
            logging.info("Conexión a Redshift cerrada.")

    
def traer_datos_clima():
     # Setup the Open-Meteo API client with cache and retry on error
    cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
    retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
    openmeteo = openmeteo_requests.Client(session = retry_session)

    # weather variables list. Se agrega el nombre de las ciudades que corresponden a cada par de latitud-longitud
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": [-32.8908, -34.6131, -24.7859, -31.4135, -33.295, -26.8241, -31.6488],
        "longitude": [-68.8272, -58.3772, -65.4117, -64.181, -66.3356, -65.2226, -60.7087],
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max", "apparent_temperature_min", "sunrise", "sunset", "daylight_duration", "sunshine_duration", "precipitation_sum", "rain_sum", "showers_sum", "snowfall_sum", "precipitation_hours", "precipitation_probability_max"],
        "timezone": ["America/Sao_Paulo", "America/Sao_Paulo", "America/Sao_Paulo", "America/Sao_Paulo", "America/Sao_Paulo", "America/Sao_Paulo", "America/Sao_Paulo"],
        "past_days": 7,
        "elevation": ["NaN", "NaN", "NaN", "NaN", "NaN", "NaN", "NaN"],
        "city": ["Mendoza", "Buenos Aires", "Salta", "Cordoba", "San Luis", "Tucuman", "Santa Fe"]

    }
    responses = openmeteo.weather_api(url, params=params)

    completed_dataframe = pd.DataFrame()

    # Se crea un bucle para procesar cada localidad
    for index, response in enumerate(responses):
        latitude = params["latitude"][index]
        longitude = params["longitude"][index]
        timezone = params["timezone"][index]
        elevation = params["elevation"][index]
        city = params["city"][index]


        daily = response.Daily()

        # Se crea un diccionario para cada Provincia con la información diaria de pronósticos.
        daily_data = {
            "m_date": pd.date_range(
                start=pd.to_datetime(daily.Time(), unit="s", utc=True),
                end=pd.to_datetime(daily.TimeEnd(), unit="s", utc=True),
                freq=pd.Timedelta(seconds=daily.Interval()),
                inclusive="left",
            ).date,
            "weather_code": daily.Variables(0).ValuesAsNumpy(),
            "temperature_2m_max": daily.Variables(1).ValuesAsNumpy(),
            "temperature_2m_min": daily.Variables(2).ValuesAsNumpy(),
            "apparent_temperature_max": daily.Variables(3).ValuesAsNumpy(),
            "apparent_temperature_min": daily.Variables(4).ValuesAsNumpy(),
            "sunrise": daily.Variables(5).ValuesAsNumpy(),
            "sunset": daily.Variables(6).ValuesAsNumpy(),
            "daylight_duration": daily.Variables(7).ValuesAsNumpy(),
            "sunshine_duration": daily.Variables(8).ValuesAsNumpy(),
            "precipitation_sum": daily.Variables(9).ValuesAsNumpy(),
            "rain_sum": daily.Variables(10).ValuesAsNumpy(),
            "showers_sum": daily.Variables(11).ValuesAsNumpy(),
            "snowfall_sum": daily.Variables(12).ValuesAsNumpy(),
            "precipitation_hours": daily.Variables(13).ValuesAsNumpy(),
            "precipitation_probability_max": daily.Variables(14).ValuesAsNumpy(),
        }

        # Se pasa esa info a un DataFrame
        daily_dataframe = pd.DataFrame(data=daily_data)

        # Se agregan nuevas columnas con los parámetros usados
        daily_dataframe["latitude"] = latitude
        daily_dataframe["longitude"] = longitude
        daily_dataframe["timezone"] = timezone
        daily_dataframe["city"] = city
        daily_dataframe["load_date"] = pd.Timestamp(datetime.now()).date()


        # Se agrega esta info al dataframe general
        completed_dataframe = pd.concat([completed_dataframe, daily_dataframe], ignore_index=True)

    completed_dataframe.sort_values(by=['city', 'm_date'], ascending=False)
    return(completed_dataframe)

def insertar_data():
    conn = conectar_redshift()
    if conn:
        try:
            existing_data_query = "SELECT * FROM fedebaer_coderhouse.daily_weather_3"
            existing_data = pd.read_sql(existing_data_query, conn)

            max_existing_load_date_query = "SELECT MAX(load_date) FROM fedebaer_coderhouse.daily_weather_3"
            max_existing_load_date = pd.read_sql(max_existing_load_date_query, conn).iloc[0, 0]

            completed_dataframe = traer_datos_clima()
            max_daily_load_date = completed_dataframe['load_date'].max()

            if max_daily_load_date > max_existing_load_date:
                with conn.cursor() as cur:
                    execute_values(
                        cur,
                        '''
                        INSERT INTO fedebaer_coderhouse.daily_weather_3 (
                            m_date, weather_code, temperature_2m_max, temperature_2m_min,
                            apparent_temperature_max, apparent_temperature_min, sunrise, sunset,
                            daylight_duration, sunshine_duration, precipitation_sum, rain_sum,
                            showers_sum, snowfall_sum, precipitation_hours, precipitation_probability_max,
                            latitude, longitude, timezone, city, load_date
                        ) VALUES %s
                        ''',
                        [tuple(row) for row in completed_dataframe.values]
                    )
                    conn.commit()
                    logging.info("Datos insertados con éxito en la tabla daily_weather_3.")
            else:
                logging.info("No hay nueva data para insertar.")
        except Exception as e:
            logging.error(f"Error al insertar datos en Redshift: {str(e)}")
        finally:
            conn.close()
            logging.info("Conexión a Redshift cerrada.")
    else:
        logging.error("Conexión a Redshift fallida, no se pueden insertar datos.")

