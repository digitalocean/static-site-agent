"""
Tools for the Static Site Agent.
"""
import os
import shutil
import tempfile
import json
import subprocess
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path
from langchain_core.tools import tool
from pydantic import BaseModel
import requests

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


class DeploymentResult(BaseModel):
    """Result of deployment to DigitalOcean"""
    success: bool
    app_url: Optional[str] = None
    app_id: Optional[str] = None
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


@tool
def deploy_to_digitalocean(
    site_path: str,
    app_name: str,
    do_api_key: Optional[str] = None,
    region: str = "nyc"
) -> DeploymentResult:
    """
    Deploy the containerized site to DigitalOcean App Platform.
    
    Args:
        site_path: Path to the site directory with Dockerfile
        app_name: Name for the DigitalOcean app
        do_api_key: DigitalOcean API key (optional, will use environment variable if not provided)
        region: DigitalOcean region (default: "nyc")
    
    Returns:
        DeploymentResult with success status, app URL, and details
    """
    logger.info(f"Deploying site to DigitalOcean App Platform")
    logger.info(f"App name: {app_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Site path: {site_path}")
    
    try:
        # Get API key from environment if not provided
        if not do_api_key:
            do_api_key = os.getenv('DIGITALOCEAN_API_KEY')
            logger.info("Using DigitalOcean API key from environment")
        
        if not do_api_key:
            logger.error("✗ No DigitalOcean API key available")
            return DeploymentResult(
                success=False,
                message="DigitalOcean API key is required. Please set DIGITALOCEAN_API_KEY environment variable or provide it directly."
            )
        
        # Create a DigitalOcean App Platform spec
        app_spec = {
            "name": app_name,
            "region": region,
            "services": [
                {
                    "name": "web",
                    "github": {
                        "repo": "",
                        "branch": "main",
                        "deploy_on_push": True
                    },
                    "dockerfile_path": "Dockerfile",
                    "source_dir": "/",
                    "http_port": 80,
                    "instance_count": 1,
                    "instance_size_slug": "basic-xxs",
                    "routes": [
                        {
                            "path": "/"
                        }
                    ]
                }
            ],
            "static_sites": [
                {
                    "name": app_name,
                    "build_command": "",
                    "source_dir": "/",
                    "output_dir": "/",
                    "index_document": "index.html",
                    "error_document": "index.html",
                    "routes": [
                        {
                            "path": "/"
                        }
                    ]
                }
            ]
        }
        
        # Note: For actual deployment, we would need to:
        # 1. Push the code to a git repository (GitHub, GitLab, etc.)
        # 2. Create the app on DigitalOcean using their API
        # 3. Link the repository to the app
        
        headers = {
            "Authorization": f"Bearer {do_api_key}",
            "Content-Type": "application/json"
        }
        
        # Actually create the app using DigitalOcean API
        logger.info("Creating app on DigitalOcean App Platform...")
        
        # For DigitalOcean App Platform, we'll use their static site feature
        # which can serve static files directly
        app_spec = {
            "name": app_name,
            "region": region,
            "static_sites": [
                {
                    "name": app_name,
                    "build_command": "",
                    "source_dir": "/",
                    "output_dir": "/",
                    "index_document": "index.html",
                    "error_document": "index.html",
                    "github": {
                        "repo": "",
                        "branch": "main",
                        "deploy_on_push": True
                    }
                }
            ]
        }
        
        try:
            response = requests.post(
                "https://api.digitalocean.com/v2/apps",
                headers=headers,
                json={"spec": app_spec},
                timeout=30
            )
            
            if response.status_code in [200, 201]:
                app_data = response.json()
                app_id = app_data.get("app", {}).get("id")
                app_url = app_data.get("app", {}).get("default_ingress", f"https://{app_name}.ondigitalocean.app")
                
                logger.info(f"✓ App created successfully!")
                logger.info(f"  App ID: {app_id}")
                logger.info(f"  App URL: {app_url}")
                
                return DeploymentResult(
                    success=True,
                    app_url=app_url,
                    app_id=app_id,
                    message=f"""Successfully created app on DigitalOcean App Platform!

App Details:
- Name: {app_name}
- Region: {region}
- App ID: {app_id}
- URL: {app_url}

NOTE: To complete deployment, you need to:
1. Create a GitHub repository
2. Copy your site files from {site_path} to the repository
3. Link the repository to the app in DigitalOcean control panel
4. The app will auto-deploy from the repository

Alternatively, you can upload files directly via the DigitalOcean control panel."""
                )
            else:
                error_msg = response.json().get("message", response.text)
                logger.error(f"✗ Failed to create app: {error_msg}")
                
                return DeploymentResult(
                    success=False,
                    message=f"Failed to create app on DigitalOcean: {error_msg}"
                )
                
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ API request failed: {str(e)}")
            return DeploymentResult(
                success=False,
                message=f"Failed to connect to DigitalOcean API: {str(e)}"
            )
        
    except Exception as e:
        return DeploymentResult(
            success=False,
            message=f"Error deploying to DigitalOcean: {str(e)}"
        )


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
