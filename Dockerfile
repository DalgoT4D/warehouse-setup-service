FROM python:3.10-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    gnupg \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Terraform
RUN curl -fsSL https://apt.releases.hashicorp.com/gpg | apt-key add - \
    && apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main" \
    && apt-get update && apt-get install -y terraform \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy project files
COPY . .

# Create venv and install dependencies
RUN uv venv /app/.venv && \
    /app/.venv/bin/uv pip install -e ".[dev]"

# Use the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"] 