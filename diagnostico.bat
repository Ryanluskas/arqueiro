@echo off
echo =======================================
echo  DIAGNOSTICO - Arqueiro Bot
echo =======================================
echo.

echo [1] Python detectado:
py --version
py -c "import struct,sys; print('  Arquitetura:', struct.calcsize('P')*8, 'bits'); print('  Executavel:', sys.executable)"
echo.

echo [2] Modulos instalados:
py -c "import openpyxl; print('  openpyxl OK -', openpyxl.__version__)"
py -c "import openpyxl" 2>nul || echo   openpyxl: NAO INSTALADO
py -c "import playwright; print('  playwright OK')"
py -c "import playwright" 2>nul || echo   playwright: NAO INSTALADO
echo.

echo [3] Tentando instalar agora:
py -m pip install --prefer-binary openpyxl playwright
echo.

echo [4] Instalando browser Chromium:
py -m playwright install chromium
echo.

echo [5] Teste final:
py -c "from playwright.sync_api import sync_playwright; print('  playwright FUNCIONANDO')"
echo.

echo =======================================
pause
