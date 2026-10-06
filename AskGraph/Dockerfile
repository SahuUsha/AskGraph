# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MPLBACKEND=Agg

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt /app/

# psycopg2-binary and every other pinned dep ship manylinux wheels, so no
# compiler is needed. build-essential + gcc + libpq-dev added ~300MB and a
# larger CVE surface to build nothing.
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Bust the COPY cache on every deploy so frontend/backend changes always land
# in the image, even when Docker layer caching on the VPS would otherwise
# reuse a stale COPY . /app/ layer.
ARG GIT_SHA=dev
RUN echo "AskGraph build ${GIT_SHA}"

# Copy the current directory contents into the container at /app
COPY . /app/
ENV APP_VERSION=${GIT_SHA}

# Run as a non-root user; the app never writes to its own directory.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port 8000 to the outside world
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
