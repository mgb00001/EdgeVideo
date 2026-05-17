@echo off
title EdgeVideo — Install Dependencies
color 0B
echo.
echo   Installing EdgeVideo Python dependencies...
echo.
pip install -r requirements.txt
echo.
if %errorlevel%==0 (
    echo   All dependencies installed successfully.
) else (
    echo   One or more packages failed to install. See errors above.
)
echo.
pause
