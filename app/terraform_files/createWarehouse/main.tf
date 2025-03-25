provider "aws" {
  region     = "ap-south-1"   # Specify the region
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
  token      = var.aws_session_token
}

# Data to get the existing RDS instance information
data "aws_db_instance" "PostgresRDS" {
  db_instance_identifier = var.rds_instance_identifier
}

# Create the database and user using remote-exec provisioner
resource "null_resource" "setup_database" {
  connection {
    type        = "ssh"
    user        = var.REMOTE_USER
    private_key = file("${var.SSH_KEY}")
    host        = data.aws_instance.ec2_instance_id.public_ip
  }

  provisioner "remote-exec" {
    inline = [
      "echo 'Creating Database and User on RDS instance' ",
      
      # Creating the new database on RDS
      "PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c 'CREATE DATABASE ${var.APP_DB_NAME};'",
      
      # Creating the new user with a password
      "PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c \"CREATE USER ${var.APP_DB_USER} WITH PASSWORD '${var.APP_DB_PASS}';\"",
      
      # Granting all privileges on the new database to the new user
      "PGPASSWORD=${var.POSTGRES_PASSWORD} psql -h ${data.aws_db_instance.PostgresRDS.address} -U ${var.POSTGRES_USER} -c 'GRANT ALL PRIVILEGES ON DATABASE ${var.APP_DB_NAME} TO ${var.APP_DB_USER};'"
    ]
  }

  triggers = {
    always_run = "${timestamp()}"
  }
}

# Data to get the EC2 instance details (for SSH access)
data "aws_instance" "ec2_instance_id" {
  instance_id = var.ec2_instance_id
}