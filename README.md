# AirWatch

Real-time air quality anomaly detection and investigation system for Israel.

## What it does

- Streams air quality data from Israeli monitoring stations (OpenAQ, IMS)
- Detects anomalies using classical ML (Isolation Forest, Autoencoder) and Graph Neural Networks
- Investigates anomalies with LLM-powered agents (LangGraph)
- Alerts via Slack/email with human-readable explanations

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| Data | httpx, pandas, numpy, OpenAQ API, IMS Envista API |
| ML | scikit-learn, PyTorch, PyTorch Geometric |
| Agents | LangGraph, LangChain, Claude API, Chroma (RAG) |
| API | FastAPI, pydantic |
| Dashboard | Streamlit, Folium, Plotly |
| Infra | Docker, AWS (Lambda, EventBridge, DynamoDB, SNS), Terraform |
| CI/CD | GitHub Actions, ruff, mypy, pytest |

## Project Structure

```
airwatch/
├── src/
│   ├── data/          # API clients, data pipeline
│   ├── detection/     # ML models, GNN, ensemble
│   ├── agents/        # LangGraph agents (investigation, root cause, alert, orchestrator)
│   ├── api/           # FastAPI endpoints
│   ├── dashboard/     # Streamlit app
│   └── schemas/       # Pydantic models (shared contracts)
├── tests/
│   ├── unit/
│   └── integration/
├── configs/           # Configuration files
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -e ".[dev]"
pre-commit install
```

## Development

```bash
make lint      # ruff check + format
make typecheck # mypy
make test      # pytest
make up        # docker-compose up
```
