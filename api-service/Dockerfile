# Use an official Python runtime as a parent image
FROM python:3.9.19-slim-bullseye

# Set the working directory
WORKDIR /usr/src/app

# Copy the necessary files
COPY app.py .
COPY config.py .
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]
