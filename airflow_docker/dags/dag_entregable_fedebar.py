from datetime import timedelta, datetime
from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.utils.dates import days_ago
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from airflow.hooks.base_hook import BaseHook
from weather_info_ETL import enviar_email, traer_datos_clima, crear_tabla_en_bd, insertar_data

default_args = {
    'owner': 'FedeBar',
    'start_date': datetime(2024, 5, 27),
    'retries': 1,
    'retry_delay': timedelta(minutes=3),
    'on_failure_callback': enviar_email  # Callback para enviar email en caso de fallo
}

ingestion_dag = DAG(
    dag_id='ingestion_data',
    default_args=default_args,
    description='Agrega datos de clima de cada día',
    schedule_interval=timedelta(days=1),
    catchup=False
)

task_1 = PythonOperator(
    task_id='levantar_datos_API',
    python_callable=traer_datos_clima,
    dag=ingestion_dag,
)

task_2 = PythonOperator(
    task_id='crear_tabla_si_no_existe',
    python_callable=crear_tabla_en_bd,
    dag=ingestion_dag,
)

task_3 = PythonOperator(
    task_id='insertar_datos',
    python_callable=insertar_data,
    dag=ingestion_dag,
)

task_4 = PythonOperator(
    task_id='enviar_notificacion',
    python_callable=enviar_email,
    provide_context=True,  
    dag=ingestion_dag,
)

task_1 >> task_2 >> task_3 >> task_4
