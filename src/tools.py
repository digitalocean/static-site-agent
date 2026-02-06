"""
Tools for the Static Site Agent.
"""
import os
import shutil
import tempfile
import json
import subprocess
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from langchain_core.tools import tool
from pydantic import BaseModel

# Setup logger
logger = logging.getLogger("static-site-agent")


class SiteGenerationResult(BaseModel):
    """Result of static site generation"""
    success: bool
    site_path: str
    message: str
    files_created: list[str] = []


class ContainerizationResult(BaseModel):
    """Result of containerization"""
    success: bool
    image_name: str
    message: str
    dockerfile_path: Optional[str] = None


class SpacesDeploymentResult(BaseModel):
    """Result of deployment to DigitalOcean Spaces"""
    success: bool
    bucket: Optional[str] = None
    region: Optional[str] = None
    index_url: Optional[str] = None
    cdn_url: Optional[str] = None
    message: str


class ListSpacesBucketsResult(BaseModel):
    """Result of listing DigitalOcean Spaces buckets"""
    success: bool
    buckets: list[str] = []
    region: Optional[str] = None
    message: str


class DownloadSiteFromSpacesResult(BaseModel):
    """Result of downloading a site from a Space to local disk"""
    success: bool
    site_path: str
    bucket: Optional[str] = None
    files_downloaded: list[str] = []
    message: str


class DeleteSpacesBucketResult(BaseModel):
    """Result of deleting a DigitalOcean Spaces bucket (site)"""
    success: bool
    bucket: Optional[str] = None
    message: str


@tool
def generate_static_site(site_type: str, style_hints: Optional[str] = None, site_name: Optional[str] = "mysite") -> SiteGenerationResult:
    """
    Generate a static website based on user requirements.
    
    Args:
        site_type: Type of site to generate (e.g., "portfolio", "blog", "landing page", "business")
        style_hints: Optional style preferences (e.g., "modern and minimalist", "colorful and playful", "professional")
        site_name: Name for the site directory (default: "mysite")
    
    Returns:
        SiteGenerationResult with success status, path, and details
    """
    logger.info(f"Generating {site_type} site with name '{site_name}'")
    logger.info(f"Style hints: {style_hints or 'None'}")
    
    try:
        # Create a temporary directory for the site
        tmp_dir = tempfile.mkdtemp(prefix=f"static-site-{site_name}-")
        site_path = os.path.join(tmp_dir, site_name)
        os.makedirs(site_path, exist_ok=True)
        
        # Generate HTML content based on site type and style
        html_content = _generate_html_content(site_type, style_hints, site_name)
        css_content = _generate_css_content(site_type, style_hints)
        
        # Create files
        files_created = []
        
        # Create index.html
        index_path = os.path.join(site_path, "index.html")
        with open(index_path, "w") as f:
            f.write(html_content)
        files_created.append("index.html")
        
        # Create styles.css
        css_path = os.path.join(site_path, "styles.css")
        with open(css_path, "w") as f:
            f.write(css_content)
        files_created.append("styles.css")
        
        # Create nginx config for serving
        nginx_config = """server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;
    
    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""
        nginx_path = os.path.join(site_path, "nginx.conf")
        with open(nginx_path, "w") as f:
            f.write(nginx_config)
        files_created.append("nginx.conf")
        
        logger.info(f"✓ Successfully generated site at: {site_path}")
        logger.info(f"✓ Files created: {', '.join(files_created)}")
        
        return SiteGenerationResult(
            success=True,
            site_path=site_path,
            message=f"Successfully generated {site_type} site at {site_path}",
            files_created=files_created
        )
        
    except Exception as e:
        return SiteGenerationResult(
            success=False,
            site_path="",
            message=f"Error generating site: {str(e)}",
            files_created=[]
        )


@tool
def containerize_site(site_path: str, image_name: Optional[str] = "static-site") -> ContainerizationResult:
    """
    Create a Docker container for the static site.
    
    Args:
        site_path: Path to the generated static site directory
        image_name: Name for the Docker image (default: "static-site")
    
    Returns:
        ContainerizationResult with success status and details
    """
    logger.info(f"Containerizing site at: {site_path}")
    logger.info(f"Docker image name: {image_name}")
    
    try:
        if not os.path.exists(site_path):
            return ContainerizationResult(
                success=False,
                image_name="",
                message=f"Site path {site_path} does not exist"
            )
        
        # Create Dockerfile
        dockerfile_content = """FROM nginx:alpine

# Copy site files
COPY . /usr/share/nginx/html/

