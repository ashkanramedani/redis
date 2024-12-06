# Use the official Python image
FROM python:3.12.7

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .


# Configure pip to use the local repository and fallback to PyPI
RUN mkdir ~/.pip && echo "[global]\nfind-links = http://pip-repo:5000\nindex-url = https://pypi.org/simple" > ~/.pip/pip.conf


RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose the port the app runs on
EXPOSE 8000

# Run the application
#  uvicorn main:app --host 0.0.0.0 --port 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
