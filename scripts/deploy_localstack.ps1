Param(
    [string]$Region = $Env:AWS_REGION,
    [string]$Endpoint = $Env:AWS_ENDPOINT_URL,
    [string]$BucketName = $Env:BUCKET_NAME,
    [string]$TableName = $Env:TABLE_NAME
)

if (-not $Region) { $Region = 'us-east-1' }
if (-not $Endpoint) { $Endpoint = 'http://localhost:4566' }
if (-not $BucketName) { $BucketName = 'images-bucket' }
if (-not $TableName) { $TableName = 'Images' }

if (-not $Env:AWS_ACCESS_KEY_ID) { $Env:AWS_ACCESS_KEY_ID = 'test' }
if (-not $Env:AWS_SECRET_ACCESS_KEY) { $Env:AWS_SECRET_ACCESS_KEY = 'test' }

Write-Host "Ensure LocalStack resources (Region=$Region, Endpoint=$Endpoint)"

# Ensure S3 bucket exists
Write-Host "Ensuring S3 bucket '$BucketName'..."
aws s3 ls "s3://$BucketName" --endpoint-url $Endpoint --region $Region *> $null
if ($LASTEXITCODE -ne 0) {
    aws s3 mb "s3://$BucketName" --endpoint-url $Endpoint --region $Region | Out-Host
} else {
    Write-Host "Bucket already exists: $BucketName"
}

# Ensure DynamoDB table exists
Write-Host "Ensuring DynamoDB table '$TableName'..."
aws dynamodb describe-table --table-name $TableName --endpoint-url $Endpoint --region $Region *> $null
if ($LASTEXITCODE -ne 0) {
    $spec = [ordered]@{
        TableName = $TableName
        AttributeDefinitions = @(
            @{ AttributeName = 'image_id'; AttributeType = 'S' }
            @{ AttributeName = 'user_id'; AttributeType = 'S' }
            @{ AttributeName = 'created_at'; AttributeType = 'N' }
        )
        KeySchema = @(@{ AttributeName = 'image_id'; KeyType = 'HASH' })
        BillingMode = 'PAY_PER_REQUEST'
        GlobalSecondaryIndexes = @(
            @{ IndexName = 'by_user_created'
               KeySchema = @(
                   @{ AttributeName = 'user_id'; KeyType = 'HASH' }
                   @{ AttributeName = 'created_at'; KeyType = 'RANGE' }
               )
               Projection = @{ ProjectionType = 'ALL' }
            }
        )
    }

    $json = $spec | ConvertTo-Json -Depth 6
    $tmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), '.json')
    # Write UTF-8 without BOM to avoid AWS CLI JSON parsing issues on Windows PowerShell 5
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllBytes($tmp, $utf8NoBom.GetBytes($json))
    try {
        $uriPath = $tmp -replace '\\','/'
        aws dynamodb create-table --endpoint-url $Endpoint --region $Region --cli-input-json "file://$uriPath" | Out-Host
    }
    finally {
        Remove-Item -Path $tmp -ErrorAction SilentlyContinue
    }
} else {
    Write-Host "Table already exists: $TableName"
}

Write-Host "LocalStack resources ensured."
