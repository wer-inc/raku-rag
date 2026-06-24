variable "region" {
  description = "AWS region to deploy the demo VM into."
  type        = string
  default     = "ap-northeast-1"
}

variable "instance_type" {
  description = "EC2 instance type. m6i.large (2 vCPU / 8 GB) comfortably runs PG + answer-service + API + web."
  type        = string
  default     = "m6i.large"
}

variable "root_volume_gb" {
  description = "Root EBS volume size (GB)."
  type        = number
  default     = 30
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH admin access."
  type        = string
}

variable "allow_ssh_cidr" {
  description = "CIDR allowed to SSH (port 22). Set to your office/VPN IP, e.g. 203.0.113.4/32."
  type        = string
}

variable "allow_http_cidrs" {
  description = "CIDRs allowed to reach the demo UI (port 80). Restrict to prospect/office IPs; default open."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "repo_url" {
  description = "HTTPS git URL of the raku-rag repo to clone on the VM."
  type        = string
  default     = "https://github.com/wer-inc/raku-rag.git"
}

variable "repo_branch" {
  description = "Branch to deploy."
  type        = string
  default     = "develop"
}

variable "github_token" {
  description = "Optional read-only PAT for cloning a PRIVATE repo on first boot (not persisted on the VM)."
  type        = string
  default     = ""
  sensitive   = true
}