# Copy nginx config if exists
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
"""
        
        dockerfile_path = os.path.join(site_path, "Dockerfile")
        with open(dockerfile_path, "w") as f:
            f.write(dockerfile_content)
        
        logger.info(f"✓ Dockerfile created at: {dockerfile_path}")
        logger.info("Building Docker image...")
        
        # Build Docker image
        try:
            result = subprocess.run(
                ["docker", "build", "-t", image_name, site_path],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"✗ Docker build failed: {result.stderr}")
                return ContainerizationResult(
                    success=False,
                    image_name="",
                    message=f"Docker build failed: {result.stderr}",
                    dockerfile_path=dockerfile_path
                )
            
            logger.info(f"✓ Docker image '{image_name}' built successfully")
            
            return ContainerizationResult(
                success=True,
                image_name=image_name,
                message=f"Successfully built Docker image '{image_name}'",
                dockerfile_path=dockerfile_path
            )
            
        except subprocess.TimeoutExpired:
            return ContainerizationResult(
                success=False,
                image_name="",
                message="Docker build timed out after 5 minutes"
            )
        except FileNotFoundError:
            return ContainerizationResult(
                success=False,
                image_name="",
                message="Docker not found. Please ensure Docker is installed and running."
            )
            
    except Exception as e:
        return ContainerizationResult(
            success=False,
            image_name="",
            message=f"Error containerizing site: {str(e)}"
        )


# File extensions to upload to Spaces (static site assets only; skip nginx.conf, Dockerfile)
_SPACES_UPLOAD_EXTENSIONS = {".html", ".css", ".js", ".json", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".eot", ".txt", ".xml", ".webmanifest"}
# MIME types for common static assets
_SPACES_CONTENT_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".eot": "application/vnd.ms-fontobject",
    ".txt": "text/plain",
    ".xml": "application/xml",
    ".webmanifest": "application/manifest+json",
}


def _spaces_bucket_exists(client, bucket_name: str) -> bool:
    """Return True if the bucket exists and we have access to it."""
    try:
        client.head_bucket(Bucket=bucket_name)
        return True
    except Exception as e:
        resp = getattr(e, "response", None)
        if isinstance(resp, dict):
            code = (resp.get("Error") or {}).get("Code") if isinstance(resp.get("Error"), dict) else None
            if code in ("404", "NoSuchBucket"):
                return False
        raise


def _spaces_retry(fn, *args, max_attempts: int = 3, **kwargs):
    """Call fn(*args, **kwargs) with retries on 403/503/500 (rate limit or transient errors)."""
    from botocore.exceptions import ClientError
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except ClientError as e:
            last_err = e
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in ("AccessDenied", "403") or status in (403, 500, 503):
                if attempt < max_attempts - 1:
                    delay = (attempt + 1) * 2
                    logger.warning(f"Spaces request failed ({code or status}), retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise
            else:
                raise
    if last_err:
        raise last_err


def _spaces_set_bucket_public_policy(client, bucket_name: str) -> bool:
    """Set a bucket policy so all objects are publicly readable. Returns True if set."""
    try:
        policy = json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            }]
        })
        client.put_bucket_policy(Bucket=bucket_name, Policy=policy)
        logger.info(f"✓ Set bucket policy for public read on {bucket_name}")
        return True
    except Exception as e:
        logger.warning(f"Could not set bucket policy: {e}")
        return False


@tool
def deploy_to_spaces(
    site_path: str,
    bucket_name: str,
    region: str = "nyc3",
    spaces_access_key: Optional[str] = None,
    spaces_secret_key: Optional[str] = None,
    make_public: bool = True,
    create_bucket_if_missing: bool = True,
) -> SpacesDeploymentResult:
    """
    Upload the static site files to a DigitalOcean Space (S3-compatible). This actually
    saves the site to the user's Space so it can be served publicly. If the bucket
    does not exist and create_bucket_if_missing is True, the bucket is created first.

    Args:
        site_path: Path to the generated static site directory (from generate_static_site).
        bucket_name: Name of the DigitalOcean Space (bucket) to upload to. 3-63 chars, lowercase letters/numbers/dashes, must start with letter or number. Created automatically if missing and create_bucket_if_missing is True.
        region: Spaces region (e.g. nyc3, sfo3, ams3). Default nyc3.
        spaces_access_key: Spaces S3-compatible access key (optional; uses SPACES_ACCESS_KEY_ID env if not set).
        spaces_secret_key: Spaces S3-compatible secret key (optional; uses SPACES_SECRET_ACCESS_KEY env if not set).
        make_public: If True, set object ACL to public-read so the site is viewable. Default True.
        create_bucket_if_missing: If True, create the Space (bucket) via the API when it does not exist. Default True.

    Returns:
        SpacesDeploymentResult with index_url and instructions.
    """
    logger.info(f"Deploying static site to Spaces bucket '{bucket_name}' in {region}")
    logger.info(f"Site path: {site_path}")

    try:
        if not spaces_access_key:
            spaces_access_key = os.getenv("SPACES_ACCESS_KEY_ID") or os.getenv("SPACES_KEY")
        if not spaces_secret_key:
            spaces_secret_key = os.getenv("SPACES_SECRET_ACCESS_KEY") or os.getenv("SPACES_SECRET")

        if not spaces_access_key or not spaces_secret_key:
            logger.error("✗ Spaces credentials not available")
            return SpacesDeploymentResult(
                success=False,
                message="Spaces credentials required. Set SPACES_ACCESS_KEY_ID and SPACES_SECRET_ACCESS_KEY (or SPACES_KEY / SPACES_SECRET), or pass them to this tool."
            )

        if not os.path.isdir(site_path):
            return SpacesDeploymentResult(
                success=False,
                message=f"Site path does not exist or is not a directory: {site_path}"
            )

        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError:
            return SpacesDeploymentResult(
                success=False,
                message="boto3 is required for Spaces deployment. Install with: pip install boto3"
            )

        endpoint_url = f"https://{region}.digitaloceanspaces.com"
        client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=spaces_access_key,
            aws_secret_access_key=spaces_secret_key,
            config=Config(signature_version="s3v4"),
        )

        # Create bucket if it doesn't exist and we're allowed to (with retry for rate limits)
        if not _spaces_bucket_exists(client, bucket_name):
            if create_bucket_if_missing:
                try:
                    _spaces_retry(lambda: client.create_bucket(Bucket=bucket_name))
                    logger.info(f"✓ Created Space (bucket) '{bucket_name}' in {region}")
                except ClientError as e:
                    code = e.response.get("Error", {}).get("Code", "")
                    if code == "BucketAlreadyExists":
                        # Another user owns a bucket with this name
                        return SpacesDeploymentResult(
                            success=False,
                            bucket=bucket_name,
                            region=region,
                            message=f"Bucket name '{bucket_name}' is already taken by another account. Choose a different bucket name (globally unique across DigitalOcean Spaces)."
                        )
                    if code == "InvalidBucketName":
                        return SpacesDeploymentResult(
                            success=False,
                            bucket=bucket_name,
                            region=region,
                            message="Invalid bucket name. Use 3-63 characters: lowercase letters, numbers, dashes only; must start with a letter or number."
                        )
                    return SpacesDeploymentResult(
                        success=False,
                        bucket=bucket_name,
                        region=region,
                        message=f"Failed to create bucket: {e.response.get('Error', {}).get('Message', str(e))}"
                    )
            else:
                return SpacesDeploymentResult(
                    success=False,
                    bucket=bucket_name,
                    region=region,
                    message=f"Bucket '{bucket_name}' does not exist. Create it in the DigitalOcean control panel (Spaces), or set create_bucket_if_missing=True to create it via the API."
                )

        # Collect and upload only static web files (retry on rate limit; fallback to no-ACL + bucket policy if AccessDenied)
        files_to_upload = []
        site_path_abs = os.path.abspath(site_path)
        for root, _dirs, files in os.walk(site_path_abs):
            for name in files:
                path = os.path.join(root, name)
                rel = os.path.relpath(path, site_path_abs)
                ext = os.path.splitext(name)[1].lower()
                if ext not in _SPACES_UPLOAD_EXTENSIONS:
                    logger.debug(f"Skipping non-web file: {rel}")
                    continue
                key = rel.replace("\\", "/")
                content_type = _SPACES_CONTENT_TYPES.get(ext, "application/octet-stream")
                files_to_upload.append((path, key, content_type))

        uploaded = []
        use_acl = make_public
        for path, key, content_type in files_to_upload:
            extra = {"ContentType": content_type}
            if use_acl:
                extra["ACL"] = "public-read"
            try:
                _spaces_retry(
                    lambda p=path, k=key, e=extra: client.upload_file(p, bucket_name, k, ExtraArgs=e)
                )
                uploaded.append(key)
                logger.info(f"  Uploaded: {key}")
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code == "AccessDenied" and use_acl:
                    # Some Spaces buckets disallow object ACLs; upload without ACL and use bucket policy
                    logger.warning("Upload with ACL failed (AccessDenied), retrying without ACL...")
                    use_acl = False
                    extra_no_acl = {"ContentType": content_type}
                    _spaces_retry(
                        lambda p=path, k=key, e=extra_no_acl: client.upload_file(p, bucket_name, k, ExtraArgs=e)
                    )
                    uploaded.append(key)
                    logger.info(f"  Uploaded: {key} (no ACL)")
                else:
                    raise

        if make_public and not use_acl and uploaded:
            _spaces_set_bucket_public_policy(client, bucket_name)

        if not uploaded:
            return SpacesDeploymentResult(
                success=False,
                bucket=bucket_name,
                region=region,
                message="No static web files found to upload (expected at least index.html, styles.css)."
            )

        # Public URL: bucket and region form the host
        base_url = f"https://{bucket_name}.{region}.digitaloceanspaces.com"
        index_url = f"{base_url}/index.html"
        cdn_url = f"https://{bucket_name}.{region}.cdn.digitaloceanspaces.com"

        logger.info(f"✓ Uploaded {len(uploaded)} file(s) to Space '{bucket_name}'")
        logger.info(f"  Index URL: {index_url}")

        return SpacesDeploymentResult(
            success=True,
            bucket=bucket_name,
            region=region,
            index_url=index_url,
            cdn_url=cdn_url,
            message=f"""Successfully uploaded the static site to your DigitalOcean Space.

