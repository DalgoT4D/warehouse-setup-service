# Variables to be defined in terraform.tfvars or variables.tf
variable "rds_instance_identifier" {
  description = "The identifier of the existing RDS instance."
}

variable "POSTGRES_USER" {
  description = "The PostgreSQL master username for the RDS instance."
}

variable "POSTGRES_PASSWORD" {
  description = "The PostgreSQL master password for the RDS instance."
}

variable "APP_DB_NAME" {
  description = "The name of the new database to create."
}

variable "APP_DB_USER" {
  description = "The new database user."
}

variable "APP_DB_PASS" {
  description = "The password for the new database user."
}

variable "REMOTE_USER" {
  description = "The SSH user for the EC2 instance."
}

variable "SSH_KEY" {
  description = "The private key file for SSH authentication."
}

variable "ec2_instance_id" {
  description = "The EC2 instance ID used for SSH access."
}