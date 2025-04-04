Procedure to use terraform scripts for "superset" deployment.


Script  Overview : 


It consists of two sections, one making applications available on the given remote application server and second creating resources on aws infrastructure or configure aws components in such a way that http traffic from client are redirected via load balancer to application running on ec2 instance.


First part
 


1. Pulling the latest "docker-superset" repo from github viz.


https://github.com/DalgoT4D/docker-superset.git


2. Generate_make_client                                    ⇐  take input from terraform.tfvars 
3. Updates "superset.env"                                 ⇐  take input from terraform.tfvars
4. Ship entire repo to remote machine with docker-compose.yml and superset.env.
5. Execute build.sh                                             <= build container onto remote machine.
6. docker compose                                             <= launch application
7. start-superset.sh                                             <= create admin user and db migration


Second Part


1. Adding listener rule to existing HTTP 443 port of given load balancer.
2. Adding ingress inbound rule onto existing security group of Application server.




Terraform.tfvars




# Below parameters are needed for script execution


Location of script directory, terraform will be execute from here
AUTOROOT_DIR        = "/home/XXXX/YYYY"


Remote user login on application server ( usually it's "ubuntu" )
REMOTE_USER         = "ubuntu"


SSH Key on local machine
SSH_KEY             = "/home/XXX/.ssh/id_rsa.pem"


Local directory where repo is copied,will be deleted at every execution
LOCAL_CLONE_DIR     = "/home/XXX/YYY/superset-repo"


Superserset, don't want to hardcode, incase of future changes
SUPERSET_MIDDLE_DIR = "gensuperset/make-client"


Remote machine directory, where repo is copied
So superset.env, will be available in /home/ubuntu/gensuperset/make-client/testngo1/superset.env


REMOTE_CLONE_DIR    = "/home/ubuntu"


RDS name used in your aws environment
rdsname             = "rail-db-1"


# End




# Below parameters are for Generate make client


CLIENT_NAME        = "testngo1"
PROJECT_OR_ENV     = "prod"
BASE_IMAGE         = "tech4dev/superset:4.1.1"
SUPERSET_VERSION   = "4"
OUTPUT_IMAGE_TAG   = "1.1"
CONTAINER_PORT     = "9990"
CELERY_FLOWER_PORT = "5555"
ARCH_TYPE          = "linux/amd64"
OUTPUT_DIR         = "testngo1"


# End


# Below Parameters are needed for superset.env


SUPERSET_ADMIN_USERNAME = "YYY"                   ⇐ Client GUI login name
SUPERSET_ADMIN_PASSWORD = "XXXX"                  ⇐ Client GUI password
SUPERSET_ADMIN_EMAIL    = "admin@ngo.org"         ⇐ Client mail
POSTGRES_USER           = "XXXX"                  ⇐ Postgres login
POSTGRES_PASSWORD       = "YYYYY"                 ⇐ Postgres password
APP_DB_USER             = "XXXXX_testngo1"        ⇐ Client user for app
APP_DB_PASS             = "testngo1"              ⇐ Client passwd for app
APP_DB_NAME             = "XXXXX_testngo1"        ⇐ Client database
ENABLE_OAUTH            = ""                      ⇐ Empty as of now


# End


# Below Parameters required for aws resource creation


alb_name      = "rails-alb-1  "             ⇐ Load Balancer name
cur_vpc       = "vpc-XXXXXXXXXXXXXXXXX"     ⇐ Current VPC Name
appli_ec2     = "i-YYYYYYYYYYYYYYYYY"       ⇐ ec2 instance on aws
neworg_port   = 9990                        ⇐ Container port for the new organization
neworg_name   = "mydemongo2.dalgo.in"       ⇐ Domain name for the new organization
rule_priority = 100                         ⇐ Priority for the load balancer rule (1-50000)
# End

The rule_priority parameter defines the priority for the load balancer rule (values between 1-50000).
If not specified, it defaults to 200. Each rule must have a unique priority number, with higher 
numbers having lower precedence. It is recommended to use values with gaps (e.g., 100, 200, 300) 
to allow for inserting rules in between if needed later.

PORT SYNCHRONIZATION
===================
The script has been enhanced to automatically synchronize the port between the Docker container and the AWS target group.
If the generate-make-client.sh script finds that the initially requested port (from CONTAINER_PORT) is already
in use, it will automatically find an available port and update the docker-compose.yml file.

The Terraform script now handles this potential port change in two phases:
1. First, it creates the AWS target group with the port specified in the tfvars file (neworg_port)
2. After the container is running, it extracts the actual port from docker-compose.yml by:
   - Parsing the docker-compose.yml file for port mappings
   - If not found, checking running Docker containers
   - If still not found, falling back to the CONTAINER_PORT value
3. If the actual port differs from the configured port, it registers a new target with the actual port
   in the existing target group, so traffic is correctly routed

This approach ensures that the AWS load balancer always forwards traffic to the correct port that the
container is actually using, even when port conflicts occur, while also avoiding Terraform plan/apply
errors related to unknown values in for_each.

MULTIPLE CLIENT DEPLOYMENTS
===========================
The script is designed to support multiple client deployments by using unique identifiers. Each deployment:

1. Uses a unique identifier combining CLIENT_NAME and port to ensure resource names don't conflict
2. Stores port information in client-specific files
3. Uses stable triggers based on client configuration rather than timestamps to prevent unnecessary recreations

To create multiple clients, you need to:
1. Create separate terraform.tfvars files for each client (e.g., client1.tfvars, client2.tfvars)
2. Run terraform with the specific vars file:
   terraform apply -var-file=client1.tfvars
   terraform apply -var-file=client2.tfvars

Note that Terraform's default behavior is to manage all resources in the state file. If you need to 
destroy a specific client's resources, you'll need to use the appropriate var file:
terraform destroy -var-file=client1.tfvars

Make sure the neworg_port entry matches the CONTAINER_PORT entry as an initial value, but the script 
will handle any port changes automatically if needed.

Prerequisite / Execution Environment
================================
Unlike bash and python3 , which are usually installed on the system by default.
Terraform you have to manually install with aws credentials, both are must, because terraform uses aws api's as part of resource creation on aws infrastructure in your account. 


provider "aws" {
  region     = "ap-south-1"
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
  token      = var.aws_session_token
}




1. Create a fresh directory and copy four files, terraform.tfvars.example, variables.tf, main.tf and neworg.json
This is available in platform_infra/Tf4aws directory.
2. Copy terraform.tf.example into terraform.tfvars.
3. Copy your public key on ec2 machine for passwordless ssh execution.
4. Make sure "git"  is available on the local machine.
5. Make sure "psql" command executable from the given remote application server to aws RDS instance.
6. Make sure terraform and aws configured on the local machine.
7. Make sure proper aws credentials, if not configure with "aws configure".
8. Verify it's configured properly with command "aws sts get-caller-identity".
9. Before executing the terraform command, make sure to export all three environment variables in the shell. ( viz. $AWS_ACCESS_KEY_ID",","$AWS_SECRET_ACCESS_KEY","$AWS_SESSION_TOKEN"  )
10. There are three options we generally use with terraform, ( plan, apply, delete ).
11. terraform plan , shows action on resources  in aws infrastructure account which you have configured as part of "aws configure".
12. terraform apply, will create resources as mentioned in "main.tf".
13. terraform destroy, will delete resources mentioned in "main.tf".


To launch the superset application and configure aws automatically, use below command.
        
        $ terraform init ; terraform fmt ; terraform validate


$ terraform apply --auto-approve -var "aws_access_key=$AWS_ACCESS_KEY_ID" -var "aws_secret_key=$AWS_SECRET_ACCESS_KEY" -var "aws_session_token=$AWS_SESSION_TOKEN"