- Bucket: {bucket_name} (region: {region})
- Files uploaded: {', '.join(uploaded)}
- View your site: {index_url}
- CDN URL (if CDN is enabled on the Space): {cdn_url}/index.html

Note: Spaces does not support default index documents. Use the index URL above, or enable the Space CDN and optionally add a custom domain in the DigitalOcean control panel."""
        )
    except Exception as e:
        logger.error(f"✗ Spaces deployment failed: {str(e)}", exc_info=True)
        return SpacesDeploymentResult(
            success=False,
            bucket=bucket_name,
            region=region,
            message=f"Failed to deploy to Spaces: {str(e)}"
        )


@tool
def list_spaces_buckets(
    region: str = "nyc3",
    spaces_access_key: Optional[str] = None,
    spaces_secret_key: Optional[str] = None,
) -> ListSpacesBucketsResult:
    """
    List all DigitalOcean Spaces buckets (static sites) in this account.
    Use this when the user wants to see their existing sites or pick a site to edit.

    Args:
        region: Spaces region used for the API (e.g. nyc3, sfo3, ams3). Default nyc3.
        spaces_access_key: Optional; uses SPACES_ACCESS_KEY_ID or SPACES_KEY env if not set.
        spaces_secret_key: Optional; uses SPACES_SECRET_ACCESS_KEY or SPACES_SECRET env if not set.

    Returns:
        ListSpacesBucketsResult with list of bucket names and region.
    """
    logger.info(f"Listing Spaces buckets in region {region}")
    try:
        if not spaces_access_key:
            spaces_access_key = os.getenv("SPACES_ACCESS_KEY_ID") or os.getenv("SPACES_KEY")
        if not spaces_secret_key:
            spaces_secret_key = os.getenv("SPACES_SECRET_ACCESS_KEY") or os.getenv("SPACES_SECRET")
        if not spaces_access_key or not spaces_secret_key:
            return ListSpacesBucketsResult(
                success=False,
                message="Spaces credentials required. Set SPACES_ACCESS_KEY_ID and SPACES_SECRET_ACCESS_KEY (or SPACES_KEY / SPACES_SECRET).",
            )
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            return ListSpacesBucketsResult(
                success=False,
                message="boto3 is required. Install with: pip install boto3",
            )
        endpoint_url = f"https://{region}.digitaloceanspaces.com"
        client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=spaces_access_key,
            aws_secret_access_key=spaces_secret_key,
            config=Config(signature_version="s3v4"),
        )
        response = _spaces_retry(client.list_buckets)
        buckets = [b["Name"] for b in response.get("Buckets", [])]
        logger.info(f"✓ Found {len(buckets)} bucket(s): {buckets}")
        # Include view URL for each bucket so the chat UI can show clickable links
        base_urls = [
            f"https://{name}.{region}.digitaloceanspaces.com/index.html"
            for name in buckets
        ]
        lines = [f"{name}: {url}" for name, url in zip(buckets, base_urls)] if buckets else ["none"]
        message = "Found {} Space(s):\n".format(len(buckets)) + "\n".join(lines)
        return ListSpacesBucketsResult(
            success=True,
            buckets=buckets,
            region=region,
            message=message,
        )
    except Exception as e:
        logger.error(f"Failed to list Spaces buckets: {e}", exc_info=True)
        return ListSpacesBucketsResult(
            success=False,
            message=f"Failed to list buckets: {str(e)}",
        )


@tool
def download_site_from_spaces(
    bucket_name: str,
    region: str = "nyc3",
    spaces_access_key: Optional[str] = None,
    spaces_secret_key: Optional[str] = None,
) -> DownloadSiteFromSpacesResult:
    """
    Download a static site from a DigitalOcean Space (bucket) to a local directory
    so it can be edited. Use this when the user wants to edit an existing site:
    first list sites with list_spaces_buckets, then download the chosen bucket with
    this tool, then use read_file/write_file to edit, then deploy_to_spaces to save back.

    Args:
        bucket_name: Name of the Space (bucket) to download from.
        region: Spaces region (e.g. nyc3, sfo3, ams3). Default nyc3.
        spaces_access_key: Optional; uses env if not set.
        spaces_secret_key: Optional; uses env if not set.

    Returns:
        DownloadSiteFromSpacesResult with site_path (use this path for read_file, write_file, and deploy_to_spaces).
    """
    logger.info(f"Downloading site from Space '{bucket_name}' in {region}")
    try:
        if not spaces_access_key:
            spaces_access_key = os.getenv("SPACES_ACCESS_KEY_ID") or os.getenv("SPACES_KEY")
        if not spaces_secret_key:
            spaces_secret_key = os.getenv("SPACES_SECRET_ACCESS_KEY") or os.getenv("SPACES_SECRET")
        if not spaces_access_key or not spaces_secret_key:
            return DownloadSiteFromSpacesResult(
                success=False,
                site_path="",
                message="Spaces credentials required.",
            )
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError:
            return DownloadSiteFromSpacesResult(
                success=False,
                site_path="",
                message="boto3 is required. Install with: pip install boto3",
            )
        endpoint_url = f"https://{region}.digitaloceanspaces.com"
        client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=spaces_access_key,
            aws_secret_access_key=spaces_secret_key,
            config=Config(signature_version="s3v4"),
        )
        if not _spaces_bucket_exists(client, bucket_name):
            return DownloadSiteFromSpacesResult(
                success=False,
                site_path="",
                bucket=bucket_name,
                message=f"Bucket '{bucket_name}' does not exist or is not accessible.",
            )
        tmp_dir = tempfile.mkdtemp(prefix=f"spaces-download-{bucket_name}-")
        downloaded = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket_name):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                local_path = os.path.join(tmp_dir, key)
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                _spaces_retry(client.download_file, bucket_name, key, local_path)
                downloaded.append(key)
        if not downloaded:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return DownloadSiteFromSpacesResult(
                success=False,
                site_path="",
                bucket=bucket_name,
                message=f"Bucket '{bucket_name}' is empty; no files to download.",
            )
        logger.info(f"✓ Downloaded {len(downloaded)} file(s) to {tmp_dir}")
        return DownloadSiteFromSpacesResult(
            success=True,
            site_path=tmp_dir,
            bucket=bucket_name,
            files_downloaded=downloaded,
            message=f"Downloaded {len(downloaded)} file(s) to {tmp_dir}. Use this path for read_file, write_file, and deploy_to_spaces.",
        )
    except Exception as e:
        logger.error(f"Failed to download from Spaces: {e}", exc_info=True)
        return DownloadSiteFromSpacesResult(
            success=False,
            site_path="",
            bucket=bucket_name,
            message=f"Failed to download: {str(e)}",
        )


@tool
def delete_site_from_spaces(
    bucket_name: str,
    region: str = "nyc3",
    spaces_access_key: Optional[str] = None,
    spaces_secret_key: Optional[str] = None,
) -> DeleteSpacesBucketResult:
    """
    Permanently delete a static site (DigitalOcean Space/bucket) by name.
    This removes all objects in the bucket and then deletes the bucket. Use when the user
    asks to delete or remove a site. Confirm the bucket name with list_spaces_buckets if needed.

    Args:
        bucket_name: Name of the Space (bucket) to delete.
        region: Spaces region (e.g. nyc3, sfo3, ams3). Default nyc3.
        spaces_access_key: Optional; uses env if not set.
        spaces_secret_key: Optional; uses env if not set.

    Returns:
        DeleteSpacesBucketResult with success status and message.
    """
    logger.info(f"Deleting Space (bucket) '{bucket_name}' in {region}")
    try:
        if not spaces_access_key:
            spaces_access_key = os.getenv("SPACES_ACCESS_KEY_ID") or os.getenv("SPACES_KEY")
        if not spaces_secret_key:
            spaces_secret_key = os.getenv("SPACES_SECRET_ACCESS_KEY") or os.getenv("SPACES_SECRET")
        if not spaces_access_key or not spaces_secret_key:
            return DeleteSpacesBucketResult(
                success=False,
                bucket=bucket_name,
                message="Spaces credentials required.",
            )
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError
        except ImportError:
            return DeleteSpacesBucketResult(
                success=False,
                bucket=bucket_name,
                message="boto3 is required. Install with: pip install boto3",
            )
        endpoint_url = f"https://{region}.digitaloceanspaces.com"
        client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=endpoint_url,
            aws_access_key_id=spaces_access_key,
            aws_secret_access_key=spaces_secret_key,
            config=Config(signature_version="s3v4"),
        )
        if not _spaces_bucket_exists(client, bucket_name):
            return DeleteSpacesBucketResult(
                success=False,
                bucket=bucket_name,
                message=f"Bucket '{bucket_name}' does not exist or is not accessible.",
            )
        # Delete all objects (Spaces/S3 require empty bucket before delete_bucket)
        paginator = client.get_paginator("list_objects_v2")
        deleted_count = 0
        for page in paginator.paginate(Bucket=bucket_name):
            contents = page.get("Contents", [])
            if not contents:
                continue
            keys = [{"Key": obj["Key"]} for obj in contents]
            _spaces_retry(client.delete_objects, Bucket=bucket_name, Delete={"Objects": keys})
            deleted_count += len(keys)
        # Delete the bucket
        _spaces_retry(client.delete_bucket, Bucket=bucket_name)
        logger.info(f"✓ Deleted bucket '{bucket_name}' ({deleted_count} object(s) removed)")
        return DeleteSpacesBucketResult(
            success=True,
            bucket=bucket_name,
            message=f"Successfully deleted site (bucket) '{bucket_name}' and removed {deleted_count} file(s).",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", str(e))
        logger.error(f"Failed to delete bucket: {e}", exc_info=True)
        return DeleteSpacesBucketResult(
            success=False,
            bucket=bucket_name,
            message=f"Failed to delete bucket: {code or msg}",
        )
    except Exception as e:
        logger.error(f"Failed to delete bucket: {e}", exc_info=True)
        return DeleteSpacesBucketResult(
            success=False,
            bucket=bucket_name,
            message=f"Failed to delete bucket: {str(e)}",
        )


def _resolve_site_path(path: str) -> Optional[str]:
    """Resolve path to a real path; allow only under temp dir for safety."""
    try:
        real = os.path.realpath(os.path.abspath(path))
        tmp = os.path.realpath(tempfile.gettempdir())
        if real == tmp or real.startswith(tmp + os.sep):
            return real
    except Exception:
        pass
    return None


@tool
def read_file(file_path: str) -> str:
    """
    Read the contents of a file. Use for editing a site: after download_site_from_spaces,
    read index.html or styles.css with this tool, then modify and write back with write_file.
    Only files under the system temp directory (e.g. downloaded or generated sites) can be read.

    Args:
        file_path: Full path to the file (e.g. site_path + '/index.html' from download_site_from_spaces).

    Returns:
        File contents as a string, or an error message.
    """
    try:
        resolved = _resolve_site_path(file_path)
        if not resolved or not os.path.isfile(resolved):
            return f"Error: path not allowed or not a file: {file_path}"
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"


@tool
def write_file(file_path: str, content: str) -> str:
    """
    Write content to a file. Use after editing: write the modified HTML or CSS back,
    then call deploy_to_spaces(site_path, bucket_name) to save the site back to the bucket.
    Only paths under the system temp directory (downloaded or generated sites) can be written.

    Args:
        file_path: Full path to the file (e.g. site_path + '/index.html').
        content: New file content (string).

    Returns:
        Success or error message.
    """
    try:
        resolved = _resolve_site_path(file_path)
        if not resolved:
            return f"Error: path not allowed: {file_path}"
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote {resolved}"
    except Exception as e:
        return f"Error writing file: {str(e)}"


def _generate_html_content(site_type: str, style_hints: Optional[str], site_name: str) -> str:
    """Generate HTML content based on site type and style hints"""
    
    # Base templates for different site types
    templates = {
        "portfolio": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{site_name} - Portfolio</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header>
        <nav>
            <h1>{site_name}</h1>
            <ul>
                <li><a href="#about">About</a></li>
                <li><a href="#projects">Projects</a></li>
                <li><a href="#contact">Contact</a></li>
            </ul>
        </nav>
    </header>
    
    <main>
        <section id="hero">
            <h2>Welcome to My Portfolio</h2>
            <p>Creative professional showcasing my best work</p>
        </section>
        
        <section id="about">
            <h2>About Me</h2>
            <p>I'm a passionate creator with a love for building amazing things.</p>
        </section>
        
        <section id="projects">
            <h2>My Projects</h2>
            <div class="project-grid">
                <div class="project-card">
                    <h3>Project One</h3>
                    <p>A fantastic project that showcases my skills.</p>
                </div>
                <div class="project-card">
                    <h3>Project Two</h3>
                    <p>Another amazing project with great results.</p>
                </div>
                <div class="project-card">
                    <h3>Project Three</h3>
                    <p>Yet another successful project completed.</p>
                </div>
            </div>
        </section>
        
        <section id="contact">
            <h2>Get In Touch</h2>
            <p>Email: hello@{site_name}.com</p>
        </section>
    </main>
    
    <footer>
        <p>&copy; 2026 {site_name}. All rights reserved.</p>
    </footer>
</body>
</html>""",
        
        "landing": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{site_name}</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header>
        <nav>
            <h1>{site_name}</h1>
            <a href="#signup" class="cta-button">Get Started</a>
        </nav>
    </header>
    
    <main>
        <section id="hero">
            <h2>Transform Your Business Today</h2>
            <p>The best solution for modern businesses</p>
            <a href="#signup" class="cta-button">Sign Up Now</a>
        </section>
        
        <section id="features">
            <h2>Why Choose Us</h2>
            <div class="feature-grid">
                <div class="feature">
                    <h3>Fast</h3>
                    <p>Lightning-fast performance</p>
                </div>
                <div class="feature">
                    <h3>Reliable</h3>
                    <p>99.9% uptime guarantee</p>
                </div>
                <div class="feature">
                    <h3>Secure</h3>
                    <p>Enterprise-grade security</p>
                </div>
            </div>
        </section>
        
        <section id="signup">
            <h2>Ready to Get Started?</h2>
            <p>Join thousands of satisfied customers today!</p>
            <form>
                <input type="email" placeholder="Enter your email">
                <button type="submit">Sign Up</button>
            </form>
        </section>
    </main>
    
    <footer>
        <p>&copy; 2026 {site_name}. All rights reserved.</p>
    </footer>
