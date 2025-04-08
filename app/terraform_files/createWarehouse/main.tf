provider "aws" {
  region     = "ap-south-1"   # Specify the region
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

# Data to get the existing RDS instance information
data "aws_db_instance" "PostgresRDS" {
 db_instance_identifier = var.rdsname
}

# Create the database and user using local-exec provisioner
resource "null_resource" "setup_database" {
  provisioner "local-exec" {
    command = <<-EOT
      # Install required packages if not present
      which psql || (sudo apt-get update && sudo apt-get install -y postgresql-client)
      
      echo 'Creating Database, Schema, and User on RDS instance'
      
      # Creating the new database on RDS
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c 'CREATE DATABASE ${var.APP_DB_NAME};' || echo 'Database may already exist, continuing...'
      
      # Creating the new user with a password
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c "CREATE USER ${var.APP_DB_USER} WITH PASSWORD '${var.APP_DB_PASS}';" || echo 'User may already exist, continuing...'
      
      # Grant all privileges on the new database to the new user
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c 'GRANT ALL PRIVILEGES ON DATABASE ${var.APP_DB_NAME} TO ${var.APP_DB_USER};'
      
      # Create a new schema 'staging' inside the newly created DB
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -d ${var.APP_DB_NAME} -c 'CREATE SCHEMA IF NOT EXISTS staging;'
      
      # Grant usage and create privileges on the schema to the user
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -d ${var.APP_DB_NAME} -c 'GRANT USAGE ON SCHEMA staging TO ${var.APP_DB_USER};'
      
      # Optionally: grant all privileges on all future tables in staging schema
      PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -d ${var.APP_DB_NAME} -c 'ALTER DEFAULT PRIVILEGES IN SCHEMA staging GRANT ALL ON TABLES TO ${var.APP_DB_USER};'
    EOT
  }

  triggers = {
    always_run = "${timestamp()}"
  }
}