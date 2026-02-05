# Static Site Agent

An A2A (Agent-to-Agent) compliant agent that generates, containerizes, and deploys static websites to **DigitalOcean Spaces**.

[![Deploy to DO](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/digitalocean/static-site-agent/tree/main&refcode=)

## Features

- **AI-Powered Site Generation**: Generate static websites based on natural language descriptions
- **Multiple Site Types**: Supports portfolio, landing page, blog, and business sites
- **Style Customization**: Apply style hints like "modern and minimalist", "colorful and playful", or "professional"
- **Automatic Containerization**: Creates Docker containers for your generated sites
- **DigitalOcean Spaces Deployment**: Uploads the generated site directly to your DigitalOcean Space (creates the bucket if needed and saves the site so it can be served publicly)

## Quick Deploy

Click the button above to deploy this agent directly to DigitalOcean App Platform. You'll need to:
1. Connect your GitHub account and fork this repository
2. Configure the required environment variables:
   - `DO_GRADIENT_API_KEY` or `OPENAI_API_KEY` (for AI site generation)
   - `SPACES_ACCESS_KEY_ID` and `SPACES_SECRET_ACCESS_KEY` (for uploading sites to your DigitalOcean Space)

## Local Deploy (no GitHub)

If you prefer deploying from your local machine without GitHub, use a container image and `doctl`:

1. Build the image locally:
```bash
docker build -t static-site-agent:latest .
```

2. Push the image to a registry (choose one):
- Docker Hub (public):
```bash
docker tag static-site-agent:latest docker.io/<your_dockerhub_username>/static-site-agent:latest
docker push docker.io/<your_dockerhub_username>/static-site-agent:latest
```
- DigitalOcean Container Registry:
```bash
doctl registry create <registry-name>   # if you don't have one
doctl registry login
docker tag static-site-agent:latest registry.digitalocean.com/<registry-name>/static-site-agent:latest
docker push registry.digitalocean.com/<registry-name>/static-site-agent:latest
```

3. Update the image in `.do/deploy.template.yaml` to match your pushed image.

4. Create the app using `doctl`:
```bash
doctl auth switch --context <your-context>
doctl apps create --spec .do/deploy.template.yaml
```

This path avoids GitHub permissions entirely by deploying from your own container image.

## Prerequisites

- Docker and Docker Compose installed (for local development)
- OpenAI API key OR DigitalOcean Gradient AI model access key
- Spaces access keys (for deploying generated sites to your Space; create under API → Spaces Keys)
- Docker network named `agents-net` (create with: `docker network create agents-net`)

## Setup

1. Clone the repository and navigate to the static-site-agent directory:
```bash
cd static-site-agent
```

2. Set your environment variables (choose one):

**Option A: Using DigitalOcean Gradient AI (Recommended)**
```bash
export DO_GRADIENT_API_KEY="your-do-model-access-key"
export SPACES_ACCESS_KEY_ID="your-spaces-access-key"
export SPACES_SECRET_ACCESS_KEY="your-spaces-secret-key"
```

**Option B: Using OpenAI**
```bash
export OPENAI_API_KEY="your-openai-api-key"
export SPACES_ACCESS_KEY_ID="your-spaces-access-key"
export SPACES_SECRET_ACCESS_KEY="your-spaces-secret-key"
```

Spaces keys are created in the DigitalOcean control panel under **API** → **Spaces Keys**. The agent can create the Space (bucket) automatically if it doesn't exist.

3. Build and run the agent:
```bash
docker-compose up --build
```

The agent will be available at `http://localhost:5002` with a built-in chat interface!

## Usage

### Using the Built-in Chat Interface (Recommended)

1. Open your browser to http://localhost:5002
2. You'll see a beautiful chat interface ready to use
3. Type your request or click one of the suggested prompts
4. The agent will generate, containerize, and help deploy your site!

### Example Prompts

### Example 1: Simple Portfolio
```
Create a modern minimalist portfolio site for a web developer
```

### Example 2: Landing Page
```
Generate a colorful and playful landing page for a kids' app with a signup form
```

### Example 3: Blog
```
Build a professional blog site with a dark theme
```

### Example 4: Deploy to Spaces (saves site to your Space)
```
Create a landing page and upload it to my DigitalOcean Space named my-website in nyc3
```

## How It Works

The agent uses three main tools:

1. **generate_static_site**: Creates HTML/CSS files in a temporary directory
   - Parameters: `site_type`, `style_hints`, `site_name`
   - Outputs: Static site files (index.html, styles.css, nginx.conf)

2. **containerize_site**: Creates a Docker image for the site
   - Parameters: `site_path`, `image_name`
   - Outputs: Dockerfile and built Docker image

3. **deploy_to_spaces**: Uploads the static site files to a DigitalOcean Space (S3-compatible). Creates the bucket via the API if it doesn't exist, then uploads the files.
   - Parameters: `site_path`, `bucket_name`, `region` (e.g. nyc3), optional `spaces_access_key` / `spaces_secret_key` (or use env), `create_bucket_if_missing` (default True)
   - Outputs: Index URL and CDN URL for the deployed site.

## Architecture

```
static-site-agent/
├── src/
│   ├── __init__.py
│   ├── __main__.py       # FastAPI server
│   ├── agent.py          # LangChain agent logic
│   ├── models.py         # Pydantic models for A2A protocol
│   └── tools.py          # Site generation, containerization, and deployment tools
├── AgentCard.json        # A2A agent metadata
├── Dockerfile            # Container definition
├── docker-compose.yml    # Docker Compose configuration
└── README.md            # This file
```

## Supported Site Types

- **portfolio**: Personal or professional portfolio with projects showcase
- **landing**: Product landing page with features and call-to-action
- **blog**: Blog layout with article listings
- **business**: Business website (uses landing template)

## Style Hints

Style hints influence the color scheme and design:
- "modern and minimalist" or "dark" → Dark theme with blue accents
- "colorful and playful" → Light theme with pink accents
- "professional" or "business" → Clean white theme with professional blue

## API Endpoint

The agent exposes a single JSON-RPC 2.0 endpoint:

**POST /** - Send messages to the agent

Example request:
```json
{
  "jsonrpc": "2.0",
  "id": "123",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [
        {
          "kind": "text",
          "text": "Create a modern portfolio site"
        }
      ]
    }
  }
}
```

## Environment Variables

- `OPENAI_API_KEY` or `DO_GRADIENT_API_KEY`: Required for AI-powered site generation
- `SPACES_ACCESS_KEY_ID` and `SPACES_SECRET_ACCESS_KEY`: Required to upload sites to DigitalOcean Spaces (create under API → Spaces Keys in the DO control panel). Alternatively `SPACES_KEY` and `SPACES_SECRET` are supported.

## Notes

- Generated sites are created in temporary directories with the prefix `static-site-`
- Docker must be available for containerization to work
- **Spaces deployment** uploads the generated files directly to your Space and returns a public URL; no GitHub required. The bucket is created automatically if it doesn't exist.

## Troubleshooting

**Docker permission issues**: Make sure Docker socket is mounted correctly in docker-compose.yml

**Port already in use**: Change the port mapping in docker-compose.yml from `5002:5000` to another port

**Gradient AI API errors**: Verify your GRADIENT_API_KEY is valid and has sufficient credits

## License

MIT License - See LICENSE file for details