</body>
</html>""",
        
        "blog": """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{site_name} Blog</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header>
        <nav>
            <h1>{site_name}</h1>
            <ul>
                <li><a href="#home">Home</a></li>
                <li><a href="#posts">Posts</a></li>
                <li><a href="#about">About</a></li>
            </ul>
        </nav>
    </header>
    
    <main>
        <section id="hero">
            <h2>Welcome to {site_name}</h2>
            <p>Thoughts, stories, and ideas</p>
        </section>
        
        <section id="posts">
            <article class="blog-post">
                <h3>Getting Started with Web Development</h3>
                <p class="post-meta">January 22, 2026</p>
                <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit...</p>
                <a href="#" class="read-more">Read More</a>
            </article>
            
            <article class="blog-post">
                <h3>The Future of Technology</h3>
                <p class="post-meta">January 20, 2026</p>
                <p>Sed do eiusmod tempor incididunt ut labore et dolore magna...</p>
                <a href="#" class="read-more">Read More</a>
            </article>
            
            <article class="blog-post">
                <h3>Best Practices for Modern Development</h3>
                <p class="post-meta">January 18, 2026</p>
                <p>Ut enim ad minim veniam, quis nostrud exercitation ullamco...</p>
                <a href="#" class="read-more">Read More</a>
            </article>
        </section>
    </main>
    
    <footer>
        <p>&copy; 2026 {site_name}. All rights reserved.</p>
    </footer>
