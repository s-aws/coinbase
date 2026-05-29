# Quick Start Guide

This guide will help you get up and running with the Coinbase AGENTS repository quickly.

## Prerequisites

Before you begin, ensure you have the following installed:
- Python 3.9 or higher
- pip (Python package manager)
- Git

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd coinbase-agents
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Copy the example configuration:
   ```bash
   cp config.example.py config.py
   ```

2. Update the configuration with your Coinbase API credentials and settings.

## Running the System

1. Start the main application:
   ```bash
   python main.py
   ```

2. The system will initialize and begin monitoring the market.

## Next Steps

- Review the [Agent Architecture](docs/agents/AGENT_ARCHITECT.md) documentation
- Check the [Core Models](core/models.py) to understand data structures
- Explore the [Business Logic Components](#business-logic-components) in the README

## Troubleshooting

If you encounter issues:
1. Check that all dependencies are installed
2. Verify your configuration settings
3. Review the [Test Documentation](tests/README.md) for running tests
4. Consult the [Key Invariants](docs/agents/INVARIANTS.md) for system constraints

For additional help, see the [Full Documentation](README.md).