param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,
    [string]$Repository = "Tharunreddygtr/repo-architecture-explorer"
)

$BaseUrl = $BaseUrl.TrimEnd('/')
$WebhookUrl = "$BaseUrl/api/github/pr-webhook"
$Secret = Read-Host "Enter the same GITHUB_WEBHOOK_SECRET configured on the service"

if ([string]::IsNullOrWhiteSpace($Secret)) {
    throw "A webhook secret is required."
}

$Config = @{
    url          = $WebhookUrl
    content_type = "json"
    secret       = $Secret
    insecure_ssl = "0"
}

$Payload = @{
    name   = "web"
    active = $true
    events = @("pull_request")
    config = $Config
} | ConvertTo-Json -Depth 5

$Payload | gh api "repos/$Repository/hooks" --method POST --input -
Write-Host "Webhook created at $WebhookUrl"
