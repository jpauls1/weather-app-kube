# Use an official Python runtime as a parent image
FROM python:3.9.19-slim-bullseye

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make the worker script executable
RUN chmod +x worker.py

# Run worker.py when the container launches
CMD ["./worker.py"]
