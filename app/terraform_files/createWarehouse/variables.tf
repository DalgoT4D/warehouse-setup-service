# Variables to be defined in terraform.tfvars or variables.tf
variable "rdsname" {
  description = "The identifier of the existing RDS instance."
}

variable "RDS_DOMAIN" {
  description = "The domain name of the RDS instance."
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

variable "DB_PORT" {
  description = "The port number for the PostgreSQL database (default is 5432)."
  default     = 5432
}

variable "aws_access_key"{
  description = "aws access key"
}
variable "aws_secret_key"{
  description = "aws access key"
}

