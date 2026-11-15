# Sciclips

Automated science-video production and publishing for QuantaTale.

## Automated publishing

Sciclips renders and validates each video, then publishes through Buffer to the connected YouTube and TikTok channels. Video media is stored as a public GitHub Release asset so Buffer can fetch it. No Cloudinary account, URL, or secret is used.

The automatic GitHub Actions workflow requires `BUFFER_API_KEY` and, when channel IDs are not configured, can discover connected channels through Buffer. GitHub Actions supplies `GITHUB_TOKEN` and `GITHUB_REPOSITORY` for release-asset hosting; the workflow grants `contents: write` for this purpose.

Buffer's API requires a publicly accessible media URL. GitHub Release assets provide the public download URL passed to Buffer. A Buffer post being accepted is not the same as confirmed public publication; platform visibility must be checked separately.
