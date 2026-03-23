# crypto-mvp Installation Guide (Windows 10/11)

This guide explains how to install and run crypto-mvp on a brand-new Windows machine.

## Prerequisites

Install these first:

1. Git for Windows
   Download: https://git-scm.com/download/win
   During install: accept all defaults.

2. Python 3.11+
   Download: https://www.python.org/downloads/
   Important: check Add Python to PATH during install.

3. Docker Desktop for Windows
   Download: https://www.docker.com/products/docker-desktop/
   Docker Desktop requires WSL2. The installer will guide you if anything is missing.
   After install: open Docker Desktop and wait until it shows Engine running.

## Installation Steps

1. Open PowerShell as Administrator.

2. Clone the repository:

   git clone https://github.com/palbotics/crypto-mvp.git
   cd crypto-mvp

3. Run the setup script:

   .\setup.ps1

   This script will:
   - Create the Python virtual environment
   - Install Python dependencies
   - Start PostgreSQL in Docker
   - Run database migrations

4. Copy your .env file into the crypto-mvp folder.
   Transfer it from your dev machine (it contains all credentials).

5. Start the system:

   .\start-crypto-mvp.bat

## Transferring your .env file

The .env file contains all credentials and is NOT stored in git.

Copy it from your dev machine to the new machine using a secure method:
- USB drive
- Secure file transfer
- Encrypted email attachment (if your environment allows it)

Place .env in the crypto-mvp root folder.

Never share this file or commit it to git.

## Verifying the installation

After running .\start-crypto-mvp.bat:

- Four PowerShell windows should open:
  - Collector
  - Paper Trader
  - Dashboard
  - Funding Monitor

- Open this URL in your browser:
  http://localhost:8000

- Check the status indicators:
  API, Paper Trader, and DB should all be green.

- Run the readiness checker:

  python scripts/check_live_entry_conditions.py

  Expected result:
  8/9 checks passing in normal waiting conditions.
  Funding APR may still fail until market conditions are favorable.

## Troubleshooting

Common issues and fixes:

- python not found
  Cause: Python PATH not set.
  Fix: reinstall Python and check Add Python to PATH.

- Docker not running
  Cause: Docker Desktop is closed or still starting.
  Fix: start Docker Desktop from Start menu and wait for the whale icon to indicate running status.

- port 8000 already in use
  Cause: another process is using dashboard port 8000.
  Fix:

  netstat -ano | findstr :8000

  Then stop that PID in Task Manager or via PowerShell.

- database connection failed
  Cause: PostgreSQL container is not running.
  Fix:

  docker start crypto-mvp-postgres

- Module not found
  Cause: virtual environment not active for manual commands.
  Fix:

  .venv\Scripts\Activate.ps1

  Then re-run your Python command.
