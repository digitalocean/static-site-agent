# Static Site Agent

An A2A (Agent-to-Agent) compliant agent that generates, containerizes, and deploys static websites to DigitalOcean App Platform.

[![Deploy to DO](https://www.deploytodo.com/do-btn-blue.svg)](https://cloud.digitalocean.com/apps/new?repo=https://github.com/digitalocean/static-site-agent/tree/main&refcode=)

## Features

- **AI-Powered Site Generation**: Generate static websites based on natural language descriptions
- **Multiple Site Types**: Supports portfolio, landing page, blog, and business sites
- **Style Customization**: Apply style hints like "modern and minimalist", "colorful and playful", or "professional"
- **Automatic Containerization**: Creates Docker containers for your generated sites
- **DigitalOcean Deployment**: Deploys to DigitalOcean App Platform with a single command

## Quick Deploy

Click the button above to deploy this agent directly to DigitalOcean App Platform. You'll need to:
1. Connect your GitHub account and fork this repository
2. Configure the required environment variables:
   - `DO_GRADIENT_API_KEY` or `OPENAI_API_KEY` (for AI site generation)
   - `DIGITALOCEAN_API_KEY` (for deploying generated sites)

## Prerequisites

- Docker and Docker Compose installed (for local development)
- OpenAI API key OR DigitalOcean Gradient AI model access key
- DigitalOcean API key (for deployment)
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
export DIGITALOCEAN_API_KEY="your-digitalocean-api-key"
```

**Option B: Using OpenAI**
```bash
export OPENAI_API_KEY="your-openai-api-key"
export DIGITALOCEAN_API_KEY="your-digitalocean-api-key"
```

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

### Example 4: Complete Deployment
```
Create a landing page for a SaaS product with a modern design, 
containerize it, and deploy it to DigitalOcean using my API key: do_xxxxx
```

## How It Works

The agent uses three main tools:

1. **generate_static_site**: Creates HTML/CSS files in a temporary directory
   - Parameters: `site_type`, `style_hints`, `site_name`
   - Outputs: Static site files (index.html, styles.css, nginx.conf)

2. **containerize_site**: Creates a Docker image for the site
   - Parameters: `site_path`, `image_name`
   - Outputs: Dockerfile and built Docker image

3. **deploy_to_digitalocean**: Deploys to DigitalOcean App Platform
   - Parameters: `site_path`, `app_name`, `do_api_key`, `region`
   - Outputs: Deployment instructions and app URL

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

- `GRADIENT_API_KEY`: Required for AI-powered site generation using Gradient AI
- `GRADIENT_BASE_URL`: Optional, defaults to `https://api.gradient.ai/api/v1`
- `DIGITALOCEAN_API_KEY`: Required for deployment to DigitalOcean

## Notes

- Generated sites are created in temporary directories with the prefix `static-site-`
- Docker must be available for containerization to work
- Full automated deployment to DigitalOcean requires additional setup (git repository integration)
- The agent provides manual deployment instructions as an alternative

## Troubleshooting

**Docker permission issues**: Make sure Docker socket is mounted correctly in docker-compose.yml

**Port already in use**: Change the port mapping in docker-compose.yml from `5002:5000` to another port

**Gradient AI API errors**: Verify your GRADIENT_API_KEY is valid and has sufficient credits

## License

MIT License - See LICENSE file for details
