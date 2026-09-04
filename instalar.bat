@echo off
echo =============================================
echo  Instalando dependencias do Arqueiro Bot
echo  (usando Python 3.12 64-bit)
echo =============================================
echo.
py -3.12 --version
echo.
echo Instalando pacotes...
py -3.12 -m pip install --prefer-binary playwright pandas openpyxl requests
echo.
if errorlevel 1 (
    echo [ERRO] Falha na instalacao. Veja mensagem acima.
    pause
    exit /b 1
)
echo.
echo Instalando browser Chromium...
py -3.12 -m playwright install chromium
echo.
echo =============================================
echo  Pronto! Para iniciar o bot:
echo  py -3.12 gui.py
echo =============================================
pause
