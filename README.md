Image Storage Service (FastAPI + LocalStack)

This service stores images in S3 and their metadata in DynamoDB. It provides simple REST APIs to upload , list (with filters), download (stream), and delete images.

**Clone**
- `git clone <repo-url>`
- `cd image_storage_service`

**Prerequisites**
- Docker Desktop with `docker compose`
- AWS CLI v2 (`aws --version`)
- Windows PowerShell 
- Python 3.9+ (only needed to run tests locally)

**Start Services**
- `docker compose up -d --build`
- Verify LocalStack health: `Invoke-RestMethod http://127.0.0.1:4566/_localstack/health`

**Provision S3 + DynamoDB (LocalStack)**
- `powershell -ExecutionPolicy Bypass -File scripts/deploy_localstack.ps1`
- Verify:
  - `aws s3 ls --endpoint-url http://localhost:4566 --region us-east-1`
  - `aws dynamodb list-tables --endpoint-url http://localhost:4566 --region us-east-1`

**Open Swagger**
- `http://localhost:8000/docs`
- Endpoints:
  - Upload: `POST /images/upload-file`
    - Form fields: `user_id` (required), `file` (required JPG/PNG), `metadata` (JSON string, optional), `tags` (CSV, optional), `title`/`description` (optional)
  - List: `GET /images` with optional `user_id`, `tag`, `created_after`, `created_before`
  - Download: `GET /images/{image_id}/download` (streams file as attachment)
  - Delete: `DELETE /images/{image_id}`

**Run Unit Tests**
- `python -m venv .venv`
- `.venv\Scripts\Activate`
- `pip install -r requirements.txt`
- `pytest -q`


**Project Structure**
- `app/main.py` – FastAPI app entry
- `app/routers/images.py` – REST endpoints
- `app/aws/storage.py` – S3/DynamoDB logic
- `app/core/config.py` – settings/env
- `scripts/deploy_localstack.ps1` – LocalStack provisioning
- `tests/` – unit tests (moto-based; no LocalStack required)