</body>
</html>"""
    }
    
    # Default to landing page if type not found
    template = templates.get(site_type.lower(), templates["landing"])
    return template.format(site_name=site_name)


def _generate_css_content(site_type: str, style_hints: Optional[str]) -> str:
    """Generate CSS content based on site type and style hints"""
    
    # Determine color scheme based on style hints
    if style_hints:
        hints_lower = style_hints.lower()
        if "dark" in hints_lower or "modern" in hints_lower:
            primary_color = "#2563eb"
            bg_color = "#0f172a"
            text_color = "#f1f5f9"
            card_bg = "#1e293b"
        elif "colorful" in hints_lower or "playful" in hints_lower:
            primary_color = "#ec4899"
            bg_color = "#fef3c7"
            text_color = "#1f2937"
            card_bg = "#ffffff"
        elif "professional" in hints_lower or "business" in hints_lower:
            primary_color = "#0369a1"
            bg_color = "#ffffff"
            text_color = "#1f2937"
            card_bg = "#f8fafc"
        else:
            primary_color = "#3b82f6"
            bg_color = "#ffffff"
            text_color = "#1f2937"
            card_bg = "#f9fafb"
    else:
        primary_color = "#3b82f6"
        bg_color = "#ffffff"
        text_color = "#1f2937"
        card_bg = "#f9fafb"
    
    css = f"""* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
    line-height: 1.6;
    color: {text_color};
    background-color: {bg_color};
}}

