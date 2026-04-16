@echo off
chcp 65001 >nul
title 策略量化稽核系統 (Monthly Meta-Audit)
echo ========================================================
echo           Monthly Meta-Audit Pipeline UI Starter
echo ========================================================
echo.
echo 檢查套件依賴是否環境具備 (Streamlit, Plotly)...
python -m pip install -q streamlit pandas numpy plotly openpyxl

echo.
echo 正在啟動 Streamlit 伺服器...
echo 請不要關閉此視窗，系統將自動開啟您的預設瀏覽器...
echo.

python -m streamlit run "%~dp0app.py" --server.port 8505

pause
