output "public_ip" {
  description = "Elastic IP of the demo VM."
  value       = aws_eip.demo.public_ip
}

output "public_url" {
  description = "Open this in a browser once provisioning finishes (~3-5 min after apply)."
  value       = "http://${aws_eip.demo.public_ip}/"
}

output "ssh" {
  description = "SSH command for admin/log access."
  value       = "ssh ubuntu@${aws_eip.demo.public_ip}"
}