header {{
    background-color: {card_bg};
    padding: 1rem 2rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}}

nav {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    max-width: 1200px;
    margin: 0 auto;
}}

nav h1 {{
    color: {primary_color};
    font-size: 1.5rem;
}}

nav ul {{
    display: flex;
    list-style: none;
    gap: 2rem;
}}

nav a {{
    color: {text_color};
    text-decoration: none;
    transition: color 0.3s;
}}

nav a:hover {{
    color: {primary_color};
}}

main {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}}

section {{
    margin: 4rem 0;
}}

#hero {{
    text-align: center;
    padding: 4rem 2rem;
}}

#hero h2 {{
    font-size: 3rem;
    color: {primary_color};
    margin-bottom: 1rem;
}}

#hero p {{
    font-size: 1.25rem;
    margin-bottom: 2rem;
}}

h2 {{
    font-size: 2rem;
    margin-bottom: 1.5rem;
    color: {primary_color};
}}

.cta-button {{
    display: inline-block;
    background-color: {primary_color};
    color: white;
    padding: 0.75rem 2rem;
    border-radius: 0.5rem;
    text-decoration: none;
    font-weight: 600;
    transition: transform 0.2s, box-shadow 0.2s;
}}

.cta-button:hover {{
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}}

.project-grid, .feature-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    gap: 2rem;
    margin-top: 2rem;
}}

