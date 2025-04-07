FROM python:3.10-slim

WORKDIR /app

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    gnupg \
    software-properties-common \
    && rm -rf /var/lib/apt/lists/*

# Install Terraform with architecture detection (works on both ARM64 and AMD64)
RUN TERRAFORM_VERSION="1.4.6" \
    && ARCH=$(dpkg --print-architecture) \
    && case ${ARCH} in \
        amd64) TERRAFORM_ARCH="amd64" ;; \
        arm64) TERRAFORM_ARCH="arm64" ;; \
        *) echo "Unsupported architecture: ${ARCH}" && exit 1 ;; \
    esac \
    && curl -fsSL -o /tmp/terraform.zip https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TERRAFORM_ARCH}.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm -f /tmp/terraform.zip \
    && terraform --version

# Create README.md placeholder to avoid build errors
RUN echo "# Warehouse Setup" > README.md

# Copy project files
COPY . .

# Install base Python dependencies
RUN pip install --no-cache-dir fastapi uvicorn[standard] celery[redis] redis pydantic pydantic-settings httpx python-dotenv flower

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8006"] 