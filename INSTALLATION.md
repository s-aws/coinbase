# Installation Guide

This document provides detailed instructions for installing and setting up the Coinbase AGENTS repository.

## System Requirements

- Python 3.9 or higher
- pip (Python package manager)
- Git
- Virtual environment support

## Installation Steps

### 1. Clone the Repository

```bash
git clone <repository-url>
cd coinbase-agents
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

If you're developing or contributing to the project, install development dependencies:

```bash
pip install -r requirements-dev.txt
```

### 4. Environment Setup

Create a local environment configuration:

```bash
cp .env.example .env
```

Edit `.env` to include your Coinbase API credentials and other configuration values.

### 5. Database Setup (if applicable)

If the system requires a database:

```bash
# Run database migrations
python manage.py migrate
```

### 6. Verify Installation

Run a basic test to ensure everything is working:

```bash
python -c "import core.models; print('Installation successful')"
```

## Development Installation

For developers who want to contribute to the codebase:

1. Install development dependencies:
   ```bash
   pip install -r requirements-dev.txt
   ```

2. Install pre-commit hooks:
   ```bash
   pre-commit install
   ```

3. Run the test suite:
   ```bash
   pytest tests/ -v
   ```

## Docker Installation (Optional)

For containerized deployment:

1. Build the Docker image:
   ```bash
   docker build -t coinbase-agents .
   ```

2. Run the container:
   ```bash
   docker run -it coinbase-agents
   ```

## Troubleshooting

### Common Issues

**Python version issues:**
- Ensure you're using Python 3.9 or higher
- Use `python --version` to check your version

**Virtual environment issues:**
- Make sure you've activated the virtual environment
- Re-create the environment if needed: `rm -rf venv && python -m venv venv`

**Dependency installation issues:**
- Try upgrading pip: `pip install --upgrade pip`
- Clear pip cache: `pip cache purge`

### Verification

After installation, verify your setup by running:

```bash
python -m pytest tests/ --tb=short -v
```

This should run the test suite without errors.

## Next Steps

After successful installation, refer to the [Quick Start Guide](QUICK_START.md) to begin using the system.