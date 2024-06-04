FROM apache/airflow:2.9.1-python3.8

# Switch to root user to copy the requirements.txt file
USER root
COPY requirements.txt /requirements.txt

# Switch to airflow user to install dependencies
USER airflow
RUN pip install --no-cache-dir -r /requirements.txt
