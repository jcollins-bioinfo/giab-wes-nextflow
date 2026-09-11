# Economical Explorer hosting

Separate state boundary, configured only. One Lightsail Container service, scale
one, with Nano or Micro selected from measured image memory requirements.
Fargate/ALB remain disabled. No domain, database, NAT or new DNS zone is created.
No runtime task role or scientific storage access is supplied to the app.

Before apply: verify the configured operator identity and private deployment approval; build
and audit the exact amd64 Explorer image; run the cgroup memory/concurrent HTTP
probe; inspect existing service, ECR policy, DNS and certificate state. Import
existing resources rather than overwriting drift. Inputs require the actual image
and measured peak, explicit first-month authorization and a renewal decision date.
Keep private tfvars, plans and state outside Git, with encrypted durable backup.

1. Initialize with the locked provider and review a saved plan in this directory.
2. Initially leave `validated_certificate_name` empty. Review the one-service cost
   and ECR image-pull principal policy before apply. This ECR policy must not replace
   an unexpected existing policy. Record the provider-generated URL and activation.
3. Verify HTTPS, root directory, full app path, POST callbacks, exports and separate
   synthetic/canonical readiness at that actual URL. Retain the previous image.
4. Only then request/validate a project Lightsail certificate and use its actual
   name here. Inspect authoritative DNS and preserve every existing record before
   giving the owner the exact generated validation/`apps` records for manual entry.
   Never modify DNS automatically.
5. Record an owner decision before the next month. Disabling a service is not a
   verified way to stop billing. To shut down, save the image/provenance, inspect
   `terraform plan -destroy`, then destroy **this state only**. Verify the named
   container service no longer exists with `aws lightsail get-container-services
   --service-name giab-wes-demo-explorer --profile giab-operator --region us-west-2`.
   This state does not contain scientific S3 buckets, results, or ECR images.

Shutdown commands are prepared, not live-tested: no service has been activated.
Storage, retained images and transfer overages can incur charges independently of
the base service. Enforce deployment limits through private configuration and monitoring.