.project-card, .feature {{
    background-color: {card_bg};
    padding: 2rem;
    border-radius: 0.5rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    transition: transform 0.2s;
}}

.project-card:hover, .feature:hover {{
    transform: translateY(-4px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}}

.project-card h3, .feature h3 {{
    color: {primary_color};
    margin-bottom: 0.5rem;
}}

.blog-post {{
    background-color: {card_bg};
    padding: 2rem;
    border-radius: 0.5rem;
    margin-bottom: 2rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}}

.blog-post h3 {{
    color: {primary_color};
    margin-bottom: 0.5rem;
}}

.post-meta {{
    color: #6b7280;
    font-size: 0.875rem;
    margin-bottom: 1rem;
}}

.read-more {{
    color: {primary_color};
    text-decoration: none;
    font-weight: 600;
}}

.read-more:hover {{
    text-decoration: underline;
}}

form {{
    display: flex;
    gap: 1rem;
    max-width: 500px;
    margin: 2rem auto;
}}

input[type="email"] {{
    flex: 1;
    padding: 0.75rem;
    border: 2px solid #e5e7eb;
    border-radius: 0.5rem;
    font-size: 1rem;
}}

button[type="submit"] {{
    background-color: {primary_color};
    color: white;
    padding: 0.75rem 2rem;
    border: none;
    border-radius: 0.5rem;
    font-weight: 600;
    cursor: pointer;
    transition: transform 0.2s;
}}

button[type="submit"]:hover {{
    transform: translateY(-2px);
}}

footer {{
    background-color: {card_bg};
    text-align: center;
    padding: 2rem;
    margin-top: 4rem;
}}

@media (max-width: 768px) {{
    nav {{
        flex-direction: column;
        gap: 1rem;
    }}
    
    nav ul {{
        flex-direction: column;
        text-align: center;
        gap: 1rem;
    }}
    
    #hero h2 {{
        font-size: 2rem;
    }}
    
    form {{
        flex-direction: column;
    }}
}}
"""
    
    return css
