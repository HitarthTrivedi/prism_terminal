@echo off
  cd /d "%~dp0"
  echo.
  echo   Starting Prism...
  echo -----------------------------------------
  if not exist ".venv" (
      echo   First run - creating virtual environment...
      python -m venv .venv
      .venv\Scripts\pip install --quiet --upgrade pip setuptools packaging
      echo   Installing dependencies, this can take a minute...
      .venv\Scripts\pip install --quiet -r requirements.txt
      echo   Ready.
  )

  .venv\Scripts\python prism.py %*




