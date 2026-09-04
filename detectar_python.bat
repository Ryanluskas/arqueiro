@echo off
echo === Pythons instalados ===
py --list
echo.
echo === Testando cada versao ===
for %%v in (3.13 3.12 3.11 3.10 3.9) do (
    py -%%v -c "import playwright,pandas; print('%%v OK - playwright e pandas DISPONIVEIS')" 2>nul
)
echo.
echo === Python padrao (py sem versao) ===
py -c "import sys,struct; print(sys.version, struct.calcsize('P')*8,'bits')"
echo.
pause
