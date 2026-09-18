# Evidence clip storage -- the architecture table already promised S3 here, but
# the source PDF spec (agent-worker ECS/SQS/EFS only) never included it. Added
# for real parity with the GCP (google_storage_bucket) and Azure (Blob Storage
# container) environments, which both have their clip-storage resource from
# the start. 90-day lifecycle delete matches the GCP bucket's own policy.

resource "aws_s3_bucket" "incident_clips" {
  bucket = "${var.project_name}-incident-clips-${var.environment}"

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "incident_clips" {
  bucket = aws_s3_bucket.incident_clips.id

  rule {
    id     = "expire-after-90-days"
    status = "Enabled"

    # Provider warns (will be a hard error in a future version) without an
    # explicit filter/prefix -- caught by running validate, not by inspection.
    filter {}

    expiration {
      days = 90
    }
  }
}

resource "aws_s3_bucket_public_access_block" "incident_clips" {
  bucket = aws_s3_bucket.incident_clips.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
